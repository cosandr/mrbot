from __future__ import annotations

import re
import time
from io import BytesIO
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import ext.embed_helpers as emh
from ext.context import Context
from ext.parsers import parsers
from ext.utils import find_similar_str, to_columns_vert
from .templates import AllMemeTemplates

if TYPE_CHECKING:
    from mrbot import MrBot


"""
TODO
- Change font and starting position at runtime
"""


class MakeMeme(commands.Cog, name="Make Meme"):

    def __init__(self, bot):
        self.bot: MrBot = bot
        self._re_entry = re.compile(r'\s*-entry\s+', re.IGNORECASE)
        self._templates = None

    async def cog_load(self):
        self._templates = await self.bot.loop.run_in_executor(None, lambda: AllMemeTemplates())

    @parsers.group(
        name='make',
        brief='Make meme from template',
        invoke_without_command=True,
        parser_args=[
            parsers.Arg('name', nargs='+', help='Name of template to use'),
            parsers.Arg('--entry', '-e', nargs='+', action='append', help='Name of template to use'),
        ],
    )
    async def make(self, ctx: Context):
        name = ' '.join(ctx.parsed.name)
        try:
            template = self._templates[name]
        except KeyError:
            return await ctx.send(f'No template {name} found.')
        # Parse args
        entries = [' '.join(e) for e in ctx.parsed.entry]
        # entries = self._re_entry.split(entries)
        # entries = [e for e in entries if e != '']
        if len(entries) != len(template):
            return await ctx.send(f'This template requires {len(template)} entries but {len(entries)} were given')
        start = time.perf_counter()
        img = await self.bot.loop.run_in_executor(None, lambda: template.make(entries))
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        comp_time = time.perf_counter() - start
        embed = emh.embed_init(self.bot, 'Make Meme')
        embed.description = template.name
        embed.set_image(url="attachment://meme.png")
        embed.set_footer(text=f"Completed in {comp_time*1000:.2f}ms", icon_url=embed.footer.icon_url)
        embed.colour = discord.Colour.green()
        await ctx.send(embed=embed, file=discord.File(buf, filename="meme.png"))

    @make.command(name='list', brief='List available templates')
    async def make_list(self, ctx: Context):
        all_memes = self._list_memes(name=None)
        embed = emh.embed_init(self.bot, 'Make Meme')
        embed.title = 'List'
        embed.description = "```" + to_columns_vert(all_memes, num_cols=2, sort=True) + "```"
        return await ctx.send(embed=embed)

    def _list_memes(self, name: str = None) -> list:
        names = self._templates.to_list()
        if name is None:
            return names
        return find_similar_str(name, names)
