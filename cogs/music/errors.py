from discord.ext import commands


class NoVoiceConnectionError(commands.CommandError):
    """Raised when a voice channel connection is required but not found"""
    pass


class EmptyPlaylistError(commands.CommandError):
    """Raised when the playlist is empty but one is required"""
    pass
