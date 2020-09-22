from __future__ import annotations

import os
from datetime import datetime
from typing import Union, Tuple, List, Optional, Dict

import asyncpg
import discord
from discord.ext import commands

from ext.utils import re_id, find_closest_match
from mrbot import MrBot
from .base import Common
from .guild import Guild

instance_check = commands.Bot
if os.getenv('IS_TEST', False):
    from test.mock_bot import TestBot

    instance_check = (commands.Bot, TestBot)


class User(Common):
    psql_table_name = 'users'
    psql_table_name_nicks = 'user_nicks'
    psql_table_name_activities = 'user_activities'
    psql_table_name_status = 'user_status'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            id            BIGINT NOT NULL UNIQUE,
            name          VARCHAR(32) NOT NULL,
            discriminator SMALLINT,
            avatar        VARCHAR(34)
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_nicks} (
            nick     VARCHAR(32),
            user_id  BIGINT NOT NULL REFERENCES {psql_table_name} (id) ON DELETE CASCADE,
            guild_id BIGINT NOT NULL REFERENCES {Guild.psql_table_name} (id) ON DELETE CASCADE,
            UNIQUE (user_id, guild_id)
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_activities} (
            activity TEXT,
            time     TIMESTAMP NOT NULL DEFAULT NOW(),
            user_id  BIGINT NOT NULL REFERENCES {psql_table_name} (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_status} (
            online   BOOLEAN NOT NULL,
            mobile   BOOLEAN NOT NULL DEFAULT false,
            time     TIMESTAMP NOT NULL DEFAULT NOW(),
            user_id  BIGINT NOT NULL REFERENCES {psql_table_name} (id) ON DELETE CASCADE
        );
    """
    psql_all_tables = Guild.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name, psql_table_name_nicks, psql_table_name_activities,
                             psql_table_name_status): psql_table})

    __slots__ = Common.__slots__ + \
        ('id', 'name', '_discriminator', 'avatar', 'all_nicks', 'activity', 'activity_time',
         'online', 'mobile', 'status_time')

    def __init__(self,
                 id_: int, name: str = None, discriminator: int = None, avatar: str = None,
                 all_nicks: dict = None,
                 activity: str = None, activity_time: datetime = None,
                 online: bool = None, mobile=False, status_time: datetime = None,
                 ):
        self.id: int = id_
        self.name: str = name
        self.discriminator: int = discriminator
        self.avatar: str = avatar
        # Nicks
        self.all_nicks: Dict[int, str] = {}
        if all_nicks and isinstance(all_nicks, dict):
            self.all_nicks = {k: v for k, v in all_nicks.items() if isinstance(v, str)}
        # Activity
        self.activity: str = activity
        self.activity_time: datetime = activity_time
        # Status
        self.online: bool = online
        self.mobile: bool = mobile
        self.status_time: datetime = status_time

    @property
    def nick(self):
        """Get first nickname from any guild"""
        if self.all_nicks:
            return next(iter(self.all_nicks.values()))
        return ''

    @property
    def all_nicks_str(self):
        if self.all_nicks:
            return ', '.join(self.all_nicks.values())
        return ''

    @property
    def discriminator(self):
        return self._discriminator

    @discriminator.setter
    def discriminator(self, value: int):
        try:
            self._discriminator = int(value)
        except (TypeError, ValueError):
            self._discriminator = None

    @property
    def avatar_url(self):
        if not self.avatar:
            if not self.discriminator:
                return None
            return f'https://cdn.discordapp.com/embed/avatars/{self.discriminator % 5}.png?size=256'
        img_fmt = 'png'
        if self.avatar.startswith('a_'):
            img_fmt = 'gif'
        return f'https://cdn.discordapp.com/avatars/{self.id}/{self.avatar}.{img_fmt}?size=512'

    @property
    def display_name(self):
        """Returns nickname if one is set, otherwise username. Empty string if neither"""
        if self.nick:
            return self.nick
        if self.name:
            return self.name
        return ''

    def get_nick(self, guild_id: int):
        """Returns first nick, or empty string if it doesn't exist"""
        return self.all_nicks.get(guild_id, '')

    def to_psql(self) -> Tuple[str, list]:
        """Returns a query to insert/update users table"""
        q = (f'INSERT INTO {self.psql_table_name} '
             '(id, name, discriminator, avatar) VALUES ($1, $2, $3, $4) '
             'ON CONFLICT (id) DO UPDATE SET name=$2, discriminator=$3, avatar=$4')
        q_args = [self.id, self.name, self.discriminator, self.avatar]
        return q, q_args

    def to_psql_nick(self, guild_id: int) -> Tuple[str, list]:
        """Returns query to update nickname in guild_id, must be present in User.all_nicks"""
        nick_in_guild = self.all_nicks.get(guild_id, None)
        q = (f'INSERT INTO {self.psql_table_name_nicks} '
             '(user_id, guild_id, nick) VALUES ($1, $2, $3) '
             'ON CONFLICT (user_id, guild_id) DO UPDATE SET nick=$3')
        q_args = [self.id, guild_id, nick_in_guild]
        return q, q_args

    def to_psql_activity(self) -> Tuple[str, list]:
        """Returns a query to insert/update user activities table"""
        q = (f'INSERT INTO {self.psql_table_name_activities} '
             '(user_id, activity, time) VALUES ($1, $2, $3)')
        q_args = [self.id, self.activity, self.activity_time or datetime.utcnow()]
        return q, q_args

    def to_psql_status(self) -> Tuple[str, list]:
        """Returns a query to insert/update user status table"""
        q = (f'INSERT INTO {self.psql_table_name_status} '
             '(user_id, online, mobile, time) VALUES ($1, $2, $3, $4)')
        q_args = [self.id, self.online, self.mobile, self.status_time or datetime.utcnow()]
        return q, q_args

    async def to_discord(self, ctx: Union[MrBot, commands.Context], guild_id: int = None) -> Optional[Union[discord.Member, discord.User]]:
        bot, guild, _ = self._split_ctx(ctx, guild_id)
        # Check guild, return Member
        if guild:
            member: discord.Member = guild.get_member(self.id)
            if member:
                return member
        # Check all bot users, return User
        user: discord.User = bot.get_user(self.id)
        if user:
            return user
        # Fetch from API
        try:
            return await bot.fetch_user(self.id)
        except discord.errors.NotFound:
            return None

    # noinspection PyTypeChecker
    @staticmethod
    def _split_ctx(ctx: Union[MrBot, commands.Context], guild_id: int = None) -> Tuple[MrBot, discord.Guild, int]:
        """Split Context into bot and guild, try to get guild if Bot and guild_id are given."""
        if isinstance(ctx, instance_check):
            bot: MrBot = ctx
            if not guild_id:
                guild = None
            else:
                guild: discord.Guild = bot.get_guild(guild_id)
        elif isinstance(ctx, commands.Context):
            bot: MrBot = ctx.bot
            guild: discord.Guild = ctx.guild
            guild_id = ctx.guild.id
        else:
            raise TypeError(f'Unknown type {type(ctx)}, need Bot or Context')
        return bot, guild, guild_id

    @staticmethod
    def make_psql_query(with_nick=False, with_all_nicks=False, with_activity=False, with_status=False,
                        where: str = '') -> str:
        """Return a query to get a user from PSQL

        :param with_nick: Get nick only for this guild, it will be added as first query argument
        :param with_all_nicks: Get all nicknames, overridden by with_nick
        :param with_activity: Get latest user activity
        :param with_status: Get latest user status
        :param where: Add WHERE condition"""
        select_args = 'u.id, u.name, u.discriminator, u.avatar'
        from_args = f'FROM {User.psql_table_name} u'
        if with_nick:
            select_args += ', n.nick AS nick, n.guild_id AS nick_guild_id'
            from_args += f' LEFT JOIN {User.psql_table_name_nicks} n ON (u.id = n.user_id AND n.guild_id = $1)'
        elif with_all_nicks:
            # For each user, return an array containing the nickname and its associated guild
            # The first index is the nick and the second is the guild_id as a string!
            # Returns [None, None] if they don't exist
            select_args += ", array_agg(array[n.nick::text, n.guild_id::text]) AS all_nicks"
            from_args += f' LEFT JOIN {User.psql_table_name_nicks} n ON (u.id = n.user_id)'
        if with_activity:
            select_args += ', a.activity AS activity, a.time AS activity_time'
            from_args += (f' LEFT JOIN LATERAL (SELECT activity, time FROM {User.psql_table_name_activities} '
                          'WHERE user_id = u.id ORDER BY time DESC LIMIT 1) a ON true')
        if with_status:
            select_args += ', s.online AS online, s.mobile AS mobile, s.time AS status_time'
            from_args += (f' LEFT JOIN LATERAL (SELECT online, mobile, time FROM {User.psql_table_name_status} '
                          'WHERE user_id = u.id ORDER BY time DESC LIMIT 1) s ON true')
        q = f'SELECT {select_args} {from_args}'
        if where:
            q += f' WHERE {where}'
        if with_nick:
            return q
        if with_all_nicks:
            q += ' GROUP BY u.id, u.name, u.discriminator, u.avatar'
            if with_activity:
                q += ', a.activity, a.time'
            if with_status:
                q += ', s.online, s.mobile, s.time'
        return q

    @classmethod
    def from_search_discord_users(cls, search_name: str, users: List[Union[discord.User, discord.Member]]) -> Optional[User]:
        """Returns the closest match in a list of discord Users"""
        similarities = {}
        for i in range(len(users)):
            user = users[i]
            names = [user.name]
            if isinstance(user, discord.Member):
                if user.nick:
                    names.append(user.nick)
                for r in user.roles:
                    if len(r.members) == 1:
                        names.append(r.name)
            _, sim = find_closest_match(search_name, names)
            if sim:
                similarities[i] = sim
        if similarities:
            closest_idx = max(similarities, key=similarities.get)
            return cls.from_discord(users[closest_idx])
        return None

    @classmethod
    async def from_search(cls, ctx: Union[MrBot, commands.Context], search: Union[int, str],
                          guild_id: int = None, **kwargs) -> Optional[User]:
        """Look for user with a name/nickname similar to search, if search is ID look for that instead"""
        search_id: int = 0
        search_user: str = ''
        if isinstance(search, (int, str, float)):
            search = str(search)
            m = re_id.search(search)
            if m:
                search_id = int(m.group())
            else:
                search_user = search
        # We have an ID, fetch directly
        if search_id:
            return await cls.from_id(ctx, user_id=search_id, guild_id=guild_id, **kwargs)
        bot, guild, guild_id = cls._split_ctx(ctx, guild_id)
        # Search by name instead, starting with guild members
        if guild:
            user = cls.from_search_discord_users(search_user, guild.members)
            if user:
                return user
        # Search in PSQL table
        async with bot.pool.acquire() as con:
            all_users = await cls.from_psql_all(con, guild_id, **kwargs)
        similarities = {}
        for i in range(len(all_users)):
            u = all_users[i]
            names = []
            if u.name:
                names.append(u.name)
            if u.all_nicks:
                names += list(u.all_nicks.values())
            if not names:
                continue
            _, sim = find_closest_match(search_user, names)
            if sim:
                similarities[i] = sim
        if similarities:
            closest_idx = max(similarities, key=similarities.get)
            return all_users[closest_idx]
        # Check bot cache, returns discord.User
        user = cls.from_search_discord_users(search_user, bot.users)
        if user:
            return user
        return None

    @classmethod
    async def from_id(cls, ctx: Union[MrBot, commands.Context], user_id: int,
                      guild_id: int = None, **kwargs) -> Optional[User]:
        bot, _, guild_id = cls._split_ctx(ctx, guild_id=guild_id)
        # Check cache
        d_user = bot.get_user(user_id)
        if d_user:
            return cls.from_discord(d_user)
        # Check PSQL
        async with bot.pool.acquire() as con:
            if kwargs.get('with_nick', False) and guild_id:
                q = cls.make_psql_query(where='u.id=$2', **kwargs)
                r = await con.fetchrow(q, guild_id, user_id)
            else:
                q = cls.make_psql_query(where='u.id=$1', **kwargs)
                r = await con.fetchrow(q, user_id)
            if r:
                return cls.from_psql_res(r)
        # Fetch from API
        try:
            d_user = await bot.fetch_user(user_id)
        except discord.errors.NotFound:
            return None
        return cls.from_discord(d_user)

    @classmethod
    def from_discord(cls, user: Union[discord.User, discord.Member]) -> Optional[User]:
        all_nicks = {}
        activity = None
        online = None
        mobile = False
        if isinstance(user, discord.Member):
            all_nicks[user.guild.id] = user.nick
            mobile = user.is_on_mobile()
            online = str(user.status) != 'offline'
            if user.activity and user.activity.name:
                activity = user.activity.name
        return cls(
            id_=user.id,
            name=user.name,
            discriminator=int(user.discriminator),
            avatar=user.avatar,
            all_nicks=all_nicks,
            activity=activity,
            online=online,
            mobile=mobile,
        )

    @classmethod
    def from_psql_res(cls, res: asyncpg.Record, prefix: str = '') -> Optional[User]:
        if not res.get(f'{prefix}id', None):
            return None
        all_nicks = {}
        all_nicks_list = res.get(f'{prefix}all_nicks')
        # We expect a list where each element (string) is [<name>, <guild_id>]
        if all_nicks_list:
            for nick_pair in all_nicks_list:
                # Should never happen
                if not nick_pair or not len(nick_pair) == 2:
                    continue
                nick, guild_id = nick_pair[0], nick_pair[1]
                if nick is None or guild_id is None:
                    continue
                all_nicks[int(guild_id)] = nick
        # We have nick and nick_guild_id instead
        elif res.get(f'{prefix}nick') and res.get(f'{prefix}nick_guild_id'):
            all_nicks[res[f'{prefix}nick_guild_id']] = res[f'{prefix}nick']
        return cls(
            id_=res.get(f'{prefix}id'),
            name=res.get(f'{prefix}name'),
            discriminator=res.get(f'{prefix}discriminator'),
            avatar=res.get(f'{prefix}avatar'),
            all_nicks=all_nicks,
            activity=res.get(f'{prefix}activity'),
            activity_time=res.get(f'{prefix}activity_time'),
            online=res.get(f'{prefix}online'),
            mobile=res.get(f'{prefix}mobile'),
            status_time=res.get(f'{prefix}status_time'),
        )

    @classmethod
    async def from_psql_all(cls, con: asyncpg.Connection, guild_id=None, **kwargs) -> List[User]:
        """Returns all users from PSQL, kwargs passed to make_psql_query"""
        if guild_id is not None and 'with_nick' in kwargs:
            results = await con.fetch(cls.make_psql_query(**kwargs), guild_id)
        else:
            results = await con.fetch(cls.make_psql_query(**kwargs))
        users = []
        for r in results:
            users.append(cls.from_psql_res(r))
        return users
