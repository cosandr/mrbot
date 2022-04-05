from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Union, List, Optional, Tuple

import asyncpg
import discord
from discord.ext import commands

import config as cfg
from ext.utils import get_url, re_id, find_similar_str
from .base import Common
from .channel import Channel
from .guild import Guild
from .user import User
from ..context import Context

if TYPE_CHECKING:
    from mrbot import MrBot


class Message(Common):
    psql_table_name = 'messages'
    psql_table_name_edits = 'message_edits'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            content     VARCHAR(2000),
            time        TIMESTAMPTZ NOT NULL,
            deleted     BOOLEAN DEFAULT false,
            edited      BOOLEAN DEFAULT false,
            msg_id      BIGINT UNIQUE NOT NULL,
            user_id     BIGINT NOT NULL REFERENCES {User.psql_table_name} (id),
            ch_id       BIGINT NOT NULL REFERENCES {Channel.psql_table_name} (id),
            guild_id    BIGINT REFERENCES {Guild.psql_table_name} (id),
            attachments TEXT [],
            embed       JSONB,
            CONSTRAINT chk_empty CHECK (content IS NOT NULL OR attachments IS NOT NULL OR embed IS NOT NULL)
        );
        CREATE TABLE IF NOT EXISTS {psql_table_name_edits} (
            content     VARCHAR(2000),
            time        TIMESTAMPTZ NOT NULL,
            attachments TEXT [],
            embed       JSONB,
            msg_id      BIGINT NOT NULL REFERENCES {psql_table_name} (msg_id) ON DELETE CASCADE,
            CONSTRAINT chk_empty CHECK (content IS NOT NULL OR attachments IS NOT NULL OR embed IS NOT NULL)
        );
        CREATE OR REPLACE FUNCTION insert_edited_message()
            RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO {psql_table_name_edits} (content, time, attachments, embed, msg_id)
            VALUES (OLD.content, OLD.time, OLD.attachments, OLD.embed, OLD.msg_id);
            NEW.edited = true;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS trigger_insert_edited_message ON {psql_table_name};
        CREATE TRIGGER trigger_insert_edited_message BEFORE update ON {psql_table_name}
        FOR EACH ROW WHEN (NEW.deleted = false) EXECUTE PROCEDURE insert_edited_message();
    """
    # Dictionary containing all required tables and their names in order
    psql_all_tables = Guild.psql_all_tables.copy()
    psql_all_tables.update(Channel.psql_all_tables)
    psql_all_tables.update(User.psql_all_tables)
    psql_all_tables.update({(psql_table_name, psql_table_name_edits): psql_table})

    __slots__ = Common.__slots__ + \
        ('id', 'time', 'content', 'attachments', 'embed', 'deleted', 'edits', 'author', 'channel', 'guild')

    # noinspection PyTypeChecker
    def __init__(self, id_: int, time_: datetime = None, content: str = '', attachments: List[str] = None,
                 embed: dict = None, deleted: bool = False, edits: list = None, author: User = None,
                 channel: Channel = None, guild: Guild = None):
        self.id: int = id_
        self.time: datetime = time_
        self.content: str = content
        # URLs of message attachments
        self.attachments: List[str] = [] if not attachments else attachments
        self.embed: dict = embed
        self.deleted: bool = deleted
        self.edits: List[Message] = [] if not edits else edits
        self.author: User = author
        self.channel: Channel = channel
        self.guild: Guild = guild

    def __str__(self):
        return self.content

    @property
    def urls(self):
        ret = []
        if self.content:
            ret += get_url(self.content, one=False)
        if self.embed:
            em = discord.Embed.from_dict(self.embed)
            if isinstance(em.image.url, str):
                ret.append(em.image.url)
            if isinstance(em.video.url, str):
                ret.append(em.video.url)
            if em.description:
                ret += get_url(em.description, one=False)
            for f in em.fields:
                if f.name:
                    ret += get_url(f.name, one=False)
                if f.value:
                    ret += get_url(f.value, one=False)
        if self.attachments:
            ret += self.attachments
        return ret

    def to_psql(self) -> Tuple[str, list]:
        """"Returns a query and its arguments to insert/update this message into a table"""
        q = (f'INSERT INTO {self.psql_table_name} '
             '(content, time, attachments, embed, deleted, edited, msg_id, user_id, ch_id, guild_id) '
             'VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) '
             'ON CONFLICT (msg_id) DO UPDATE SET '
             'content=$1, time=$2, attachments=$3, embed=$4, deleted=$5, edited=$6')
        # Replace empty string with None
        content = self.content if self.content else None
        q_args = [content, self.time, self.attachments, self.embed_str, self.deleted,
                  self.edited, self.id, self.author.id, self.channel.id, self.guild_id]
        return q, q_args

    def to_psql_edit(self) -> Tuple[str, list]:
        """"Returns a query and its arguments to insert this message as edited"""
        q = (f'INSERT INTO {self.psql_table_name_edits} '
             '(content, time, attachments, embed, msg_id) VALUES ($1, $2, $3, $4)')
        # Replace empty string with None
        content = self.content if self.content else None
        q_args = [content, self.time, self.attachments, self.embed_str, self.id]
        return q, q_args

    def to_psql_mark_deleted(self) -> Tuple[str, list]:
        """Returns a query and its arguments to mark this message as edited/deleted"""
        q = f'UPDATE {self.psql_table_name} SET deleted=$2 WHERE msg_id=$1'
        q_args = [self.id, self.deleted]
        return q, q_args

    @property
    def edited(self):
        """Returns True if this message has been edited"""
        return len(self.edits) > 0

    @property
    def embed_str(self):
        """Embed serialized by JSON"""
        if not self.embed:
            return None
        return json.dumps(self.embed)

    @property
    def guild_id(self):
        if not self.guild:
            return None
        return self.guild.id

    @property
    def extra(self) -> str:
        if not self.urls:
            return ''
        return '\n'.join(self.urls)

    @property
    def first_image(self) -> Optional[str]:
        """Returns the URL of the first image in this message"""
        return self.get_url(img_only=True)

    @property
    def first_url(self) -> Optional[str]:
        return self.get_url(img_only=False)

    def get_url(self, img_only=False) -> Optional[str]:
        """Returns the first URL in this message"""
        # Search content
        if not self.urls:
            ret = get_url(self.content, img_only=img_only)
            if ret:
                return ret
            return None
        # Already processed
        if not img_only:
            return self.urls[0]
        for url in self.urls:
            ret = get_url(url, img_only=True)
            if ret:
                return ret
        return None

    @property
    def local_time(self) -> datetime:
        return self.time.replace(tzinfo=timezone.utc).astimezone(tz=None)

    @property
    def time_str(self) -> str:
        """Format timestamp as HH:MM - DD.MM.YY (UTC)"""
        return self.time.strftime(cfg.TIME_FORMAT) + ' UTC'

    @property
    def local_time_str(self) -> str:
        """Format timestamp as HH:MM - DD.MM.YY (Local time)"""
        return self.local_time.strftime(cfg.TIME_FORMAT)

    @property
    def is_pm(self) -> bool:
        return not isinstance(self.guild, Guild)

    @property
    def jump_url(self) -> str:
        if self.is_pm:
            return f'https://discordapp.com/channels/@me/{self.channel.id}/{self.id}'
        return f'https://discordapp.com/channels/{self.guild.id}/{self.channel.id}/{self.id}'

    @property
    def discord_embed(self) -> discord.Embed:
        """Embed from this message"""
        embed = discord.Embed()
        embed.set_footer(text=self.time_str)
        if self.author.avatar_url:
            embed.set_author(name=self.author.display_name, icon_url=self.author.avatar_url)
        else:
            embed.set_author(name=self.author.display_name)
        embed.description = self.content
        if self.urls:
            embed.add_field(name='Attachments', value=self.extra, inline=True)
        msg_img = self.first_image
        if msg_img:
            embed.set_image(url=msg_img)
        embed.add_field(name='Jump URL', value=f'[Click Me!]({self.jump_url})')
        return embed

    @property
    def discord_embed_field(self) -> Tuple[str, str]:
        name = f'{self.author.display_name} at {self.time_str}'
        if len(self.content) <= 50:
            value = f'{self.content}\n[Original]({self.jump_url})'
        else:
            value = f'{self.content[:40]}...\n[Original]({self.jump_url})'
        return name, value

    def discord_add_embed_field(self, embed: discord.Embed) -> discord.Embed:
        """Add this message in a compact form to an Embed"""
        name, value = self.discord_embed_field
        embed.add_field(name=name, value=value, inline=False)
        return embed

    async def to_discord(self, bot: MrBot) -> Optional[discord.Message]:
        """Returns a discord.Message, if it exists"""
        # Check internal cache
        for msg in bot.cached_messages:
            if msg.id == self.id:
                return msg
        # Fetch from API
        try:
            channel: discord.TextChannel = bot.get_channel(self.channel.id)
            if not channel:
                return None
            msg = await channel.fetch_message(self.id)
            return msg
        except discord.errors.NotFound:
            return None

    @staticmethod
    async def jump_url_from_psql(con: asyncpg.Connection, msg_id: int) -> Optional[str]:
        q = f'SELECT msg_id, ch_id, guild_id FROM {Message.psql_table_name} WHERE msg_id=$1'
        res = await con.fetchrow(q, msg_id)
        if not res:
            return None
        msg: Message = Message(
            id_=res['msg_id'],
            channel=Channel(id_=res['ch_id']),
            guild=Guild(id_=res['guild_id']) if res['guild_id'] else None,
        )
        return msg.jump_url

    @staticmethod
    async def to_discord_from_id(bot: MrBot, msg_id: int, ch_id: int):
        # We only need message and channel IDs
        msg: Message = Message(id_=msg_id, channel=Channel(id_=ch_id))
        return await msg.to_discord(bot)

    @classmethod
    async def from_user_id(cls, ctx: Union[MrBot, Context], user_id: int, ch_id: int = None, **kwargs) -> Optional[Message]:
        """Attempt to return the last message sent by user ID
        :param ctx: Context or Bot instance, ch_id must be provided in order to fetch from API using a Bot
        :param user_id: ID of the user we're interested in
        :param ch_id: ID of the channel to search in, not needed for Context
        :param kwargs: Passed to Message.from_psql
        :returns: Latest message sent by this user, None if not found
        """
        bot, channel, ch_id = cls._split_ctx(ctx, ch_id)
        # Check internal cache
        for msg in bot.cached_messages:
            if msg.author.id == user_id:
                if ch_id:
                    if ch_id == msg.channel.id:
                        return cls.from_discord(msg)
                    else:
                        continue
                return cls.from_discord(msg)
        # Check PSQL
        async with bot.pool.acquire() as con:
            if ch_id:
                q = f'SELECT msg_id FROM {cls.psql_table_name} WHERE user_id=$1 AND ch_id=$2 ORDER BY time DESC LIMIT 1'
                msg_id = await bot.pool.fetchval(q, user_id, ch_id)
            else:
                q = f'SELECT msg_id FROM {cls.psql_table_name} WHERE user_id=$1 ORDER BY time DESC LIMIT 1'
                msg_id = await bot.pool.fetchval(q, user_id)
            if msg_id:
                return await cls.from_psql(con=con, msg_id=msg_id, **kwargs)
        # Fetch from API
        if not channel:
            return None
        async for msg in channel.history(limit=20):
            if msg.author.id == user_id:
                return cls.from_discord(msg)
        return None

    @classmethod
    async def from_id(cls, ctx: Union[MrBot, Context], msg_id: int, ch_id: int = None, **kwargs) -> Optional[Message]:
        """Attempt to return the Message with given ID

        :param ctx: Context or Bot instance, ch_id must be provided in order to fetch from API using a Bot
        :param msg_id: ID of the Message to get
        :param ch_id: ID of the channel to search in, not needed for Context
        :param kwargs: Passed to Message.from_psql
        :returns: The requested Message, None if not found
        """
        bot, channel, ch_id = cls._split_ctx(ctx, ch_id)
        # Check internal cache
        for msg in bot.cached_messages:
            if msg.id == msg_id:
                return cls.from_discord(msg)
        # Check PSQL
        async with bot.pool.acquire() as con:
            msg = await cls.from_psql(con=con, msg_id=msg_id, **kwargs)
            if msg:
                return msg
        # Fetch from API
        if not channel:
            return None
        try:
            msg = await channel.fetch_message(msg_id)
            return cls.from_discord(msg)
        except discord.errors.NotFound:
            return None

    @classmethod
    def from_discord(cls, msg: discord.Message) -> Optional[Message]:
        attachments = []
        for att in msg.attachments:
            if isinstance(att.url, str):
                attachments.append(att.url)
        embed = None
        if msg.embeds:
            embed = msg.embeds[0].to_dict()
        return cls(
            id_=msg.id,
            time_=msg.created_at,
            content=msg.content,
            embed=embed,
            attachments=attachments,
            author=User.from_discord(msg.author),
            channel=Channel.from_discord(msg.channel),
            guild=Guild.from_discord(msg.guild),
        )

    # noinspection PyTypeChecker
    @staticmethod
    def _split_ctx(ctx: Union[MrBot, Context], ch_id: int = None) -> Tuple[MrBot, discord.TextChannel, int]:
        """Split Context into bot and channel, try to get channel if Bot and ch_id are given."""
        if isinstance(ctx, commands.Bot):
            bot: MrBot = ctx
            if not ch_id:
                channel = None
            else:
                channel: discord.TextChannel = bot.get_channel(ch_id)
        elif isinstance(ctx, Context):
            bot: MrBot = ctx.bot
            channel: discord.TextChannel = ctx.channel
            ch_id = ctx.channel.id
        else:
            raise TypeError(f'Unknown type {type(ctx)}, need Bot or Context')
        return bot, channel, ch_id

    @classmethod
    async def with_url(cls, ctx: Union[MrBot, Context], search: Union[None, int, str] = None, ch_id: int = None,
                       img_only: bool = False, skip_id: Optional[int] = None) -> Optional[Message]:
        """Look for a message with a URL in it

        :param ctx: Context or Bot instance, ch_id must be provided in order to fetch from API using a Bot
        :param search: ID of the user we're interested in
        :param ch_id: ID of the channel to search in, not needed for Context
        :param img_only: Only messages with image URLs
        :param skip_id: Skip messages from user with this ID
        :returns: Message matching criteria, None if not found
        """
        start = time.perf_counter()
        bot, channel, ch_id = cls._split_ctx(ctx, ch_id)
        if not ch_id:
            return None
        search_id: int = 0
        search_user: str = ''
        if isinstance(search, (int, str, float)):
            search = str(search)
            m = re_id.search(search)
            if m:
                search_id = int(m.group())
            else:
                search_user = search
        bot.logger.debug('search_id: %d, search_user: %s', search_id, search_user)

        def valid_msg_check(msg_: Message):
            check_ids = [msg_.id, msg_.author.id]
            check_names = []
            check_content = ''
            if msg_.author.name:
                check_names.append(msg_.author.name)
            if msg_.author.all_nicks:
                check_names += list(msg_.author.all_nicks.values())
            if msg_.content:
                check_content = msg_.content
            check_content += msg_.extra
            # Invalid message if ID is ignored
            if skip_id in check_ids:
                return False
            # No content to search
            if not get_url(check_content, img_only):
                return False
            # Don't check any IDs or names
            if not search_id and not search_user:
                return True
            # Check for matching IDs
            if search_id and search_id in check_ids:
                return True
            # Try to match username
            if search_user and find_similar_str(search_user, check_names):
                return True
            return False

        for d_msg in bot.cached_messages:
            if d_msg.channel.id == ch_id:
                msg = cls.from_discord(d_msg)
                if valid_msg_check(msg):
                    bot.logger.info('URL found in cache in %.2fms', (time.perf_counter() - start) * 1000)
                    return msg
        async with bot.pool.acquire() as con:
            q = cls.make_psql_query(with_author=True, with_nick=True, where='ch_id=$1 ORDER BY time DESC LIMIT 50')
            results = await con.fetch(q, ch_id)
            for r in results:
                msg = await cls.from_psql_res(r, con, with_edits=False)
                if valid_msg_check(msg):
                    bot.logger.info('URL found in PSQL in %.2fms', (time.perf_counter() - start) * 1000)
                    return msg
        if not channel:
            return None
        async for d_msg in channel.history(limit=20):
            msg = cls.from_discord(d_msg)
            if valid_msg_check(msg):
                bot.logger.info('URL found from API in %.2fms', (time.perf_counter() - start) * 1000)
                return msg
        bot.logger.info('No URL found in %.2fms', (time.perf_counter() - start) * 1000)
        return None

    @staticmethod
    def make_psql_query(with_author=False, with_channel=False, with_guild=False, with_nick=False, where: str = ''):
        """Return a query to get a messages from PSQL, must add filters if desired"""
        select_args = 'm.content, m.time, m.attachments, m.embed, m.deleted, m.edited, m.msg_id, m.user_id, m.ch_id, m.guild_id'
        from_args = f'FROM {Message.psql_table_name} m'
        if with_nick:
            select_args += ', n.nick AS user_nick'
            from_args += f' LEFT JOIN {User.psql_table_name_nicks} n ON (m.user_id = n.user_id AND m.guild_id = n.guild_id)'
        if with_author:
            select_args += (', u.name AS user_name, u.discriminator AS user_discriminator, u.avatar AS user_avatar'
                            ', u.activity AS user_activity, u.mobile AS user_mobile')
            from_args += f' INNER JOIN {User.psql_table_name} u ON (m.user_id = u.id)'
        if with_channel:
            select_args += ', c.name AS ch_name, c.voice AS ch_voice'
            from_args += f' INNER JOIN {Channel.psql_table_name} c ON (m.ch_id = c.id)'
        if with_guild:
            select_args += ', g.name AS guild_name'
            from_args += f' LEFT JOIN {Guild.psql_table_name} g ON (m.guild_id = g.id)'
        q = f'SELECT {select_args} {from_args}'
        if where:
            q += f' WHERE {where}'
        return q

    @classmethod
    async def from_psql_res(cls, res: asyncpg.Record, con: asyncpg.Connection = None, with_edits=False) -> Optional[Message]:
        """Return a message from PSQL query result (such as from make_psql_query)
        Includes edited history if con and with_edits are provided"""
        if not res:
            return
        embed = res.get('embed', None)
        if embed:
            embed = json.loads(embed)
        edits = []
        if con and res.get('edited') and with_edits:
            q = f'SELECT content, time, attachments, embed FROM {cls.psql_table_name_edits} WHERE msg_id=$1'
            res_edit = await con.fetch(q, res['msg_id'])
            for r in res_edit:
                edit_embed = res.get('embed', None)
                if edit_embed:
                    edit_embed = json.loads(edit_embed)
                edits.append(cls(id_=res['msg_id'],
                                 time_=r.get('time'),
                                 content=r.get('content'),
                                 attachments=r.get('attachments'),
                                 embed=edit_embed,
                                 ))
        return cls(
            id_=res['msg_id'],
            time_=res.get('time'),
            content=res.get('content'),
            attachments=res.get('attachments'),
            embed=embed,
            deleted=res.get('deleted'),
            edits=edits,
            author=User.from_psql_res(res, 'user_'),
            channel=Channel.from_psql_res(res, 'ch_'),
            guild=Guild.from_psql_res(res, 'guild_'),
        )

    @classmethod
    async def from_psql(cls, con: asyncpg.Connection, msg_id: int, with_edits=False, **kwargs) -> Optional[Message]:
        """Return Message from PSQL with given ID"""
        q = cls.make_psql_query(where='m.msg_id=$1', **kwargs)
        res = await con.fetchrow(q, msg_id)
        return await cls.from_psql_res(res, con, with_edits)
