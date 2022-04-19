from __future__ import annotations

import asyncio
import itertools
import logging
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord.ext import commands

import config as cfg
from ext.context import Context
from ext.errors import UnapprovedGuildError
from ext.internal import Message
from ext.psql import create_table, debug_query

if TYPE_CHECKING:
    from mrbot import MrBot


class Stars(commands.Cog, name='Stars'):
    psql_table_name = 'stars'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            msg_id BIGINT NOT NULL UNIQUE REFERENCES {Message.psql_table_name} (msg_id) ON DELETE CASCADE,
            posted_id BIGINT REFERENCES {Message.psql_table_name} (msg_id),
            count SMALLINT NOT NULL
        );
    """
    psql_all_tables = Message.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        # TODO: Store in config, per guild
        self.count_threshold = 2

    async def cog_load(self):
        await self.bot.sess_ready.wait()
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)

    async def cog_check(self, ctx: Context):
        if await self.bot.is_owner(ctx.author):
            return True
        # Ignore DMs
        if not ctx.guild:
            raise UnapprovedGuildError()
        return True

    @commands.group(name='stars', brief='Top starred messages', invoke_without_command=True)
    async def stars(self, ctx: Context):
        embed = discord.Embed()
        async with self.bot.pool.acquire() as con:
            res = await con.fetch(f'SELECT msg_id, posted_id, count FROM {self.psql_table_name} ORDER BY count DESC LIMIT 10')
            for r in res:
                # Use bot so we don't try to query API
                orig_msg = await Message.from_id(self.bot, r['msg_id'])
                name, value = orig_msg.discord_embed_field
                if r['posted_id']:
                    posted_msg = await Message.from_id(self.bot, r['posted_id'])
                    value += f'\n[{r["count"]} stars]({posted_msg.jump_url})'
                else:
                    value += f'\n{r["count"]} stars'
                embed.add_field(name=name, value=value, inline=False)
        return await ctx.send(embed=embed)

    @commands.has_permissions(administrator=True)
    @stars.command(name='add', brief='Immediately add message to starred list')
    async def stars_add(self, ctx: Context, msg_id: int):
        msg: Message = await Message.from_id(self.bot, msg_id, ctx.channel.id)
        if not msg:
            return await ctx.send(f'Message with ID {msg_id} not found.')
        q = (f'INSERT INTO {self.psql_table_name} (msg_id, count) VALUES ($1, $2) ON CONFLICT (msg_id) '
             f'DO UPDATE SET count=({self.psql_table_name}).count+1')
        await self.run_query(q, (msg_id, 1))
        await self._post_starred(msg.id, msg.channel.id, msg.guild.id)

    @commands.has_permissions(administrator=True)
    @stars.command(name='rm', brief='Immediately remove message from starred list')
    async def stars_rm(self, ctx: Context, msg_id: int):
        posted_id: int = await self.bot.pool.fetchval(f'SELECT posted_id FROM {self.psql_table_name} WHERE msg_id=$1', msg_id)
        if posted_id is None:
            return await ctx.send(f'Message with ID {msg_id} not starred.')
        ok = await self._remove_starred(msg_id, ctx.guild.id)
        if not ok:
            return await ctx.send('Failed to unstar message, check logs.')
        return await ctx.send('Message unstarred.')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        # Ignore DMs
        if not payload.guild_id:
            return
        # Ignore non-star emoji
        if str(payload.emoji) != cfg.STAR:
            return
        await self._increment_stars(payload.message_id, 1)
        count = await self.bot.pool.fetchval(f'SELECT count FROM {self.psql_table_name} WHERE msg_id=$1', payload.message_id)
        if count and count >= self.count_threshold:
            asyncio.create_task(self._post_starred(payload.message_id, payload.channel_id, payload.guild_id))

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        # Ignore DMs
        if not payload.guild_id:
            return
        # Ignore non-star emoji
        if str(payload.emoji) != cfg.STAR:
            return
        # Get existing count
        count = await self.bot.pool.fetchval(f'SELECT count FROM {self.psql_table_name} WHERE msg_id=$1', payload.message_id)
        count -= 1
        # This message isn't in the table
        if count is None:
            return
        # We're at 0, remove from table and starred channel if applicable
        if count <= 0:
            asyncio.create_task(self._remove_starred(payload.message_id, payload.guild_id))
        else:
            await self.run_query(f'UPDATE {self.psql_table_name} SET count=$2 WHERE msg_id=$1', (payload.message_id, count))

    async def _increment_stars(self, msg_id: int, count: int = 1):
        q = (f'INSERT INTO {self.psql_table_name} (msg_id, count) VALUES ($1, $2) ON CONFLICT (msg_id) '
             f'DO UPDATE SET count=({self.psql_table_name}).count+1')
        await self.run_query(q, (msg_id, count))

    async def _post_starred(self, msg_id: int, ch_id: int, guild_id: int):
        # Get #starred channel
        ch: discord.TextChannel = discord.utils.get(self.bot.get_guild(guild_id).text_channels, name='starred')
        if ch is None:
            self.logger.warning('Guild %d does not have a #starred channel.', guild_id)
            return
        # Fetch message
        msg = await Message.from_id(self.bot, msg_id, ch_id=ch_id)
        if not msg:
            self.logger.warning('Could not fetch message by ID: %d', msg_id)
            return
        embed = msg.discord_embed
        embed.colour = discord.Colour.gold()
        try:
            posted_msg = await ch.send(embed=embed)
        except discord.errors.Forbidden:
            self.logger.error(f'Bot cannot post in channel {str(ch)}')
            return
        # Update entry in PSQL
        await self.run_query(f'UPDATE {self.psql_table_name} SET posted_id=$2 WHERE msg_id=$1', (msg_id, posted_msg.id))

    async def _remove_starred(self, msg_id: int, guild_id: int) -> bool:
        posted_id = await self.bot.pool.fetchval(f'SELECT posted_id FROM {self.psql_table_name} WHERE msg_id=$1', msg_id)
        ok = await self.run_query(f'DELETE FROM {self.psql_table_name} WHERE msg_id=$1', (msg_id, ))
        if not posted_id:
            return ok
        # Get #starred channel
        ch: discord.TextChannel = discord.utils.get(self.bot.get_guild(guild_id).text_channels, name='starred')
        d_msg: discord.Message = await Message.to_discord_from_id(self.bot, posted_id, ch.id)
        ok = True
        if not d_msg:
            ok = False
            self.logger.warning('Could not fetch Discord message by ID: %d', posted_id)
            return ok
        try:
            await d_msg.delete()
        except Exception as e:
            ok = False
            self.logger.warning('Could not delete Discord message with ID %d: %s', posted_id, e)
        return ok

    async def run_query(self, q: str, q_args: tuple):
        for _ in range(3):
            try:
                await self.bot.pool.execute(q, *q_args)
                return True
            except asyncpg.exceptions.InterfaceError as e:
                self.logger.error('Connection interface error, will retry: %s', str(e))
                continue
            except asyncpg.exceptions.UniqueViolationError as e:
                self.logger.warning(str(e))
            except asyncpg.exceptions.ForeignKeyViolationError as e:
                self.logger.error('Foreign key is missing: %s', str(e))
                await self.bot.msg_queue.join()
                continue
            except Exception as e:
                self.logger.error('Connection exec failed: %s', str(e))
                debug_query(q, q_args, e)
        return False


async def setup(bot):
    await bot.add_cog(Stars(bot))
