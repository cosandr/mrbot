import socket
from urllib.parse import urlparse

from discord.ext import commands

from .context import Context
from .errors import ConnectionClosedError


def open_connection_check(path: str = ''):
    """Returns False if connection at `path` is closed, checks configured bot config path without arguments"""
    async def predicate(ctx: Context):
        nonlocal path
        if not path:
            path = ctx.bot.config.brains
        # UNIX socket
        if path.startswith('/'):
            short_path = path.split('/')[-1]
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            ok = sock.connect_ex(path) == 0
        # HTTP path
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            url = urlparse(path)
            if url.port:
                port = url.port
            elif url.scheme == "https":
                port = 443
            else:
                port = 80
            short_path = f'{url.hostname}:{port}'
            ok = sock.connect_ex((url.hostname, port)) == 0
        sock.close()
        if not ok:
            raise ConnectionClosedError(short_path)
        return True

    return commands.check(predicate)
