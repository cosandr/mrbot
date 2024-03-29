from __future__ import annotations

import itertools
import logging
import re
from typing import TYPE_CHECKING, List

import discord
from discord.ext import commands

import config as cfg
from ext import utils
from ext.context import Context
from ext.internal import Message, User, Guild
from ext.parsers import parsers
from ext.psql import create_table, try_run_query
from .pasta import Pasta

if TYPE_CHECKING:
    from mrbot import MrBot


class PastaCog(commands.Cog, name="Pasta"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.re_id = re.compile(r'\d{18}')

    async def cog_load(self):
        await self.bot.sess_ready.wait()
        names = itertools.chain(*Pasta.psql_all_tables.keys())
        q = Pasta.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)

    @parsers.group(
        name='pasta',
        brief='Fine selection of pastas available',
        invoke_without_command=True,
        parser_args=[
            parsers.Arg('name', type=str, help='Pasta name'),
            parsers.Arg('--all', default=False, help='Include pasta for which you lack permissions', action='store_true'),
        ],
    )
    async def pasta(self, ctx: Context):
        q = Pasta.make_psql_query_full(where='p.name=$1')
        res = await self.bot.pool.fetchrow(q, ctx.parsed.name)
        if p := Pasta.from_psql_res(res):
            return await p.maybe_send(ctx)
        all_pasta = await self.list_all_pasta_names(ctx, ctx.parsed.all)
        if not all_pasta:
            return await ctx.send('No pastas available.')

        if meant := utils.find_similar_str(ctx.parsed.name, all_pasta):
            return await ctx.send(f'Pasta `{ctx.parsed.name}` not found, did you mean: {self.format_pasta_names(meant, question=True)}')

        return await ctx.send(f'Pasta `{ctx.parsed.name}` not found, all available pasta: {self.format_pasta_names(all_pasta)}')

    @pasta.command(
        name='info',
        brief='Display pasta info',
        parser_args=[
            parsers.Arg('name', type=str.lower, help='Pasta name'),
        ],
    )
    async def pasta_info(self, ctx: Context):
        q = Pasta.make_psql_query_full(where='p.name=$1')
        res = await self.bot.pool.fetchrow(q, ctx.parsed.name)
        p = Pasta.from_psql_res(res)
        if not p:
            return await ctx.send(f'No pasta {ctx.parsed.name} found.')
        if not p.check_permissions(ctx):
            p.content = "HIDDEN"
        return await ctx.send(embed=self.embed_pasta_info(p))

    @pasta.command(
        name='list',
        aliases=['search'],
        brief='Show or search pastas',
        parser_args=[
            parsers.Arg('name', nargs='?', help='Pasta name'),
            parsers.Arg('--all', default=False, help='Include pasta for which you lack permissions', action='store_true'),
        ],
    )
    async def pasta_list(self, ctx: Context):
        all_pasta = await self.list_all_pasta_names(ctx, ctx.parsed.all)
        if not all_pasta:
            return await ctx.send('No pastas available.')
        # No search requested, list all
        if not ctx.parsed.name:
            return await ctx.send(f'Available pastas: {self.format_pasta_names(all_pasta)}')

        if meant := utils.find_similar_str(ctx.parsed.name, all_pasta):
            return await ctx.send(f'{utils.fmt_plural_str(len(meant), "pasta")} similar to `{ctx.parsed.name}` found: {self.format_pasta_names(meant)}')

        await ctx.send(f'No pasta close to `{ctx.parsed.name}` found.')

    @pasta.command(
        name='add',
        aliases=['import'],
        brief='Add a new pasta',
        parser_args=[
            parsers.Arg('name', type=str.lower, help='Pasta name'),
            parsers.Arg('content', nargs='*', help='Pasta content'),
            parsers.Arg('-m', '--message-id', type=int, action='append', help='Use content from message IDs'),
            parsers.Arg('--no-user', default=False, help='Do not register yourself as owner', action='store_true'),
            parsers.Arg('--no-guild', default=False, help='Do not register pasta with the current guild', action='store_true'),
        ],
    )
    async def pasta_add(self, ctx: Context):
        if not ctx.parsed.content and not ctx.parsed.message_id:
            return await ctx.send('Provide content or message IDs')
        q = Pasta.make_psql_query_full(where='p.name=$1')
        res = await self.bot.pool.fetchrow(q, ctx.parsed.name)
        if p := Pasta.from_psql_res(res):
            return await ctx.send(f'Pasta {ctx.parsed.name} already exists.', embed=self.embed_pasta_info(p))
        # Did we get content directly?
        if ctx.parsed.content:
            content = ' '.join(ctx.parsed.content)
        # Construct pasta from ID's
        else:
            content = ''
            for msg_id in ctx.parsed.message_id:
                msg = await Message.from_id(self.bot, msg_id, ctx.channel.id)
                if not msg:
                    return await ctx.send(f"No message with ID {msg_id} found.")
                content += msg.content
        user = None
        if not ctx.parsed.no_user:
            user = User.from_discord(ctx.author)
        guild = None
        if not ctx.parsed.no_guild:
            guild = Guild.from_discord(ctx.guild)
        p = Pasta(name=ctx.parsed.name, content=content, user=user, guild=guild)
        async with self.bot.pool.acquire() as con:
            async with con.transaction():
                q, q_args = p.to_psql()
                await try_run_query(con, q, q_args, self.logger, user=user, guild=guild)
        return await ctx.send("New pasta registered.", embed=self.embed_pasta_info(p))

    @pasta.command(
        name='del',
        aliases=['delete', 'remove', 'rem'],
        brief='Delete a pasta',
        parser_args=[
            parsers.Arg('name', type=str.lower, help='Pasta name'),
        ],
    )
    async def pasta_del(self, ctx: Context):
        q = Pasta.make_psql_query_full(where='p.name=$1')
        res = await self.bot.pool.fetchrow(q, ctx.parsed.name)
        p = Pasta.from_psql_res(res)
        if not p:
            return await ctx.send(f'No pasta {ctx.parsed.name} found.')
        if err := p.edit_error(ctx):
            return await ctx.send(err)
        async with self.bot.pool.acquire() as con:
            async with con.transaction():
                q = f"DELETE FROM {Pasta.psql_table_name} WHERE name=$1"
                await con.execute(q, ctx.parsed.name)
        return await ctx.send('Pasta removed.', embed=self.embed_pasta_info(p))

    @pasta.command(
        name='edit',
        brief='Edit a pasta',
        parser_args=[
            parsers.Arg('target', type=str.lower, help='Pasta name'),
            parsers.Arg('-n', '--name', type=str.lower, help='Change name'),
            parsers.Arg('-c', '--content', nargs='*', help='Change content'),
            parsers.Arg('-m', '--message-id', type=int, action='append', help='Use content from message IDs'),
            parsers.Arg('-u', '--user', type=int, help='Change owner, use 0 to remove'),
            parsers.Arg('-g', '--guild-id', type=int, help='Change guild, use 0 to remove'),
        ],
    )
    async def pasta_edit(self, ctx: Context):
        q = Pasta.make_psql_query_full(where='p.name=$1')
        res = await self.bot.pool.fetchrow(q, ctx.parsed.target)
        p = Pasta.from_psql_res(res)
        if not p:
            return await ctx.send(f'No pasta {ctx.parsed.target} found.')
        if err := p.edit_error(ctx):
            return await ctx.send(err)
        new_p = p.copy()
        # Check if new name already exists
        if ctx.parsed.name:
            q = f'SELECT count(1) FROM {Pasta.psql_table_name} WHERE name=$1'
            if await self.bot.pool.fetchval(q, ctx.parsed.name):
                return await ctx.send(f'Pasta with name {ctx.parsed.name} is already registered.')
            new_p.name = ctx.parsed.name
        if ctx.parsed.content:
            new_p.content = ' '.join(ctx.parsed.content)
        # Construct pasta from ID's
        elif ctx.parsed.message_id:
            new_p.content = ''
            for msg_id in ctx.parsed.message_id:
                msg = await Message.from_id(self.bot, msg_id, ctx.channel.id)
                if not msg:
                    return await ctx.send(f"No message with ID {msg_id} found.")
                new_p.content += msg.content
        user = None
        if ctx.parsed.user is not None:
            if ctx.parsed.user:
                user = await User.from_search(ctx, ctx.parsed.user)
                if not user:
                    return await ctx.send(f'No user {ctx.parsed.user} found')
            new_p.user = user
        guild = None
        if ctx.parsed.guild_id is not None:
            if ctx.parsed.guild_id:
                d_guild = discord.utils.find(lambda g: g.id == ctx.parsed.guild_id, self.bot.guilds)
                if not d_guild:
                    return await ctx.send(f'The bot is not a member of any guild with ID {ctx.parsed.guild_id}')
                guild = Guild.from_discord(d_guild)
            new_p.guild = guild
        if p == new_p:
            return await ctx.send('No changes requested.')
        async with self.bot.pool.acquire() as con:
            async with con.transaction():
                # Delete old entry
                q = f"DELETE FROM {Pasta.psql_table_name} WHERE name=$1"
                await con.execute(q, ctx.parsed.target)
                # Add new entry
                q, q_args = new_p.to_psql()
                await try_run_query(con, q, q_args, self.logger, user=user, guild=guild)
        return await ctx.send(f'{ctx.parsed.target} edited', embed=self.embed_pasta_info(new_p))

    @staticmethod
    def embed_pasta_info(p: Pasta, max_content_len=50) -> discord.Embed:
        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        extra_len = len(p.content) - max_content_len
        if extra_len <= 0:
            content = p.content
        else:
            content = f'{p.content[:max_content_len]} ... {extra_len} more characters'

        embed.add_field(name='Name', value=p.name, inline=False)
        embed.add_field(name='Content', value=content, inline=False)
        if p.owner_name:
            embed.add_field(name='Owner', value=p.owner_name, inline=True)
        if p.guild:
            embed.add_field(name='Guild', value=p.guild.name if p.guild.name else str(p.guild.id), inline=True)
        if p.added:
            embed.add_field(name='Added', value=utils.format_dt(p.added, cfg.TIME_FORMAT, cfg.TIME_ZONE), inline=False)
        return embed

    @staticmethod
    def format_pasta_names(names: List[str], question=False) -> str:
        if len(names) > 6:
            return f'```{utils.to_columns_vert(names, num_cols=4, sort=False)}```'
        if question:
            return ', '.join(names) + '?'
        return ', '.join(names)

    async def get_all_pasta(self) -> List[Pasta]:
        q = Pasta.make_psql_query()
        results = await self.bot.pool.fetch(q)
        all_pastas = []
        for r in results:
            all_pastas.append(Pasta.from_psql_res(r))
        return all_pastas

    async def list_all_pasta_names(self, ctx: Context, all_=False):
        all_pastas = await self.get_all_pasta()
        names = []
        for p in all_pastas:
            if p.check_permissions(ctx):
                names.append(p.name)
            elif all_:
                names.append(f'{p.name}*')
        return names
