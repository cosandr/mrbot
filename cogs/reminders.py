from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, List

import asyncpg
import discord
import pytimeparse
import dateparser
from discord.ext import commands

import config as cfg
from ext import utils
from ext.context import Context
from ext.internal import User, Channel
from ext.parsers import parsers
from ext.psql import create_table

if TYPE_CHECKING:
    from mrbot import MrBot


class Reminders(commands.Cog, name="Reminders"):
    psql_table_name = 'reminders'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id         SERIAL UNIQUE,
            title      TEXT NOT NULL,
            recipients BIGINT [],
            notify_ts  TIMESTAMP NOT NULL,
            repeat     BIGINT,
            updated    TIMESTAMP,
            added      TIMESTAMP DEFAULT (NOW() at time zone 'utc'),
            fired      BOOLEAN DEFAULT false,
            failed     BOOLEAN DEFAULT false,
            owner_id   BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            channel_id BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE
        );
    """
    psql_all_tables = User.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        # Check table
        self.bot.loop.create_task(self.async_init())
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self._sleep_task: Optional[asyncio.Task] = None

    async def async_init(self):
        await self.bot.connect_task
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)
        await self.bot.wait_until_ready()
        await self.refresh_worker()

    @parsers.group(name='reminder', brief='Reminder group', invoke_without_command=True)
    async def reminder(self, ctx: Context):
        return

    @reminder.command(
        name='add',
        brief='Add item to reminders',
        parser_args=[
            parsers.Arg('title', nargs='+', help='Main item content'),
            parsers.Arg('--timestamp', '-t', required=True, nargs='+', help='Time for notification'),
            parsers.Arg('--channel', '-c', default=None, help='Optional channel'),
            parsers.Arg('--repeat', '-r', default=None, nargs='*', help='Optional repeat interval'),
            parsers.Arg('--recipients', '-u', default=None, nargs='*', help='Users which will be notified (you will always be notified)'),
        ],
    )
    async def reminder_add(self, ctx: Context):
        title = ' '.join(ctx.parsed.title)
        timestamp = ' '.join(ctx.parsed.timestamp)
        repeat = ' '.join(ctx.parsed.repeat) if ctx.parsed.repeat else None
        recipients = ctx.parsed.recipients or []
        channel = ctx.parsed.channel or ctx.channel.id
        # Try to parse
        parsed_ts = dateparser.parse(timestamp, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': False})
        parsed_repeat = None
        if not parsed_ts:
            return await ctx.send(f'Could not parse timestamp "{timestamp}"')
        if datetime.utcnow() >= parsed_ts:
            return await ctx.send('Reminder timestamp cannot be in the past')
        if repeat:
            parsed_repeat = pytimeparse.parse(repeat)
            if not parsed_repeat:
                return await ctx.send(f'Could not parse repeat interval "{repeat}"')

        users = []
        for r in recipients:
            u = await User.from_search(ctx, r)
            if not u:
                return await ctx.send(f'Could not find user {r}')
            # Silently ignore self
            if u.id == ctx.author.id:
                continue
            users.append(u.id)

        async with self.bot.pool.acquire() as con:
            q = (f"INSERT INTO {self.psql_table_name} (title, recipients, notify_ts, repeat, owner_id, channel_id) "
                 "VALUES ($1, $2, $3, $4, $5, $6)")
            await con.execute(q, title, users, parsed_ts, parsed_repeat, ctx.author.id, channel)
            await self.refresh_worker()
            # Fetch what we just added for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE owner_id=$1 AND notify_ts=$2 ORDER BY added DESC LIMIT 1"
            res = await con.fetchrow(q, ctx.author.id, parsed_ts)
        embed = await self.reminder_show_item(res, ctx)
        embed.set_author(name="Reminder Item Add", icon_url=str(ctx.author.avatar_url))
        return await ctx.send(embed=embed)

    @reminder.command(
        name='list',
        brief="List all reminders you're involved with",
        parser_args=[
            parsers.Arg('--absolute', '-a', default=False, help='Show absolute times', action='store_true'),
        ],
    )
    async def reminder_list(self, ctx):
        q = f"SELECT * FROM {self.psql_table_name} WHERE owner_id=$1 OR $1=ANY(recipients)"
        async with self.bot.pool.acquire() as con:
            result = await con.fetch(q, ctx.author.id)
        if len(result) == 0:
            await ctx.send(f"{ctx.author.display_name} is not involved with any reminders.")
            return
        tmp_val = []
        for res in result:
            if ctx.parsed.absolute:
                ts = self.format_dt_tz(res["notify_ts"])
                tmp_val.append(f'{res["id"]}: {res["title"]} at {ts}')
            else:
                ts = utils.human_timedelta_short(res["notify_ts"])
                tmp_val.append(f'{res["id"]}: {res["title"]} {ts}')
        for i, p in enumerate(utils.paginate("\n".join(tmp_val))):
            if i == 0:
                await ctx.send("Reminder summary:\n" + p)
                continue
            await ctx.send(p)

    @reminder.command(
        name='del',
        brief='Delete a reminder by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def reminder_del(self, ctx: Context):
        res = await self.get_reminder_item(ctx)
        if not res:
            return
        async with self.bot.pool.acquire() as con:
            q = f"DELETE FROM {self.psql_table_name} WHERE id=$1"
            await con.execute(q, ctx.parsed.index)
        await self.refresh_worker()
        embed = await self.reminder_show_item(res, ctx)
        embed.set_author(name="Reminder Deleted", icon_url=str(ctx.author.avatar_url))
        return await ctx.send(embed=embed)

    @reminder.command(
        name='show',
        brief='Show single item by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def reminder_show(self, ctx: Context):
        res = await self.get_reminder_item(ctx)
        if not res:
            return

        embed = await self.reminder_show_item(res, ctx)
        embed.set_author(name="Todo Item Show", icon_url=str(ctx.author.avatar_url))
        return await ctx.send(embed=embed)

    async def reminder_show_item(self, res: asyncpg.Record, ctx: Context = None, utc=False, firing=False):
        """Returns an embed for `res` PSQL query"""
        added = self.format_dt_tz(res['added'])
        tmp_val = f"Added: {added}\n"
        if not firing:
            notify_ts = self.format_dt_tz(res['notify_ts'])
            tmp_val += f"Notify at: {notify_ts}\n"
        if res['updated'] is not None:
            tmp_val += f"Updated: {self.format_dt_tz(res['updated'])}\n"
        if res['repeat']:
            tmp_val += f"Repeat: {utils.human_seconds(res['repeat'])}\n"
        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        embed.set_footer(
            text=f"Time is {'in UTC' if utc else 'local'}, date format dd.mm.yy",
            icon_url=str(self.bot.user.avatar_url),
        )
        embed.add_field(name=f"{res['id']}. {res['title']}",
                        value=tmp_val,
                        inline=False)
        if res['recipients'] and not firing:
            names = []
            for r in res['recipients']:
                u = await User.from_id(ctx, r, with_nick=True)
                if u:
                    names.append(u.display_name)
                else:
                    names.append(str(r))
            embed.add_field(name="Recipients",
                            value=", ".join(names),
                            inline=False)
        return embed

    async def get_reminder_item(self, ctx: Context):
        """Gets a reminder and checks if the caller can use it"""
        async with self.bot.pool.acquire() as con:
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        if not res:
            await ctx.send(f"No reminder with index {ctx.parsed.index} found")
            return None
        if not res['owner_id'] == ctx.author.id or ctx.author.id in res['recipients']:
            await ctx.send(f"Reminder with index {ctx.parsed.index} isn't yours")
            return None
        return res

    @staticmethod
    def format_dt_tz(dt: datetime, utc=False) -> str:
        if utc:
            return dt.strftime(cfg.TIME_FORMAT)
        return dt.replace(tzinfo=timezone.utc).astimezone().strftime(cfg.TIME_FORMAT)

    async def refresh_worker(self):
        if self._sleep_task:
            self._sleep_task.cancel()
        async with self.bot.pool.acquire() as con:
            q = f"SELECT * FROM {self.psql_table_name} WHERE fired=false AND failed=false ORDER BY notify_ts ASC LIMIT 1"
            results = await con.fetch(q)
        if not results:
            return
        self.bot.loop.create_task(self.sleep_worker(results))

    async def fire_reminder(self, res: asyncpg.Record):
        ch = self.bot.get_channel(res['channel_id'])
        q_failed = f"UPDATE {self.psql_table_name} SET failed=true WHERE id=$1"
        embed = await self.reminder_show_item(res, firing=True)
        repeat_td = timedelta(seconds=res['repeat']) if res['repeat'] else None
        self.logger.debug("Repeat: %s", repeat_td)
        async with self.bot.pool.acquire() as con:
            if not ch:
                self.logger.warning("Could not find channel %s for reminder ID %d", res['channel_id'], res['id'])
                await con.execute(q_failed, res['id'])
                return
            try:
                mentions = [User(id_=res['owner_id']).mention()]
                if res['recipients']:
                    mentions += [User(id_=r).mention() for r in res['recipients']]
                await ch.send(content=" ".join(mentions), embed=embed)
                if repeat_td:
                    new_dt = datetime.utcnow() + repeat_td
                    self.logger.debug("New time for reminder %d: %s", res['id'], utils.human_timedelta_short(res['notify_ts']))
                    q = f"UPDATE {self.psql_table_name} SET notify_ts=$2 WHERE id=$1"
                    await con.execute(q, res['id'], new_dt)
                    await self.refresh_worker()
                else:
                    q = f"UPDATE {self.psql_table_name} SET fired=true WHERE id=$1"
                    await con.execute(q, res['id'])
            except discord.DiscordException as e:
                self.logger.error("Could not send reminder ID %d: %s", res['id'], str(e))
                await con.execute(q_failed, res['id'])

    async def sleep_worker(self, results: List[asyncpg.Record]):
        for r in results:
            start = datetime.utcnow()
            if start >= r['notify_ts']:
                self.logger.debug("Got reminder from the past [%s], firing immediately", utils.human_timedelta_short(r['notify_ts']))
                await self.fire_reminder(r)
                continue
            duration = abs((start - r['notify_ts']).total_seconds())
            try:
                self.logger.debug("Sleep task starting, %s [%d seconds]", utils.human_seconds(duration), duration)
                await asyncio.sleep(duration)
                await self.fire_reminder(r)
            except asyncio.CancelledError:
                ran_for = (datetime.utcnow() - start).total_seconds()
                self.logger.debug("Sleep task cancelled, %s remaining", utils.human_seconds(ran_for))
                return


def setup(bot):
    bot.add_cog(Reminders(bot))
