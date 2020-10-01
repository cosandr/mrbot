from datetime import datetime
from typing import Tuple

import asyncpg

from ext.context import Context
from ext.internal import User, Guild
from ext.utils import paginate


class Pasta:
    psql_table_name = 'pasta'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            name      VARCHAR(50) UNIQUE,
            content   TEXT NOT NULL,
            user_id   BIGINT REFERENCES {User.psql_table_name} (id),
            guild_id  BIGINT REFERENCES {Guild.psql_table_name} (id),
            added     TIMESTAMP DEFAULT NOW()
        );
    """
    # Depends on Guild and User tables
    psql_all_tables = Guild.psql_all_tables.copy()
    psql_all_tables.update(User.psql_all_tables)
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, name, content, user=None, guild=None, added=None):
        self.name: str = name
        self.content: str = content
        self.user: User = user
        self.guild: Guild = guild
        self.added: datetime = added if added else datetime.utcnow()

    def __eq__(self, other):
        if not isinstance(other, Pasta):
            return False
        return (self.name == other.name and
                self.content == other.content and
                self.user_id == other.user_id and
                self.guild_id == other.guild_id and
                self.added == other.added)

    async def send(self, ctx: Context):
        for p in paginate(self.content, wrap=''):
            await ctx.send(p)

    async def maybe_send(self, ctx: Context):
        if err := self.view_error(ctx):
            return await ctx.send(err)
        return await self.send(ctx)

    def edit_error(self, ctx: Context) -> str:
        # Pasta has set owner
        if self.user_id:
            if ctx.author.id != self.user_id and ctx.author.id != ctx.bot.owner_id:
                return f'{self.name} is owned by {self.owner_name}.'
        # No owner and wrong guild
        elif ctx.guild and self.guild_id and ctx.guild.id != self.guild_id:
            return f'{self.name} belongs to {self.guild_name}.'
        return ''

    def view_error(self, ctx: Context) -> str:
        """Returns error string if calling user doesn't permission to view this pasta,
        empty string if it can be viewed.

        Permission overview:

        - Public when neither user_id nor guild_id are set
        - Anyone in a specific guild when guild_id is set
        - Owner when user_id is set, overrides guild_id if set
        - Owner when only user_id is set
        - Bot owner can use any pasta
        """
        # Public pasta
        if not self.user and not self.guild:
            return ''
        # Allow pasta and bot owner
        if self.user_id == ctx.author.id or ctx.author.id == ctx.bot.owner_id:
            return ''
        # Allow anyone in the same guild
        if ctx.guild and self.guild_id == ctx.guild.id:
            return ''
        owner_name = self.owner_name
        # If we get here, the pasta cannot be shown, figure out why
        if guild_name := self.guild_name:
            return f'{self.name} can only be used by {owner_name} or in {guild_name}.'
        return f'{self.name} can only be used by {owner_name}.'

    def check_permissions(self, ctx: Context) -> bool:
        """Returns True if calling user has permission to view this pasta"""
        return not self.view_error(ctx)

    def copy(self):
        return Pasta(
            name=self.name,
            content=self.content,
            user=self.user,
            guild=self.guild,
            added=self.added,
        )

    @property
    def owner_name(self):
        if not self.user:
            return ''
        if self.user.name:
            owner_name = self.user.name
            if self.user.discriminator:
                owner_name += f'#{self.user.discriminator}'
            return owner_name
        return f'user ID {self.user.id}'

    @property
    def guild_name(self):
        if not self.guild:
            return ''
        if self.guild.name:
            return f'the `{self.guild.name}` guild'
        return f'the guild with ID {self.guild.id}'

    @property
    def user_id(self):
        if self.user:
            return self.user.id
        return None

    @property
    def guild_id(self):
        if self.guild:
            return self.guild.id
        return None

    def to_psql(self) -> Tuple[str, list]:
        """Returns a query in the form (name, content, ...) VALUES ($1,$2, ...) and its arguments"""
        q = (f'INSERT INTO {self.psql_table_name} '
             '(name, content, user_id, guild_id, added) VALUES ($1, $2, $3, $4, $5) '
             'ON CONFLICT (name) DO UPDATE SET content=$2, user_id=$3, guild_id=$4')
        q_args = [self.name, self.content, self.user_id, self.guild_id, self.added]
        return q, q_args

    @staticmethod
    def make_psql_query(with_user=False, with_nick=False, with_guild=False, where: str = '') -> str:
        """Return a query to get a pasta from PSQL

        :param with_user: Join info from users table
        :param with_nick: Join info from user nicknames table
        :param with_guild: Join info from guilds table
        :param where: Filter output"""
        select_args = 'p.name, p.content, p.user_id, p.guild_id, p.added'
        from_args = f'FROM {Pasta.psql_table_name} p'
        if with_user:
            select_args += ', u.name AS user_name, u.discriminator AS user_discriminator, u.avatar AS user_avatar'
            from_args += f' LEFT JOIN {User.psql_table_name} u ON (p.user_id = u.id)'
        if with_nick:
            select_args += ', un.nick AS user_nick, un.guild_id AS user_nick_guild_id'
            from_args += f' LEFT JOIN {User.psql_table_name_nicks} un ON (p.user_id = un.user_id AND un.guild_id = p.guild_id)'
        if with_guild:
            select_args += ', g.name AS guild_name'
            from_args += f' LEFT JOIN {Guild.psql_table_name} g ON (p.guild_id = g.id)'
        q = f'SELECT {select_args} {from_args}'
        if where:
            q += f' WHERE {where}'
        return q

    @staticmethod
    def make_psql_query_full(where: str = '') -> str:
        """Like make_psql_query but always runs table joins"""
        return Pasta.make_psql_query(with_user=True, with_nick=True, with_guild=True, where=where)

    @classmethod
    def from_psql_res(cls, res: asyncpg.Record):
        if not res or not res.get('name') or not res.get('content'):
            return None
        return cls(
            name=res['name'],
            content=res['content'],
            user=User.from_psql_res(res, 'user_'),
            guild=Guild.from_psql_res(res, 'guild_'),
            added=res.get('added'),
        )
