from discord.ext import commands


class ConnectionClosedError(commands.CommandError):
    """Raised when a required connection is closed"""
    def __init__(self, path: str):
        self.path = path


class UnapprovedGuildError(commands.CommandError):
    """Raised when a command can only be used in specific guilds"""
    pass


class MissingConfigError(Exception):
    """Raised when an extension is missing its config"""
    pass
