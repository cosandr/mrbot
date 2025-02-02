from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from aiohttp import web
from discord.ext import commands

if TYPE_CHECKING:
    from mrbot import MrBot


class HealthCheck(commands.Cog, name="HealthCheck"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(
            f"{self.bot.logger.name}.{self.__class__.__name__}"
        )
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        app = web.Application()
        app.add_routes(
            [
                web.get("/health", self.health),
            ]
        )
        # https://docs.aiohttp.org/en/stable/web_advanced.html#application-runners
        self.runner = web.AppRunner(app)

    async def cog_load(self):
        await self.bot.wait_until_ready()
        await self.runner.setup()
        site = web.TCPSite(
            self.runner, self.bot.config.http.host, self.bot.config.http.port
        )
        await site.start()

    async def cog_unload(self):
        await self.runner.cleanup()

    async def health(self, r: web.Request) -> web.Response:
        self.logger.debug(r.path)
        status = 200
        body = {"status": "OK"}
        if not self.bot.is_ready() or self.bot.is_closed():
            status = 500
            body["status"] = "BOT_NOT_READY"
            body["error"] = "Bot is not ready and/or connection is closed"
        # Run simple query
        try:
            async with self.bot.pool.acquire() as con:
                await con.fetch("SELECT NOW()")
        except Exception as e:
            status = 500
            body["status"] = "POSTGRES_ERR"
            body["error"] = f"Postgres failure: {str(e)}"

        return web.Response(
            content_type="application/json", status=status, body=json.dumps(body)
        )


async def setup(bot):
    await bot.add_cog(HealthCheck(bot))
