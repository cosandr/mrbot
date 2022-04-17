from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import ext.embed_helpers as emh
from ext.context import Context
from ext.errors import MissingConfigError
from .checks import connect_voice_check, is_voice_check
from .youtube import YouTube, get_stream_url

if TYPE_CHECKING:
    from mrbot import MrBot


class Music(commands.Cog, name="YouTube Music"):

    yt = None

    def __init__(self, bot):
        self.bot: MrBot = bot
        self.api_key: str = ''
        self.read_config()
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.voice_con = None
        self.controls_msg = None
        self.song_counter = 0
        self.song_queue = []
        self.volume = 0.05
        self.no_autoplay = asyncio.Event()
        self.alexa_running = asyncio.Event()
        self.re_yt = re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.\S+')
        self.bot.loop.create_task(self.async_load())

    def read_config(self):
        self.api_key = self.bot.config.api_keys.get('google')
        if not self.api_key:
            raise MissingConfigError('Google API key not found')

    async def async_load(self):
        await self.bot.sess_ready.wait()
        self.yt = YouTube(self.bot.aio_sess, self.api_key)

    def cog_unload(self):
        self.bot.cleanup_tasks.append(self.bot.loop.create_task(self._dc()))

    @commands.group(brief='Play direct YT link or search for song name', invoke_without_command=True)
    @connect_voice_check()
    async def alexa(self, ctx: Context, *, name: str):
        if self.alexa_running.is_set():
            return await ctx.send("Alexa is already running.")
        # https://youtu.be/WgNIfnjr4t0
        # https://www.youtube.com/watch?v=fZPPFVajqvA&t=0s
        match = self.re_yt.search(name)
        # No direct link, search for string instead.
        if match is None:
            res = await self.yt.search(name, playlist=False)
            if res is None:
                return await ctx.send(f"No results found for `{name}`.")
            embed = emh.embed_init(self.bot, "YouTube Video Search")
            i = 0
            for video in res:
                # url, title, uploader, published, type, id
                vid_info = f"Uploaded by: {video['uploader']}"
                embed.add_field(name=f"{i} - {video['title']}", value=vid_info, inline=False)
                i += 1
            embed.title = f"Autoplaying first result in 5s, reply with a different number or 'stop' to cancel."
            msg = await ctx.send(embed=embed)

            def check(m):
                return m.author.id == ctx.author.id and not m.content.startswith(ctx.prefix)
            try:
                self.alexa_running.set()
                reply = await self.bot.wait_for('message', check=check, timeout=5.0)
                if reply.content == 'stop':
                    self.alexa_running.clear()
                    embed.title = "Cancelled."
                    return await msg.edit(embed=embed)
                elif reply.content in ['0', '1', '2', '3', '4']:
                    self.alexa_running.clear()
                    add_song = res[int(reply.content)]
                    embed.title = f"Added {add_song['title']} as next song in queue."
                    playback = await self.insert_and_play(add_song)
                    if not playback:
                        return await emh.embed_socket_err(msg, embed, "Playback failure.")
                    await msg.edit(embed=embed)
                    return await ctx.invoke(self.bot.get_command("controls"))
                else:
                    self.alexa_running.clear()
                    embed.title = "Unrecognized response."
                    return await msg.edit(embed=embed)
            except asyncio.TimeoutError:
                self.alexa_running.clear()
                embed.title = f"Added {res[0]['title']} as next song in queue."
                playback = await self.insert_and_play(res[0])
                if not playback:
                    return await emh.embed_socket_err(msg, embed, "Playback failure.")
                await msg.edit(embed=embed)
                return await ctx.invoke(self.bot.get_command("controls"))
        # Direct video link, play from it
        else:
            url = match.group()
            # Extract video ID
            prefixes = ['https://youtu.be/', 'https://www.youtube.com/watch?v=']
            vid_id = None
            for prefix in prefixes:
                tmp = url.split(prefix, 1)
                if len(tmp) == 2:
                    vid_id = tmp[1]
                    break
            if vid_id is None:
                return await ctx.send("Invalid YouTube video URL.")
            video = await self.yt.video_info(vid_id)
            if video is None:
                return await ctx.send("Invalid YouTube video URL.")
            vid_info = f"Uploaded by: {video['uploader']}\nType: {video['type']}"
            views = video.get('views', None)
            if views is not None:
                vid_info += f"\nViews: {int(views):,d}"
            embed = emh.embed_init(self.bot, "YouTube Direct Video Link")
            embed.add_field(name=video['title'], value=vid_info, inline=False)
            embed.title = "Added to song queue."
            msg = await ctx.send(embed=embed)
            playback = await self.insert_and_play(video)
            if not playback:
                return await emh.embed_socket_err(msg, embed, "Playback failure.")
            return await ctx.invoke(self.bot.get_command("controls"))

    @alexa.command(name='playlist', brief='Same but for playlists')
    @connect_voice_check()
    async def alexa_playlist(self, ctx: Context, *, name: str):
        if self.alexa_running.is_set():
            return await ctx.send(f"Alexa is already running.")

        async def replace_and_play(_res):
            self.no_autoplay.set()
            self.song_queue = _res
            self.song_counter = 0
            playback = await self._curr()
            if not playback:
                return await ctx.send("Playback failure.")
            return await ctx.invoke(self.bot.get_command("controls"))
        # https://www.youtube.com/playlist?list=PL5tKokWGFK1Eb89gAr1m0toEh0i4lOlfD
        # My cancer playlist
        if name == 'drecancer':
            res = await self.yt.playlist_videos("PL5tKokWGFK1Eb89gAr1m0toEh0i4lOlfD")
            return await replace_and_play(res)

        match = self.re_yt.search(name)
        if match is not None:
            url = match.group()
            tmp = url.split("https://www.youtube.com/playlist?list=", 1)
            if len(tmp) != 2:
                return await ctx.send("Invalid YouTube playlist URL.")
            res = await self.yt.playlist_videos(tmp[1])
            if res is None:
                return await ctx.send("Invalid YouTube playlist URL.")
            return await replace_and_play(res)
        else:
            search_res = await self.yt.search(name, playlist=True)
            if search_res is None:
                return await ctx.send(f"No results found for `{name}`.")
            embed = emh.embed_init(self.bot, "YouTube Playlist Search")
            i = 0
            for video in search_res:
                # url, title, uploader, published, type, id
                vid_info = f"Added by: {video['uploader']}"
                embed.add_field(name=f"{i} - {video['title']}", value=vid_info, inline=False)
                i += 1
            embed.title = f"Replacing queue with first result in 5s, reply with a different number or 'stop' to cancel."
            msg = await ctx.send(embed=embed)

            def check(m):
                return (m.author.id == ctx.author.id) and (not m.content.startswith("!"))
            try:
                self.alexa_running.set()
                reply = await self.bot.wait_for('message', check=check, timeout=5.0)
                if reply.content == 'stop':
                    self.alexa_running.clear()
                    embed.title = "Cancelled."
                    return await msg.edit(embed=embed)
                elif reply.content in ['0', '1', '2', '3', '4']:
                    self.alexa_running.clear()
                    add_song = search_res[int(reply.content)]
                    embed.title = f"Song queue changed to {add_song['title']}."
                    res = await self.yt.playlist_videos(add_song['id'])
                    if res is None:
                        return await ctx.send(f"Could not fetch items in playlist {add_song['title']}.")
                    await msg.edit(embed=embed)
                    return await replace_and_play(res)
                else:
                    self.alexa_running.clear()
                    embed.title = "Unrecognized response."
                    return await msg.edit(embed=embed)
            except asyncio.TimeoutError:
                self.alexa_running.clear()
                embed.title = f"Song queue changed to {search_res[0]['title']}."
                res = await self.yt.playlist_videos(search_res[0]['id'])
                if res is None:
                    return await ctx.send(f"Could not fetch items in playlist {search_res[0]['title']}.")
                await msg.edit(embed=embed)
                return await replace_and_play(res)

    @commands.command(brief='Show controls embed')
    @is_voice_check()
    async def controls(self, ctx: Context):
        msg_content = "See !playlist for entire playlist."
        embed = emh.embed_init(self.bot, "Music Controls")
        embed.set_footer(text="Receiving commands.", icon_url=embed.footer.icon_url)
        embed.title = f'Playing, {self.volume*100:.0f}% volume'
        embed.description = "\n".join(self.get_songs_around(limit=6))
        if self.controls_msg is not None:
            with contextlib.suppress(Exception):
                await self.controls_msg.delete()
        self.controls_msg = await ctx.send(content=msg_content, embed=embed)
        control_em = ['⏮', '⏯', '⏭', '⏹']
        for em in control_em:
            await self.controls_msg.add_reaction(em)

        def check(r: discord.Reaction, u: discord.User):
            return (r.message.id == self.controls_msg.id and str(r.emoji) in control_em and
                    u != self.bot.user)

        while True:
            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            except asyncio.TimeoutError:
                break
            else:
                if str(reaction.emoji) == '⏮':
                    self.no_autoplay.set()
                    await self._prev()
                elif str(reaction.emoji) == '⏯':
                    await self._toggle()
                elif str(reaction.emoji) == '⏭':
                    self.no_autoplay.set()
                    await self._next()
                elif str(reaction.emoji) == '⏹':
                    await self._stop()
                    embed.title = 'Stopped'
                    break
                await self.controls_msg.remove_reaction(str(reaction.emoji), user)
                embed.title = f'Playing, {self.volume*100:.0f}% volume'
                embed.description = "\n".join(self.get_songs_around(limit=6))
                await self.controls_msg.edit(content=msg_content, embed=embed)
        embed.set_footer(text="Use !controls to listen to commands again.", icon_url=embed.footer.icon_url)
        embed.colour = discord.Colour.red()
        await self.controls_msg.clear_reactions()
        await self.controls_msg.edit(content=msg_content, embed=embed)

    @commands.command(name='volume', brief='Change volume, 0 to 100')
    @is_voice_check()
    async def set_volume(self, ctx: Context, volume: int):
        """Changes the player's volume"""
        self.volume = volume/100
        ctx.voice_client.source.volume = self.volume
        return await ctx.send(f"Changed volume to {volume}%.")

    @commands.command(brief='Stop playing and clear playlist')
    @is_voice_check()
    async def stop(self, ctx: Context):
        await self._stop()

    @commands.command(brief='Disconnect from voice channel')
    async def dc(self, ctx: Context):
        await self._dc()

    @commands.command(brief='Display songs in song queue')
    @is_voice_check()
    async def playlist(self, ctx: Context):
        tmp = ""
        for song in self.get_song_queue():
            tmp += song + "\n"
            if len(tmp) > 1950:
                await ctx.send("```" + tmp + "```")
                tmp = ""
        return await ctx.send("```" + tmp + "```")

    @commands.command(brief='Skip to specific song, see !playlist')
    @is_voice_check()
    async def skip(self, ctx: Context, index: int):
        self.no_autoplay.set()
        if (index < 0) or (index >= len(self.song_queue)):
            return await ctx.send("Invalid song index.")
        self.song_counter = index
        await self._curr()

    @commands.command(brief='Switch bot voice channel')
    async def join(self, ctx: Context, *, channel=None):
        """Joins/moves to caller voice channel if no arguments are given."""
        if channel is None:
            if ctx.author.voice is None:
                return await ctx.send(f"No channel name provided and you are not in any channels.")
            found_channel = ctx.author.voice.channel
        else:
            found_channel = discord.utils.find(lambda vc: (channel in vc.name.lower()) or (vc.name.lower() == channel), ctx.guild.voice_channels)
            if found_channel is None:
                return await ctx.send(f"Channel {channel} not found.")

        if self.voice_con is not None:
            await self.voice_con.move_to(found_channel)
        else:
            self.voice_con = await found_channel.connect()

    async def async_after_song(self):
        """Decides what to do after a song has ended."""
        # Last song, stop.
        if self.song_counter == len(self.song_queue)-1:
            await self.bot.change_presence(activity=None)
            return
        if self.no_autoplay.is_set():
            self.no_autoplay.clear()
        else:
            await self._next()

    async def play_from_url(self, url):
        """Fetches and plays a video from given URL."""
        stream_url = await self.bot.loop.run_in_executor(None, lambda: get_stream_url(url))
        if stream_url is None:
            return False
        ffmpeg_options = {'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                          'options': '-vn'}
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(stream_url, **ffmpeg_options), volume=self.volume)

        def after_song(err):
            if err:
                self.logger.warning(f"Song playback ended with error: {err}")
            asyncio.run_coroutine_threadsafe(self.async_after_song(), self.bot.loop)

        if self.voice_con.is_playing():
            self.voice_con.stop()
        self.voice_con.play(source, after=after_song)
        await self._upd_presence()
        return True

    async def insert_and_play(self, add_song):
        self.no_autoplay.set()
        if len(self.song_queue) == 0:
            self.song_queue = [add_song]
        else:
            self.song_queue.insert(self.song_counter+1, add_song)
        return await self._next()

    async def _upd_presence(self):
        await self.bot.change_presence(activity=discord.Game(name=f"[> {self.curr_song_name()}"))

    async def _dc(self):
        if self.bot.guilds[0].me.activity:
            await self.bot.change_presence(activity=None)
        if self.voice_con is not None:
            await self.voice_con.disconnect()
            self.voice_con = None

    async def _stop(self):
        self.no_autoplay.set()
        await self.bot.change_presence(activity=None)
        if self.voice_con is not None:
            self.song_queue = []
            self.song_counter = 0
            self.voice_con.stop()

    async def _prev(self):
        """Plays previous song in global queue. Resets if out of bounds."""
        self.song_counter -= 1
        if (self.song_counter < 0) or (self.song_counter >= len(self.song_queue)):
            self.song_counter = 0
        return await self.play_from_url(self.song_queue[self.song_counter]['url'])

    async def _next(self):
        """Plays next song in global queue. Resets if out of bounds."""
        self.song_counter += 1
        if self.song_counter >= len(self.song_queue):
            self.song_counter = 0
        return await self.play_from_url(self.song_queue[self.song_counter]['url'])

    async def _curr(self):
        """Plays current song in global queue."""
        return await self.play_from_url(self.song_queue[self.song_counter]['url'])

    async def _pause(self):
        self.voice_con.pause()
        await self.bot.change_presence(activity=discord.Game(name=f"|| {self.curr_song_name()}"))

    async def _resume(self):
        self.voice_con.resume()
        await self.bot.change_presence(activity=discord.Game(name=f"[> {self.curr_song_name()}"))

    async def _toggle(self):
        if self.voice_con.is_playing():
            await self._pause()
        else:
            await self._resume()

    def curr_song_name(self):
        """Returns currently playing song name"""
        return self.song_queue[self.song_counter]['title']

    def get_song_queue(self):
        """Returns entire song queue, marking currently playing song"""
        tmp = []
        for i in range(len(self.song_queue)):
            song_name = self.song_queue[i]['title']
            if i == self.song_counter:
                tmp.append(f"{i}> {song_name}")
            else:
                tmp.append(f"{i}- {song_name}")
        return tmp

    def get_songs_around(self, limit: int = 5):
        """Returns `limit` songs around currently playing song"""
        tmp = []
        upper_bound = self.song_counter + limit
        if upper_bound >= len(self.song_queue):
            upper_bound = len(self.song_queue) - 1
        lower_bound = self.song_counter - limit
        if lower_bound < 0:
            upper_bound -= lower_bound
            lower_bound = 0
        for i in range(lower_bound, upper_bound):
            if (i < 0) or (i >= len(self.song_queue)):
                break
            song_name = self.song_queue[i]['title']
            if i == self.song_counter:
                tmp.append(f"{i}> {song_name}")
            else:
                tmp.append(f"{i}- {song_name}")
        return tmp

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if self.voice_con is None:
            return
        if len(self.song_queue) == 0:
            return
        members_in_channel = len(self.voice_con.channel.members)
        # Bot left alone, pause.
        if (members_in_channel == 1) and (self.voice_con.is_playing()):
            await self._pause()
        # One person and bot, resume.
        elif (members_in_channel == 2) and (not self.voice_con.is_playing()):
            await self._resume()
