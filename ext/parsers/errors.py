from discord.ext import commands


class ArgParseError(commands.CommandError):
    """Raised when argparser failed to parse args"""
    def __init__(self, err: str):
        self.err = err


class ArgParseMessageError(commands.CommandError):
    """Raised when argparser prints a message"""
    def __init__(self, message: str):
        self.message = message
