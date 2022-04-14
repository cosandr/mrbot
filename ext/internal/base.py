from abc import ABCMeta, abstractmethod
from datetime import datetime
from typing import Tuple, Dict, Set

import asyncpg
import discord

import config as cfg
from ext.utils import format_dt


class CommonMeta(metaclass=ABCMeta):
    @abstractmethod
    def __eq__(self, other):
        raise NotImplemented

    @abstractmethod
    def __str__(self):
        raise NotImplemented

    @abstractmethod
    def __repr__(self):
        raise NotImplemented

    @property
    @abstractmethod
    def psql_table_name(self) -> str:
        raise NotImplemented

    @property
    @abstractmethod
    def psql_table(self) -> str:
        raise NotImplemented

    @property
    @abstractmethod
    def psql_all_tables(self) -> Dict[Tuple[str], str]:
        raise NotImplemented

    @abstractmethod
    def diff(self, other) -> Set[str]:
        raise NotImplemented

    @abstractmethod
    def to_psql(self) -> Tuple[str, list]:
        raise NotImplemented

    @classmethod
    @abstractmethod
    def from_discord(cls, *args):
        raise NotImplemented

    @abstractmethod
    async def to_discord(self, *args, **kwargs) -> discord.abc.Snowflake:
        raise NotImplemented

    @staticmethod
    @abstractmethod
    def make_psql_query(*args) -> str:
        raise NotImplemented

    @classmethod
    @abstractmethod
    def from_psql_res(cls, res: asyncpg.Record, prefix: str):
        raise NotImplemented


class Common(CommonMeta):
    # __slots__ = ('psql_table', 'psql_table_name', 'psql_all_tables')
    __slots__ = ()

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        for k in self.__slots__:
            if getattr(self, k) != getattr(other, k):
                return False
        return True

    def __str__(self):
        return getattr(self, 'name', '')

    def __repr__(self):
        attrs = []
        for k in self.__slots__:
            name = k
            # Remove leading _, we probably have a setter
            if name[0] == '_':
                name = name[1:]
            # Replace id with id_
            elif name == 'id':
                name = 'id_'
            attrs.append(f'{name}={repr(getattr(self, k))}')
        return f'{self.__class__.__name__}({", ".join(attrs)})'

    def asdict(self) -> dict:
        ret = {}
        for k in self.__slots__:
            ret[k] = getattr(self, k)
        return ret

    @property
    @abstractmethod
    def psql_table_name(self) -> str:
        raise NotImplemented

    @property
    @abstractmethod
    def psql_table(self) -> str:
        raise NotImplemented

    @property
    @abstractmethod
    def psql_all_tables(self) -> Dict[Tuple[str], str]:
        raise NotImplemented

    def pretty_repr(self, _level=0) -> str:
        attrs = []
        for k in self.__slots__:
            name = k
            if name[0] == '_':
                name = name[1:]
            v = getattr(self, k)
            # Always show booleans, but ignore empty lists, dicts, None etc
            if isinstance(v, bool) or v:
                if func := getattr(v, "pretty_repr", None):
                    attrs.append(f'{" " * _level * 2}{name}:\n{func(_level+1)}')
                elif isinstance(v, datetime):
                    attrs.append(f'{" " * _level * 2}{name}: {format_dt(v, cfg.TIME_FORMAT, cfg.TIME_ZONE)}')
                else:
                    attrs.append(f'{" " * _level * 2}{name}: {str(v)}')
        return "\n".join(attrs)

    def diff(self, other) -> Set[str]:
        """Returns list of properties which are different"""
        if not isinstance(other, self.__class__):
            raise TypeError(f'Cannot compare {type(self)} to {type(other)}')
        props = set()
        for k in self.__slots__:
            if getattr(self, k) != getattr(other, k):
                props.add(k)
        return props

    @abstractmethod
    def to_psql(self) -> Tuple[str, list]:
        raise NotImplemented

    @classmethod
    @abstractmethod
    def from_discord(cls, *args):
        raise NotImplemented

    @abstractmethod
    async def to_discord(self, *args, **kwargs) -> discord.abc.Snowflake:
        raise NotImplemented

    @staticmethod
    @abstractmethod
    def make_psql_query(*args) -> str:
        raise NotImplemented

    @classmethod
    @abstractmethod
    def from_psql_res(cls, res: asyncpg.Record, prefix: str):
        raise NotImplemented
