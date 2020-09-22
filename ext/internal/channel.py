from __future__ import annotations

from typing import Tuple, Union, List, Optional

import asyncpg
import discord
from discord.ext import commands

from mrbot import MrBot
from .base import Common
from .guild import Guild


class Channel(Common):
    psql_table_name = 'channels'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id       BIGINT NOT NULL UNIQUE,
            name     VARCHAR(100),
            voice    BOOLEAN DEFAULT false,
            guild_id BIGINT REFERENCES {Guild.psql_table_name} (id)
        );
    """
    psql_all_tables = Guild.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, id_: int, name: str = None, guild: Guild = None, voice: bool = False):
        self.id: int = id_
        self.name: str = name
        self.guild: Guild = guild
        self.voice: bool = voice

    @property
    def guild_id(self):
        if not self.guild:
            return None
        return self.guild.id

    def to_psql(self) -> Tuple[str, list]:
        """Returns a query in the form (id, name, ...) VALUES ($1,$2, ...) ON CONFLICT ... and its arguments"""
        q = (f'INSERT INTO {self.psql_table_name} '
             '(id, name, guild_id, voice) VALUES ($1, $2, $3, $4) '
             'ON CONFLICT (id) DO UPDATE SET name=$2')
        q_args = [self.id, self.name, self.guild_id, self.voice]
        return q, q_args

    def to_discord(self, bot: Union[MrBot, commands.Bot]) -> Union[discord.abc.GuildChannel, discord.abc.PrivateChannel]:
        return bot.get_channel(self.id)

    @classmethod
    def from_discord(cls, channel):
        if not isinstance(channel, (discord.abc.GuildChannel, discord.abc.PrivateChannel)):
            return None
        if not hasattr(channel, 'id'):
            return None
        # noinspection PyUnresolvedReferences
        return cls(
            id_=channel.id,
            name=channel.name if hasattr(channel, 'name') else None,
            guild=Guild.from_discord(channel.guild) if hasattr(channel, 'guild') else None,
            voice=isinstance(channel, discord.VoiceChannel),
        )

    @staticmethod
    def make_psql_query(with_guild=False, where: str = ''):
        """Return a query to get a channel from PSQL

        :param with_guild: Join info from guilds table
        :param where: Filter output"""
        select_args = 'c.id, c.name, c.voice, c.guild_id'
        from_args = f'FROM {Channel.psql_table_name} c'
        if with_guild:
            select_args += ', g.name AS guild_name'
            from_args += f' LEFT JOIN {Guild.psql_table_name} g ON (c.guild_id = g.id)'
        q = f'SELECT {select_args} {from_args}'
        if where:
            q += f' WHERE {where}'
        return q

    @classmethod
    def from_psql_res(cls, res: asyncpg.Record, prefix: str = '') -> Optional[Channel]:
        if not res.get(f'{prefix}id', None):
            return None
        guild = None
        if res.get(f'{prefix}guild_id', None):
            guild = Guild.from_psql_res(res, f'{prefix}guild_')
        return cls(
            id_=res.get(f'{prefix}id'),
            name=res.get(f'{prefix}name', None),
            voice=res.get(f'{prefix}voice', False),
            guild=guild,
        )

    @classmethod
    async def from_psql_all(cls, con: asyncpg.Connection, **kwargs) -> List[Channel]:
        """Returns all channels from PSQL, kwargs passed to make_psql_query"""
        results = await con.fetch(cls.make_psql_query(**kwargs))
        channels = []
        for r in results:
            channels.append(cls.from_psql_res(r))
        return channels
