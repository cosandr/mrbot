from __future__ import annotations

from argparse import Namespace
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

if TYPE_CHECKING:
    from mrbot import MrBot


class Context(commands.Context):
    bot: MrBot
    view: commands.view.StringView

    @property
    def parsed(self) -> Optional[Namespace]: ...
    @parsed.setter
    def parsed(self, val: Namespace): ...
    async def list_group_subcmds(self) -> discord.Message: ...
