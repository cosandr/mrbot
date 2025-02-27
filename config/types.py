import json
import os
import re
from typing import List, Union, Dict, Optional

import discord

from ext.utils import pg_connection


class BaseConfig:
    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        for k, v in vars(self).items():
            if v != getattr(other, k):
                return False
        return True

    def __repr__(self):
        attrs = []
        for k, v in vars(self).items():
            name = k
            # Remove leading _, we probably have a setter
            if name[0] == '_':
                name = name[1:]
            # Replace id with id_
            elif name == 'id':
                name = 'id_'
            attrs.append(f'{name}={repr(v)}')
        return f'{self.__class__.__name__}({", ".join(attrs)})'

    def pretty_repr(self, _level=0):
        attrs = []
        for k, v in vars(self).items():
            name = k
            if name[0] == '_':
                name = name[1:]
            # Always show booleans, but ignore empty lists, dicts, None etc
            if isinstance(v, bool) or v:
                if func := getattr(v, "pretty_repr", None):
                    attrs.append(f'{" " * _level * 2}{name}:\n{func(_level + 1)}')
                else:
                    attrs.append(f'{" " * _level * 2}{name}: {str(v)}')
        return "\n".join(attrs)


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


class RoleDef(BaseConfig):
    """Role definition for guild.json"""

    def __init__(self, name, **kwargs):
        self.name: str = name
        self.permission_overwrite = discord.PermissionOverwrite(**kwargs)

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


class MemberDef(BaseConfig):
    """Member definition for guild.json"""

    def __init__(self, id_, name, self_role=False, roles=None):
        self.id: int = id_
        self.name: str = name
        self.self_role: bool = self_role
        self.roles: List[str] = roles
        # Ensure stuff that should be a list is a list
        if self.roles and not isinstance(self.roles, list):
            self.roles = [self.roles]


class TextChannelDef(BaseConfig):
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


class GuildDef(BaseConfig):
    """Overall definition for guild.json"""

    def __init__(self, id_, name='', members=None, text_channels=None, roles=None):
        self.id: int = id_
        self.name: str = name
        self.members: Dict[int, MemberDef] = members
        self.text_channels: Dict[str, TextChannelDef] = text_channels
        self.roles: Dict[str, RoleDef] = roles

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


class PostgresConfig(BaseConfig):
    def __init__(self, **kwargs):
        self.main: str = kwargs.pop('main', '')
        self.public: str = kwargs.pop('public', '')
        self.web: str = kwargs.pop('web', '')
        self.live: str = kwargs.pop('live', '')

    def safe_repr(self, _level=0):
        """Like pretty_repr but hides passwords"""
        attrs = []
        for k, v in vars(self).items():
            if not v:
                continue
            name = k
            if name[0] == '_':
                name = name[1:]
            if m := re.match(r'postgres://\S+:(\S+)@\S*/\w+', v):
                span = m.span(1)
                safe_v = f'{v[:span[0]]}<password>{v[span[1]:]}'
                attrs.append(f'{" " * _level * 2}{name}: {str(safe_v)}')
        return "\n".join(attrs)

    @staticmethod
    def kwargs_from_env():
        env_map = {
            "main": os.getenv("MAIN_DSN"),
            "web": os.getenv("WEB_DSN"),
            "public": os.getenv("PUBLIC_DSN"),
            "live": os.getenv("LIVE_DSN"),
        }
        return {k: v for k, v in env_map.items() if v is not None}

    @classmethod
    def from_env(cls):
        return cls(**cls.kwargs_from_env())


class PathsConfig(BaseConfig):
    def __init__(self, **kwargs):
        self.data: str = kwargs.pop('data', './data')
        self.upload: str = kwargs.pop('upload', './upload')

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, p):
        self._verify_path(p)
        self._data = p

    @property
    def upload(self):
        return self._upload

    @upload.setter
    def upload(self, p):
        self._verify_path(p)
        self._upload = p

    @staticmethod
    def _verify_path(p):
        if not os.path.exists(p):
            os.mkdir(p)
        elif not os.access(p, os.W_OK | os.R_OK):
            raise RuntimeError(f'Insufficient permissions for {p}')

    @staticmethod
    def kwargs_from_env():
        env_map = {
            "data": os.getenv("DATA_PATH"),
            "upload": os.getenv("UPLOAD_PATH"),
        }
        return {k: v for k, v in env_map.items() if v is not None}


class ChannelsConfig(BaseConfig):
    def __init__(self, **kwargs):
        self.exceptions: Optional[int] = kwargs.pop('exceptions', None)
        self.default_voice: Optional[int] = kwargs.pop('default_voice', None)
        self.test: Optional[int] = kwargs.pop('test', None)


class HttpConfig(BaseConfig):
    def __init__(self, **kwargs):
        self.host: Optional[str] = kwargs.pop('host', 'localhost')
        self.port: Optional[int] = int(kwargs.pop('port', 8080))

    @staticmethod
    def kwargs_from_env():
        env_map = {
            "host": os.getenv("HTTP_SERVER_HOST"),
            "port": os.getenv("HTTP_SERVER_PORT"),
        }
        return {k: v for k, v in env_map.items() if v is not None}


class KubeConfig(BaseConfig):
    def __init__(self, **kwargs):
        self.namespace: str = kwargs.pop('namespace')
        self.selector: Optional[str] = kwargs.pop('selector', "app.kubernetes.io/instance=mrbot")
        self.label_key: Optional[str] = kwargs.pop('label_key', "is-busy")
        self.label_value: Optional[str] = kwargs.pop('label_value', "true")

    @staticmethod
    def kwargs_from_env():
        env_map = {
            "namespace": os.getenv("POD_NAMESPACE"),
            "selector": os.getenv("POD_SELECTOR"),
            "label_key": os.getenv("BUSY_LABEL_KEY"),
            "label_value": os.getenv("BUSY_LABEL_VALUE"),
        }
        return {k: v for k, v in env_map.items() if v is not None}


class BotConfig(BaseConfig):
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
                 guilds=None, hostname='', paths=None, channels=None, http=None,
                 kube=None):
        self.token: str = token
        self.psql: PostgresConfig = psql
        self.api_keys: dict = api_keys or dict()
        self.approved_guilds: List[int] = approved_guilds or []
        self.brains: str = brains
        self.guilds: Dict[int, GuildDef] = guilds or {}
        self.hostname: str = hostname
        self.paths: PathsConfig = paths
        self.channels: ChannelsConfig = channels
        self.http: HttpConfig = http
        self.kube: Optional[KubeConfig] = kube

    def safe_repr(self, _level=0):
        """Like pretty_repr but shorter and hides sensitive information (token, API keys)"""
        attrs = []
        for k, v in vars(self).items():
            if not v:
                continue
            name = k
            if name[0] == '_':
                name = name[1:]
            if func := getattr(v, "safe_repr", None) or getattr(v, "pretty_repr", None):
                attrs.append(f'{" " * _level * 2}{name}:\n{func(_level + 1)}')
            elif name == 'token':
                attrs.append(f'{" " * _level * 2}{name}: {v[:3]}...{v[-3:]}')
            elif name == 'api_keys':
                attrs.append(f'{" " * _level * 2}{name}: {", ".join(v.keys())}')
            elif name == 'guilds':
                attrs.append(f'{" " * _level * 2}{name}:')
                for g in v.values():
                    if g.name:
                        attrs.append(f'{" " * (_level + 1) * 2}{g.name} [{g.id}]')
                    else:
                        attrs.append(f'{" " * (_level + 1) * 2}[{g.id}]')
            else:
                attrs.append(f'{" " * _level * 2}{name}: {str(v)}')
        return "\n".join(attrs)

    @staticmethod
    def kwargs_from_dict(data: dict):
        """Construct kwargs for self from dict"""
        psql_kwargs = {}
        kwargs = dict(api_keys={}, approved_guilds=[], guilds={})
        _paths = dict()
        _channels = dict()
        _http = dict()
        _kube = dict()
        for d in data.get('configs', []):
            if v := d.get('token'):
                kwargs['token'] = v
            for name, dsn in d.get('psql', {}).items():
                if dsn:
                    psql_kwargs[name] = dsn
            for name, val in d.get('api-keys', {}).items():
                kwargs['api_keys'][name] = val
            if v := d.get('approved_guilds'):
                kwargs['approved_guilds'] += v
            if v := d.get('brains'):
                kwargs['brains'] = v
            if v := d.get('hostname'):
                kwargs['hostname'] = v
            for name, val in d.get('paths', {}).items():
                _paths[name] = val
            for name, val in d.get('channels', {}).items():
                _channels[name] = val
            for name, val in d.get('http', {}).items():
                _http[name] = val
            for name, val in d.get('kube', {}).items():
                _kube[name] = val

        for d in data.get('guilds', []):
            g = GuildDef.from_dict(d)
            kwargs['guilds'][g.id] = g

        kwargs['psql'] = PostgresConfig(**psql_kwargs)
        kwargs['paths'] = PathsConfig(**_paths)
        kwargs['channels'] = ChannelsConfig(**_channels)
        kwargs['http'] = HttpConfig(**_http)
        if _kube:
            kwargs['kube'] = KubeConfig(**_kube)

        return kwargs

    @classmethod
    def from_dict(cls, data: dict):
        """Read all from single dict"""
        kwargs = cls.kwargs_from_dict(data)

        if not kwargs.get('token'):
            raise RuntimeError('Token not found in config')

        if not kwargs['psql'].main:
            raise RuntimeError('DSN for main PostgreSQL connection was not found')

        return cls(**kwargs)

    @classmethod
    async def from_psql(cls, dsn: str, extra: List[str] = None):
        """Load config from PSQL table, always loads data named main and all guilds"""
        all_dict = dict(configs=[], guilds=[])
        extra = extra or []

        def get_config(r_list, n):
            for r in r_list:
                if r['name'] == n and r['type'] == 'config':
                    return r
            return None

        async with pg_connection(dsn=dsn) as con:
            all_rows = await con.fetch(f'SELECT * FROM {cls.psql_table_name}')
            # Add main and guilds
            for row in all_rows:
                if row['name'] == 'main' and row['type'] == 'config':
                    all_dict['configs'].append(json.loads(row['data']))
                elif row['type'] == 'guild':
                    all_dict['guilds'].append(json.loads(row['data']))
            # Add extra
            for name in extra:
                if row := get_config(all_rows, name):
                    all_dict['configs'].append(json.loads(row['data']))
                else:
                    raise RuntimeError(f'Requested config row {name} not found in table `{cls.psql_table_name}`')
        return cls.from_dict(all_dict)

    @classmethod
    def from_json(cls, configs: Union[str, List[str]], guilds: Union[str, List[str]] = None):
        """Read secrets and paths JSON files, later data overrides previous data"""
        all_dict = dict(configs=[], guilds=[])
        if isinstance(configs, str):
            configs = [configs]
        if guilds:
            if isinstance(guilds, str):
                guilds = [guilds]
        else:
            guilds = []
        for file_name in configs:
            with open(file_name, 'r') as f:
                data: dict = json.load(f)
            all_dict['configs'].append(data)

        for file_name in guilds:
            with open(file_name, 'r') as f:
                data: dict = json.load(f)
            all_dict['guilds'].append(data)

        return cls.from_dict(all_dict)

    @classmethod
    async def from_env_psql(cls, psql_configs: List[str] = None):
        """Load config from env and PSQL, env vars override PG vars"""
        psql_kwargs = PostgresConfig.kwargs_from_env()
        if "main" not in psql_kwargs:
            raise RuntimeError("MAIN_DSN is required")

        loaded_configs = set()
        configs = []
        guilds = []
        async with pg_connection(dsn=psql_kwargs["main"]) as con:
            all_rows = await con.fetch(f'SELECT * FROM {cls.psql_table_name}')
        for row in all_rows:
            if row['type'] == 'guild':
                guilds.append(json.loads(row['data']))
            if row['type'] == 'config' and row['name'] in psql_configs:
                configs.append(json.loads(row['data']))
                loaded_configs.add(row['name'])

        missing_rows = [name for name in psql_configs if name not in loaded_configs]
        fail_missing_rows = bool(os.getenv('FAIL_MISSING_ROWS', 1))
        if missing_rows and fail_missing_rows:
            raise RuntimeError(f'Requested config row {", ".join(missing_rows)} not found in table `{cls.psql_table_name}`')

        env_config = {
            "api-keys": {},
            "psql": psql_kwargs,
            "paths": PathsConfig.kwargs_from_env(),
            "http": HttpConfig.kwargs_from_env(),
        }
        if v := os.getenv("BRAINS_PATH"):
            env_config["brains"] = v
        if v := os.getenv("TOKEN"):
            env_config["token"] = v
        if v := os.getenv("MRBOT_HOSTNAME"):
            env_config["hostname"] = v
        if v := os.getenv("GOOGLE_API_KEY"):
            env_config["api-keys"]["google"] = v
        if v := os.getenv("WOLFRAM_API_KEY"):
            env_config["api-keys"]["wolfram"] = v
        if os.getenv("POD_NAMESPACE"):
            env_config["kube"] = KubeConfig.kwargs_from_env()
        # Construct config dict for use with cls.from_dict()
        configs.append(env_config)
        return cls.from_dict({"configs": configs, "guilds": guilds})
