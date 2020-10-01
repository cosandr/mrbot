from ext.context import Context
from .errors import *


def is_voice_check():
    """Returns False if bot is not connected to voice"""
    async def predicate(ctx: Context):
        if ctx.cog.voice_con is None:
            raise NoVoiceConnectionError()

        if not ctx.cog.song_queue:
            raise EmptyPlaylistError()

        return True
    return commands.check(predicate)


def connect_voice_check():
    """Try to connect to voice channel if necessary"""
    async def predicate(ctx: Context):
        if ctx.cog.voice_con is None:
            if ctx.author.voice:
                ctx.cog.voice_con = await ctx.author.voice.channel.connect()
            else:
                channel = ctx.bot.get_channel(423141750106882048)
                await ctx.send(f"You are not connected to a voice channel. Defaulting to {channel.name}.")
                ctx.cog.voice_con = await channel.connect()

        return True
    return commands.check(predicate)
