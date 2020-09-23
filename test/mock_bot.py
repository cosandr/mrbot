import logging
from asyncio import AbstractEventLoop
from typing import Optional

import asyncpg
import discord
from aiohttp import ClientSession

from config import BotConfig


class Connection:
    def __init__(self):
        self._messages = []


class Response:
    def __init__(self):
        self.status = 404
        self.reason = 'Not found'


class TestBot:

    def __init__(self, loop):
        self.loop: AbstractEventLoop = loop
        self.config = BotConfig.from_json(
            secrets=['config/secrets.json', 'config/secrets_test.json'],
            paths=['config/paths.json'],
        )
        self.pool_live: Optional[asyncpg.pool.Pool] = None
        self.pool: Optional[asyncpg.pool.Pool] = None
        self.pool_pub: Optional[asyncpg.pool.Pool] = None
        self.aio_sess: Optional[ClientSession] = None
        self._connection = Connection()
        # --- Logger ---
        self.logger: logging.Logger = logging.getLogger('discord')
        self.logger.setLevel(logging.DEBUG)
        logger_fmt = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
        # Console Handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(logger_fmt)
        # File Handler
        fh = logging.FileHandler(filename='mock-bot.log', encoding='utf-8', mode='w')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logger_fmt)
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)
        # --- Logger ---
        self.users = []

    def get_user(self, user_id):
        return None

    def get_channel(self, ch_id):
        return None

    def get_guild(self, guild_id):
        return None

    async def fetch_user(self, user_id):
        raise discord.errors.NotFound(Response(), 'User not found')

    async def async_init(self, con_live=False, con_pub=False):
        self.aio_sess = ClientSession()
        self.pool = await asyncpg.create_pool(dsn=self.config.psql.main, max_size=32)
        live_dsn = self.config.psql.live
        public_dsn = self.config.psql.public
        if con_live:
            self.pool_live = await asyncpg.create_pool(dsn=live_dsn)
        if con_pub:
            self.pool_pub = await asyncpg.create_pool(dsn=public_dsn)

    async def close(self):
        await self.aio_sess.close()
        await self.pool.close()
        if self.pool_live:
            await self.pool_live.close()
        if self.pool_pub:
            await self.pool_pub.close()
