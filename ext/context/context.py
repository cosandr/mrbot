import argparse
from typing import Optional

import discord
from discord.ext import commands


class Context(commands.Context):
    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.parsed: Optional[argparse.Namespace] = None

    async def list_group_subcmds(self) -> discord.Message:
        """Called when a group cannot be invoked without a subcommand.
        Returns an embed with all available subcommands in the group.
        """
        owner_called = await self.bot.is_owner(self.author)
        embed = discord.Embed()
        embed.colour = discord.Colour.red()
        embed.set_author(name=f"{self.command.name} cannot be called directly", icon_url=str(self.bot.get_user(self.bot.owner_id).avatar_url))
        embed.title = "Available subcommands:"
        for subcmd in self.command.commands:
            if not owner_called and subcmd.hidden:
                continue
            embed.add_field(name=subcmd.name, value=subcmd.brief, inline=False)
        return await self.send(embed=embed)
