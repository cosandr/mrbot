from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib import parse

from discord.ext import commands

import ext.embed_helpers as emh
from ext.context import Context
from ext import utils

if TYPE_CHECKING:
    from mrbot import MrBot


class Search(commands.Cog, name="Search"):
    def __init__(self, bot):
        self.bot: MrBot = bot

    @commands.command(name='wiki', brief='Wikipedia search')
    async def wiki(self, ctx: Context, *, query: str):
        start = time.perf_counter()
        url = "https://en.wikipedia.org/w/api.php?format=json&action=query&prop=extracts&exintro&explaintext&redirects=1"
        params = {'titles': query}
        async with self.bot.aio_sess.get(url=url, params=params) as resp:
            data = await resp.json()
        page = next(iter(data['query']['pages'].values()))
        title = page['title']
        content = page.get('extract', None)
        if content is None:
            return await ctx.send(f"No results for {query}.")
        embed = emh.embed_init(self.bot, "Wikipedia")
        embed.title = title
        embed.description = content[:1000]
        encoded_tmp = parse.quote(title)
        embed.url = f"https://en.wikipedia.org/wiki/{encoded_tmp}"
        # Get images on page
        imgs = "https://en.wikipedia.org/w/api.php?action=parse&format=json&prop=images"
        params = {'page': title}
        async with self.bot.aio_sess.get(url=imgs, params=params) as resp:
            data = await resp.json()
        img_names = data['parse']['images']
        # Get specific image url
        img_guess = None
        for name in img_names:
            if not name.lower().endswith(('.jpg', '.png', '.jpeg')):
                continue
            img_guess = name
            break

        if img_guess is not None:
            img_q = "https://en.wikipedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url&format=json"
            params = {'titles': f'Image:{img_guess}'}
            async with self.bot.aio_sess.get(url=img_q, params=params) as resp:
                data = await resp.json()
            tmp = next(iter(data['query']['pages'].values()))
            img_url = tmp["imageinfo"][0]['url']
            embed.set_image(url=img_url)

        embed.set_footer(text=f"Query in {(time.perf_counter()-start)*1000:.0f}ms", icon_url=utils.str_or_none(self.bot.user.avatar))
        return await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Search(bot))
