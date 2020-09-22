from __future__ import annotations

from typing import Tuple, Union, Optional, List

import asyncpg
import discord
from discord.ext import commands

from mrbot import MrBot
from .base import Common


class Guild(Common):
    psql_table_name = 'guilds'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id   BIGINT NOT NULL UNIQUE,
            name VARCHAR(100)
        );
    """
    psql_all_tables = {(psql_table_name,): psql_table}

    __slots__ = Common.__slots__ + \
        ('id', 'name')

    def __init__(self, id_: int, name: str = None):
        self.id: int = id_
        self.name: str = name

    def to_psql(self) -> Tuple[str, list]:
        """Returns a query in the form (id, name, ...) VALUES ($1,$2, ...) and its arguments"""
        q = (f'INSERT INTO {self.psql_table_name} '
             '(id, name) VALUES ($1, $2) '
             'ON CONFLICT (id) DO UPDATE SET name=$2')
        q_args = [self.id, self.name]
        return q, q_args

    @staticmethod
    def make_psql_query(where: str = ''):
        """Return a query to get a guild from PSQL

        :param where: Filter output"""
        select_args = 'g.id, g.name'
        from_args = f'FROM {Guild.psql_table_name} g'
        q = f'SELECT {select_args} {from_args}'
        if where:
            q += f' WHERE {where}'
        return q

    def to_discord(self, bot: Union[MrBot, commands.Bot]) -> discord.Guild:
        return bot.get_guild(self.id)

    @classmethod
    def from_discord(cls, guild: discord.Guild) -> Optional[Guild]:
        if not guild:
            return None
        return cls(
            id_=guild.id,
            name=guild.name,
        )

    @classmethod
    def from_psql_res(cls, res: asyncpg.Record, prefix: str = '') -> Optional[Guild]:
        if not res.get(f'{prefix}id', None):
            return None
        return cls(
            id_=res.get(f'{prefix}id'),
            name=res.get(f'{prefix}name', None),
        )

    @classmethod
    async def from_psql_all(cls, con: asyncpg.Connection, **kwargs) -> List[Guild]:
        """Returns all guilds from PSQL, kwargs passed to make_psql_query"""
        results = await con.fetch(cls.make_psql_query(**kwargs))
        guilds = []
        for r in results:
            guilds.append(cls.from_psql_res(r))
        return guilds
