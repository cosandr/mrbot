from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import random
import re
import time
import traceback
import unicodedata
import uuid
from io import BytesIO
from typing import TYPE_CHECKING

import asyncpg
import discord
import matplotlib.pyplot as plt
import numpy as np
import wolframalpha
from discord.ext import commands
from jellyfish import jaro_winkler_similarity
from scipy import stats
from sympy import preview

import config as cfg
import ext.embed_helpers as emh
from ext import utils
from ext.context import Context
from ext.errors import MissingConfigError
from ext.internal import Message, User
from ext.parsers import parsers
from ext.psql import create_table
from ext.utils import pg_connection, str_or_none

if TYPE_CHECKING:
    from mrbot import MrBot


class Misc(commands.Cog, name="Miscellaneous"):
    # Web database
    psql_table_name_web = 'misc'
    psql_table_web = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name_web} (
            name    VARCHAR(200) PRIMARY KEY,
            content TEXT NOT NULL,
            created TIMESTAMPTZ DEFAULT NOW(),
            updated TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE OR REPLACE FUNCTION update_{psql_table_name_web}()
            RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated = now();
        RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS trigger_update_{psql_table_name_web} ON {psql_table_name_web};
        CREATE TRIGGER trigger_update_{psql_table_name_web} BEFORE UPDATE ON {psql_table_name_web}
            FOR EACH ROW EXECUTE PROCEDURE update_{psql_table_name_web}();
    """
    psql_all_tables_web = {(psql_table_name_web,): psql_table_web}

    def __init__(self, bot):
        self.bot: MrBot = bot
        self.wolf_key: str = ''
        self.web_dsn: str = ''
        self.pub_dsn: str = ''
        self.read_config()
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.dota2_heroes = None
        self.wolf_client = wolframalpha.Client(self.wolf_key)

    def read_config(self):
        self.wolf_key = self.bot.config.api_keys.get('wolfram')
        self.web_dsn = self.bot.config.psql.web
        self.pub_dsn = self.bot.config.psql.public
        if not self.wolf_key:
            raise MissingConfigError('Wolfram Alpha API key not found')
        if not self.web_dsn:
            raise MissingConfigError('Postgres DSN for web database not found')
        if not self.pub_dsn:
            raise MissingConfigError('Postgres DSN for public database not found')

    async def cog_load(self):
        await self.bot.sess_ready.wait()
        names = itertools.chain(*self.psql_all_tables_web.keys())
        q = self.psql_all_tables_web.values()
        async with pg_connection(dsn=self.web_dsn) as con:
            await create_table(con, names, q, self.logger)

    @commands.command(name='mycolour', brief='Changes your role colour', aliases=['mycolor'])
    @commands.bot_has_permissions(manage_roles=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.guild_only()
    async def set_role_colour(self, ctx: Context, *, colour: str):
        g_def = self.bot.config.guilds.get(ctx.guild.id)
        if not g_def:
            return await ctx.send("This guild has no role definitions, cannot use this command.")
        m_def = g_def.members.get(ctx.author.id, None)
        if not m_def:
            return await ctx.send("You do not have a defined role, cannot use this command.")
        role = discord.utils.get(ctx.guild.roles, name=m_def.name)
        if not role:
            return await ctx.send("Defined role not found in this guild, cannot use this command.")
        rgb_dict = {}
        re_colour = re.compile(r'^\s*[^#](.*)#(\w+)')
        with open(os.path.join(os.path.dirname(__file__), 'rgb.txt'), 'r') as fr:
            for line in fr:
                if m := re_colour.match(line):
                    rgb_dict[m.group(0).strip()] = m.group(1)
        colour = colour.lower()
        colour_int = rgb_dict.get(colour, None)
        if colour_int:
            colour_int = int(colour_int, 16)
        else:
            try:
                colour_int = int(colour, 16)
            except ValueError:
                return await ctx.send(f'Cannot convert {colour} to hex. Use names or values (without #) from https://xkcd.com/color/rgb/')
        await role.edit(colour=discord.Colour(colour_int))
        await ctx.send(f'{m_def.name} colour changed to {colour}')

    @commands.command(name='msglen', brief='Msg length histogram')
    async def msg_length(self, ctx: Context, member: str):
        user: User = await User.from_search(ctx, member)
        if not user:
            return await ctx.send(f'No user {member} found')
        filter_ch = 422397894956548097
        q = f'SELECT LENGTH(subq.content) FROM (SELECT content FROM {Message.psql_table_name} WHERE user_id=$1 AND ch_id=$2) AS subq'
        async with self.bot.pool.acquire() as con:
            res = await con.fetch(q, user.id, filter_ch)
        start = time.perf_counter()
        res_list = []
        for r in res:
            if r['length'] is not None:
                res_list.append(r['length'])
        fig = plt.figure()
        ax = fig.add_subplot(1, 1, 1)
        text_colour = 'xkcd:grey'
        ax.hist(res_list, bins='auto', align='left', range=(0, 100), rwidth=0.75, color=text_colour)
        # Make background transparent
        ax.set_facecolor('#36393E')
        fig.set_facecolor('#36393E')
        plt.xlabel('Characters')
        plt.ylabel('Occurances')

        ax.spines['bottom'].set_color(text_colour)
        ax.spines['left'].set_color(text_colour)
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)

        ax.xaxis.label.set_color(text_colour)
        ax.yaxis.label.set_color(text_colour)
        ax.tick_params(axis='x', colors=text_colour)
        ax.tick_params(axis='y', colors=text_colour)

        ax.legend(
            [f'n={len(res_list)}\n$\\mu$={np.mean(res_list):.1f}\nmed={np.median(res_list):.1f}\nmod={stats.mode(res_list)[0][0]:.1f}'],
            frameon=False, handlelength=0, handletextpad=0)
        plt.setp(ax.get_legend().get_texts(), color=text_colour)

        ax.set_title(f'Stats for {user.display_name}', color=text_colour)
        end = time.perf_counter()
        tmp = BytesIO()
        plt.savefig(tmp, facecolor=ax.get_facecolor(), bbox_inches='tight', format='png')
        tmp.seek(0)
        await ctx.send(f'Only messages in {ctx.guild.get_channel(filter_ch).mention}\nPlotted in {(end-start)*1000:.0f}ms',
                       file=discord.File(tmp, filename="stats.png"))

    @parsers.command(
        name='msgwords',
        brief='Msg word bar chart',
        parser_args=[
            parsers.Arg('user', nargs='+', help='User to fetch'),
            parsers.Arg('--words', default=False, help='Count words', action='store_true'),
            parsers.Arg('--limit', '-l', default=25, type=int, help='Result limit'),
        ],
    )
    async def msg_words(self, ctx: Context):
        search_user = " ".join(ctx.parsed.user)
        user: User = await User.from_search(ctx, search_user)
        if not user:
            return await ctx.send(f'No user {search_user} found')
        if ctx.parsed.words:
            q = ("SELECT regexp_split_to_table(LOWER(subq.content), '\\s') AS words FROM "
                 f"(SELECT content FROM {Message.psql_table_name} WHERE user_id=$1) AS subq")
        else:
            q = ('SELECT LOWER(subq.content) AS words FROM '
                 f'(SELECT content FROM {Message.psql_table_name} WHERE user_id=$1) AS subq')
        async with self.bot.pool.acquire() as con:
            res = await con.fetch(q, user.id)
        start = time.perf_counter()
        res_list = []
        for r in res:
            if r['words'] is not None:
                res_list.append(r['words'])
        word_counts = {}
        for word in res_list:
            if word_counts.get(word, None) is None:
                word_counts[word] = 1
            else:
                word_counts[word] += 1
        s = [(k, word_counts[k]) for k in sorted(word_counts, key=word_counts.get, reverse=True)]
        adj_s = []
        adj_lim = ctx.parsed.limit if len(s) > ctx.parsed.limit else len(s)
        for i in range(adj_lim):
            if s[i][1] <= 1:
                break
            adj_s.append(s[i])
        text_colour = 'xkcd:grey'
        word, frequency = zip(*adj_s)
        indices = np.arange(len(adj_s))
        if ctx.parsed.words:
            fig = plt.figure(figsize=(5, 10))
        else:
            fig = plt.figure(figsize=(10, 10))
        ax = fig.add_subplot(1, 1, 1)
        ax.barh(indices, frequency, color=text_colour)
        ax.set_yticks(indices)
        ax.set_yticklabels(word)
        ax.invert_yaxis()

        ax.set_facecolor('#36393E')
        fig.set_facecolor('#36393E')

        ax.spines['bottom'].set_color(text_colour)
        ax.spines['left'].set_color(text_colour)
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)

        ax.xaxis.label.set_color(text_colour)
        ax.yaxis.label.set_color(text_colour)
        ax.tick_params(axis='x', colors=text_colour)
        ax.tick_params(axis='y', colors=text_colour)

        ax.set_title(f'Stats for {user.name}', color=text_colour)
        end = time.perf_counter()
        tmp = BytesIO()
        plt.savefig(tmp, facecolor=ax.get_facecolor(), bbox_inches='tight', format='png')
        tmp.seek(0)
        if ctx.parsed.words:
            ret_str = f'Showing the {len(adj_s)} most commonly used words.\n'
        else:
            ret_str = f'Showing the {len(adj_s)} most commonly sent messages.\n'
        ret_str += f'Plotted in {(end-start)*1000:.0f}ms'
        await ctx.send(ret_str, file=discord.File(tmp, filename="words.png"))
        plt.close(fig=fig)
        return

    @parsers.command(
        name='sql',
        brief="Run SQL command",
        parser_args=[
            parsers.Arg('cmd', nargs='+', help='SQL command to run'),
            parsers.Arg('--use-public', default=False, help='Use public pool', action='store_true'),
        ],
    )
    async def sql(self, ctx: Context):
        # remove ```sql\n```
        if ctx.parsed.cmd[0] == '```' and ctx.parsed.cmd[-1] == '```':
            cmd = '\n'.join(ctx.parsed.cmd[1:-1])
        else:
            cmd = '\n'.join(ctx.parsed.cmd)

        fetch_cmd = False
        running_live = False
        if await self.bot.is_owner(ctx.author) and not ctx.parsed.use_public:
            con = await self.bot.pool.acquire()
            running_live = True
            print("Running live")
        else:
            con = await asyncpg.connect(dsn=self.pub_dsn)
            print("Running public")

        if any(c in cmd.upper() for c in ['DROP', 'DELETE']):
            msg = await ctx.send("Confirm destructive operation.")
            react_emoji = '✅'
            await msg.add_reaction(react_emoji)

            def check(reaction, user):
                return reaction.message.id == msg.id and str(reaction.emoji) == react_emoji and \
                    user == ctx.author

            try:
                await self.bot.wait_for('reaction_add', timeout=5.0, check=check)
            except asyncio.TimeoutError:
                return await msg.delete()

        start = time.perf_counter()
        try:
            if cmd.upper().startswith('SELECT'):
                fetch_cmd = True
                res = await con.fetch(cmd)
            else:
                res = await con.execute(cmd)
        except Exception as e:
            exec_time = f"Time: {(time.perf_counter() - start)*1000:.2f}ms"
            await ctx.send(f"ERROR: {str(e)}\n{exec_time}")
            return
        finally:
            if running_live:
                await self.bot.pool.release(con)
            else:
                await con.close()

        exec_time = f"Time: {(time.perf_counter() - start)*1000:.2f}ms"
        if not fetch_cmd:
            await ctx.send(f"{res}\n{exec_time}")
            return
        elif len(res) == 0:
            await ctx.send(f"(0 rows)\n{exec_time}")
            return
        tmp_arr = []
        for col in res[0].keys():
            tmp_arr.append([col])

        for row in res:
            # Columns
            i = 0
            for v in row.values():
                tmp_arr[i].append(str(v))
                i += 1

        # Add header
        ret_str = ""
        longest_name = {}
        i = 0
        for arr in tmp_arr:
            tmp = 0
            for el in arr:
                if len(el) > tmp:
                    tmp = len(el)
            longest_name[i] = tmp
            i += 1
            # ret_str += f"{' '*int(tmp/2)}{arr[0]:{int(tmp/2)}s} | "
            ret_str += f"{arr[0]:{tmp}s} | "
        # Remove trailing |
        ret_str = ret_str[:-2]
        # Add line of -
        ret_str += "\n" + "-"*len(ret_str)
        # Add rows
        for j in range(1, len(res)+1):
            tmp = ""
            for i in range(len(tmp_arr)):
                tmp += f"{tmp_arr[i][j]:{longest_name[i]}s} | "
            tmp = tmp[:-2]
            if len(ret_str) + len(tmp) > 2000:
                await ctx.send(f'```\n{ret_str}\n{exec_time}```')
                ret_str = tmp
            ret_str += f"\n{tmp}"

        row_str = f"({len(res)} rows)" if len(res) > 1 else "(1 row)"
        await ctx.send(f'```\n{ret_str}\n{row_str}\n\n{exec_time}\n```')

    @commands.command(name='roll', brief='Roll a number', aliases=['dice'])
    async def num_roll(self, ctx: Context, val: int):
        await ctx.send(random.randint(0, val))

    @commands.command(name='charinfo', brief='Display unicode character info')
    async def charinfo(self, ctx: Context, *, characters: str):
        def to_string(c):
            digit = f'{ord(c):x}'
            name = unicodedata.name(c, 'Name not found.')
            return f'`\\U{digit:>08}`: {name} - {c} \N{EM DASH} <http://www.fileformat.info/info/unicode/char/{digit}>'
        msg = '\n'.join(map(to_string, characters))
        return await ctx.send(msg)

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        # Only applies to me
        if self.bot.owner_id != before.id:
            return

        activity_blacklist = ('Visual Studio Code', 'Sublime Text', 'PyCharm')
        was_playing = False
        is_playing = False
        for act in before.activities:
            # Don't do anything if previous activity is similar to blacklist
            if s := utils.find_closest_match(act.name, activity_blacklist):
                if s[1] > 0.7:
                    return
            was_playing = True
            break
        for act in after.activities:
            # Don't do anything if current activity is similar to blacklist
            if s := utils.find_closest_match(act.name, activity_blacklist):
                if s[1] > 0.7:
                    return
            is_playing = True
            break

        q = (f"INSERT INTO {self.psql_table_name_web} (name, content) VALUES ($1, $2) "
             "ON CONFLICT (name) DO UPDATE SET content=$2")
        async with pg_connection(dsn=self.web_dsn) as con:
            if (was_playing is False) and (is_playing is True):
                token = uuid.uuid1().hex
                await con.execute(q, 'stream_token', token)
                self.logger.info("Stream token created.")

            if (was_playing is True) and (is_playing is False):
                await con.execute(q, 'stream_token', 'null')
                self.logger.info("Stream token removed.")

    @commands.group(name='d2', brief='Dota 2 command group')
    async def dota2(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            return await ctx.list_group_subcmds()

    @dota2.before_invoke
    async def dota2_get_heroes(self, ctx: Context):
        if self.dota2_heroes is None:
            resp_bytes = await utils.bytes_from_url("https://api.opendota.com/api/heroes", self.bot.aio_sess)
            self.dota2_heroes = json.load(resp_bytes)

    @dota2.command(name='random', brief="Randoms a Dota 2 hero")
    async def dota2_random(self, ctx: Context):
        hero = random.choice(self.dota2_heroes)
        return await ctx.send(embed=self.dota2_hero_embed(ctx, hero))

    @dota2.command(name='legs', brief="Randoms a hero with at least given leg count")
    async def dota2_legs(self, ctx: Context, legs: int):
        hero_list = []
        for hero in self.dota2_heroes:
            if hero['legs'] >= legs:
                hero_list.append(hero)
        if len(hero_list) == 0:
            return await ctx.send(f"No heroes with at least {legs} legs found.")
        return await ctx.send(embed=self.dota2_hero_embed(ctx, random.choice(hero_list)))

    @commands.command(brief='Evaluate input as LaTeX and output image')
    async def latex(self, ctx: Context, *expr):
        embed = emh.embed_init(self.bot, "LaTeX")
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        embed.description = f"Input `{' '.join(expr)}`"
        tmp_bytes = BytesIO()
        start = time.perf_counter()
        try:
            preamble = "\\documentclass[30pt]{article}\n\\pagestyle{empty}\\begin{document}\\huge"
            await self.bot.loop.run_in_executor(None, lambda: preview(' '.join(expr), viewer='BytesIO',
                                                                      outputbuffer=tmp_bytes, output='png',
                                                                      preamble=preamble))
        except Exception:
            error = traceback.format_exc().splitlines()[-1]
            only_relevant = error.split("!")[1].split("No pages of output.")[0].replace("\\n", "\n")
            embed.colour = discord.Colour.red()
            embed.set_footer(text="FAILED", icon_url=embed.footer.icon_url)
            embed.description += "\n**Error**\n" + only_relevant
            return await ctx.send(embed=embed)
        end = time.perf_counter()
        tmp_bytes.seek(0)
        embed.colour = discord.Colour.green()
        embed.set_footer(text=f"Completed in {end-start:.2f}s", icon_url=embed.footer.icon_url)
        f = discord.File(tmp_bytes, filename="latex.png")
        embed.set_image(url="attachment://latex.png")
        return await ctx.send(file=f, embed=embed)

    @commands.command(name='wolf', brief='New Wolfram Alpha query')
    async def wolf(self, ctx: Context, *args):
        q_wolf = ' '.join(args)
        if len(q_wolf) < 1:
            return await ctx.send('No input given.')
        embed = emh.embed_init(self.bot, "Wolfram Alpha")
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        embed.description = f'Input `{q_wolf}`'
        msg = await ctx.send(embed=embed)
        start = time.perf_counter()
        res = await self.bot.loop.run_in_executor(None, lambda: self.wolf_client.query(q_wolf))
        embed.colour = discord.Colour.green()
        embed.description = ''
        embed.title = 'Results'
        end = time.perf_counter()
        embed.set_footer(text=f"Completed in {end-start:.2f}s", icon_url=embed.footer.icon_url)
        for pod in res.pods:
            if (('Plot' in pod.title) or (pod.title == 'Number line') or
                    (pod.title == 'Position in the complex plane')):
                embed.set_image(url=next(next(pod.subpod).img).src)
            else:
                embed.add_field(name=f"{pod.title}", value=f"{pod.text}", inline=False)

        return await msg.edit(embed=embed)

    @commands.group(brief='Link RL VOD', invoke_without_command=True)
    async def rl(self, ctx: Context, *name):
        if len(name) == 0:
            return await ctx.send(f"No VOD specified. Check `{ctx.prefix}rl list` or `{ctx.prefix}rl list all`.")
        else:
            name = str(" ".join(name).lower())
            if "btn" in name:
                name = name.replace("btn", "return of by the numbers")

        # First check for exact match
        q = "SELECT filename, uuid FROM uuids WHERE type='rl' AND filename ILIKE $1"
        async with pg_connection(dsn=self.web_dsn) as con:
            result = await con.fetchrow(q, name)
        if result is not None:
            return await ctx.send(f"Match found {result['filename']}:\n{self.bot.config.hostname}/rl?v={result['uuid']}")
        # Fetch all because we need to guess which clip the user meant.
        q = "SELECT filename, uuid FROM uuids WHERE type='rl' ORDER BY created DESC"
        async with pg_connection(dsn=self.web_dsn) as con:
            result = await con.fetch(q)
        # Look for matches
        meant = {}
        ret_str = "```"
        for pair in result:
            cleaned_name = pair['filename'].lower().replace("#", "")
            # Contains check
            if name in cleaned_name:
                return await ctx.send(f"Match found {pair['filename']}:\n{self.bot.config.hostname}/rl?v={pair['uuid']}")
            # Don't include date in jaro_winkler_similarity
            # Consider using re to match date instead.
            elif jaro_winkler_similarity(name, cleaned_name.split("_", 1)[0]) > 0.8:
                meant[pair['filename']] = pair['uuid']
        # Return closest match if only one clip was found.
        if len(meant) == 1:
            for k, v in meant.items():
                return await ctx.send(f"Closest match {k}:\n{self.bot.config.hostname}/rl?v={v}")
        # Print list of suggestions if more than one match exists.
        for suggestion in meant.keys():
            ret_str += "\n" + suggestion
        ret_str += "```"
        # No matches at all.
        if ret_str == "``````":
            return await ctx.send(f'No VOD matching {name} found, see {ctx.prefix}rl list.')
        return await ctx.send(f"VOD {name} not found, did you mean: {ret_str}")

    @rl.command(name='list', brief='List available RL VODs')
    async def rl_list(self, ctx: Context, show_all=None):
        if show_all is not None and show_all == 'all':
            return await self.get_uuid_name_list(ctx, 'rl', list_all=True)
        return await self.get_uuid_name_list(ctx, 'rl', list_all=False)

    @commands.group(brief='Link one of Dre\'s clips', invoke_without_command=True)
    async def clip(self, ctx: Context, *name):
        if len(name) == 0:
            return await ctx.send(f"No clip specified. Check `{ctx.prefix}clip list` or `{ctx.prefix}clip list all`.")
        else:
            name = str(" ".join(name).lower())

        # First check for exact match
        q = "SELECT filename, uuid FROM uuids WHERE type='clips' AND filename ILIKE $1"
        async with pg_connection(dsn=self.web_dsn) as con:
            result = await con.fetchrow(q, name)
        if result is not None:
            return await ctx.send(f"Match found {result['filename']}:\n{self.bot.config.hostname}/clip?v={result['uuid']}")
        # Fetch all because we need to guess which clip the user meant.
        q = "SELECT filename, uuid FROM uuids WHERE type='clips' ORDER BY created DESC"
        async with pg_connection(dsn=self.web_dsn) as con:
            result = await con.fetch(q)
        # Look for matches
        meant = {}
        ret_str = "```"
        for pair in result:
            cleaned_name = pair['filename'].lower()
            # Contains check
            if name in cleaned_name:
                meant[pair['filename']] = pair['uuid']
            # Don't include game in jaro_winkler_similarity
            elif jaro_winkler_similarity(name, cleaned_name.split("_", 1)[1]) > 0.8:
                meant[pair['filename']] = pair['uuid']
        # Return closest match if only one clip was found.
        if len(meant) == 1:
            for k, v in meant.items():
                return await ctx.send(f"Closest match {k}:\n{self.bot.config.hostname}/clip?v={v}")
        # Print list of suggestions if more than one match exists.
        for suggestion in meant.keys():
            ret_str += "\n" + suggestion
        ret_str += "```"
        # No matches at all.
        if ret_str == "``````":
            return await ctx.send(f'No clip matching {name} found, see {ctx.prefix}clip list.')
        return await ctx.send(f"Clip {name} not found, did you mean: {ret_str}")

    @clip.command(name='list', brief='List available vidya clips')
    async def clip_list(self, ctx: Context, list_all=None):
        if list_all == 'all':
            return await self.get_uuid_name_list(ctx, 'clips', True)
        return await self.get_uuid_name_list(ctx, 'clips', False)

    @commands.command(name='react', brief="Add reaction to last message")
    @commands.bot_has_permissions(manage_messages=True)
    async def add_react(self, ctx: Context, text: str, msg_id: int = None):
        if msg_id is not None:
            try:
                msg = await ctx.fetch_message(msg_id)
            except discord.errors.NotFound:
                return await ctx.send(f"No message with ID {msg_id} found.")
        else:
            msg = await discord.utils.get(ctx.history(limit=2, before=ctx.message))
        await ctx.message.delete()
        await self.bot.add_reaction_str(msg, text)

    @commands.command(name='stream', brief="Post Dre's livestream link")
    async def stream(self, ctx: Context):
        live_path = '/mnt/hls/live.m3u8'
        is_live = False
        if os.path.exists(live_path):
            if time.time() - os.path.getmtime(live_path) < 10:
                is_live = True

        if is_live:
            async with pg_connection(dsn=self.web_dsn) as con:
                q = f"SELECT content FROM {self.psql_table_name_web} WHERE name='stream_token'"
                result = await con.fetchrow(q)
            if result is not None:
                if result['content'] != 'null':
                    return await ctx.send(f"Dre stream is live.\n{self.bot.config.hostname}/stream/login?token={result['content']}")
            else:
                return await ctx.send(f"Dre stream is live, but no token was generated. Password is 'memes'.\n{self.bot.config.hostname}/stream")
        else:
            return await ctx.send(f"Dre stream is offline.")

    @commands.command(name='thank', hidden=True)
    async def thank(self, ctx: Context):
        return await ctx.send(f"{cfg.EMOJI_DICT['n']} {cfg.EMOJI_DICT['o']} {cfg.EMOJI_DICT['!']}")

    @commands.command(name='monbaguette', brief='Good meme')
    async def monbaguette(self, ctx: Context):
        return await ctx.send(embed=discord.Embed().set_image(url='https://pbs.twimg.com/media/DDg_fOaVYAAL_tP.jpg'))

    async def get_uuid_name_list(self, ctx: Context, list_type='rl', list_all=False):
        """Fetches and returns a list of clips of given type from PSQL DB"""
        clip_list = []
        if list_all:
            q = "SELECT filename FROM uuids WHERE type=$1 ORDER BY created DESC"
        else:
            q = "SELECT filename FROM uuids WHERE type=$1 ORDER BY created DESC LIMIT 10"
        async with pg_connection(dsn=self.web_dsn) as con:
            result = await con.fetch(q, list_type)
        for d in result:
            clip_list.append(d['filename'] + "\n")

        ret_str = ""
        for i in range(len(clip_list)):
            if len(ret_str) + len(clip_list[i]) > 1900:
                await ctx.send("```" + ret_str + "```")
                ret_str = ''
            ret_str += clip_list[i]
        return await ctx.send("```" + ret_str + "```")

    def dota2_hero_embed(self, ctx: Context, hero):
        attr_names = {'agi': 'Agility',
                      'str': 'Strength',
                      'int': 'Intelligence'}
        hero_icon = f"http://cdn.dota2.com/apps/dota2/images/heroes/{hero['name'].replace('npc_dota_hero_', '')}_full.png"
        embed = discord.Embed()
        embed.colour = discord.Colour.green()
        embed.set_author(name=hero['localized_name'])
        embed.set_thumbnail(url=hero_icon)
        embed.set_footer(text=ctx.author.display_name, icon_url=str_or_none(ctx.author.avatar))
        embed.add_field(name="Primary Attribute", value=attr_names[hero['primary_attr']], inline=False)
        embed.add_field(name="Attack Type", value=hero['attack_type'], inline=False)
        embed.add_field(name="Roles", value=", ".join(hero['roles']), inline=False)
        embed.add_field(name="Legs", value=hero['legs'], inline=False)
        return embed
