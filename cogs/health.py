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

        if self.bot.config.kube is not None:
            from kubernetes_asyncio import config

            try:
                config.load_incluster_config()
                self.logger.debug("Kubernetes API initialized from cluster config")
            except config.config_exception.ConfigException:
                await config.load_kube_config()
                self.logger.debug("Kubernetes API initialized from kubeconfig")

        await self.runner.setup()
        site = web.TCPSite(
            self.runner, self.bot.config.http.host, self.bot.config.http.port
        )
        await site.start()

    async def cog_unload(self):
        await self.runner.cleanup()

    async def health(self, _r: web.Request) -> web.Response:
        status = 200
        body = {"status": "OK"}
        if not self.bot.is_ready() or self.bot.is_closed():
            status = 500
            body["status"] = "BOT_NOT_READY"
            body["error"] = "Bot is not ready and/or connection is closed"
            self.logger.error("Bot ready health check failed")

        # Run simple query
        try:
            async with self.bot.pool.acquire() as con:
                await con.fetch("SELECT NOW()")
        except Exception as e:
            status = 500
            body["status"] = "POSTGRES_ERR"
            body["error"] = f"Postgres failure: {str(e)}"
            self.logger.exception("Postgres health check failed")

        # Check Kubernetes API
        if self.bot.config.kube is not None:
            from kubernetes_asyncio import client
            from kubernetes_asyncio.client.api_client import ApiClient

            async with ApiClient() as api:
                core = client.CoreApi(api)
                try:
                    await core.get_api_versions()
                except Exception as e:
                    status = 500
                    body["status"] = "KUBE_ERR"
                    body["error"] = f"Kubernetes failure: {str(e)}"
                    self.logger.exception("Kubernetes API health check failed")

        return web.Response(
            content_type="application/json", status=status, body=json.dumps(body)
        )


async def setup(bot):
    await bot.add_cog(HealthCheck(bot))
