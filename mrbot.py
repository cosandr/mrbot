import asyncio
import json
import logging
import os
import signal
import traceback
from base64 import b64decode
from typing import List, Optional

import asyncpg
import discord
from aiohttp import ClientSession, UnixConnector
from discord.ext import commands
from pkg_resources import get_distribution

import config as cfg
from ext.embed_helpers import embed_local_file
from ext.errors import MissingConfigError
from ext.brains import Response, BrainsAPIError
from ext.utils import cleanup_http_params, human_seconds


class MrBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        self.config: cfg.BotConfig = kwargs.pop('config')
        super().__init__(*args, **kwargs)
        # --- Bot variable init ---
        self.aio_sess: Optional[ClientSession] = None
        self.unix_sess: Optional[ClientSession] = None
        self.pool: Optional[asyncpg.pool.Pool] = None
        self._close_ran: bool = False
        self.cleanup_tasks: List[asyncio.Task] = []
        self.exec_times: List[float] = []
        # --- Logger ---
        logger_fmt = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
        # Console Handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logger_fmt)
        # File Handler
        self.log_file_name = kwargs.pop('log_file_name', 'mrbot.log')
        fh = logging.FileHandler(filename=self.log_file_name, encoding='utf-8', mode='w')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logger_fmt)
        # Root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)
        root_logger.addHandler(fh)
        root_logger.addHandler(ch)
        # Discord logger (API stuff)
        discord_logger = logging.getLogger('discord')
        discord_logger.setLevel(logging.WARNING)
        # Bot logger
        self.logger_name = self.__class__.__name__
        self.logger = logging.getLogger(self.logger_name)
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        # --- Load stuff ---
        self.connect_task: asyncio.Task = self.loop.create_task(self.connect_sess())
        self.extension_override = kwargs.pop('extension_override', None)
        self.load_all_extensions()
        signal.signal(signal.SIGTERM, self._signal_handler)
        # Queue for message logger
        self.msg_queue = asyncio.PriorityQueue()
        self.psql_lock = asyncio.Lock()

    def run(self, *args, **kwargs):
        super().run(self.config.token, *args, **kwargs)

    def _signal_handler(self, _signal_num, _frame) -> None:
        """Close gracefully on SIGTERM"""
        self.loop.create_task(self.close())

    async def connect_sess(self) -> None:
        """Connects to postgres `discord` database using a pool and aiohttp"""
        self.pool = await asyncpg.create_pool(dsn=self.config.psql)
        # noinspection PyProtectedMember
        self.logger.info(f"Pool connected to database `{self.pool._working_params.database}`.")
        self.aio_sess = ClientSession()
        self.logger.info("Aiohttp session initialized.")
        if self.config.brains.startswith('/'):
            self.logger.info("Unix session initialized.")
            self.unix_sess = ClientSession(connector=UnixConnector(path=self.config.brains))

    async def on_ready(self) -> None:
        self.logger.info((f"Logged in as {self.user.name} [{self.user.id}], "
                          f"d.py version {get_distribution('discord.py').version}"))

    async def close(self) -> None:
        if self._close_ran:
            return
        self._close_ran = True
        self.logger.info(f"{'-'*10} Cleanup start {'-'*10}")
        self.logger.info('--- Unloading cogs')
        self.unload_all_extensions()
        for task in self.cleanup_tasks:
            if not task.done():
                self.logger.info(f'------ Waiting for {task.get_coro()}')
            await task
        self.logger.info('--- Closing aiohttp session')
        await self.aio_sess.close()
        if self.unix_sess:
            self.logger.info('--- Closing unix session')
            await self.unix_sess.close()
        self.logger.info('--- Closing PSQL pool')
        await asyncio.wait_for(self.pool.close(), 3)
        self.logger.info(f"{'-'*10} Cleanup done {'-'*11}\n")
        await super().close()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.id == self.user.id:
            return

        # Only process commands starting with a single prefix
        if not message.content.startswith(self.command_prefix*2, 0, 2):
            await self.process_commands(message)

    @staticmethod
    async def add_reaction_str(msg: discord.Message, in_str: str) -> None:
        """Add Unicode emoji to given message.\n
        Sends warning if repeat letters are detected.

        :param msg: Message to add emoji to
        :param in_str: String to add as reaction
        """
        err_str = ""
        in_str = in_str.lower()
        # Track valid letters and how many times they occur
        first_set = set()
        second_set = set()
        react_count = len(msg.reactions)
        for c in in_str:
            if react_count >= 20:
                break
            if c not in cfg.EMOJI_DICT:
                err_str += f"`{c}` cannot be added as reaction.\n"
                continue
            if c in first_set:
                if c not in second_set:
                    err_str += f"`{c}` occurs more than once, only first occurrence added.\n"
                    second_set.add(c)
                continue
            await msg.add_reaction(cfg.EMOJI_DICT[c])
            first_set.add(c)
            react_count += 1
        if err_str != "":
            await msg.channel.send(err_str)

    async def list_group_subcmds(self, ctx: commands.Context) -> discord.Message:
        """Called when a group cannot be invoked without a subcommand.
        Returns an embed with all available subcommands in the group.

        :param ctx: The context from which the group was invoked
        """
        owner_called = await self.is_owner(ctx.author)
        embed = discord.Embed()
        embed.colour = discord.Colour.red()
        embed.set_author(name=f"{ctx.command.name} cannot be called directly", icon_url=str(self.get_user(self.owner_id).avatar_url))
        embed.title = "Available subcommands:"
        for subcmd in ctx.command.commands:
            if not owner_called and subcmd.hidden:
                continue
            embed.add_field(name=subcmd.name, value=subcmd.brief, inline=False)
        return await ctx.send(embed=embed)

    def load_all_extensions(self, logger: logging.Logger = None) -> None:
        """Load all bot cogs in `cogs` folder, ignores files starting with `disabled`."""
        loaded = []
        skipped = []
        failed = []
        if self.extension_override is not None:
            to_load = self.extension_override
        else:
            to_load = []
            for file in os.listdir('cogs'):
                if file == '__pycache__':
                    continue
                file_name, file_extension = os.path.splitext(f"cogs/{file}")
                # Load .py files or folders (modules), skip files starting with _
                if file_extension in ('.py', ''):
                    if file.startswith('disabled_'):
                        skipped.append(file_name)
                        continue
                to_load.append(file_name.replace("/", "."))
        err_msg = "\n"
        ret_str = "\n"
        for ext_name in to_load:
            try:
                self.load_extension(ext_name)
                loaded.append(ext_name)
            except Exception as error:
                if hasattr(error, 'original') and isinstance(error.original, MissingConfigError):
                    err_msg += f'{error}\n'
                else:
                    err_msg += ''.join(traceback.format_exception(type(error), error, error.__traceback__)) + "\n"
                failed.append(ext_name)
        if len(skipped) > 0:
            ret_str += "Skipped:\n"
            for cog in skipped:
                ret_str += f"-- {cog}\n"
        ret_str += "Loaded:\n"
        for cog in loaded:
            ret_str += f"-> {cog}\n"
        if len(failed) > 0:
            ret_str += "Failed:\n"
            for cog in failed:
                ret_str += f"!! {cog}\n"
            ret_str += err_msg
        if logger is None:
            logger = self.logger
        logger.info(ret_str.rstrip())

    def unload_all_extensions(self) -> None:
        """Same as `load_all_extensions` except it unloads them."""
        # DO NOT REMOVE, avoids error below
        # RuntimeError: dictionary changed size during iteration
        for name in [k for k in self.extensions.keys()]:
            try:
                self.unload_extension(name)
            except:
                self.logger.exception(f'Failed to unload {name}')

    async def brains_post_request(self, url: str, **kwargs) -> Response:
        """Return Response from brains API POST request, url should include slash"""
        # Clean up params
        if kwargs.get('params'):
            kwargs['params'] = cleanup_http_params(kwargs['params'])
        # JSON encode data
        if kwargs.get('data'):
            kwargs['data'] = json.dumps(kwargs['data'])
        if self.unix_sess:
            sess = self.unix_sess
            url = f'http://unix{url}'
        else:
            sess = self.aio_sess
            url = f'{self.config.brains}{url}'
        try:
            async with sess.post(url, **kwargs) as resp:
                r = await Response.from_resp(resp)
        except Exception as e:
            raise BrainsAPIError(e)
        return r

    async def brains_get_request(self, url: str, **kwargs) -> Response:
        """Return Response from brains API GET request, url should include slash"""
        # Clean up params
        if kwargs.get('params'):
            kwargs['params'] = cleanup_http_params(kwargs['params'])
        if self.unix_sess:
            sess = self.unix_sess
            url = f'http://unix{url}'
        else:
            sess = self.aio_sess
            url = f'{self.config.brains}{url}'
        try:
            async with sess.get(url, **kwargs) as resp:
                r = await Response.from_resp(resp)
        except Exception as e:
            raise BrainsAPIError(e)
        return r

    async def check_url_status(self, url: str, allow_redirects=False) -> bool:
        """Runs a HEAD request and returns True if the status code is between 200 and 300"""
        try:
            async with self.aio_sess.head(url, allow_redirects=allow_redirects) as resp:
                return 200 <= resp.status < 300
        except Exception as e:
            self.logger.debug(f'HEAD request for {url} failed: {e}')
            return False

    async def upload_file(self, wb: bytes, file_name: str) -> str:
        """Uploads input bytes and checks the resulting URL to make sure it is valid"""
        file_path = os.path.join(self.config.upload, file_name)
        url = f'{self.config.hostname}/discord/{file_name}'
        if not os.path.exists(file_path):
            try:
                with open(file_path, 'wb') as fw:
                    fw.write(wb)
                os.chmod(file_path, 0o644)
                self.logger.debug(f'Uploaded {file_name}')
            except:
                self.logger.exception(f'Cannot upload {file_name}')
                return ''
        if await self.check_url_status(url):
            return url
        return ''

    async def brains_image_request(self, url: str, msg: discord.Message, embed: discord.Embed, **kwargs):
        """Run the POST or GET request and edit the message with its image/url"""
        if 'data' in kwargs:
            r = await self.brains_post_request(url, **kwargs)
        else:
            r = await self.brains_get_request(url, **kwargs)
        if not r.ok:
            return await msg.edit(embed=r.fail_embed(embed, "Server error"))
        comp_time = human_seconds(r.time, num_units=1, precision=2)
        embed.set_footer(text=f"Completed in {comp_time}", icon_url=embed.footer.icon_url)
        img_url = ''
        # We got a URL
        if 'url' in r.data:
            if await self.check_url_status(r.data['url']):
                img_url = r.data['url']
            else:
                self.logger.warning(f'Got bad URL from brains API {r.data["url"]}')
        # We got an image
        if not img_url and 'image' in r.data:
            img_bytes = b64decode(r.data['image'])
            # Too big, upload to local web server
            if len(img_bytes) > cfg.DISCORD_MAX_SIZE:
                img_url = await self.upload_file(img_bytes, r.data['filename'])
            else:
                await msg.delete()
                embed.colour = discord.Colour.green()
                embed, file = embed_local_file(embed, img_bytes, r.data['filename'])
                return await msg.channel.send(embed=embed, file=file)
        if not img_url:
            embed.colour = discord.Colour.red()
            embed.set_footer()
            embed.clear_fields()
            embed.add_field(name="Error", value="Could not find any valid URLs from the API response", inline=True)
            return await msg.edit(embed=embed)
        # If we get here, we have a valid URL, either to a video or GIF
        embed.colour = discord.Colour.green()
        if r.data.get('codec'):
            await msg.edit(content=img_url, embed=embed)
            return
        embed.set_image(url=img_url)
        await msg.edit(embed=embed)
