import asyncio
import itertools
import logging
import re
import time
from datetime import datetime
from typing import Optional, Union

import asyncpg
import discord
from discord.ext import commands

from mrbot import MrBot
from ext.internal import Channel, Guild, Message, User
from ext.psql import create_table, debug_query, ensure_foreign_key, try_foreign_key_add
from ext.utils import QueueItem


class Collector(commands.Cog, name="PSQL Collector", command_attrs={'hidden': True}):
    psql_table_name_typed = 'stalk_typed'
    psql_table_name_voice = 'stalk_voice'
    psql_table_name_typed_log = f'{psql_table_name_typed}_log'
    psql_table_name_voice_log = f'{psql_table_name_voice}_log'
    psql_table_name_command_log = 'command_log'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name_typed} (
            time      TIMESTAMP NOT NULL,
            user_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id     BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id),
            guild_id  BIGINT REFERENCES {Guild.psql_table_name} (id),
            UNIQUE (user_id)
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_voice} (
            connect    TIMESTAMP,
            disconnect TIMESTAMP,
            user_id    BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id      BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id),
            guild_id   BIGINT NOT NULL REFERENCES {Guild.psql_table_name} (id),
            UNIQUE (user_id),
            CONSTRAINT chk_empty CHECK (connect IS NOT NULL OR disconnect IS NOT NULL)
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_command_log} (
            name     VARCHAR(200) NOT NULL,
            cog_name VARCHAR(100),
            time     TIMESTAMP NOT NULL,
            bot_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id),
            user_id  BIGINT NOT NULL REFERENCES {User.psql_table_name} (id),
            ch_id    BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id),
            guild_id BIGINT REFERENCES {Guild.psql_table_name} (id)
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_typed_log} (
            time      TIMESTAMP NOT NULL,
            user_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id     BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE,
            guild_id  BIGINT REFERENCES {Guild.psql_table_name} (id) ON DELETE CASCADE
        );
        CREATE OR REPLACE FUNCTION log_{psql_table_name_typed}()
            RETURNS trigger AS $$
        BEGIN
            INSERT INTO {psql_table_name_typed_log} VALUES (OLD.time, OLD.user_id, OLD.ch_id, OLD.guild_id);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS trigger_log_{psql_table_name_typed} ON {psql_table_name_typed};
        CREATE TRIGGER trigger_log_{psql_table_name_typed} BEFORE UPDATE ON {psql_table_name_typed}
            FOR EACH ROW EXECUTE PROCEDURE log_{psql_table_name_typed}();

        CREATE TABLE IF NOT EXISTS {psql_table_name_voice_log} (
            connect    TIMESTAMP,
            disconnect TIMESTAMP,
            user_id    BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            ch_id      BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE,
            guild_id   BIGINT NOT NULL REFERENCES {Guild.psql_table_name} (id) ON DELETE CASCADE
        );
        CREATE OR REPLACE FUNCTION log_{psql_table_name_voice}()
            RETURNS trigger AS $$
        BEGIN
            INSERT INTO {psql_table_name_voice_log} VALUES (OLD.connect, OLD.disconnect, OLD.user_id, OLD.ch_id, OLD.guild_id);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS trigger_log_{psql_table_name_voice} ON {psql_table_name_voice};
        CREATE TRIGGER trigger_log_{psql_table_name_voice} BEFORE UPDATE ON {psql_table_name_voice}
            FOR EACH ROW EXECUTE PROCEDURE log_{psql_table_name_voice}();
    """
    # Message already depends on Guild, Channel and User tables
    psql_all_tables = Message.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name_typed, psql_table_name_voice, psql_table_name_command_log,
                             psql_table_name_typed_log, psql_table_name_voice_log): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        self.queue_task = self.bot.loop.create_task(self.run_queue())
        self.con: Optional[asyncpg.Connection] = None
        self.lock: asyncio.Lock = asyncio.Lock()
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger_name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.re_key = re.compile(r'Key.*is not present in table \"(\w+)\"\.')
        self.bot.loop.create_task(self.async_init())
        self._cache = dict(users={}, channels={}, guilds={})

    async def async_init(self):
        await self.bot.connect_task
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)
        self.con = await self.bot.pool.acquire()
        self.logger.info('Connection acquired')
        # Load from PSQL into cache
        for u in (await User.from_psql_all(self.con, with_all_nicks=True)):
            self._cache['users'][u.id] = u
        for c in (await Channel.from_psql_all(self.con, with_guild=True)):
            self._cache['channels'][c.id] = c
        for g in (await Guild.from_psql_all(self.con)):
            self._cache['guilds'][g.id] = g
        self.logger.info('Loaded %d guilds, %d channels and %d users',
                         len(self._cache['guilds']), len(self._cache['channels']), len(self._cache['users']))
        # Ensure bot is in user table first
        await self.bot.wait_until_ready()
        await self.bot.msg_queue.put(QueueItem(0, ensure_foreign_key(con=self.con, obj=User.from_discord(self.bot.user),
                                                                     logger=self.logger)))

    async def cog_check(self, ctx):
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

    #region Event Listeners

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # User connected to channel
        if after.channel:
            q = (f'INSERT INTO {self.psql_table_name_voice} '
                 '(connect, user_id, ch_id, guild_id) VALUES ($1, $2, $3, $4) '
                 'ON CONFLICT (user_id) DO UPDATE SET '
                 'connect=$1, ch_id=$3, guild_id=$4')
            q_args = [datetime.utcnow(), member.id, after.channel.id, after.channel.guild.id]
            channel = Channel.from_discord(after.channel)
        # User disconnected
        elif before.channel:
            q = (f'INSERT INTO {self.psql_table_name_voice} '
                 '(disconnect, user_id, ch_id, guild_id) VALUES ($1, $2, $3, $4) '
                 'ON CONFLICT (user_id) DO UPDATE SET '
                 'disconnect=$1, ch_id=$3, guild_id=$4')
            q_args = [datetime.utcnow(), member.id, before.channel.id, before.channel.guild.id]
            channel = Channel.from_discord(before.channel)
        else:
            return

        user = User.from_discord(member)
        await self.bot.msg_queue.put(QueueItem(5, self.run_query(q, q_args, user=user, channel=channel)))
        await self.check_and_update(user=user, channel=channel)

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
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
        await self.bot.msg_queue.put(QueueItem(5, self.run_query(q, q_args, user=int_user, channel=int_ch, guild=int_guild)))

    @commands.Cog.listener()
    async def on_typing(self, channel: discord.abc.Messageable, user: Union[discord.User, discord.Member], when: datetime):
        if self.queue_task.done():
            return
        # Ignore DMs
        if not hasattr(channel, 'guild'):
            return
        # Ignore bots
        if user.bot:
            return
        int_user = User.from_discord(user)
        int_channel = Channel.from_discord(channel)
        q = (f'INSERT INTO {self.psql_table_name_typed} (time, user_id, ch_id, guild_id) '
             'VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET time=$1')
        q_args = [when, int_user.id, int_channel.id, int_channel.guild_id]
        await self.bot.msg_queue.put(QueueItem(5, self.run_query(q, q_args, user=int_user, channel=int_channel)))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if self.queue_task.done():
            return
        user = User.from_discord(after)
        # Get cached user to avoid unnecessary updates
        cached_user: Optional[User] = self._cache['users'].get(user.id)
        if str(after.status) != "offline":
            user.online = datetime.utcnow()
            if cached_user:
                user.offline = cached_user.offline
        else:
            user.offline = datetime.utcnow()
            if cached_user:
                user.online = cached_user.online
        # Ignore activities for bots
        if after.bot:
            user.activity = None
        await self.check_and_update(user=user)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
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
        if self.queue_task.done():
            return
        msg = Message(id_=payload.message_id, deleted=True)
        q, q_args = msg.to_psql_mark_deleted()
        await self.bot.msg_queue.put(QueueItem(2, self.run_query(q, q_args, msg=msg)))

    #endregion

    #region Queue Functions

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

    #endregion

    #region Integrity functions

    async def check_and_update(self, user: User = None, channel: Channel = None, guild: Guild = None):
        """Updates cache and PSQL tables if needed"""
        if channel:
            if not guild and channel.guild:
                guild = channel.guild
            if self._cache['channels'].get(channel.id) != channel:
                q, q_args = channel.to_psql()
                await self.bot.msg_queue.put(QueueItem(7, self.run_query(q, q_args, channel=channel, guild=guild)))
                self._cache['channels'][channel.id] = channel
                self.logger.info('Updated channel %s in guild %s', str(channel), str(guild))
        if guild and self._cache['guilds'].get(guild.id) != guild:
            q, q_args = guild.to_psql()
            await self.bot.msg_queue.put(QueueItem(6, self.run_query(q, q_args, guild=guild)))
            self._cache['guilds'][guild.id] = guild
            self.logger.info('Updated guild %s', str(guild))
        cached_user: Optional[User] = self._cache['users'].get(user.id)
        if user and cached_user != user:
            q, q_args = user.to_psql()
            await self.bot.msg_queue.put(QueueItem(8, self.run_query(q, q_args, user=user)))
            self.logger.info('Updated user %s', str(user))
        if not guild or not cached_user or not user:
            self._cache['users'][user.id] = user
            return
        # Do we need to update nickname?
        if cached_user.get_nick(guild.id) != user.get_nick(guild.id):
            q, q_args = user.to_psql_nick(guild.id)
            await self.bot.msg_queue.put(QueueItem(10, self.run_query(q, q_args, user=user, guild=guild)))
            self.logger.info('Updated user nick %s in guild %s', str(user), str(guild))
        self._cache['users'][user.id] = user

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

    #endregion


def setup(bot):
    bot.add_cog(Collector(bot))
