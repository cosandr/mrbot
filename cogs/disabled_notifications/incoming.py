import json
import logging
from datetime import datetime

import discord

import config as cfg

logger = logging.getLogger('discord.Notifications')
TIME_FORMAT_NO_DATE = '%H:%M:%S'


class Incoming:
    """
    {
        "name": <source name>,
        "content": <message to display>,
        # OPTIONAL
        "time": <time of event>,
        "embed": <Discord embed as a dict>
    }
    From shell
    jq -n --arg name "test name" --arg content "content here" '{name: $name, content: $content}'
    Send with ncat
    <JSON> | nc SERVER_IP LISTEN_PORT
    """
    def __init__(self, name, content, time=None, embed=None):
        self.name: str = name
        self.content: str = content
        self.time: datetime = time
        self.embed: discord.Embed = embed

    @property
    def time_str(self):
        return self.time.strftime(cfg.TIME_FORMAT)

    @property
    def time_str_no_date(self):
        return self.time.strftime(TIME_FORMAT_NO_DATE)

    def __eq__(self, other):
        if not isinstance(other, Incoming):
            return False
        this_embed = self.embed.to_dict() if self.embed else None
        other_embed = other.embed.to_dict() if other.embed else None
        return (self.name == other.name and
                self.content == other.content and
                self.time == other.time and
                this_embed == other_embed)

    def __gt__(self, other):
        if not isinstance(other, Incoming):
            raise TypeError(f"Cannot compare {type(self)} with {type(other)}")
        return self.time > other.time

    @classmethod
    def from_payload(cls, payload: bytes):
        """Construct Incoming object from json data"""
        json_data: dict = json.loads(payload.decode('utf-8'))
        if not json_data.get('time'):
            json_data['time'] = datetime.now()
        else:
            try:
                json_data['time'] = datetime.fromisoformat(json_data['time'])
            except:
                logger.error('Incoming data timestamp cannot be parsed: %s', str(json_data['time']))
                json_data['time'] = datetime.now()
        name = json_data.get('name')
        if not name:
            raise Exception('Incoming data is missing name')
        content = json_data.get('content', None)
        embed_data = json_data.get('embed', None)
        if not content and not embed_data:
            raise Exception('Incoming data is missing content and embed')
        if embed_data:
            embed = discord.Embed.from_dict(embed_data)
        else:
            embed = None
        return cls(
            name=name,
            content=content,
            time=json_data['time'],
            embed=embed,
        )

    def to_msg_kwargs(self) -> dict:
        """Return arguments to be used with send method in Discord"""
        if self.embed:
            self.embed.set_footer(text=self.time_str)
            msg_content = f'Notification from {self.name} with embed'
        else:
            msg_content = f'Notification from {self.name} at {self.time_str}'
        if self.content:
            msg_content += f'\n```{self.content}```'
        return dict(content=msg_content, embed=self.embed)
