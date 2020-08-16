from discord.ext import commands


class InvalidPepeUnit(commands.CommandError):
    """Raised when we can't find a unit"""
    pass
