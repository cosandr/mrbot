from __future__ import annotations

import itertools
import logging
import random
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from emoji import EMOJI_UNICODE

import config as cfg
from ext import utils, parsers
from ext.context import Context
from ext.internal import Guild
from ext.psql import create_table
from ext.utils import re_id
from .config import ReactionsConfig

if TYPE_CHECKING:
    from mrbot import MrBot


class Reactions(commands.Cog, name="Reaction"):
    psql_table_name = 'reactions'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            category   VARCHAR(200) NOT NULL UNIQUE,
            react_list VARCHAR(20) [] NOT NULL,
            weight     SMALLINT,
            guild_id   BIGINT REFERENCES {Guild.psql_table_name} (id)
    );
    """
    psql_all_tables = Guild.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        self.config = ReactionsConfig()
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.all_emoji = set(EMOJI_UNICODE.values())
        # Regex compile
        self.re_ruski = re.compile(r'[бвгджзклмнпрстфхцчшщаэыуояеёюи]', re.IGNORECASE)
        self.re_crab = re.compile(r'is\s+gone', re.IGNORECASE)
        self.re_url = re.compile(r'https?://\S+')
        self.re_gyazo = re.compile(r'https://gyazo\.com/\w{32}')
        self.re_twitch = re.compile(r'https?://(clips\.|www\.)?twitch\S+')
        self.re_reddit = re.compile(r'https?://\S+(redd\.it|reddit\.com)\S+')
        self.re_em = re.compile(r'<a?:\w+?:\d{18}>')
        self.re_em_id = re.compile(r'\d{18}')
        self.re_em_unicode = re.compile('(?:\U0001f1e6[\U0001f1e8-\U0001f1ec\U0001f1ee\U0001f1f1\U0001f1f2\U0001f1f4\U0001f1f6-\U0001f1fa\U0001f1fc\U0001f1fd\U0001f1ff])|(?:\U0001f1e7[\U0001f1e6\U0001f1e7\U0001f1e9-\U0001f1ef\U0001f1f1-\U0001f1f4\U0001f1f6-\U0001f1f9\U0001f1fb\U0001f1fc\U0001f1fe\U0001f1ff])|(?:\U0001f1e8[\U0001f1e6\U0001f1e8\U0001f1e9\U0001f1eb-\U0001f1ee\U0001f1f0-\U0001f1f5\U0001f1f7\U0001f1fa-\U0001f1ff])|(?:\U0001f1e9[\U0001f1ea\U0001f1ec\U0001f1ef\U0001f1f0\U0001f1f2\U0001f1f4\U0001f1ff])|(?:\U0001f1ea[\U0001f1e6\U0001f1e8\U0001f1ea\U0001f1ec\U0001f1ed\U0001f1f7-\U0001f1fa])|(?:\U0001f1eb[\U0001f1ee-\U0001f1f0\U0001f1f2\U0001f1f4\U0001f1f7])|(?:\U0001f1ec[\U0001f1e6\U0001f1e7\U0001f1e9-\U0001f1ee\U0001f1f1-\U0001f1f3\U0001f1f5-\U0001f1fa\U0001f1fc\U0001f1fe])|(?:\U0001f1ed[\U0001f1f0\U0001f1f2\U0001f1f3\U0001f1f7\U0001f1f9\U0001f1fa])|(?:\U0001f1ee[\U0001f1e8-\U0001f1ea\U0001f1f1-\U0001f1f4\U0001f1f6-\U0001f1f9])|(?:\U0001f1ef[\U0001f1ea\U0001f1f2\U0001f1f4\U0001f1f5])|(?:\U0001f1f0[\U0001f1ea\U0001f1ec-\U0001f1ee\U0001f1f2\U0001f1f3\U0001f1f5\U0001f1f7\U0001f1fc\U0001f1fe\U0001f1ff])|(?:\U0001f1f1[\U0001f1e6-\U0001f1e8\U0001f1ee\U0001f1f0\U0001f1f7-\U0001f1fb\U0001f1fe])|(?:\U0001f1f2[\U0001f1e6\U0001f1e8-\U0001f1ed\U0001f1f0-\U0001f1ff])|(?:\U0001f1f3[\U0001f1e6\U0001f1e8\U0001f1ea-\U0001f1ec\U0001f1ee\U0001f1f1\U0001f1f4\U0001f1f5\U0001f1f7\U0001f1fa\U0001f1ff])|\U0001f1f4\U0001f1f2|(?:\U0001f1f4[\U0001f1f2])|(?:\U0001f1f5[\U0001f1e6\U0001f1ea-\U0001f1ed\U0001f1f0-\U0001f1f3\U0001f1f7-\U0001f1f9\U0001f1fc\U0001f1fe])|\U0001f1f6\U0001f1e6|(?:\U0001f1f6[\U0001f1e6])|(?:\U0001f1f7[\U0001f1ea\U0001f1f4\U0001f1f8\U0001f1fa\U0001f1fc])|(?:\U0001f1f8[\U0001f1e6-\U0001f1ea\U0001f1ec-\U0001f1f4\U0001f1f7-\U0001f1f9\U0001f1fb\U0001f1fd-\U0001f1ff])|(?:\U0001f1f9[\U0001f1e6\U0001f1e8\U0001f1e9\U0001f1eb-\U0001f1ed\U0001f1ef-\U0001f1f4\U0001f1f7\U0001f1f9\U0001f1fb\U0001f1fc\U0001f1ff])|(?:\U0001f1fa[\U0001f1e6\U0001f1ec\U0001f1f2\U0001f1f8\U0001f1fe\U0001f1ff])|(?:\U0001f1fb[\U0001f1e6\U0001f1e8\U0001f1ea\U0001f1ec\U0001f1ee\U0001f1f3\U0001f1fa])|(?:\U0001f1fc[\U0001f1eb\U0001f1f8])|\U0001f1fd\U0001f1f0|(?:\U0001f1fd[\U0001f1f0])|(?:\U0001f1fe[\U0001f1ea\U0001f1f9])|(?:\U0001f1ff[\U0001f1e6\U0001f1f2\U0001f1fc])|(?:\U0001f3f3\ufe0f\u200d\U0001f308)|(?:\U0001f441\u200d\U0001f5e8)|(?:[\U0001f468\U0001f469]\u200d\u2764\ufe0f\u200d(?:\U0001f48b\u200d)?[\U0001f468\U0001f469])|(?:(?:(?:\U0001f468\u200d[\U0001f468\U0001f469])|(?:\U0001f469\u200d\U0001f469))(?:(?:\u200d\U0001f467(?:\u200d[\U0001f467\U0001f466])?)|(?:\u200d\U0001f466\u200d\U0001f466)))|(?:(?:(?:\U0001f468\u200d\U0001f468)|(?:\U0001f469\u200d\U0001f469))\u200d\U0001f466)|[\u2194-\u2199]|[\u23e9-\u23f3]|[\u23f8-\u23fa]|[\u25fb-\u25fe]|[\u2600-\u2604]|[\u2638-\u263a]|[\u2648-\u2653]|[\u2692-\u2694]|[\u26f0-\u26f5]|[\u26f7-\u26fa]|[\u2708-\u270d]|[\u2753-\u2755]|[\u2795-\u2797]|[\u2b05-\u2b07]|[\U0001f191-\U0001f19a]|[\U0001f1e6-\U0001f1ff]|[\U0001f232-\U0001f23a]|[\U0001f300-\U0001f321]|[\U0001f324-\U0001f393]|[\U0001f399-\U0001f39b]|[\U0001f39e-\U0001f3f0]|[\U0001f3f3-\U0001f3f5]|[\U0001f3f7-\U0001f3fa]|[\U0001f400-\U0001f4fd]|[\U0001f4ff-\U0001f53d]|[\U0001f549-\U0001f54e]|[\U0001f550-\U0001f567]|[\U0001f573-\U0001f57a]|[\U0001f58a-\U0001f58d]|[\U0001f5c2-\U0001f5c4]|[\U0001f5d1-\U0001f5d3]|[\U0001f5dc-\U0001f5de]|[\U0001f5fa-\U0001f64f]|[\U0001f680-\U0001f6c5]|[\U0001f6cb-\U0001f6d2]|[\U0001f6e0-\U0001f6e5]|[\U0001f6f3-\U0001f6f6]|[\U0001f910-\U0001f91e]|[\U0001f920-\U0001f927]|[\U0001f933-\U0001f93a]|[\U0001f93c-\U0001f93e]|[\U0001f940-\U0001f945]|[\U0001f947-\U0001f94b]|[\U0001f950-\U0001f95e]|[\U0001f980-\U0001f991]|\u00a9|\u00ae|\u203c|\u2049|\u2122|\u2139|\u21a9|\u21aa|\u231a|\u231b|\u2328|\u23cf|\u24c2|\u25aa|\u25ab|\u25b6|\u25c0|\u260e|\u2611|\u2614|\u2615|\u2618|\u261d|\u2620|\u2622|\u2623|\u2626|\u262a|\u262e|\u262f|\u2660|\u2663|\u2665|\u2666|\u2668|\u267b|\u267f|\u2696|\u2697|\u2699|\u269b|\u269c|\u26a0|\u26a1|\u26aa|\u26ab|\u26b0|\u26b1|\u26bd|\u26be|\u26c4|\u26c5|\u26c8|\u26ce|\u26cf|\u26d1|\u26d3|\u26d4|\u26e9|\u26ea|\u26fd|\u2702|\u2705|\u270f|\u2712|\u2714|\u2716|\u271d|\u2721|\u2728|\u2733|\u2734|\u2744|\u2747|\u274c|\u274e|\u2757|\u2763|\u2764|\u27a1|\u27b0|\u27bf|\u2934|\u2935|\u2b1b|\u2b1c|\u2b50|\u2b55|\u3030|\u303d|\u3297|\u3299|\U0001f004|\U0001f0cf|\U0001f170|\U0001f171|\U0001f17e|\U0001f17f|\U0001f18e|\U0001f201|\U0001f202|\U0001f21a|\U0001f22f|\U0001f250|\U0001f251|\U0001f396|\U0001f397|\U0001f56f|\U0001f570|\U0001f587|\U0001f590|\U0001f595|\U0001f596|\U0001f5a4|\U0001f5a5|\U0001f5a8|\U0001f5b1|\U0001f5b2|\U0001f5bc|\U0001f5e1|\U0001f5e3|\U0001f5e8|\U0001f5ef|\U0001f5f3|\U0001f6e9|\U0001f6eb|\U0001f6ec|\U0001f6f0|\U0001f930|\U0001f9c0|[#|0-9]\u20e3')
        self.react_list = {}
        self.react_weights = {}
        # Check required table and load reactions
        self.bot.loop.create_task(self.async_init())

    async def async_init(self):
        await self.bot.connect_task
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            async with self.bot.pool.acquire() as con:
                await create_table(con, names, q, self.logger)
                self.config = await ReactionsConfig.read_psql(con)
        await self.load_reactions()

    async def load_reactions(self):
        async with self.bot.pool.acquire() as con:
            q = f'SELECT category, react_list, weight FROM {self.psql_table_name}'
            res = await con.fetch(q)
        self.react_list = {}
        self.react_weights = {}
        for r in res:
            self.react_list[r['category']] = r['react_list']
            self.react_weights[r['category']] = r['weight']

    @commands.group(name='reactions', brief='List link reactions', invoke_without_command=True)
    async def reactions(self, ctx: Context):
        q = f'SELECT category, react_list FROM {self.psql_table_name}'
        async with self.bot.pool.acquire() as con:
            results = await con.fetch(q)
        if not results:
            return await ctx.send('No reactions added.')
        ret = [f"# {r['category']}\n{utils.to_columns_vert(r['react_list'], num_cols=4, sort=True)}" for r in results]
        for p in utils.paginate('\n'.join(ret)):
            await ctx.send(p)

    @reactions.command(name="add", brief="Add a link reaction")
    async def reactions_add(self, ctx: Context, reaction: str, category: str):
        if not await self.check_category(ctx, category):
            return
        valid, err_str = self.validate_reaction(reaction)
        if not valid:
            return await ctx.send(err_str)
        async with self.bot.pool.acquire() as con:
            q = f"UPDATE {self.psql_table_name} SET react_list=array_append(react_list, $2) WHERE category=$1"
            await con.execute(q, category, reaction)
        await ctx.send(f"{reaction} added as a {category} reaction.")
        await self.load_reactions()

    @reactions.command(name="move", brief="Change link reaction category")
    async def reactions_move(self, ctx: Context, reaction: str, new_category: str):
        if not await self.check_category(ctx, new_category):
            return
        reaction = reaction.lower()
        valid = False
        old_cat = None
        for k, v in self.react_list.items():
            if reaction in v:
                valid = True
                old_cat = k
        if not valid:
            return await ctx.send(f"No reaction {reaction} found.")
        async with self.bot.pool.acquire() as con:
            q_get = f"SELECT react_list FROM {self.psql_table_name} WHERE category=$1;"
            q_upd = f"UPDATE {self.psql_table_name} SET react_list=$2 WHERE category=$1;"
            async with con.transaction():
                # Fetch and remove reaction from old category
                res = await con.fetchval(q_get, old_cat)
                res.remove(reaction)
                # Write changes
                await con.execute(q_upd, old_cat, res)
                # Fetch new category and add reaction
                res = await con.fetchval(q_get, new_category)
                res.append(reaction)
                # Write changes
                await con.execute(q_upd, new_category, res)
        await ctx.send(f"{reaction} moved from {old_cat} to {new_category}.")
        await self.load_reactions()

    @reactions.command(name="del", brief="Delete a link reaction")
    async def reactions_del(self, ctx: Context, reaction: str):
        reaction = reaction.lower()
        valid = False
        category = None
        for k, v in self.react_list.items():
            if reaction in v:
                valid = True
                category = k
        if not valid:
            await ctx.send(f"No reaction {reaction} found.")
            return
        async with self.bot.pool.acquire() as con:
            q = f"UPDATE {self.psql_table_name} SET react_list=array_remove(react_list, $2) WHERE category=$1"
            await con.execute(q, category, reaction)
        await ctx.send(f"{reaction} removed from {category} reactions.")
        await self.load_reactions()

    @reactions.command(name="search", brief="Search for a link reaction")
    async def reactions_search(self, ctx: Context, reaction: str):
        if len(reaction) <= 1:
            await ctx.send(f"Be more specific.")
            return
        reaction = reaction.lower()
        ret_str = ""
        for k, v in self.react_list.items():
            similar = utils.find_similar_str(reaction, v)
            if similar:
                ret_str += f"{k}: {', '.join(similar)}\n"
        if len(ret_str) == 0:
            await ctx.send(f"No reactions similar to {reaction} found.")
        else:
            await ctx.send(ret_str)

    @staticmethod
    def reactions_config_parser(parser: parsers.ArgumentParser):
        sub = parser.add_subparsers()
        parser_on_message = sub.add_parser('on-message')
        parser_on_message.add_argument('-l', '--list', action='store_true', help='Show config')
        parser_on_message.add_argument('-r', '--remove', action='store_true', help='Remove instead of adding')
        parser_on_message.add_argument('-c', '--ignore-channel', type=int, help='Add channel to ignore')
        parser_on_message.set_defaults(func='reactions_config_on_message')

    @reactions.command(
        name='config',
        brief='Edit reactions config',
        cls=parsers.Command,
        hidden=True,
        parser_callback=reactions_config_parser,
    )
    @commands.is_owner()
    async def reactions_config(self, ctx: Context):
        return

    async def reactions_config_on_message(self, ctx: Context):
        if ctx.parsed.list:
            if not self.config.on_message_ignore_channels:
                return await ctx.send('No channels configured')
            tmp = 'Ignored channels:```'
            for ch_id in self.config.on_message_ignore_channels:
                if ch := self.bot.get_channel(ch_id):
                    tmp += f'\n- {ch.mention}'
                    if ch.guild:
                        tmp += f' in guild {ch.guild.name}'
                else:
                    tmp += f'\n- ID {ch_id}'
            return await ctx.send(f'{tmp}```')
        ch_id = ctx.parsed.ignore_channel
        if ch_id:
            if not re_id.match(str(ch_id)):
                return await ctx.send(f'Invalid ID {ch_id}')
            async with self.bot.pool.acquire() as con:
                changed = await self.config.edit_on_message_ignore_channels(con, ch_id, ctx.parsed.remove)
            action = "Removed" if ctx.parsed.remove else "Added"
            if changed:
                return await ctx.send(f'{action} channel ID {ch_id}')
            return await ctx.send('No config changes made')

    async def check_category(self, ctx: Context, category: str) -> bool:
        if category not in self.react_list:
            meant = utils.find_similar_str(category, self.react_list.keys())
            if meant:
                await ctx.send(f"Invalid category {category}, did you mean: {', '.join(meant)}?")
                return False
            await ctx.send(f"Invalid category {category}")
            return False
        return True

    def validate_reaction(self, in_str: str):
        err_str = ""
        in_str = in_str.lower()
        # Track valid letters and how many times they occur
        first_set = set()
        second_set = set()
        valid = True
        if len(in_str) > 20:
            err_str += "20 character limit exceeded.\n"
            valid = False
        for c in in_str:
            if c not in cfg.EMOJI_DICT:
                err_str += f"`{c}` cannot be added as reaction.\n"
                valid = False
                continue
            if c in first_set:
                if c not in second_set:
                    err_str += f"`{c}` occurs more than once.\n"
                    valid = False
                    second_set.add(c)
                continue
            first_set.add(c)
        for k, v in self.react_list.items():
            if in_str in v:
                valid = False
                err_str = f"{in_str} already exists as a {k} reaction."
        return valid, err_str

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user:discord.User):
        if len(reaction.message.reactions) >= 20:
            return
        if user.id == self.bot.user.id:
            return
        # Ignore bots
        if user.bot:
            return
        # Ignore DMs
        if not reaction.message.guild:
            return
        # Ignore star emoji
        if reaction.emoji == cfg.STAR:
            return
        # Only apply to approved guilds
        if reaction.message.guild.id not in self.bot.config.approved_guilds:
            return
        try:
            await reaction.message.add_reaction(reaction.emoji)
        except Exception as e:
            if reaction.custom_emoji:
                self.logger.warning(f"Failed to add custom emoji {reaction.emoji}: {e}")
            else:
                self.logger.warning(f"Failed to add Unicode emoji {ord(reaction.emoji):x}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id == self.bot.user.id:
            return
        if message.content.startswith(self.bot.command_prefix):
            return
        # Ignore DMs
        if not message.guild:
            return
        # Only apply to approved guilds
        if message.guild.id not in self.bot.config.approved_guilds:
            return
        # Ignore blacklisted channels
        if message.channel.id in self.config.on_message_ignore_channels:
            return
        # Add unicode emoji
        react_added = set()
        for m in self.re_em_unicode.finditer(message.content):
            if len(message.reactions) >= 20:
                return
            em = m.group()
            if em in react_added:
                continue
            try:
                await message.add_reaction(em)
                react_added.add(em)
            except Exception as e:
                self.logger.warning(f"Failed to add Unicode emoji {ord(em):x}: {e}")
                break
        # Add custom emoji
        for match in self.re_em.finditer(message.content):
            if len(message.reactions) >= 20:
                return
            if not isinstance(match.group(), str):
                continue
            found_id = int(self.re_em_id.search(match.group()).group())
            try:
                em = self.bot.get_emoji(found_id)
                if em:
                    await message.add_reaction(em)
            except Exception as e:
                self.logger.warning(f"Failed to add custom emoji {match.group()}: {e}")
                continue

        if len(message.reactions) >= 20:
            return
        # Add russian flag if cyrillic letters in message
        if self.re_ruski.search(message.content):
            await message.add_reaction("\N{REGIONAL INDICATOR SYMBOL LETTER R}\N{REGIONAL INDICATOR SYMBOL LETTER U}")

        if len(message.reactions) >= 20:
            return
        # Add crab 'is gone' is in message
        if self.re_crab.search(message.content):
            await message.add_reaction("\N{CRAB}")

        # Add emoji if it is mentioned in text, ignore short words
        words = [w for w in message.content.split() if len(w) >= 3]
        for em in self.bot.emojis:
            if len(message.reactions) >= 20:
                return
            if m := utils.find_closest_match(em.name, words):
                # Only exact matches for short words
                if len(m[0]) < 5 and m[1] != 1.0:
                    continue
                if m[1] < 0.95:
                    continue
                self.logger.debug("Added emoji %s similar to word %s [%.2f]", em.name, m[0], m[1])
                await message.add_reaction(em)

        if len(message.reactions) >= 20:
            return

        url = None
        # Look for URL in message content first
        match = self.re_url.search(message.content)
        if match is not None:
            url = match.group()
        # Look for attachments
        elif len(message.attachments) > 0:
            url = message.attachments[0].url
        elif len(message.embeds) > 0:
            url = message.embeds[0].image.url

        if not isinstance(url, str):
            # 50% chance to add respond to question if there are no reactions already
            if len(message.reactions) == 0 and message.content.endswith('?') and random.randint(0, 10) < 5:
                if random.randint(0, 10) < 5:
                    await self.bot.add_reaction_str(message, "no")
                else:
                    await self.bot.add_reaction_str(message, "yes")
            return

        # 20% chance to add random emoji if there are no reactions already
        if len(message.reactions) == 0 and random.randint(0, 10) < 2:
            await message.add_reaction(random.choice(self.bot.emojis))
            return

        pos_override = None
        # --- Special weight changes ---
        # Jens
        if message.author.id == 337710538928816138:
            if self.re_gyazo.match(url) is not None:
                pos_override = 80
            elif self.re_twitch.match(url) is not None:
                pos_override = 10
        # Yan
        if message.author.id == 153882790599852032:
            if self.re_reddit.match(url) is not None:
                pos_override = 40

        weights = self.react_weights.copy()
        if pos_override:
            ratio = weights['neutral']/weights['negative']
            weights['positive'] = pos_override
            weights['negative'] = round((100 - weights['rare'] - weights['positive']) / (1 + ratio))
            weights['neutral'] = round(weights['negative'] * ratio)
            weights['neutral'] += 100 - sum(weights.values())
        # Calculate thresholds
        random_num = random.randint(0, 100)
        start = 0
        end = 0
        for k, v in weights.items():
            end += v
            if start <= random_num < end:
                await self.bot.add_reaction_str(message, random.choice(self.react_list[k]))
                break
            start = end
