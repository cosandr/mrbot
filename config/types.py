import json
from typing import NamedTuple, List, Union, Dict, Optional

import discord

from ext.utils import pg_connection


class Generic(NamedTuple):
    name: str
    value: str


class DefaultPermissions:
    """Some default PermissionOverwrite's"""
    @staticmethod
    def read_write():
        """Permission allowing reading and writing messages"""
        return discord.PermissionOverwrite(
            read_messages=True,
            read_message_history=True,
            send_messages=True,
            send_tts_messages=True,
            manage_messages=False,
            embed_links=True,
            attach_files=True,
            mention_everyone=True,
            external_emojis=True,
            add_reactions=True,
        )

    @staticmethod
    def read_only():
        """Permission only allowing reading messages"""
        return discord.PermissionOverwrite(
            read_messages=True,
            read_message_history=True,
            send_messages=False,
            send_tts_messages=False,
            add_reactions=True
        )

    @staticmethod
    def deny():
        """Permission blocking access"""
        return discord.PermissionOverwrite(
            read_messages=False,
            read_message_history=False,
            send_messages=False,
            send_tts_messages=False
        )


class RoleDef:
    """Role definition for guild.json"""
    def __init__(self, name, **kwargs):
        self.name: str = name
        self.permission_overwrite = discord.PermissionOverwrite(**kwargs)

    def __eq__(self, other):
        if not isinstance(other, RoleDef):
            return False
        return self.name == other.name and self.permission_overwrite == other.permission_overwrite

    def to_dict(self) -> dict:
        ret = {self.name: {}}
        for k, v in self.permission_overwrite:
            if v is not None:
                ret[self.name][k] = v
        return ret

    def to_permissions(self) -> discord.Permissions:
        """Return a Permissions objects from this role's overwrites"""
        perms = discord.Permissions()
        update_dict = {}
        for k, v in self.permission_overwrite:
            if v is not None:
                update_dict[k] = v
        if update_dict:
            perms.update(**update_dict)
        return perms


class MemberDef:
    """Member definition for guild.json"""
    def __init__(self, id_, name, self_role=False, roles=None):
        self.id: int = id_
        self.name: str = name
        self.self_role: bool = self_role
        self.roles: List[str] = roles
        # Ensure stuff that should be a list is a list
        if self.roles and not isinstance(self.roles, list):
            self.roles = [self.roles]

    def __eq__(self, other):
        if not isinstance(other, MemberDef):
            return False
        return (self.id == other.id and self.name == other.name and
                self.self_role == other.self_role and self.roles == other.roles)


class TextChannelDef:
    """Text channel definition for guild.json"""
    def __init__(self, name, roles=None, member_names=None, member_ids=None, read_only=False):
        self.name: str = name
        self.roles: List[str] = roles
        self.member_names: List[str] = member_names
        self.member_ids: List[int] = member_ids
        self.read_only: bool = read_only
        # Ensure stuff that should be a list is a list
        if self.roles and not isinstance(self.roles, list):
            self.roles = [self.roles]
        if self.member_names and not isinstance(self.member_names, list):
            self.member_names = [self.member_names]
        if self.member_ids and not isinstance(self.member_ids, list):
            self.member_ids = [self.member_ids]

    def __eq__(self, other):
        if not isinstance(other, TextChannelDef):
            return False
        return (self.name == other.name and self.read_only == other.read_only and
                self.member_names == other.member_names and self.roles == other.roles and
                self.member_ids == other.member_ids)


class GuildDef:
    """Overall definition for guild.json"""
    def __init__(self, id_, name='', members=None, text_channels=None, roles=None):
        self.id: int = id_
        self.name: str = name
        self.members: Dict[int, MemberDef] = members
        self.text_channels: Dict[str, TextChannelDef] = text_channels
        self.roles: Dict[str, RoleDef] = roles

    def __eq__(self, other):
        if not isinstance(other, GuildDef):
            return False
        return (self.id == other.id and self.name == other.name and self.members == other.members and
                self.text_channels == other.text_channels and self.roles == other.roles)

    def find_user_name(self, name: str) -> Optional[MemberDef]:
        """Find a member definition by name"""
        for m in self.members.values():
            if m.name == name:
                return m
        return None

    @staticmethod
    def _ensure_list(data) -> list:
        if not isinstance(data, list):
            return [data]
        return data

    @classmethod
    def from_dict(cls, data: dict):
        kwargs = dict(members={}, text_channels={}, roles={})
        kwargs['id_'] = data.get('id')
        kwargs['name'] = data.get('name')
        for name, perms in data.get('roles', {}).items():
            kwargs['roles'][name] = RoleDef(name=name, **perms)
        for id_, v in data.get('members', {}).items():
            kwargs['members'][int(id_)] = MemberDef(
                id_=int(id_),
                name=v.get('name', ''),
                self_role=v.get('self_role', False),
                roles=v.get('roles', []),
            )
        for name, v in data.get('text_channels', {}).items():
            kwargs['text_channels'][name] = TextChannelDef(
                name=name,
                roles=v.get('roles', []),
                member_names=v.get('member_names', []),
                member_ids=v.get('member_ids', []),
                read_only=v.get('read_only', False),
            )
        return cls(**kwargs)

    @classmethod
    def from_json(cls, file_name: str):
        with open(file_name, 'r') as f:
            data: dict = json.load(f)
        return cls.from_dict(data=data)


class PostgresConfig:
    def __init__(self):
        self.main: str = ''
        self.public: str = ''
        self.web: str = ''
        self.live: str = ''


class BotConfig:
    """Global bot config, will not start without most of it"""
    psql_table_name = 'bot_config'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            name  VARCHAR(20) NOT NULL,
            type  VARCHAR(10) NOT NULL,
            data  JSONB NOT NULL,
            UNIQUE (name, type)
    );
    """
    psql_all_tables = {(psql_table_name,): psql_table}

    def __init__(self, token, psql, api_keys=None, approved_guilds=None, brains='',
                 data='', guilds=None, hostname='', upload=''):
        self.token: str = token
        self.psql: PostgresConfig = psql
        self.api_keys: dict = api_keys or dict()
        self.approved_guilds: List[int] = approved_guilds or []
        self.brains: str = brains
        self.data: str = data
        self.guilds: Dict[int, GuildDef] = guilds or {}
        self.hostname: str = hostname
        self.upload: str = upload

    @classmethod
    def from_dict(cls, data: dict):
        """Read all from single dict"""
        kwargs = dict(psql=PostgresConfig(), api_keys={}, approved_guilds=[], guilds={})

        for d in data.get('secrets', []):
            if v := d.get('token'):
                kwargs['token'] = v
            if v := d.get('psql'):
                for name, dsn in v.items():
                    setattr(kwargs['psql'], name, dsn)
            if v := d.get('approved_guilds'):
                kwargs['approved_guilds'] += v
            for name, val in d.get('api-keys', {}).items():
                kwargs['api_keys'][name] = val

        for d in data.get('paths', []):
            if v := d.get('data'):
                kwargs['data'] = v
            if v := d.get('upload'):
                kwargs['upload'] = v
            if v := d.get('brains'):
                kwargs['brains'] = v
            if v := d.get('hostname'):
                kwargs['hostname'] = v

        for d in data.get('guilds', []):
            g = GuildDef.from_dict(d)
            kwargs['guilds'][g.id] = g

        if not kwargs.get('token'):
            raise RuntimeError('Token not found in config')

        if not kwargs['psql'].main:
            raise RuntimeError('DSN for main PostgreSQL connection was not found')

        return cls(**kwargs)

    @classmethod
    async def from_psql(cls, dsn: str, extra: Dict[str, List[str]] = None):
        """Load config from PSQL table, always loads data named main and all guilds"""
        all_dict = dict(secrets=[], paths=[], guilds=[])
        extra = extra or dict()

        def add_record(r):
            if r['type'] == 'secrets':
                all_dict['secrets'].append(json.loads(r['data']))
            elif r['type'] == 'paths':
                all_dict['paths'].append(json.loads(r['data']))

        def get_record(r_list, n, t):
            for r in r_list:
                if r['name'] == n and r['type'] == t:
                    return r
            return None

        async with pg_connection(dsn=dsn) as con:
            all_rows = await con.fetch(f'SELECT * FROM {cls.psql_table_name}')
            # Add main and guilds
            for row in all_rows:
                if row['name'] == 'main':
                    add_record(row)
                elif row['type'] == 'guild':
                    all_dict['guilds'].append(json.loads(row['data']))
            # Add extra
            for r_type in ('secrets', 'paths'):
                for name in extra.get(r_type, []):
                    if row := get_record(all_rows, name, r_type):
                        add_record(row)
                    else:
                        raise RuntimeError(f'Requested row {name} of type {r_type} not found in table `{cls.psql_table_name}`')
        return cls.from_dict(all_dict)

    @classmethod
    def from_json(cls, secrets: Union[str, List[str]], paths: Union[str, List[str]],
                  guilds: Union[str, List[str]] = None):
        """Read secrets and paths JSON files, later data overrides previous data"""
        all_dict = dict(secrets=[], paths=[], guilds=[])
        if isinstance(secrets, str):
            secrets = [secrets]
        if isinstance(paths, str):
            paths = [paths]
        if guilds:
            if isinstance(guilds, str):
                guilds = [guilds]
        else:
            guilds = []
        for file_name in secrets:
            with open(file_name, 'r') as f:
                data: dict = json.load(f)
            all_dict['secrets'].append(data)

        for file_name in paths:
            with open(file_name, 'r') as f:
                data: dict = json.load(f)
            all_dict['paths'].append(data)

        for file_name in guilds:
            with open(file_name, 'r') as f:
                data: dict = json.load(f)
            all_dict['guilds'].append(data)

        return cls.from_dict(all_dict)
