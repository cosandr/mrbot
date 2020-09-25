import logging
import os
import re
import traceback
from asyncio import TimeoutError
from collections import namedtuple
from io import BytesIO
from typing import Optional

import discord
from PIL import Image
from discord.ext import commands
from jellyfish import jaro_winkler_similarity

from ext import utils
from ext.errors import UnapprovedGuildError
from ext.internal import Message
from mrbot import MrBot


class Emojis(commands.Cog, name="Emojis"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger_name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.re_file = re.compile(r'_\d+x\d+$')
        self.re_ext = re.compile(r'\.(png|jpeg|jpg|gif)$', re.IGNORECASE)
        self.Emoji = namedtuple('Emoji', ['name', 'filename', 'url'])
        self.disk_cache = self.bot.config.paths.upload + "/emojis"
        self.url = f'{self.bot.config.hostname}/discord/emojis/'
        if not os.path.exists(self.disk_cache):
            os.mkdir(self.disk_cache, 0o755)

    async def cog_check(self, ctx):
        if await self.bot.is_owner(ctx.author):
            return True
        # Ignore DMs
        if not ctx.guild:
            raise UnapprovedGuildError()
        # Only apply to approved guilds
        else:
            if ctx.guild.id not in self.bot.config.approved_guilds:
                raise UnapprovedGuildError()
        return True

    @commands.group(name='emoji', brief='Emoji command group', invoke_without_command=True)
    async def emoji(self, ctx, name: str):
        ok = await self.send_emoji(name, ctx.message.channel)
        if ok:
            return
        return await ctx.send(f'No emoji similar to {name} found')

    @emoji.command(name='import', brief='Import emoji, will be resized')
    async def emoji_import(self, ctx, name: str):
        if utils.re_url.search(name) is not None:
            return await ctx.send('No name provided.')
        # Make sure it doesn't already exist
        try:
            em = await self.get_emoji(name.lower(), loose=False)
            if em is not None:
                embed = self.make_embed(em)
                embed.description = f'An emoji with name {em.name} already exists.'
                return await ctx.send(embed=embed)
        except Exception as e:
            self.logger.warning(f"Failed to get emoji URL {name}: {e}")
            # Skip, try to recreate
            pass
        # Check message for attachments
        msg = Message.from_discord(ctx.message)
        if not msg.urls:
            return await ctx.send('No URL or attachments found in message.')
        img_url = ''
        file_ext = ''
        for url in msg.urls:
            m = self.re_ext.search(url)
            if m:
                img_url = url
                file_ext = m.group().lower()
                break
        if not img_url:
            return await ctx.send('Invalid URL, only jpg/png/gif files can be uploaded.')
        msg = await ctx.send('Downloading and resizing')
        try:
            img_buf = await utils.bytes_from_url(img_url, self.bot.aio_sess)
        except Exception as e:
            traceback.print_exc()
            return await msg.edit(content=f'Cannot download image: {str(e)}')
        # Don't resize GIFs
        resize = file_ext != '.gif'
        try:
            em = await self.bot.loop.run_in_executor(None, lambda: self.save_emoji(name, img_buf, resize=resize, ext=file_ext))
        except Exception as e:
            traceback.print_exc()
            return await msg.edit(content=f'Cannot save image: {str(e)}')
        embed = self.make_embed(em)
        return await msg.edit(content=f'Added {em.name} emoji.', embed=embed)

    @emoji.command(name='list', brief='List all available emoji')
    async def emoji_list(self, ctx, name: str=None):
        # Get list of all emojis
        all_emojis = set([em.name for em in self.bot.emojis])
        for file in os.listdir(self.disk_cache):
            file_name, file_ext = os.path.splitext(file)
            if self.re_ext.match(file_ext):
                all_emojis.add(self.re_file.sub("", file_name))
        if name is not None:
            # Get close matches
            all_emojis = utils.find_similar_str(name, list(all_emojis))
            if not all_emojis:
                return await ctx.send(f"No emojis similar to {name} found")
        return await ctx.send("```" + utils.to_columns_vert(all_emojis, num_cols=4, sort=True) + "```")

    @emoji.command(name='del', brief='Delete an emoji, must be on disk')
    async def emoji_del(self, ctx, name: str):
        em = self.find_file_emoji(name, loose=False)
        if em is None:
            return await ctx.send(f'No emoji `{name}` found.')
        embed = self.make_embed(em)
        embed.description = 'Confirm deletion'
        msg = await ctx.send(embed=embed)
        react_emoji = '✅'
        await msg.add_reaction(react_emoji)

        def check(reaction, user):
            return reaction.message.id == msg.id and str(reaction.emoji) == react_emoji and \
                user == ctx.author

        try:
            await self.bot.wait_for('reaction_add', timeout=5.0, check=check)
        except TimeoutError:
            embed.description = 'Deletion uncofirmed'
            return await msg.edit(embed=embed)
        try:
            os.unlink(f'{self.disk_cache}/{em.filename}')
            embed.description = 'Deleted'
            embed.set_image(url="")
            embed.set_author(name=em.name)
        except Exception as e:
            embed.description = f'Failed to delete: {str(e)}'
        await msg.edit(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.user.mentioned_in(message):
            return
        found_mention = False
        # Loop over all words in the message
        for word in message.content.split():
            # Only interested in words after the mention
            if str(self.bot.user.id) in word:
                found_mention = True
                continue
            if not found_mention:
                continue
            ok = await self.send_emoji(word, message.channel)
            if ok:
                return

    async def send_emoji(self, word: str, chan: discord.abc.Messageable) -> bool:
        """Attempts to get an emoji and send it"""
        try:
            em_tuple = await self.get_emoji(word, loose=False)
            if em_tuple is None:
                em_tuple = await self.get_emoji(word, loose=True)
        except Exception as e:
            traceback.print_exc()
            self.logger.warning(f"Failed to get emoji URL {word}: {e}")
            return False
        # If we get None, it was not in the cache and could not be created either, skip
        if em_tuple is None:
            return False
        msg = await chan.send(embed=self.make_embed(em_tuple))
        # Try to add as reaction
        em = self.find_bot_emoji(word, loose=False)
        if em is None:
            em = self.find_bot_emoji(word, loose=True)
        if em is None:
            self.logger.info(f'No bot emoji found for {em_tuple.name}')
            return True
        try:
            await msg.add_reaction(em)
        except Exception as e:
            self.logger.warning(f"Failed to add reaction for {em.name}: {e}")
        return True

    async def get_emoji(self, name: str, loose: bool=True) -> namedtuple:
        """Returns emoji URL, first checking disk, otherwise resizing one the bot has access to"""
        em = self.find_file_emoji(name, loose=loose)
        # Found locally
        if em is not None:
            return em
        # Check bot emojis
        em = self.find_bot_emoji(name, loose=loose)
        # Not found, return
        if em is None:
            return None
        # Download emoji to buffer
        buf = await self.download_emoji(em)
        # Don't resize if animated
        return await self.bot.loop.run_in_executor(None, lambda: self.save_emoji(em.name, buf, resize=not em.animated))

    def make_embed(self, em: namedtuple) -> discord.Embed:
        embed = utils.transparent_embed()
        embed.set_image(url=em.url)
        embed.set_author(name=em.name, url=em.url)
        return embed

    def find_bot_emoji(self, name: str, loose: bool=True) -> Optional[discord.Emoji]:
        """
        Find an emoji the bot has access to similar to/equal to (when `loose` is False) `name`
        Parameters
        ----------
        name: `str`
            Emoji name to look for
        loose: `bool` Optional[True]
            Find approximate matches
        Returns
        --------
        `discord.Emoji`
            The found emoji
        `None`
            If nothing matches
        """
        for em in self.bot.emojis:
            if name == em.name.lower():
                return em
        if not loose:
            return None
        for em in self.bot.emojis:
            em_lower = em.name.lower()
            if jaro_winkler_similarity(name, em_lower) > 0.8:
                return em
            elif name in em_lower or em_lower in name:
                return em
        return None

    def find_file_emoji(self, name: str, loose: bool=True) -> Optional[namedtuple]:
        """
        Find an emoji on the disk similar to/equal to (when `loose` is False) `name`
        Parameters
        ----------
        name: `str`
            Emoji name to look for
        loose: `bool` Optional[True]
            Find approximate matches
        Returns
        --------
        `namedtuple`
            A tuple with "name", "filename" and "url" fields
        `None`
            If nothing matches
        """
        # Only check valid files
        files = {}
        for file in os.listdir(self.disk_cache):
            file_name, file_ext = os.path.splitext(file)
            if self.re_ext.match(file_ext):
                clean = self.re_file.sub("", file_name)
                files[clean] = file
        # Check for exact matches
        for clean, file in files.items():
            if name == clean.lower():
                return self.Emoji(clean, file, self.url+file)
        if not loose:
            return None
        # Check for loose matches
        for clean, file in files.items():
            clean_lower = clean.lower()
            if jaro_winkler_similarity(name, clean_lower) > 0.8:
                return self.Emoji(clean, file, self.url+file)
            elif name in clean_lower or clean_lower in name:
                return self.Emoji(clean, file, self.url+file)
        return None

    async def download_emoji(self, em: discord.Emoji) -> BytesIO:
        """Resizes a discord Emoji and returns its on-disk URL"""
        buf = BytesIO()
        saved_bytes = await em.url.save(buf)
        if saved_bytes == 0:
            return None
        return buf

    def save_emoji(self, name: str, buf: BytesIO, resize: bool=True, new_x: int=512, ext: str=None) -> namedtuple:
        """Resize input `buf` and return its namedtuple"""
        img = Image.open(buf)
        if resize:
            new_y = int(new_x*(img.height/img.width))
            img = img.resize((new_x, new_y))
        file_name = f'{name}_{img.width}x{img.height}'
        if ext is not None:
            file_name += ext
        elif img.format is not None:
            file_name += f'.{img.format.lower()}'
        else:
            file_name += '.png'
        file_path = os.path.join(self.disk_cache, file_name)
        img.save(file_path)
        os.chmod(file_path, 0o644)
        return self.Emoji(name, file_name, self.url+file_name)


def setup(bot):
    bot.add_cog(Emojis(bot))
