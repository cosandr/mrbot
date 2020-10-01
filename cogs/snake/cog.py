from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ext.context import Context
from .snake import Playfield, Snake, SnakeDiedError

if TYPE_CHECKING:
    from mrbot import MrBot


class SnakeCog(commands.Cog, name="Snake"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        self.game_msg = None
        self.snake_running = asyncio.Event()

    @commands.command(name='snek', brief='Plej a simple gem of snek', hidden=True)
    @commands.is_owner()
    async def snake_cmd(self, ctx: Context):
        if self.snake_running.is_set():
            return await ctx.send(f"Snake is already running.")
        snake = Snake(Playfield(5, 5))
        msg_content = "Listening" + snake.field.discord()
        if self.game_msg is not None:
            try:
                await self.game_msg.delete()
            except Exception:
                pass
        self.game_msg = await ctx.send(content=msg_content)
        moves = {'⬆': snake.up,
                 '⬇': snake.down,
                 '⬅': snake.left,
                 '➡': snake.right}
        move_dir = '➡'
        for em in moves.keys():
            await self.game_msg.add_reaction(em)

        async def move_task():
            while True:
                try:
                    moves[move_dir]()
                    msg_content = f"Game running, score: {len(snake)-1}" + snake.field.discord()
                    await self.game_msg.edit(content=msg_content)
                    await asyncio.sleep(2)
                except asyncio.CancelledError:
                    msg_content = f"Timed out.\nScore: {len(snake)-1}" + snake.field.discord()
                    await self.game_msg.edit(content=msg_content)
                    break
                except SnakeDiedError as ded:
                    await self.game_msg.clear_reactions()
                    msg_content = f"You died: {ded}\nScore: {len(snake)-1}" + snake.field.discord()
                    self.snake_running.clear()
                    return await self.game_msg.edit(content=msg_content)

        def check(r: discord.Reaction, u: discord.User):
            return (r.message.id == self.game_msg.id and str(r.emoji) in moves and
                    u != self.bot.user)

        tmp_task = self.bot.loop.create_task(move_task())
        while True:
            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                tmp_task.cancel()
                break
            else:
                move_dir = str(reaction.emoji)
                await self.game_msg.remove_reaction(str(reaction.emoji), user)
        await self.game_msg.clear_reactions()
        self.snake_running.clear()
