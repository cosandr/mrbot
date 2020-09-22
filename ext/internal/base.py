from abc import ABCMeta, abstractmethod
from datetime import datetime
from typing import List, Tuple, Dict

import asyncpg
import discord

from config import TIME_FORMAT


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
    def diff(self, other) -> List[str]:
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
    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        for k in self._props:
            if getattr(self, k) != getattr(other, k):
                return False
        return True

    def __str__(self):
        return getattr(self, 'name', '')

    def __repr__(self):
        attrs = []
        for k in self._props:
            name = k
            # Remove leading _, we probably have a setter
            if name[0] == '_':
                name = name[1:]
            # Replace id with id_
            elif name == 'id':
                name = 'id_'
            attrs.append(f'{name}={repr(getattr(self, k))}')
        return f'{self.__class__.__name__}({", ".join(attrs)})'

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
        for k in self._props:
            name = k
            if name[0] == '_':
                name = name[1:]
            v = getattr(self, k)
            # Always show booleans, but ignore empty lists, dicts, None etc
            if isinstance(v, bool) or v:
                if func := getattr(v, "pretty_repr", None):
                    attrs.append(f'{" " * _level * 2}{name}:\n{func(_level+1)}')
                elif isinstance(v, datetime):
                    attrs.append(f'{" " * _level * 2}{name}: {v.strftime(TIME_FORMAT)}')
                else:
                    attrs.append(f'{" " * _level * 2}{name}: {str(v)}')
        return "\n".join(attrs)

    @property
    def _props(self) -> List[str]:
        """Return list of instance attributes which should be compared

        Excludes class attributes"""
        ret = []
        for k in vars(self).keys():
            if k.startswith(("__", "psql_table")) or k == "psql_all_tables":
                continue
            ret.append(k)
        return ret

    def diff(self, other) -> List[str]:
        """Returns list of properties which are different"""
        if not isinstance(other, self.__class__):
            raise TypeError(f'Cannot compare {type(self)} to {type(other)}')
        props = []
        for k in self._props:
            if getattr(self, k) != getattr(other, k):
                props.append(k)
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
