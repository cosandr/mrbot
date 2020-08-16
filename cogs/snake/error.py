from discord.ext import commands


class SnakeDiedError(commands.CommandError):
    """Raised when the snake has died"""
    pass
