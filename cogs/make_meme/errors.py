from discord.ext import commands


class MemeTemplateError(commands.CommandError):
    """Raised when we fail to parse a meme template JSON"""
    def __init__(self, err: str):
        self.err = err


class MemeEntryError(commands.CommandError):
    """Raised when we try to add incorrect number of entries to a meme"""
    def __init__(self, err: str):
        self.err = err


class MemeFontNotFound(commands.CommandError):
    """Raised when we can't find requested font for a meme"""
    def __init__(self, err: str):
        self.err = err
