from discord.ext import commands


class ArgParseError(commands.CommandError):
    """Raised when argparser failed to parse args"""
    def __init__(self, err: str):
        self.err = err
