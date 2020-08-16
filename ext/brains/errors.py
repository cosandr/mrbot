from discord.ext import commands


class BrainsAPIError(commands.CommandError):
    """Raised when a request to the brains API fails"""
    def __init__(self, original: Exception):
        self.original = original
