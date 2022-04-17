import sys
import traceback
from typing import List, Set

import aiohttp
import asyncpg
import discord

from cogs.music.errors import *
from ext.brains.errors import *
from ext.context import Context
from ext.errors import *
from ext.parsers.errors import *
from ext.utils import paginate, find_similar_str


async def on_command_error(ctx: Context, error: commands.CommandError):
    # This prevents any commands with local handlers being handled here in on_command_error.
    if hasattr(ctx.command, 'on_error'):
        return

    # Allows us to check for original exceptions raised and sent to CommandInvokeError.
    # If nothing is found. We keep the exception passed to on_command_error.
    error = getattr(error, 'original', error)

    if isinstance(error, commands.CommandNotFound):
        given_cmd = ctx.invoked_with
        check_similar_to: Set[str] = set()
        owner_called = await ctx.bot.is_owner(ctx.author)
        req_arr = given_cmd.split(" ")
        # Add main requested command
        check_similar_to.add(req_arr[0])
        # Check if we also have sub-commands
        if len(req_arr) > 1:
            check_similar_to.add(req_arr[1])
        meant: Set[str] = set()
        check_against: List[str] = []
        for cmd in ctx.bot.commands:
            # Don't suggest hidden commands to regular users
            if not owner_called and cmd.hidden:
                continue
            check_against.append(cmd.name)
            # Include group in suggestion
            if isinstance(cmd, commands.GroupMixin):
                group_check = [c.name for c in cmd.commands]
                for check in check_similar_to:
                    # Include main command name in suggestions
                    for m in find_similar_str(check, group_check):
                        meant.add(f'{cmd.name} {m}')
        # Check regular commands
        for check in check_similar_to:
            for m in find_similar_str(check, check_against):
                meant.add(m)
        # Once we get here, we have a list of suggestions, format and return it.
        if not meant:
            return await ctx.send(f'`{ctx.prefix}{given_cmd}` not found, see {ctx.prefix}help.')
        return await ctx.send(f"`{ctx.prefix}{given_cmd}` not found, did you mean: {', '.join(meant)}?")

    cmd_name = f'{ctx.prefix}{ctx.command.qualified_name}'

    # Custom exceptions handling
    if isinstance(error, ConnectionClosedError):
        if error.path in ctx.bot.config.brains:
            return await ctx.send(f'`{cmd_name}` requires the brains API, but it is down.')
        return await ctx.send(f"`{cmd_name}` requires a connection to `{error.path}`, but it is closed.")

    elif isinstance(error, UnapprovedGuildError):
        return await ctx.send(f"`{cmd_name}` can only be used in approved guilds.")

    elif isinstance(error, asyncpg.exceptions.PostgresError):
        await ctx.send(f"`{cmd_name}` encountered a PostgreSQL error:```{str(error)}```")
        ctx.bot.logger.error(f'[PSQL] {type(error)}: {error}')
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
        return

    elif isinstance(error, aiohttp.ClientConnectionError):
        ctx.bot.logger.error(f'[aiohttp] {type(error)}: {error}')
        return await ctx.send(f'`{cmd_name}` requires an API which is currently down.')

    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed()
        embed.colour = discord.Colour.red()
        embed.set_footer(text=ctx.author.display_name, icon_url=str(ctx.author.avatar_url))
        embed.title = "Command Error"
        embed.description = f"{cmd_name} is missing arguments."
        embed.add_field(name=error.param.name, value=f"Type: {error.param.annotation.__name__}", inline=False)
        return await ctx.send(embed=embed)

    elif isinstance(error, commands.BadArgument):
        if ctx.command.usage is not None:
            return await ctx.send(f"``{cmd_name}`` error: {error}\nUsage:\n{ctx.command.usage}")
        else:
            return await ctx.send(f"``{cmd_name}`` error: {error}")

    elif isinstance(error, commands.errors.CommandOnCooldown):
        return await ctx.send(f'``{cmd_name}`` is on cooldown for {error.retry_after:.1f}s.')

    elif isinstance(error, commands.errors.NotOwner):
        return await ctx.send(f"``{cmd_name}`` is an owner only command.")

    elif isinstance(error, commands.errors.MissingPermissions):
        return await ctx.send(f'You are missing permissions: {", ".join(error.missing_perms)}.')

    elif isinstance(error, commands.errors.BotMissingPermissions):
        return await ctx.send(f'The bot is missing permissions: {", ".join(error.missing_perms)}.')

    elif isinstance(error, commands.errors.CheckFailure):
        ctx.bot.logger.info(f'{type(error)}: {error}')
        return await ctx.send(f"``{cmd_name}`` checks failed, you may be missing permissions.")

    elif isinstance(error, BrainsAPIError):
        cmd_name = f'{ctx.prefix}{ctx.command.qualified_name}'
        return await ctx.send(f'`{cmd_name}` requires the brains API, but it failed: {error.original}.')

    elif isinstance(error, ArgParseError):
        return await ctx.send(str(error))

    elif isinstance(error, ArgParseMessageError):
        return await ctx.send(error.message)

    elif isinstance(error, NoVoiceConnectionError):
        cmd_name = f'{ctx.prefix}{ctx.command.qualified_name}'
        return await ctx.send(f"`{cmd_name}` requires the bot to be connected to a voice channel.")

    elif isinstance(error, EmptyPlaylistError):
        cmd_name = f'{ctx.prefix}{ctx.command.qualified_name}'
        return await ctx.send(f"`{cmd_name}` requires a non-empty playlist.")

    traceback_str = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    ctx.bot.logger.error(traceback_str)
    await ctx.send(f"{cmd_name} exception: {error}.")
    if ctx.bot.config.channels.exceptions:
        try:
            channel = ctx.bot.get_channel(ctx.bot.config.channels.exceptions)
            for p in paginate(traceback_str):
                await channel.send(p)
        except Exception as e:
            ctx.bot.logger.error(f'Cannot send to exceptions channel: {e}')


async def setup(bot):
    bot.add_listener(on_command_error)
