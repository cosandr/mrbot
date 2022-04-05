from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

import asyncpg
import dateparser
import discord
import pytimeparse
from discord.ext import commands

import config as cfg
from ext import utils
from ext.context import Context
from ext.internal import User, Channel
from ext.parsers import parsers
from ext.psql import create_table, ensure_foreign_key

if TYPE_CHECKING:
    from mrbot import MrBot


class Reminders(commands.Cog, name="Reminders"):
    psql_table_name = 'reminders'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id          SERIAL UNIQUE,
            title       TEXT NOT NULL,
            description TEXT,
            recipients  BIGINT [],
            notify_ts   TIMESTAMPTZ NOT NULL,
            repeat      BIGINT,
            repeat_n    INTEGER,
            updated     TIMESTAMPTZ,
            added       TIMESTAMPTZ DEFAULT NOW(),
            done        BOOLEAN DEFAULT false,
            failed      BOOLEAN DEFAULT false,
            owner_id    BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            channel_id  BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE
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
            parsers.Arg('--description', '-d', default=None, nargs='*', help='Optional description'),
            parsers.Arg('--timestamp', '-t', required=True, nargs='+', help='Time for notification'),
            parsers.Arg('--channel', '-c', default=None, help='Optional channel'),
            parsers.Arg('--repeat', '-r', default=None, nargs='*', help='Optional repeat interval'),
            parsers.Arg('--repeat-times', '-n', default=None, type=int, help='Number of times to repeat'),
            parsers.Arg('--recipients', '-u', default=None, nargs='*', help='Users which will be notified (you will always be notified)'),
        ],
    )
    async def reminder_add(self, ctx: Context):
        title = ' '.join(ctx.parsed.title)
        description = ' '.join(ctx.parsed.description) if ctx.parsed.description else None
        # Try to parse
        parse_ret = await self.parse_reminder_args(ctx)
        if isinstance(parse_ret, discord.Message):
            return
        parsed_ts, parsed_repeat, channel, users = parse_ret
        async with self.bot.pool.acquire() as con:
            q = (f"INSERT INTO {self.psql_table_name} (title, description, recipients, notify_ts, repeat, repeat_n, owner_id, channel_id) "
                 "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)")
            for _ in range(2):
                try:
                    await con.execute(q, title, description, users, parsed_ts, parsed_repeat, ctx.parsed.repeat_times, ctx.author.id, channel.id)
                    break
                except asyncpg.exceptions.ForeignKeyViolationError:
                    user_ok = await ensure_foreign_key(con=con, obj=User.from_discord(ctx.author), logger=self.logger)
                    ch_ok = await ensure_foreign_key(con=con, obj=Channel.from_discord(channel), logger=self.logger)
                    if not user_ok or not ch_ok:
                        return await ctx.send("Database error, could not add user or channel.")
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
            parsers.Arg('--all', '-a', default=False, help='Include reminders marked as done', action='store_true'),
            parsers.Arg('--absolute', default=False, help='Show absolute times', action='store_true'),
        ],
    )
    async def reminder_list(self, ctx):
        q = f"SELECT * FROM {self.psql_table_name} WHERE (owner_id=$1 OR $1=ANY(recipients))"
        if not ctx.parsed.all:
            q += " AND done=false"
        q += " ORDER BY notify_ts DESC"
        async with self.bot.pool.acquire() as con:
            result = await con.fetch(q, ctx.author.id)
        if len(result) == 0:
            await ctx.send(f"{ctx.author.display_name} has no pending or failed reminders.")
            return
        tmp_val = ""
        for res in result:
            if res['failed']:
                tmp_val += "❌ "
            elif res['done']:
                tmp_val += "✅ "
            if ctx.parsed.absolute:
                ts = self.format_dt_tz(res["notify_ts"])
                tmp_val += f'{res["id"]}: {res["title"]} at {ts}\n'
            else:
                ts = utils.human_timedelta_short(res["notify_ts"])
                tmp_val += f'{res["id"]}: {res["title"]} {ts}\n'
        for i, p in enumerate(utils.paginate(tmp_val)):
            if i == 0:
                await ctx.send("Reminder summary:\n" + p)
                continue
            await ctx.send(p)

    @reminder.command(
        name='edit',
        brief='Edit a reminder by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
            parsers.Arg('--title', '-s', default=None, nargs='*', help='Main item content'),
            parsers.Arg('--description', '-d', default=None, nargs='*', help='Description'),
            parsers.Arg('--timestamp', '-t', default=None, nargs='*', help='Time for notification'),
            parsers.Arg('--channel', '-c', default=None, help='Channel to send on'),
            parsers.Arg('--repeat', '-r', default=None, nargs='*', help='Repeat interval'),
            parsers.Arg('--repeat-times', '-n', default=None, type=int, help='Number of times to repeat'),
            parsers.Arg('--recipients', '-u', default=None, nargs='*', help='Users which will be notified (you will always be notified)'),
        ],
    )
    async def reminder_edit(self, ctx: Context):
        res = await self.get_reminder_item(ctx)
        if not res:
            return
        parse_ret = await self.parse_reminder_args(ctx, editing=True)
        if isinstance(parse_ret, discord.Message):
            return
        parsed_ts, parsed_repeat, channel, users = parse_ret
        title = ' '.join(ctx.parsed.title) if ctx.parsed.title else None
        description = ' '.join(ctx.parsed.description) if ctx.parsed.description else None
        q = f"UPDATE {self.psql_table_name} SET "
        q_args = []
        q_tmp = []
        if title:
            q_args.append(title)
            q_tmp.append(f"title=${len(q_args)}")
        if description:
            q_args.append(description)
            q_tmp.append(f"description=${len(q_args)}")
        if parsed_ts:
            q_args.append(parsed_ts)
            q_tmp.append(f"notify_ts=${len(q_args)}")
        if parsed_repeat:
            q_args.append(parsed_repeat)
            q_tmp.append(f"repeat=${len(q_args)}")
        if channel:
            q_args.append(channel.id)
            q_tmp.append(f"channel_id=${len(q_args)}")
        if users:
            q_args.append(users)
            q_tmp.append(f"recipients=${len(q_args)}")
        if ctx.parsed.repeat_times is not None:
            if not res['repeat'] and not parsed_repeat:
                return await ctx.send("Reminder does not repeat, cannot change number of repetitions.")
            if ctx.parsed.repeat_times <= 0:
                return await ctx.send('Number of repeats must be a positive number')
            q_args.append(ctx.parsed.repeat_times)
            q_tmp.append(f"repeat_n=${len(q_args)}")
        if len(q_args) == 0:
            return await ctx.send("You must specify something to edit.")
        q += ','.join(q_tmp)
        q_args.append(ctx.parsed.index)
        q += f" WHERE id=${len(q_args)}"
        async with self.bot.pool.acquire() as con:
            for _ in range(2):
                try:
                    await con.execute(q, *q_args)
                    break
                except asyncpg.exceptions.ForeignKeyViolationError:
                    user_ok = await ensure_foreign_key(con=con, obj=User.from_discord(ctx.author), logger=self.logger)
                    ch_ok = await ensure_foreign_key(con=con, obj=Channel.from_discord(channel), logger=self.logger)
                    if not user_ok or not ch_ok:
                        return await ctx.send("Database error, could not add user or channel.")
            await self.refresh_worker()
            # Fetch what we just added for display
            q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        await self.refresh_worker()
        embed = await self.reminder_show_item(res, ctx)
        embed.set_author(name="Reminder Edited", icon_url=str(ctx.author.avatar_url))
        return await ctx.send(embed=embed)

    @reminder.command(
        name='del',
        aliases=['delete', 'rm', 'remove'],
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
        embed.set_author(name="Reminder Show", icon_url=str(ctx.author.avatar_url))
        return await ctx.send(embed=embed)

    async def reminder_show_item(self, res: asyncpg.Record, ctx: Context = None, utc=False, firing=False):
        """Returns an embed for `res` PSQL query"""
        added = self.format_dt_tz(res['added'])
        tmp_val = ""
        if res['description']:
            tmp_val += f"Description: {res['description']}\n"
        tmp_val += f"Added: {added}\n"
        if not firing:
            notify_ts = self.format_dt_tz(res['notify_ts'])
            tmp_val += f"Notify at: {notify_ts}\n"
        if res['updated'] is not None:
            tmp_val += f"Updated: {self.format_dt_tz(res['updated'])}\n"
        if res['repeat']:
            tmp_val += f"Repeat: {utils.human_seconds(res['repeat'])}\n"
        if res['repeat_n']:
            tmp_val += f"Repeats left: {res['repeat_n']}\n"
        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        embed.set_footer(
            text=f"{'UTC' if utc else 'Local'}; dd.mm.yy",
            icon_url=str(self.bot.user.avatar_url),
        )
        if res['failed']:
            tmp_name = "❌ "
        elif res['done']:
            tmp_name = "✅ "
        else:
            tmp_name = ""
        if not firing:
            ch = self.bot.get_channel(res['channel_id'])
            tmp_val += f"Channel: {ch.mention if ch else 'N/A'}"
        embed.add_field(
            name=f"{tmp_name}{res['id']}. {res['title']}",
            value=tmp_val,
            inline=False,
        )
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
        if not res['owner_id'] == ctx.author.id and ctx.author.id not in res['recipients']:
            await ctx.send(f"Reminder with index {ctx.parsed.index} isn't yours")
            return None
        return res

    @staticmethod
    def format_dt_tz(dt: datetime, utc=False) -> str:
        if utc:
            return dt.strftime(cfg.TIME_FORMAT)
        return dt.replace(tzinfo=timezone.utc).astimezone().strftime(cfg.TIME_FORMAT)

    @staticmethod
    async def parse_reminder_args(ctx: Context, editing=False):
        timestamp = ' '.join(ctx.parsed.timestamp) if ctx.parsed.timestamp else None
        repeat = ' '.join(ctx.parsed.repeat) if ctx.parsed.repeat else None
        repeat_n = ctx.parsed.repeat_times
        recipients = ctx.parsed.recipients or []
        channel = ctx.parsed.channel
        if not editing and not channel:
            channel = str(ctx.channel.id)
        # This will interpret absolute times as UTC
        # parsed_ts = dateparser.parse(timestamp, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': False})
        parsed_ts = None
        if timestamp is not None:
            parsed_ts = dateparser.parse(timestamp, settings={'PREFER_DATES_FROM': 'future', 'DATE_ORDER': 'DMY'})
        if not parsed_ts and (not editing or timestamp):
            return await ctx.send(f'Could not parse timestamp "{timestamp}"')
        elif parsed_ts:
            if datetime.now(timezone.utc) >= parsed_ts:
                return await ctx.send(f'Reminder time cannot be in the past: {parsed_ts.strftime(cfg.TIME_FORMAT)}')
        parsed_repeat = None
        if repeat:
            parsed_repeat = pytimeparse.parse(repeat)
            if not parsed_repeat:
                return await ctx.send(f'Could not parse repeat interval "{repeat}"')
            if repeat_n and repeat_n <= 0:
                return await ctx.send('Number of repeats must be a positive number')
        if channel:
            ch_conv = commands.TextChannelConverter()
            try:
                channel = await ch_conv.convert(ctx, channel)
            except commands.ChannelNotFound:
                return await ctx.send(f"No channel {channel} found.")
        users = []
        for r in recipients:
            u = await User.from_search(ctx, r)
            if not u:
                return await ctx.send(f'Could not find user {r}')
            # Silently ignore self
            if u.id == ctx.author.id:
                continue
            users.append(u.id)
        return parsed_ts, parsed_repeat, channel, users

    async def refresh_worker(self):
        if self._sleep_task is not None and not self._sleep_task.done():
            self._sleep_task.cancel()
        while True:
            try:
                async with self.bot.pool.acquire() as con:
                    q = f"SELECT * FROM {self.psql_table_name} WHERE done=false AND failed=false ORDER BY notify_ts ASC LIMIT 1"
                    res = await con.fetchrow(q)
                break
            except asyncpg.exceptions.PostgresConnectionError as e:
                self.logger.warning("Cannot refresh worker: %s", str(e))
                await asyncio.sleep(5)
        if not res:
            self.logger.debug("No remaining reminders")
            return
        self.logger.debug("Starting sleep task for reminder %d", res['id'])
        self._sleep_task = self.bot.loop.create_task(self.sleep_worker(res))

    async def fire_reminder(self, res: asyncpg.Record):
        try:
            ch = self.bot.get_channel(res['channel_id'])
            q_failed = f"UPDATE {self.psql_table_name} SET failed=true WHERE id=$1"
            repeat_td = timedelta(seconds=res['repeat']) if res['repeat'] else None
            repeat_n = res['repeat_n']
            self.logger.debug("Repeat: %s", utils.human_seconds(res['repeat']) if res['repeat'] else 'N/A')
            async with self.bot.pool.acquire() as con:
                if not ch:
                    self.logger.error("Could not find channel %s for reminder ID %d", res['channel_id'], res['id'])
                    await con.execute(q_failed, res['id'])
                    return
                try:
                    mentions = [User(id_=res['owner_id']).mention()]
                    if res['recipients']:
                        mentions += [User(id_=r).mention() for r in res['recipients']]
                    if repeat_td and (repeat_n is None or repeat_n > 1):
                        new_repeat_n = repeat_n - 1 if repeat_n else None
                        new_dt = datetime.now(timezone.utc) + repeat_td
                        self.logger.debug("New time for reminder %d: %s", res['id'], utils.human_timedelta_short(new_dt))
                        q = f"UPDATE {self.psql_table_name} SET notify_ts=$2,repeat_n=$3 WHERE id=$1"
                        await con.execute(q, res['id'], new_dt, new_repeat_n)
                    else:
                        q = f"UPDATE {self.psql_table_name} SET done=true,repeat_n=NULL WHERE id=$1"
                        await con.execute(q, res['id'])
                    q = f"SELECT * FROM {self.psql_table_name} WHERE id=$1"
                    new_res = await con.fetchrow(q, res['id'])
                    embed = await self.reminder_show_item(new_res, firing=True)
                    await ch.send(content=" ".join(mentions), embed=embed)
                except discord.DiscordException as e:
                    self.logger.error("Could not send reminder ID %d: %s", res['id'], str(e))
                    await con.execute(q_failed, res['id'])
        finally:
            await self.refresh_worker()

    async def sleep_worker(self, r: asyncpg.Record):
        try:
            start = datetime.now(timezone.utc)
            if start >= r['notify_ts']:
                self.logger.debug("Reminder %d overdue [%s]", r['id'], utils.human_timedelta_short(r['notify_ts']))
                self.bot.loop.create_task(self.fire_reminder(r))
                return
            duration = abs((start - r['notify_ts']).total_seconds())
            self.logger.debug("Reminder %d due in %s [%d seconds]", r['id'], utils.human_seconds(duration), duration)
            await asyncio.sleep(duration)
            self.bot.loop.create_task(self.fire_reminder(r))
        except asyncio.CancelledError:
            return


def setup(bot):
    bot.add_cog(Reminders(bot))
