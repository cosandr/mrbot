import json
from typing import NamedTuple, List, Union, Dict, Optional

import discord


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


class BotConfig:
    """Global bot config, will not start without most of it"""
    def __init__(self, token, psql, data='', upload='', brains='',
                 hostname='', approved_guilds=None, secrets=None, guilds=None):
        self.token: str = token
        self.psql: str = psql
        self.data: str = data
        self.upload: str = upload
        self.brains: str = brains
        self.hostname: str = hostname
        self.approved_guilds: List[int] = approved_guilds
        self.guilds: Dict[int, GuildDef] = guilds
        # List of data read from the JSON file(s)
        self.secrets: List[dict] = secrets

    @classmethod
    def from_json(cls, secrets: Union[str, List[str]], paths: Union[str, List[str]],
                  guilds: Union[str, List[str]] = None):
        """Read secrets and paths JSON files, later data overrides previous data"""
        kwargs = dict(secrets=[], approved_guilds=[], guilds={})
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
            kwargs['secrets'].append(data)
            if v := data.get('token'):
                kwargs['token'] = v
            if data.get('psql') and data['psql'].get('main'):
                kwargs['psql'] = data['psql']['main']
            if v := data.get('approved_guilds'):
                kwargs['approved_guilds'] += v

        for file_name in paths:
            with open(file_name, 'r') as f:
                data: dict = json.load(f)
            if v := data.get('data'):
                kwargs['data'] = v
            if v := data.get('upload'):
                kwargs['upload'] = v
            if v := data.get('brains'):
                kwargs['brains'] = v
            if v := data.get('hostname'):
                kwargs['hostname'] = v

        for file_name in guilds:
            g = GuildDef.from_json(file_name)
            kwargs['guilds'][g.id] = g

        return cls(**kwargs)
