import asyncio
import json
from typing import Set

import asyncpg

from config import BotConfig


class ReactionsConfig:
    def __init__(self):
        self.on_message_ignore_channels: Set[int] = set()
        self.lock = asyncio.Lock()

    async def edit_on_message_ignore_channels(self, con: asyncpg.Connection, v: int, remove=False) -> bool:
        """Add or remove v from ignore list, returns True if changes were made"""
        async with self.lock:
            len_before = len(self.on_message_ignore_channels)
            if remove:
                if v in self.on_message_ignore_channels:
                    self.on_message_ignore_channels.remove(v)
            else:
                self.on_message_ignore_channels.add(v)
            if len(self.on_message_ignore_channels) != len_before:
                await self.write_psql(con)
                return True
            return False

    @classmethod
    def from_dict(cls, data: dict):
        """Read config from dict"""
        self = cls()
        if not data:
            return self
        self.on_message_ignore_channels = set(data.get('on_message_ignore_channels', []))
        return self

    @classmethod
    def from_json(cls, data: str):
        return cls.from_dict(json.loads(data))

    def to_dict(self) -> dict:
        return dict(
            on_message_ignore_channels=list(self.on_message_ignore_channels),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    async def read_psql(cls, con: asyncpg.Connection):
        q = f"SELECT data FROM {BotConfig.psql_table_name} WHERE name=$1 AND type=$2"
        data = await con.fetchval(q, 'reactions', 'cog')
        return cls.from_json(data)

    async def write_psql(self, con: asyncpg.Connection):
        if not self.lock.locked():
            raise RuntimeError('Lock must be acquired before calling this method')
        q = (f"INSERT INTO {BotConfig.psql_table_name} "
             "(name, type, data) VALUES ($1, $2, $3) "
             "ON CONFLICT (name, type) DO UPDATE SET data=$3")
        await con.execute(q, 'reactions', 'cog', self.to_json())
