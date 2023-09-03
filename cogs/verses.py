import asyncio
import itertools
import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, List, Union

import asyncpg
import dateparser
import discord
import pytimeparse
from discord.ext import commands

import config as cfg
from ext import utils, parsers
from ext.context import Context
from ext.internal import Channel, User
from ext.psql import create_table, ensure_foreign_key

if TYPE_CHECKING:
    from mrbot import MrBot


@dataclass
class VerseType:
    name: str
    value: int
    download_url: str
    regex: str

    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == other
        elif isinstance(other, int):
            return self.value == other
        elif isinstance(other, VerseType):
            return (self.name == other.name and
                    self.value == other.value and
                    self.download_url == other.download_url and
                    self.regex == other.regex)


class Verses(commands.Cog):
    psql_table_name = 'verses'
    psql_table_name_channels = 'verses_channels'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id      SERIAL UNIQUE,
            type    SMALLINT NOT NULL,
            verse   VARCHAR(100) NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_channels} (
            id            SERIAL UNIQUE,
            type          SMALLINT,
            notify_ts_ref TIMESTAMPTZ NOT NULL,
            notify_ts     TIMESTAMPTZ,
            repeat        INTEGER NOT NULL,
            delay         INTEGER,
            added         TIMESTAMPTZ DEFAULT NOW(),
            updated       TIMESTAMPTZ,
            owner_id      BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            channel_id    BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id) ON DELETE CASCADE
        );
    """
    psql_all_tables = User.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name, psql_table_name_channels): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self._sleep_task: Optional[asyncio.Task] = None
        self.verse_types: List[VerseType] = [
            VerseType(
                name="bible",
                value=1,
                download_url="https://openbible.com/textfiles/web.txt",
                regex=r'^(?P<verse>\d?\s*\S+\s+\d+:\d+)\s+(?P<content>.+)$',
            ),
            VerseType(
                name="quran",
                value=2,
                download_url="https://tanzil.net/trans/en.ahmedali",
                regex=r'^(?P<verse>\d+\s*\|\d+\s*)\|\s*(?P<content>.+)$',
            ),
        ]

    def get_verse_type(self, other: Union[str, int]) -> VerseType | None:
        if isinstance(other, str):
            for vt in self.verse_types:
                if other.lower() == vt:
                    return vt
        elif isinstance(other, int):
            for vt in self.verse_types:
                if other == vt:
                    return vt
        return None

    async def cog_load(self):
        await self.bot.sess_ready.wait()
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)

        async with self.bot.pool.acquire() as con:
            for vt in self.verse_types:
                self.verses.aliases.append(vt.name)
                count = await con.fetchval(f"SELECT count(*) FROM {Verses.psql_table_name} WHERE type=$1", vt.value)
                if not count:
                    self.logger.info("Found no verses of type '%s' in database", vt.name)
                    await self._load_verses(con, vt)
        await self.bot.wait_until_ready()
        await self.refresh_worker()

    async def _load_verses(self, con: asyncpg.Connection, vt: VerseType):
        download_path = os.path.join(tempfile.gettempdir(), f"verses_{vt.value}.txt")
        re_verse = re.compile(vt.regex)

        if not os.path.exists(download_path):
            await utils.file_from_url(download_path, vt.download_url, self.bot.aio_sess)

        start = time.perf_counter()
        q = f"INSERT INTO {Verses.psql_table_name} (type, verse, content) VALUES ($1, $2, $3)"
        q_args = []
        with open(download_path, 'r') as f:
            for line in f:
                if m := re_verse.match(line):
                    q_args.append((vt.value, m.group('verse'), m.group('content')))
        self.logger.debug(f"Prepared {len(q_args)} {vt.name} rows in {(time.perf_counter() - start)*1000:.2f}ms")

        start = time.perf_counter()
        await con.executemany(q, q_args)
        self.logger.debug(f"Inserted {len(q_args)} {vt.name} rows in {(time.perf_counter() - start)*1000:.2f}ms")

    @parsers.group(
        name='verses',
        aliases=['verse'],
        brief='Show a random verse',
        invoke_without_command=True,
    )
    async def verses(self, ctx: Context):
        verse_type = self.parse_verse_type(ctx)
        if verse_type is None:
            # Pick a random type to account for different number of verses
            verse_type = random.choice(self.verse_types)

        q = f"SELECT * FROM {self.psql_table_name} WHERE type=$1 ORDER BY random() LIMIT 1"
        async with self.bot.pool.acquire() as con:
            verse = await con.fetchrow(q, verse_type.value)
        embed = self.show_verse(verse)
        await ctx.send(embed=embed)

    @verses.command(
        name='add',
        brief='Add item to verse jobs',
        parser_args=[
            parsers.Arg('--type', default=None, help='Verse type'),
            parsers.Arg('--timestamp', '-t', required=True, nargs='+', help='Time for notification'),
            parsers.Arg('--repeat', '-r', required=True, nargs='+', help='Repeat interval'),
            parsers.Arg('--delay', '-d', default=None, nargs='*', help='Random delay limit to use each time'),
            parsers.Arg('--channel', '-c', default=None, help='Optional channel'),
        ],
    )
    async def verses_add(self, ctx: Context):
        # Try to parse
        parse_ret = await self.parse_verses_args(ctx)
        if isinstance(parse_ret, discord.Message):
            return
        parsed_ts, parsed_repeat, parsed_delay, channel = parse_ret
        verse_type = self.parse_verse_type(ctx)
        if verse_type is not None:
            verse_type = verse_type.value
        notify_ts = parsed_ts
        if parsed_delay:
            notify_ts += timedelta(seconds=random.randint(0, parsed_delay))
        async with self.bot.pool.acquire() as con:
            q = (f"INSERT INTO {self.psql_table_name_channels} (type, notify_ts_ref, notify_ts, repeat, delay, owner_id, channel_id) "
                 "VALUES ($1, $2, $3, $4, $5, $6, $7)")
            for _ in range(2):
                try:
                    await con.execute(q, verse_type, parsed_ts, notify_ts, parsed_repeat, parsed_delay, ctx.author.id, channel.id)
                    break
                except asyncpg.exceptions.ForeignKeyViolationError:
                    user_ok = await ensure_foreign_key(con=con, obj=User.from_discord(ctx.author), logger=self.logger)
                    ch_ok = await ensure_foreign_key(con=con, obj=Channel.from_discord(channel), logger=self.logger)
                    if not user_ok or not ch_ok:
                        return await ctx.send("Database error, could not add user or channel.")
            await self.refresh_worker()
            # Fetch what we just added for display
            q = f"SELECT * FROM {self.psql_table_name_channels} WHERE owner_id=$1 AND notify_ts_ref=$2"
            q_args = [ctx.author.id, parsed_ts]
            if verse_type is not None:
                q_args.append(verse_type)
                q += f" AND type=${len(q_args)}"
            q += " ORDER BY added DESC LIMIT 1"
            res = await con.fetchrow(q, *q_args)
        embed = self.show_job(res)
        embed.set_author(name="Verse Job Add", icon_url=utils.str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @verses.command(
        name='list',
        brief="List all verse jobs you've added",
        parser_args=[
            parsers.Arg('--type', default=None, help='Optional type filter'),
            parsers.Arg('--absolute', default=False, help='Show absolute times', action='store_true'),
        ],
    )
    async def verses_list(self, ctx):
        q = f"SELECT * FROM {self.psql_table_name_channels} WHERE owner_id=$1"
        q_args = [ctx.author.id]
        verse_type = self.parse_verse_type(ctx)
        if verse_type is not None:
            q_args.append(verse_type.value)
            q += f" AND type=${len(q_args)}"
        q += " ORDER BY notify_ts_ref DESC"
        async with self.bot.pool.acquire() as con:
            result = await con.fetch(q, *q_args)
        if len(result) == 0:
            await ctx.send(f"{ctx.author.display_name} has no verse jobs.")
            return
        tmp_val = ""
        for res in result:
            ch = self.bot.get_channel(res['channel_id'])
            ch = ch.name if ch else "N/A"
            if res['type']:
                vt = self.get_verse_type(res['type']).name.title()
            else:
                vt = 'any'
            if ctx.parsed.absolute:
                ts = utils.format_dt(res['notify_ts_ref'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
                tmp_val += f'{res["id"]} [{vt}]: {ch} at {ts}\n'
            else:
                ts = utils.human_timedelta_short(res["notify_ts_ref"])
                tmp_val += f'{res["id"]} [{vt}]: {ch} {ts}\n'
        for i, p in enumerate(utils.paginate(tmp_val)):
            if i == 0:
                await ctx.send("Verse job summary:\n" + p)
                continue
            await ctx.send(p)

    @verses.command(
        name='edit',
        brief='Edit a verse job by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
            parsers.Arg('--type', default=None, help='Optional type filter'),
            parsers.Arg('--timestamp', '-t', default=None, nargs='*', help='Time for notification'),
            parsers.Arg('--repeat', '-r', default=None, nargs='*', help='Repeat interval'),
            parsers.Arg('--delay', '-d', default=None, nargs='*', help='Random delay limit to use each time'),
            parsers.Arg('--channel', '-c', default=None, help='Channel to send to'),
        ],
    )
    async def verses_edit(self, ctx: Context):
        res = await self.get_job(ctx)
        if not res:
            return
        parse_ret = await self.parse_verses_args(ctx, editing=True)
        if isinstance(parse_ret, discord.Message):
            return
        parsed_ts, parsed_repeat, parsed_delay, channel = parse_ret
        verse_type = self.parse_verse_type(ctx)
        if verse_type is not None:
            verse_type = verse_type.value
        # We should always have these available
        delay = parsed_delay or res['delay']
        notify_ts_ref = parsed_ts or res['notify_ts_ref']
        notify_ts = notify_ts_ref
        if delay:
            notify_ts += timedelta(seconds=random.randint(0, delay))
        q = f"UPDATE {self.psql_table_name_channels} SET "
        q_args = []
        q_tmp = []

        def arg_exists(name: str) -> bool:
            for a in q_args:
                if re.match(f'^{name}=\\$\\d+', a):
                    return True
            return False

        if (verse_type is not None or ctx.parsed.type == 'any') and verse_type != res['type']:
            q_args.append(verse_type)
            q_tmp.append(f"type=${len(q_args)}")
        if parsed_ts:
            q_args.append(notify_ts_ref)
            q_tmp.append(f"notify_ts_ref=${len(q_args)}")
            q_args.append(notify_ts)
            q_tmp.append(f"notify_ts=${len(q_args)}")
        if parsed_repeat:
            q_args.append(parsed_repeat)
            q_tmp.append(f"repeat=${len(q_args)}")
        if parsed_delay:
            q_args.append(delay)
            q_tmp.append(f"delay=${len(q_args)}")
            if not arg_exists('notify_ts_ref'):
                q_args.append(notify_ts_ref)
                q_tmp.append(f"notify_ts_ref=${len(q_args)}")
            if not arg_exists('notify_ts'):
                q_args.append(notify_ts)
                q_tmp.append(f"notify_ts=${len(q_args)}")
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
            q = f"SELECT * FROM {self.psql_table_name_channels} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        await self.refresh_worker()
        embed = self.show_job(res)
        embed.set_author(name="Verses Job Edited", icon_url=utils.str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @verses.command(
        name='del',
        aliases=['delete', 'rm', 'remove'],
        brief='Delete a verse job by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def verses_del(self, ctx: Context):
        res = await self.get_job(ctx)
        if not res:
            return
        async with self.bot.pool.acquire() as con:
            q = f"DELETE FROM {self.psql_table_name_channels} WHERE id=$1"
            await con.execute(q, ctx.parsed.index)
        await self.refresh_worker()
        embed = self.show_job(res)
        embed.set_author(name="Verse Job Deleted", icon_url=utils.str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    @verses.command(
        name='show',
        brief='Show single job by index',
        parser_args=[
            parsers.Arg('index', type=int, help='Item number'),
        ],
    )
    async def verses_show(self, ctx: Context):
        res = await self.get_job(ctx)
        if not res:
            return

        embed = self.show_job(res)
        embed.set_author(name="Verse Job Show", icon_url=utils.str_or_none(ctx.author.avatar))
        return await ctx.send(embed=embed)

    async def get_job(self, ctx: Context):
        """Gets a bible and checks if the caller can use it"""
        async with self.bot.pool.acquire() as con:
            q = f"SELECT * FROM {self.psql_table_name_channels} WHERE id=$1"
            res = await con.fetchrow(q, ctx.parsed.index)
        if not res:
            await ctx.send(f"No job with index {ctx.parsed.index} found")
            return None
        if not res['owner_id'] == ctx.author.id:
            await ctx.send(f"Job with index {ctx.parsed.index} isn't yours")
            return None
        return res

    def show_job(self, res: asyncpg.Record):
        """Returns an embed for `res` PSQL query"""
        if res['type']:
            verse_type = self.get_verse_type(res['type']).name.title()
        else:
            verse_type = "Any"
        tmp_val = f"Type: {verse_type}\n"
        added = utils.format_dt(res['added'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
        tmp_val += f"Added: {added}\n"
        notify_ts = utils.format_dt(res['notify_ts'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
        tmp_val += f"Notify at: {notify_ts}\n"
        notify_ts_ref = utils.format_dt(res['notify_ts_ref'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
        tmp_val += f"Notify reference: {notify_ts_ref}\n"
        tmp_val += f"Repeat: {utils.human_seconds(res['repeat'])}\n"
        if res['updated'] is not None:
            updated_ts = utils.format_dt(res['updated'], cfg.TIME_FORMAT, cfg.TIME_ZONE)
            tmp_val += f"Updated: {updated_ts}\n"
        if res['delay'] is not None:
            tmp_val += f"Delay: {utils.human_seconds(res['delay'])}\n"

        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        embed.set_footer(
            text=f"{cfg.TIME_ZONE}; dd.mm.yy",
            icon_url=utils.str_or_none(self.bot.user.avatar),
        )

        ch = self.bot.get_channel(res['channel_id'])
        tmp_val += f"Channel: {ch.mention if ch else 'N/A'}"
        embed.add_field(
            name=f"{res['id']}",
            value=tmp_val,
            inline=False,
        )
        return embed

    def show_verse(self, res: asyncpg.Record):
        embed = discord.Embed()
        embed.colour = discord.Colour.random()
        embed.set_footer(
            text=self.get_verse_type(res['type']).name.title(),
        )
        embed.title = res['verse']
        # Length seems OK
        # select verse, length(content) from verses_verses group by verse, content order by length(content) desc limit 5;
        embed.description = res['content']
        return embed

    def parse_verse_type(self, ctx: Context) -> VerseType | None:
        if hasattr(ctx, 'parsed') and getattr(ctx.parsed, 'type', None):
            verse_type = self.get_verse_type(ctx.parsed.type)
        elif ctx.invoked_parents:
            # Try to find from parent command name
            verse_type = self.get_verse_type(ctx.invoked_parents[0])
        else:
            # Try to find type from command name
            verse_type = self.get_verse_type(ctx.invoked_with)
        return verse_type

    @staticmethod
    async def parse_verses_args(ctx: Context, editing=False):
        timestamp = ' '.join(ctx.parsed.timestamp) if ctx.parsed.timestamp else None
        repeat = ' '.join(ctx.parsed.repeat) if ctx.parsed.repeat else None
        channel = ctx.parsed.channel
        delay = ' '.join(ctx.parsed.delay) if ctx.parsed.delay else None
        if not editing and not channel:
            channel = str(ctx.channel.id)
        parsed_ts = None
        if timestamp is not None:
            parsed_ts = dateparser.parse(timestamp, settings={'TIMEZONE': cfg.TIME_ZONE, 'RETURN_AS_TIMEZONE_AWARE': True,
                                                              'PREFER_DATES_FROM': 'future', 'DATE_ORDER': 'DMY'})
        if not parsed_ts and (not editing or timestamp):
            return await ctx.send(f'Could not parse timestamp "{timestamp}"')
        elif parsed_ts:
            if datetime.now(timezone.utc) >= parsed_ts:
                return await ctx.send(f'Verse scheduled time cannot be in the past: {utils.format_dt(parsed_ts, cfg.TIME_FORMAT, cfg.TIME_ZONE)}')

        parsed_repeat = None
        if repeat:
            parsed_repeat = pytimeparse.parse(repeat)
            if not parsed_repeat:
                return await ctx.send(f'Could not parse repeat interval "{repeat}"')
            elif parsed_repeat <= 0:
                return await ctx.send('Repeat interval must be a positive number')
        parsed_delay = None
        if delay:
            parsed_delay = pytimeparse.parse(delay)
            if not parsed_delay:
                return await ctx.send(f'Could not parse delay interval "{repeat}"')
            elif parsed_delay <= 0:
                return await ctx.send('Delay must be a positive number')
        if channel:
            ch_conv = commands.TextChannelConverter()
            try:
                channel = await ch_conv.convert(ctx, channel)
            except commands.ChannelNotFound:
                return await ctx.send(f"No channel {channel} found.")
        return parsed_ts, parsed_repeat, parsed_delay, channel

    async def refresh_worker(self):
        self.logger.debug("Refreshing worker")
        if self._sleep_task is not None and not self._sleep_task.done():
            self.logger.debug("Cancelling sleep task")
            self._sleep_task.cancel()
        while True:
            try:
                self.logger.debug("Fetching latest job")
                async with self.bot.pool.acquire() as con:
                    q = f"SELECT * FROM {self.psql_table_name_channels} ORDER BY notify_ts ASC LIMIT 1"
                    res = await con.fetchrow(q)
                if res:
                    self.logger.debug("Job %d - Found", res['id'])
                break
            except asyncpg.exceptions.PostgresConnectionError as e:
                self.logger.warning("Cannot refresh worker: %s", str(e))
                await asyncio.sleep(5)
        if not res:
            self.logger.debug("No scheduled verses remaining")
            return
        self.logger.debug("Job %d - Starting sleep task", res['id'])
        self._sleep_task = asyncio.create_task(self.sleep_worker(res))

    async def fire_verse(self, res: asyncpg.Record):
        try:
            ch = self.bot.get_channel(res['channel_id'])
            repeat_td = timedelta(seconds=res['repeat'])
            self.logger.debug("Job %d - Repeat: %s", res['id'], utils.human_seconds(res['repeat']))
            verse = None
            async with self.bot.pool.acquire() as con:
                try:
                    if not ch:
                        self.logger.error("Job %d - Deleting, could not find channel %d",  res['id'], res['channel_id'])
                        await con.execute(f"DELETE FROM {self.psql_table_name_channels} WHERE id=$1", res['id'])
                        self.logger.debug("Job %d - Deleted", res['id'])
                        return
                    new_dt_ref: datetime = res['notify_ts_ref'] + repeat_td
                    _count = 0
                    while new_dt_ref < datetime.now(timezone.utc):
                        new_dt_ref += repeat_td
                        _count += 1
                    new_dt = new_dt_ref
                    self.logger.debug("Job %d - New reference time '%s' found in %d iterations", res['id'], new_dt_ref.isoformat(), _count)
                    if res['delay']:
                        new_dt += timedelta(seconds=random.randint(0, res['delay']))
                    self.logger.debug("Job %d - New time '%s'", res['id'], new_dt.isoformat())
                    q = f"UPDATE {self.psql_table_name_channels} SET notify_ts=$2, notify_ts_ref=$3 WHERE id=$1"
                    await con.execute(q, res['id'], new_dt, new_dt_ref)
                    self.logger.debug("Job %d - New times set in database", res['id'])

                    # Fetch and send verse
                    q = f"SELECT * FROM {self.psql_table_name} WHERE type=$1 ORDER BY random() LIMIT 1"
                    q_args = []
                    if res['type']:
                        q_args.append(res['type'])
                    else:
                        q_args.append(random.choice(self.verse_types).value)

                    self.logger.debug("Job %d - Fetching random verse of type %d", res['id'], q_args[0])
                    verse = await con.fetchrow(q, *q_args)
                    self.logger.debug("Job %d - Got verse ID '%d'", res['id'], verse['id'])
                    embed = self.show_verse(verse)
                    msg = await ch.send(embed=embed)
                    self.logger.debug("Job %d - Sent message %d in channel %d", res['id'], msg.id, ch.id)
                except discord.DiscordException as e:
                    self.logger.error("Job %d - Job failed: %s", res['id'], str(e))
                    if verse is not None:
                        self.logger.debug("Job %d - Verse ID was %d", res['id'], verse['id'])
        finally:
            await self.refresh_worker()

    async def sleep_worker(self, r: asyncpg.Record):
        self.logger.debug("Job %d - Starting sleep worker, job time '%s'", r['id'], r['notify_ts'].isoformat())
        try:
            start = datetime.now(timezone.utc)
            if start >= r['notify_ts']:
                self.logger.debug("Job %d - Overdue, current time '%s'", r['id'], start.isoformat())
                asyncio.create_task(self.fire_verse(r))
                return
            duration = abs((start - r['notify_ts']).total_seconds())
            self.logger.debug("Job %d - Due in %s [%d seconds]", r['id'], utils.human_seconds(duration), duration)
            await asyncio.sleep(duration)
            asyncio.create_task(self.fire_verse(r))
        except asyncio.CancelledError:
            self.logger.debug("Job %d - Sleep worker cancelled", r['id'])
            return


async def setup(bot):
    await bot.add_cog(Verses(bot))
