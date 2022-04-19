from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from urllib import parse

from discord.ext import commands

import ext.embed_helpers as emh
from ext.context import Context
from ext.errors import MissingConfigError
from ext import utils

if TYPE_CHECKING:
    from mrbot import MrBot


class Search(commands.Cog, name="Search"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        self.headers = dict(app_id='', app_key='')
        self.read_config()

    def read_config(self):
        if s := self.bot.config.api_keys.get('oxford'):
            self.headers['app_id'] = s.get('app_id')
            self.headers['app_key'] = s.get('app_key')
        if not self.headers['app_id']:
            raise MissingConfigError('Oxford API app ID not found')
        if not self.headers['app_key']:
            raise MissingConfigError('Oxford API app key not found')

    @commands.command(name='def', brief="Search Oxford Dictionary")
    async def oxford_def(self, ctx: Context, word: str, lang: str = 'en'):
        start = time.perf_counter()
        url = f'https://od-api.oxforddictionaries.com/api/v2/entries/{lang}/{word.lower()}'
        async with self.bot.aio_sess.get(url=url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
            else:
                return await ctx.send(f"No definiton found for `{word}` in language {lang}.")
        with open(f"{self.bot.config.paths.data}/def_{word}_{lang}.json", 'w') as fw:
            json.dump(data, fw, indent=1)
        embed = emh.embed_init(self.bot, "Oxford Dictionary")
        results = data.get("results", None)
        # Only keep first result
        results = results[0]
        embed.title = f"Definition of {results['id']} [{results['lexicalEntries'][0]['lexicalCategory']['text']}] " + \
                      f"in {results['language']}"
        entry = results['lexicalEntries'][0]['entries'][0]
        definitions = entry['senses'][0]['definitions']
        embed.add_field(name="Definitions", value="\n".join(definitions), inline=False)
        etymologies = entry.get("etymologies", None)
        if etymologies is not None:
            embed.add_field(name="Etymologies", value="\n".join(etymologies), inline=False)

        if examples := entry['senses'][0].get('examples'):
            val = ""
            for example in examples:
                val += example['text'] + "\n"
            embed.add_field(name="Examples", value=val, inline=False)
        embed.set_footer(text=f"Query in {(time.perf_counter()-start)*1000:.0f}ms",
                         icon_url=utils.str_or_none(self.bot.user.avatar))
        return await ctx.send(embed=embed)

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
