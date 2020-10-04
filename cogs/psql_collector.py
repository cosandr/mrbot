from __future__ import annotations

import asyncio
import itertools
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Union, Dict

import asyncpg
import discord
from discord.ext import commands

from ext.context import Context
from ext.internal import Channel, Guild, Message, User
from ext.psql import create_table, debug_query, ensure_foreign_key, try_foreign_key_add
from ext.utils import QueueItem

if TYPE_CHECKING:
    from mrbot import MrBot


@dataclass()
class Cache:
    users: Dict[int, User] = field(default_factory=dict)
    channels: Dict[int, Channel] = field(default_factory=dict)
    guilds: Dict[int, Guild] = field(default_factory=dict)
    typed: Dict[int, datetime] = field(default_factory=dict)


class Collector(commands.Cog, name="PSQL Collector", command_attrs={'hidden': True}):
    psql_table_name_typed = 'typed_log'
    psql_table_name_voice = 'voice_log'
    psql_table_name_command_log = 'command_log'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name_typed} (
            time      TIMESTAMP NOT NULL,
            user_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id     BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE,
            guild_id  BIGINT REFERENCES {Guild.psql_table_name} (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_voice} (
            connected  BOOLEAN NOT NULL,
            time       TIMESTAMP NOT NULL,
            user_id    BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id      BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE,
            guild_id   BIGINT NOT NULL REFERENCES {Guild.psql_table_name} (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_command_log} (
            name     VARCHAR(200) NOT NULL,
            cog_name VARCHAR(100),
            time     TIMESTAMP NOT NULL,
            bot_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            user_id  BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id    BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE,
            guild_id BIGINT REFERENCES {Guild.psql_table_name} (id) ON DELETE CASCADE
        );
    """
    # Message already depends on Guild, Channel and User tables
    psql_all_tables = Message.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name_typed, psql_table_name_voice, psql_table_name_command_log): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        self.queue_task = self.bot.loop.create_task(self.run_queue())
        self.con: Optional[asyncpg.Connection] = None
        self.lock: asyncio.Lock = asyncio.Lock()
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.re_key = re.compile(r'Key.*is not present in table \"(\w+)\"\.')
        self.bot.loop.create_task(self.async_init())
        self._type_interval = timedelta(minutes=1)
        self._cache = Cache()

    async def async_init(self):
        await self.bot.connect_task
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)
        self.con = await self.bot.pool.acquire()
        self.logger.info('Connection acquired')
        # Load from PSQL into cache
        for u in (await User.from_psql_all(self.con, with_all_nicks=True, with_activity=True, with_status=True)):
            self._cache.users[u.id] = u
        for c in (await Channel.from_psql_all(self.con, with_guild=True)):
            self._cache.channels[c.id] = c
        for g in (await Guild.from_psql_all(self.con)):
            self._cache.guilds[g.id] = g
        self.logger.info('Loaded %d guilds, %d channels and %d users',
                         len(self._cache.guilds), len(self._cache.channels), len(self._cache.users))
        # Ensure bot is in user table first
        await self.bot.wait_until_ready()
        await self.bot.msg_queue.put(QueueItem(0, ensure_foreign_key(con=self.con, obj=User.from_discord(self.bot.user),
                                                                     logger=self.logger)))

    async def cog_check(self, ctx: Context):
        return await self.bot.is_owner(ctx.author)

    def cog_unload(self):
        self.bot.cleanup_tasks.append(self.bot.loop.create_task(self.async_unload()))

    async def async_unload(self):
        await self.bot.msg_queue.put(QueueItem(9, None))
        await self.queue_task
        async with self.lock:
            try:
                await self.bot.pool.release(self.con)
                self.logger.info('Connection released')
            except Exception as e:
                self.logger.warning('Connection release failed: %s', str(e))

    # region Event Listeners

    @commands.Cog.listener()
    async def on_typing(self, channel: discord.abc.Messageable, user: Union[discord.User, discord.Member], when: datetime):
        """Update typed_log"""
        if self.queue_task.done():
            return
        # Ignore DMs
        if not hasattr(channel, 'guild'):
            return
        # Ignore bots
        if user.bot:
            return
        # Ignore webhooks
        if user.discriminator == '0000':
            return
        # Check last update time
        now = datetime.utcnow()
        if last_typed := self._cache.typed.get(user.id):
            if now - last_typed < self._type_interval:
                return
        self._cache.typed[user.id] = now
        int_user = User.from_discord(user)
        int_channel = Channel.from_discord(channel)
        q = (f'INSERT INTO {self.psql_table_name_typed} '
             '(time, user_id, ch_id, guild_id) VALUES ($1, $2, $3, $4)')
        q_args = [when, int_user.id, int_channel.id, int_channel.guild_id]
        self.logger.debug("Updated typed for user %s", user.name)
        await self.bot.msg_queue.put(QueueItem(5, self.run_query(q, q_args, user=int_user, channel=int_channel)))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Update voice_log"""
        q = (f'INSERT INTO {self.psql_table_name_voice} '
             '(connected, time, user_id, ch_id, guild_id) VALUES ($1, $2, $3, $4, $5)')
        # User connected to channel
        if after.channel:
            q_args = [True, datetime.utcnow(), member.id, after.channel.id, after.channel.guild.id]
            channel = Channel.from_discord(after.channel)
        # User disconnected
        elif before.channel:
            q_args = [False, datetime.utcnow(), member.id, before.channel.id, before.channel.guild.id]
            channel = Channel.from_discord(before.channel)
        else:
            return

        user = User.from_discord(member)
        self.logger.debug("Updated voice state for user %s", user.name)
        await self.bot.msg_queue.put(QueueItem(5, self.run_query(q, q_args, user=user, channel=channel)))
        await self.check_and_update(user=user, channel=channel)

    @commands.Cog.listener()
    async def on_command(self, ctx: Context):
        """Update command_log"""
        cog_name = ctx.cog.__cog_name__ if ctx.cog else None
        guild_id = ctx.guild.id if ctx.guild else None
        q = (f'INSERT INTO {self.psql_table_name_command_log} '
             '(name, cog_name, time, bot_id, user_id, ch_id, guild_id) '
             'VALUES ($1, $2, $3, $4, $5, $6, $7)')
        q_args = [ctx.command.qualified_name, cog_name, datetime.utcnow(), self.bot.user.id, ctx.author.id,
                  ctx.channel.id, guild_id]
        int_user = User.from_discord(ctx.author)
        int_ch = Channel.from_discord(ctx.channel)
        int_guild = Guild.from_discord(ctx.guild)
        self.logger.debug("Added command %s used by %s to command log", q_args[0], int_user.name)
        await self.bot.msg_queue.put(QueueItem(5, self.run_query(q, q_args, user=int_user, channel=int_ch, guild=int_guild)))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Update user_status"""
        # Ignore webhooks
        if after.discriminator == '0000':
            return
        if self.queue_task.done():
            return
        user = User.from_discord(after)
        if before.status != after.status:
            user.status_time = datetime.utcnow()
        if before.activity != after.activity:
            user.activity_time = datetime.utcnow()

        # Ignore activities for bots
        if after.bot:
            user.activity = None
        await self.check_and_update(user=user)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Update messages"""
        # Ignore webhooks
        if message.author.discriminator == '0000':
            return
        # Don't do anything if worker is not running
        if self.queue_task.done():
            return
        # Ignore exceptions channel
        if message.channel.id == 434276260164665345:
            return

        msg = Message.from_discord(message)
        q, q_args = msg.to_psql()
        await self.bot.msg_queue.put(QueueItem(1, self.run_query(q, q_args, msg=msg)))
        await self.check_and_update(user=msg.author, channel=msg.channel)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Update message_edits"""
        # Ignore webhooks
        if after.author.discriminator == '0000':
            return
        if self.queue_task.done():
            return
        # Ignore self edits
        if before.author.id == self.bot.user.id:
            return

        msg = Message.from_discord(after)
        q, q_args = msg.to_psql()
        await self.bot.msg_queue.put(QueueItem(3, self.run_query(q, q_args, msg=msg)))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Update messages"""
        # Ignore webhooks
        if payload.cached_message and payload.cached_message.author.discriminator == '0000':
            return
        if self.queue_task.done():
            return
        msg = Message(id_=payload.message_id, deleted=True)
        q, q_args = msg.to_psql_mark_deleted()
        await self.bot.msg_queue.put(QueueItem(2, self.run_query(q, q_args, msg=msg)))

    # endregion

    # region Queue Functions

    async def run_queue(self):
        self.logger.debug('Queue runner started')
        while True:
            # Data in queue should be a QueueItem for run_query
            item: QueueItem = await self.bot.msg_queue.get()
            if item.coro is None:
                self.logger.debug('Queue runner cancelled')
                return
            if asyncio.iscoroutine(item.coro):
                await item.coro
            else:
                self.logger.warning('Queue runner encountered unknown type: %s', type(item.coro))
            self.bot.msg_queue.task_done()

    async def run_query(self, q: str, q_args: list, msg: Message = None, user: User = None,
                        channel: Channel = None, guild: Guild = None):
        async with self.lock:
            for _ in range(3):
                try:
                    await self.con.execute(q, *q_args)
                except asyncpg.exceptions.InterfaceError as e:
                    self.logger.error('Connection interface error, will retry: %s', str(e))
                    continue
                except asyncpg.exceptions.ConnectionDoesNotExistError as e:
                    self.logger.warning('Connection closed error: %s', str(e))
                    await self.ensure_con()
                except asyncpg.exceptions.UniqueViolationError as e:
                    self.logger.warning(str(e))
                except asyncpg.exceptions.ForeignKeyViolationError as e:
                    should_continue = await try_foreign_key_add(self.con, e, self.logger, msg, user, channel, guild)
                    if should_continue:
                        continue
                    return
                except Exception as e:
                    self.logger.error('Connection exec failed: %s', str(e))
                    debug_query(q, q_args, e)
                    await self.ensure_con()
                return

    # endregion

    # region Integrity functions

    async def check_and_update(self, user: User = None, channel: Channel = None, guild: Guild = None):
        """Updates cache and PSQL tables if needed"""
        if channel:
            if not guild and channel.guild:
                guild = channel.guild
            if self._cache.channels.get(channel.id) != channel:
                q, q_args = channel.to_psql()
                await self.bot.msg_queue.put(QueueItem(7, self.run_query(q, q_args, channel=channel, guild=guild)))
                self._cache.channels[channel.id] = channel
                self.logger.info('Updated channel %s in guild %s', str(channel), str(guild))
        if guild and self._cache.guilds.get(guild.id) != guild:
            q, q_args = guild.to_psql()
            await self.bot.msg_queue.put(QueueItem(6, self.run_query(q, q_args, guild=guild)))
            self._cache.guilds[guild.id] = guild
            self.logger.info('Updated guild %s', str(guild))
        default_user = User(0)
        cached_user: Optional[User] = self._cache.users.get(user.id, default_user)
        if user:
            # Determine what is different
            diff = cached_user.diff_tol(user, guild_id=getattr(guild, 'id', None), all_nicks=False)
            if not diff:
                return
            if any(k in diff for k in ('id', 'name', 'discriminator', 'avatar')):
                q, q_args = user.to_psql()
                await self.bot.msg_queue.put(QueueItem(8, self.run_query(q, q_args, user=user)))
            if 'activity' in diff:
                q, q_args = user.to_psql_activity()
                await self.bot.msg_queue.put(QueueItem(8, self.run_query(q, q_args, user=user)))
            if any(k in diff for k in ('online', 'mobile')):
                q, q_args = user.to_psql_status()
                await self.bot.msg_queue.put(QueueItem(8, self.run_query(q, q_args, user=user)))
            if 'nick' in diff:
                q, q_args = user.to_psql_nick(guild.id)
                await self.bot.msg_queue.put(QueueItem(8, self.run_query(q, q_args, user=user, guild=guild)))
            # Shouldn't happen
            if cached_user == default_user:
                self.logger.info('Added new user %s', str(user))
            else:
                info_msg = []
                debug_msg = []
                for k in diff:
                    if k == 'nick':
                        info_msg.append(f'nick [{str(guild)}]')
                        debug_msg.append(f'\tnick [{str(guild)}]: {getattr(cached_user, k)} -> {getattr(user, k)}')
                    else:
                        info_msg.append(k)
                        debug_msg.append(f'\t{k}: {getattr(cached_user, k)} -> {getattr(user, k)}')
                self.logger.info('Updated %s for user %s', ', '.join(info_msg), str(user))
                self.logger.debug('\n%s', '\n'.join(debug_msg))
            self._cache.users[user.id] = user

    async def ensure_con(self):
        if self.queue_task.done():
            self.logger.info('Connection will not be reacquired because the worker task is done')
            return
        if not self.con:
            self.con = await self.bot.pool.acquire()
            self.logger.info('Connection was not found and acquired')
            return
        start = time.perf_counter()
        try:
            await self.bot.pool.release(self.con)
            self.logger.info('Connection released')
        except Exception as e:
            self.logger.info('Connection release failed: %s', str(e))
        finally:
            self.con = await self.bot.pool.acquire()
            self.logger.info('Connection reacquired')
        self.logger.info('Connection reacquired in %.3fms', (time.perf_counter()-start)*1000)

    # endregion


def setup(bot):
    bot.add_cog(Collector(bot))
