from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ext import utils
from .incoming import Incoming
from .response import Response

if TYPE_CHECKING:
    from mrbot import MrBot

LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 6684


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot: MrBot = bot
        self.server: Optional[asyncio.AbstractServer] = None
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.bot.loop.create_task(self.async_init())
        self.send_ch: Optional[discord.abc.Messageable] = None
        # Cache for incoming data
        self.inc_cache: Dict[str, List[Incoming]] = {}
        # How long to wait for more data, in seconds
        self.inc_timeout: int = 10
        # Resets timeout timer
        self.reset_timer = False
        self.queue = asyncio.Queue()
        self.worker_task = self.bot.loop.create_task(self.inc_worker())

    def cog_unload(self):
        self.bot.cleanup_tasks.append(self.bot.loop.create_task(self.async_unload()))

    async def async_init(self):
        await self.bot.connect_task
        await self.bot.wait_until_ready()
        self.server = await asyncio.start_server(self.server_cb, LISTEN_HOST, LISTEN_PORT)
        self.logger.info('Server listening on %s:%d', LISTEN_HOST, LISTEN_PORT)
        self.send_ch = discord.utils.get(self.bot.users, id=self.bot.owner_id)

    async def async_unload(self):
        await self.queue.put(None)
        await self.worker_task
        self.server.close()
        await self.server.wait_closed()
        self.logger.info('Server closed')

    async def inc_worker(self):
        running = True
        while running:
            item = await self.queue.get()
            if item is None:
                self.logger.debug("Worker will close")
                running = False
            if not self.inc_cache:
                self.logger.debug("No items in the cache")
                continue
            timeout = self.inc_timeout
            while timeout > 0:
                if self.reset_timer:
                    timeout = self.inc_timeout
                    self.reset_timer = False
                    self.logger.debug("Timer reset")
                else:
                    timeout -= 1
                await asyncio.sleep(1)
            self.logger.debug("Timer done, sending")
            # Send stuff in cache
            embed = utils.transparent_embed()
            date_str = datetime.now().strftime('%d.%m.%y')
            summary_str = utils.fmt_plural_str(sum(len(v) for v in self.inc_cache.values()), 'notification')
            embed.title = f'{summary_str} - {date_str}'
            for name, inc_list in self.inc_cache.items():
                for inc in inc_list:
                    if inc.embed:
                        await self.send_ch.send(embed=inc.embed)
                    if len(embed.fields) >= 20:
                        await self.send_ch.send(embed=embed)
                        embed.clear_fields()
                    embed.add_field(name=f'{inc.name} at {inc.time_str_no_date}', value=inc.content, inline=False)
            try:
                if len(embed) > 6000:
                    raise Exception(f"Embed is too long to be sent: {len(embed)} characters")
                await self.send_ch.send(embed=embed)
            except Exception as e:
                self.logger.error(f'Cannot send message: {str(e)}')
            self.inc_cache.clear()
            self.logger.debug("Worker done, item cache cleared")
        self.logger.debug("Worker closed")

    async def server_cb(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        data = await reader.read()
        try:
            inc = Incoming.from_payload(data)
        except Exception as e:
            self.logger.error(f'Cannot read incoming data: {data}\n{str(e)}')
            resp = Response(ok=False, detail=str(e))
            writer.write(resp.to_payload())
            await writer.drain()
            writer.close()
            return
        # Alternative for responding after message is sent:
        # Add writer property to inc and use it to respond in the worker task
        # Respond with OK
        if inc.name in self.inc_cache:
            self.inc_cache[inc.name].append(inc)
            resp = Response(ok=True, detail=f"Message queued with {len(self.inc_cache[inc.name])} others")
        else:
            resp = Response(ok=True, detail="Message queued")
            self.inc_cache[inc.name] = [inc]
        # Rework this somehow
        await self.queue.put(True)
        self.reset_timer = True
        writer.write(resp.to_payload())
        await writer.drain()
        writer.close()
