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
from ext.internal import User
from ext.parsers import parsers
from ext.parsers.errors import ArgParseError
from ext.psql import create_table, ensure_foreign_key, debug_query
from ext.utils import format_dt, str_or_none

if TYPE_CHECKING:
    from mrbot import MrBot


class Todo(commands.Cog, name="Todo"):
    psql_table_name = 'todo'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id        SERIAL UNIQUE,
            priority  SMALLINT NOT NULL DEFAULT 2,
            title     TEXT NOT NULL,
            extra     TEXT,
            done      TIMESTAMPTZ,
            updated   TIMESTAMPTZ,
            added     TIMESTAMPTZ DEFAULT NOW(),
            user_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE
        );
        CREATE OR REPLACE FUNCTION update_{psql_table_name}_time()
            RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS trigger_update_{psql_table_name}_time ON {psql_table_name};
        CREATE TRIGGER trigger_update_{psql_table_name}_time BEFORE update ON {psql_table_name}
        FOR EACH ROW WHEN (NEW.done IS NULL) EXECUTE PROCEDURE update_{psql_table_name}_time();
    """
    psql_all_tables = User.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        # Priorities
        self.num_to_prio = {0: "critical",
                            1: "high",
                            2: "normal",
                            3: "low",
                            4: "maybe"}
        self.prio_to_num = {v: k for k, v in self.num_to_prio.items()}
        self.prio_str = ', '.join(self.num_to_prio.values())

    async def cog_load(self):
        await self.bot.sess_ready.wait()
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)

    @parsers.group(
        name='todo',
        brief='Display all your items',
        invoke_without_command=True,
        parser_args=[
            parsers.Arg('--priority', '-p', default='all', help='Filter priority'),
            parsers.Arg('--done', '-d', default=False, help='Show done', action='store_true'),
        ],
    )
    async def todo(self, ctx: Context):
        q = self.create_list_query(ctx.parsed)
        async with self.bot.pool.acquire() as con:
            result = await con.fetch(q, ctx.author.id)
        if len(result) == 0:
            return await ctx.send(f"{ctx.author.display_name} doesn't have any entries in their todo list.")
        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        embed.set_footer(text=f"Timezone is {cfg.TIME_ZONE}, date format dd.mm.yy", icon_url=str_or_none(self.bot.user.avatar))
        embed.set_author(name=ctx.author.display_name, icon_url=str_or_none(ctx.author.avatar))
        all_fields = []
        prio_count = {v: 0 for v in self.num_to_prio.values()}
        for res in result:
            prio = self.num_to_prio[res['priority']]
            prio_count[prio] += 1
            timestamp = format_dt(res['added'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
            tmp_val = f"Priority: {prio}\nAdded: {timestamp}\nExtra: {res['extra']}\n"
            if res['updated'] is not None:
                tmp_val += f"Updated: {format_dt(res['updated'], cfg.TIME_FORMAT, cfg.TIME_ZONE)}\n"
            if res['done'] is not None:
                tmp_val += f"Done: {format_dt(res['done'], cfg.TIME_FORMAT, cfg.TIME_ZONE)}\n"
            all_fields.append({'name': f"{res['id']}. {res['title']}",
                               'value': tmp_val})
        item_sum = "Item summary:\n"
        for k, v in prio_count.items():
            if v != 0:
                item_sum += f"{k.capitalize()}: {v}\n"
        step = 5
        start = 0
        end = len(all_fields) if len(all_fields) <= step else step
        for i in range(start, end):
            name = all_fields[i]['name']
            value = all_fields[i]['value']
            embed.add_field(name=name, value=value, inline=False)
        msg = await ctx.send(content=f"{item_sum}Showing {start}-{end} out of {len(all_fields)}.", embed=embed)
        # Do not paginate if there aren't too many items
        if end == len(all_fields):
            return
        # Paginate results
        control_em = ['⬅', '➡']
        for em in control_em:
            await msg.add_reaction(em)

        def check(r: discord.Reaction, u: discord.User):
            return (r.message.id == msg.id and str(r.emoji) in control_em and
                    u.id == ctx.author.id)

        def upd_bounds(_start, _end, _step):
            """Updates paginator bounds, there is no loop functionality."""
            _start += _step
            _end += _step
            if _end >= len(all_fields):
                diff = _end - len(all_fields)
                _end -= diff
                _start -= diff
            elif _start < 0:
                _start = 0
                _end = abs(_step)
            return _start, _end

        while True:
            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                break
            else:
                em = str(reaction.emoji)
                if em == '⬅':
                    start, end = upd_bounds(start, end, -step)
                else:
                    start, end = upd_bounds(start, end, step)
                embed.clear_fields()
                for i in range(start, end):
                    name = all_fields[i]['name']
                    value = all_fields[i]['value']
                    embed.add_field(name=name, value=value, inline=False)
                msg = await msg.edit(content=f"{item_sum}Showing {start}-{end} out of {len(all_fields)}.", embed=embed)
                await msg.remove_reaction(em, user)
        # 15-16 goes to 10-11
        await msg.clear_reactions()

    @todo.command(
        name='add',
        brief='Add item to todo list',
        parser_args=[
            parsers.Arg('title', nargs='+', help='Main item content'),
            parsers.Arg('--priority', '-p', default='normal', help='Item priority'),
            parsers.Arg('--extra', '-e', default=None, nargs='*', help='Extra information'),
        ],
    )
    async def todo_add(self, ctx: Context):
        add_prio = self.prio_to_num.get(ctx.parsed.priority.lower(), None)
        title = ' '.join(ctx.parsed.title)
        extra = ' '.join(ctx.parsed.extra) if ctx.parsed.extra is not None else None
        if add_prio is None:
            return await ctx.send((f"Unrecognized priority {ctx.parsed.priority}. "
                                   f"Available priorities: `{self.prio_str}`."))
        async with self.bot.pool.acquire() as con:
            for _ in range(2):
                try:
                    q = (f"INSERT INTO {self.psql_table_name} (title, extra, priority, user_id) "
                         "VALUES ($1, $2, $3, $4)")
                    await con.execute(q, title, extra, add_prio, ctx.author.id)
                    break
                except asyncpg.exceptions.ForeignKeyViolationError:
                    ok = await ensure_foreign_key(con=con, obj=User.from_discord(ctx.author), logger=self.logger)
                    if not ok:
                        break
            # Fetch what we just added for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE user_id=$1 ORDER BY added DESC LIMIT 1"
            res = await con.fetchrow(q, ctx.author.id)
        embed = self.todo_show_item(res)
        embed.set_author(name="Todo Item Add", icon_url=str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @todo.command(
        name='edit',
        brief='Edit item in todo list',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
            parsers.Arg('--title', '-t', default=None, nargs='*', help='Main content'),
            parsers.Arg('--priority', '-p', default=None, help='Item priority'),
            parsers.Arg('--extra', '-e', default=None, nargs='*', help='Extra information'),
        ],
    )
    async def todo_edit(self, ctx: Context):
        if not await self.check_todo_item(ctx, ctx.parsed.index):
            return
        q = f"UPDATE {self.psql_table_name} SET "
        q_args = []
        q_tmp = []
        if ctx.parsed.priority:
            add_prio = self.prio_to_num.get(ctx.parsed.priority.lower())
            if add_prio is None:
                return await ctx.send((f"Unrecognized priority {ctx.parsed.priority}. "
                                       f"Available priorities: `{self.prio_str}`."))
            q_args.append(add_prio)
            q_tmp.append(f"priority=${len(q_args)}")
        if ctx.parsed.title:
            q_args.append(' '.join(ctx.parsed.title))
            q_tmp.append(f"title=${len(q_args)}")
        if ctx.parsed.extra:
            q_args.append(' '.join(ctx.parsed.extra))
            q_tmp.append(f"extra=${len(q_args)}")
        if len(q_args) == 0:
            await ctx.send(f"You must specify something to edit.")
            return
        q += ','.join(q_tmp)
        q_args.append(ctx.parsed.index)
        q += f" WHERE id=${len(q_args)}"
        async with self.bot.pool.acquire() as con:
            try:
                await con.execute(q, *q_args)
            except Exception as e:
                debug_query(q, q_args, e)
                raise e
            # Fetch what we just added for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        embed = self.todo_show_item(res)
        embed.set_author(name="Todo Item Edit", icon_url=str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @todo.command(
        name='done',
        brief='Mark item as done from todo list by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def todo_done(self, ctx: Context):
        if not await self.check_todo_item(ctx, ctx.parsed.index):
            return
        async with self.bot.pool.acquire() as con:
            q = f"UPDATE {self.psql_table_name} SET done=NOW() WHERE id=$1"
            await con.execute(q, ctx.parsed.index)
            # Fetch what we just marked done for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        embed = self.todo_show_item(res)
        embed.set_author(name="Todo Item Done", icon_url=str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @todo.command(
        name='undo',
        brief='Mark item as undone from todo list by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def todo_undo(self, ctx: Context):
        if not await self.check_todo_item(ctx, ctx.parsed.index):
            return
        async with self.bot.pool.acquire() as con:
            q = f"UPDATE {self.psql_table_name} SET done=NULL WHERE id=$1"
            await con.execute(q, ctx.parsed.index)
            # Fetch what we just marked undone for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        embed = self.todo_show_item(res)
        embed.set_author(name="Todo Item Undo", icon_url=str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @todo.command(
        name='del',
        brief='Delete item from todo list by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def todo_del(self, ctx: Context):
        if not await self.check_todo_item(ctx, ctx.parsed.index):
            return
        async with self.bot.pool.acquire() as con:
            # Fetch what we are deleting for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
            q = f"DELETE FROM {self.psql_table_name} WHERE id=$1"
            await con.execute(q, ctx.parsed.index)
        embed = self.todo_show_item(res)
        embed.set_author(name="Todo Item Deleted", icon_url=str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @todo.command(
        name='show',
        brief='Show single item by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def todo_show(self, ctx: Context):
        if not await self.check_todo_item(ctx, ctx.parsed.index):
            return
        async with self.bot.pool.acquire() as con:
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        embed = self.todo_show_item(res)
        embed.set_author(name="Todo Item Show", icon_url=str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @todo.command(
        name='list',
        brief='List all items in a compact form',
        parser_args=[
            parsers.Arg('--priority', '-p', default='all', help='Filter priority'),
            parsers.Arg('--done', '-d', default=False, help='Show done', action='store_true'),
        ],
    )
    async def todo_list(self, ctx: Context):
        q = self.create_list_query(ctx.parsed)
        async with self.bot.pool.acquire() as con:
            result = await con.fetch(q, ctx.author.id)
        if len(result) == 0:
            await ctx.send(f"{ctx.author.display_name} doesn't have any entries in their todo list.")
            return

        tmp_val = ""
        prio_count = {v: 0 for v in self.num_to_prio.values()}
        for res in result:
            prio = self.num_to_prio[res['priority']]
            prio_count[prio] += 1
            if res['done'] is not None:
                tmp_val += "✅ "
            tmp_val += f"{prio}[{res['id']}]: {res['title']}\n"
        item_sum = f"Item summary:\n"
        for k, v in prio_count.items():
            if v != 0:
                item_sum += f"{k.capitalize()}: {v}\n"
        ret_str = f"{item_sum}```{tmp_val}```"
        if len(ret_str) < 1950:
            await ctx.send(f"{ret_str}")
            return
        ret_str = "```"
        lines = tmp_val.split('\n')
        for line in lines:
            if len(ret_str) + len(line) > 1950:
                await ctx.send(f"{ret_str}```")
                ret_str = "```"
            ret_str += f"{line}\n"
        await ctx.send(f"{ret_str}```")

    def todo_show_item(self, res: asyncpg.Record):
        """Returns an embed for `res` PSQL query"""
        prio = self.num_to_prio[res['priority']]
        timestamp = format_dt(res['added'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
        tmp_val = f"Priority: {prio}\nAdded: {timestamp}\nExtra: {res['extra']}\n"
        if res['updated'] is not None:
            tmp_val += f"Updated: {format_dt(res['updated'], cfg.TIME_FORMAT, cfg.TIME_ZONE)}\n"
        if res['done'] is not None:
            tmp_val += f"Done: {format_dt(res['done'], cfg.TIME_FORMAT, cfg.TIME_ZONE)}\n"
        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        embed.set_footer(text=f"Timezone is {cfg.TIME_ZONE}, date format dd.mm.yy", icon_url=str_or_none(self.bot.user.avatar))
        embed.add_field(name=f"{res['id']}. {res['title']}",
                        value=tmp_val,
                        inline=False)
        return embed

    async def check_todo_item(self, ctx: Context, idx: int):
        """Check whether or not given item is from the author"""
        async with self.bot.pool.acquire() as con:
            q = f"SELECT count(1) FROM {self.psql_table_name} WHERE id=$1"
            result = await con.fetchrow(q, idx)
            if result['count'] == 0:
                await ctx.send(f"Invalid index {idx}.")
                return False
            q = f"SELECT count(1) FROM {self.psql_table_name} WHERE id=$1 AND user_id=$2"
            result = await con.fetchrow(q, idx, ctx.author.id)
            if result['count'] == 0:
                await ctx.send("Requested item isn't yours.")
                return False
        return True

    def create_list_query(self, parsed):
        q = f"SELECT * FROM {self.psql_table_name} WHERE user_id=$1 "
        if parsed.done:
            q += "AND done IS NOT NULL "
        else:
            q += "AND done IS NULL "
        if parsed.priority != 'all':
            list_prio = self.prio_to_num.get(parsed.priority.lower(), None)
            if list_prio is None:
                raise ArgParseError((f"Unrecognized priority {parsed.priority}. "
                                     f"Available priorities: `{self.prio_str}`."))
            q += f"AND priority<={list_prio} "
        q += "ORDER BY priority ASC"
        return q


async def setup(bot):
    await bot.add_cog(Todo(bot))
