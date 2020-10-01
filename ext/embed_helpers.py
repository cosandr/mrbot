from io import BytesIO
from typing import Tuple, Union

import discord
from discord.ext import commands

from ext.context import Context


def embed_init(bot: commands.Bot, name: str) -> discord.Embed:
    """Create standardized embed with `name` as the author

    :param bot: Bot instance
    :param name: Embed author name
    """
    embed = discord.Embed()
    embed.colour = discord.Colour.dark_blue()
    embed.set_author(name=name, icon_url=str(bot.get_user(bot.owner_id).avatar_url))
    embed.set_footer(icon_url=str(bot.user.avatar_url))
    return embed


async def embed_img_not_found(msg: discord.Message, embed: discord.Embed) -> None:
    """Edit and send standardised error embed.
    Used when an image was not found.

    :param msg: Message with the embed to edit
    :param embed: The embed object to edit
    """
    embed.colour = discord.Colour.red()
    embed.set_footer(text="FAILED", icon_url=embed.footer.icon_url)
    embed.add_field(name="No image found", value='Mr. Bot searches the past 30 messages for image links.', inline=False)
    await msg.edit(embed=embed)


async def embed_socket_err(msg: discord.Message, embed: discord.Embed, err: str) -> None:
    """Edit and send standardized error embed.
    Used when a socket command has returned an exception.

    :param msg: Message with the embed to edit
    :param embed: The embed object to edit
    :param err: The exception text that has occurred
    """
    embed.colour = discord.Colour.red()
    embed.set_footer(text="FAILED", icon_url=embed.footer.icon_url)
    embed.add_field(name="Error", value=err, inline=False)
    await msg.edit(embed=embed)


async def embed_prev_generated(ctx: Context, embed: discord.Embed, filename: str) -> discord.Message:
    """Edit and send standardized file already exists embed.

    :param ctx: Context of invocation
    :param embed: The embed object to edit
    :param filename: Filename that already exists, required for the correct link to be sent
    """
    url = f"{ctx.bot.config.hostname}/discord/{filename}"
    embed.colour = discord.Colour.green()
    embed.set_footer(text="Previously generated", icon_url=embed.footer.icon_url)
    if filename.endswith(".mp4"):
        return await ctx.send(content=url, embed=embed)
    embed.set_image(url=url)
    return await ctx.send(content=url, embed=embed)


async def embed_img_with_time(ctx: Context, msg: discord.Message, embed: discord.Embed, filename: str, comp_time: float) -> None:
    """Edit and send standardized completed image computation embed.
    Used to attach an image from `filename` parameter to the given `embed`.

    :param ctx: Context of invocation
    :param msg: Message with the embed to edit
    :param embed: The embed object to edit
    :param filename: File to set as embed URL
    :param comp_time: Time in seconds it took to complete the computation
    """
    url = f"{ctx.bot.config.hostname}/discord/{filename}"
    embed.set_footer(text=f"Completed in {comp_time:.2f}s", icon_url=embed.footer.icon_url)
    embed.colour = discord.Colour.green()
    if filename.endswith(".mp4"):
        await msg.edit(content=url, embed=embed)
        return
    embed.set_image(url=url)
    await msg.edit(embed=embed)


def embed_local_file(embed: discord.Embed, file: Union[BytesIO, bytes, str], filename: str) -> Tuple[discord.Embed, discord.File]:
    """Adds the local file (path or buffer) to the embed and returns it

    :param embed: The embed object to edit
    :param file: File-like object to upload
    :param filename: Name of the file
    :returns: Tuple with the modified embed and discord file to send with it
    """
    embed.set_image(url=f"attachment://{filename}")
    if isinstance(file, bytes):
        file = BytesIO(file)
    return embed, discord.File(file, filename=filename)

