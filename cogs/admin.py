from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import traceback
from contextlib import redirect_stdout
from datetime import timezone
from io import StringIO
from textwrap import indent
from traceback import format_exc
from typing import TYPE_CHECKING

import discord
import psutil
from discord.ext import commands

import config as cfg
import ext.embed_helpers as emh
from ext.context import Context
from ext.internal import User
from ext.parsers import parsers
from ext.psql import debug_query
from ext.utils import paginate

if TYPE_CHECKING:
    from mrbot import MrBot


class Admin(commands.Cog, name="Admin", command_attrs={'hidden': True}):
    def __init__(self, bot):
        self.bot: MrBot = bot
        self._last_result = None
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---

    async def cog_check(self, ctx: Context):
        if not await self.bot.is_owner(ctx.author):
            raise commands.errors.NotOwner
        return True

    @parsers.command(
        name='user-search',
        brief='Run User.from_search()',
        parser_args=[
            parsers.Arg('search', nargs='+', help='Search term'),
            parsers.Arg('--with_nick', default=False, help='Fetch nick', action='store_true'),
            parsers.Arg('--with_all_nicks', default=False, help='Fetch all nicknames', action='store_true'),
            parsers.Arg('--with_activity', default=False, help='Fetch latest activity', action='store_true'),
            parsers.Arg('--with_status', default=False, help='Fetch latest status', action='store_true'),
        ],
    )
    async def test_user_search(self, ctx: Context):
        search = ' '.join(ctx.parsed.search)
        kwargs = vars(ctx.parsed)
        kwargs.pop('search')
        user = await User.from_search(ctx, search, **kwargs)
        if not user:
            return await ctx.send(f'No user {search} found')
        return await ctx.send(f'```{user.pretty_repr()}```')

    @commands.command(name='logs', brief='Get bot logs')
    async def get_logs(self, ctx: Context, lines: int = 10):
        ret_str = ''
        i = 0
        with open(self.bot.log_file_name, 'r', encoding='utf-8') as fr:
            for line in reversed(list(fr)):
                if i >= lines:
                    break
                if not line or line == '\n':
                    continue
                ret_str += line
                i += 1
        await ctx.send(f'```\n{ret_str}\n```')

    @commands.group(name='psql-fix')
    async def psql_fix(self, ctx: Context):
        pass

    @psql_fix.command(name='user-nicks', brief='Update nicks in PSQL')
    async def psql_fix_user_nicks(self, ctx: Context):
        start = time.perf_counter()
        done = 0
        failed = 0
        async with self.bot.pool.acquire() as con:
            for guild in self.bot.guilds:
                for user in guild.members:
                    if not user.nick:
                        continue
                    int_user = User.from_discord(user)
                    q, q_args = int_user.to_psql_nick(guild_id=guild.id)
                    try:
                        await con.execute(q, *q_args)
                        done += 1
                    except Exception as e:
                        failed += 1
                        debug_query(q, q_args, e)
        await ctx.send(f'Added/updated {done} [{failed} failed] user nicks in {((time.perf_counter() - start) * 1000):,.3f}ms.')

    @psql_fix.command(name='users', brief='Update users in PSQL')
    async def psql_fix_users(self, ctx: Context):
        start = time.perf_counter()
        done = 0
        failed = 0
        async with self.bot.pool.acquire() as con:
            for d_user in self.bot.users:
                user = User.from_discord(d_user)
                q, q_args = user.to_psql()
                try:
                    await con.execute(q, *q_args)
                    done += 1
                except Exception as e:
                    failed += 1
                    debug_query(q, q_args, e)
        await ctx.send(f'Added/updated {done} [{failed} failed] users in {((time.perf_counter() - start) * 1000):,.3f}ms.')

    @commands.command(name='botcolour', brief='Changes bot role colour')
    @commands.bot_has_permissions(manage_roles=True)
    async def colour_bot(self, ctx: Context, colour: str):
        role = discord.utils.get(ctx.guild.roles, name='MrBot')
        await role.edit(colour=discord.Colour(int(colour, 16)))
        await ctx.send(f'Bot colour changed to {colour}')

    @parsers.group(name='dump', brief='Dump stuff group', invoke_without_command=False)
    async def dump(self, ctx: Context):
        return

    @dump.command(name='roles', brief='Dump all roles in this guild')
    async def dump_roles(self, ctx: Context):
        """Dumps discord.Permissions objects"""
        all_roles = {}
        for role in ctx.guild.roles:
            perms = {k: v for k, v in role.permissions}
            all_roles[role.name] = cfg.types.RoleDef(role.name, **perms).to_dict()
        with open(f'dumps/roles_{ctx.guild.id}.json', 'w') as f:
            json.dump(all_roles, f)
        await ctx.send(f'Dumped {len(all_roles)} roles in guild')

    @dump.command(name='channels', brief='Dump all channels in this guild', enabled=False)
    async def dump_channels(self, ctx: Context):
        """BROKEN"""
        all_channels = {}
        role_names = [r.name for r in ctx.guild.roles]
        for channel in ctx.guild.text_channels:
            roles = []
            for k, v in channel.overwrites.items():
                if isinstance(k, discord.Role):
                    roles.append(k.name)
            all_channels[channel.name] = cfg.types.TextChannelDef(name=channel.name, roles=roles)
        with open(f'dumps/text_channels_{ctx.guild.id}.json', 'w') as f:
            json.dump(all_channels, f)
        await ctx.send(f'Dumped {len(all_channels)} roles in guild')

    @parsers.group(name='reset', brief='Reset stuff group', invoke_without_command=False)
    async def reset(self, ctx: Context):
        return

    @reset.command(
        name='roles',
        brief='Reset roles',
        parser_args=[
            parsers.Arg('--i-mean-it', default=False, help='Actually do it', action='store_true'),
        ],
    )
    @commands.bot_has_permissions(manage_roles=True)
    @commands.has_permissions(manage_roles=True)
    async def reset_roles(self, ctx: Context):
        dry_run = True
        if ctx.parsed.i_mean_it:
            dry_run = False
            await ctx.send(f'Resetting roles, FOR REAL')
        else:
            await ctx.send(f'Resetting roles, dry run')
        guild_def = self.bot.config.guilds.get(ctx.guild.id, None)
        if not guild_def:
            return await ctx.send(f'No definitions for this guild.')
        if not guild_def.roles:
            return await ctx.send(f'No role definitions for this guild.')
        ret_str = ''
        create_roles = []
        # Get guild roles
        for r_name, r_def in guild_def.roles.items():
            # Can't edit self role
            if r_name == 'MrBot':
                continue
            edit_role = discord.utils.get(ctx.guild.roles, name=r_name)
            create_roles.append(
                dict(
                    edit_role=edit_role,
                    kwargs=dict(
                        name=r_name,
                        permissions=r_def.to_permissions(),
                        colour=cfg.DEFAULT_ROLE_COLOUR,
                        mentionable=True,
                    ),
                ),
            )
        # Get self-roles
        for u_id, u_def in guild_def.members.items():
            if not u_def.self_role:
                ret_str += f'No self-role defined for {u_def.name}\n'
            perms = discord.Permissions()
            edit_role = discord.utils.get(ctx.guild.roles, name=u_def.name)
            create_roles.append(
                dict(
                    edit_role=edit_role,
                    kwargs=dict(
                        name=u_def.name,
                        permissions=perms,
                        colour=cfg.DEFAULT_ROLE_COLOUR,
                        mentionable=True,
                    ),
                ),
            )
        for r_create in create_roles:
            edit_role = r_create['edit_role']
            kwargs = r_create['kwargs']
            r_name = kwargs.get('name')
            if edit_role:
                ret_str += f'Role {r_name} already exists, editing\n'
                if not dry_run:
                    await edit_role.edit(**kwargs)
            else:
                ret_str += f'Creating new role {r_name}\n'
                if not dry_run:
                    await ctx.guild.create_role(**kwargs)
        # Add roles to users
        for u_id, u_def in guild_def.members.items():
            member = ctx.guild.get_member(u_id)
            if not member:
                ret_str += f'{u_def.name} is not a member of this guild\n'
                continue
            roles = []
            for r_name in u_def.roles:
                r = discord.utils.get(ctx.guild.roles, name=r_name)
                if not r:
                    ret_str += f'Role {r_name} not found in this guild\n'
                else:
                    roles.append(r)
            if u_def.self_role:
                r = discord.utils.get(ctx.guild.roles, name=u_def.name)
                if not r:
                    ret_str += f'Role {u_def.name} not found in this guild\n'
                else:
                    roles.append(r)
            if not roles:
                ret_str += f'Found no roles to add for {u_def.name}\n'
                continue
            if not dry_run:
                await member.add_roles(*roles)
            ret_str += f'Added {len(roles)} to {member.name}\n'
        for p in paginate(ret_str):
            await ctx.send(p)

    @reset.command(
        name='rmchow',
        brief='Remove all channel overwrites',
        parser_args=[
            parsers.Arg('--i-mean-it', default=False, help='Actually do it', action='store_true'),
        ],
    )
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    @commands.has_permissions(manage_roles=True, manage_channels=True)
    async def reset_rmchow(self, ctx: Context):
        if ctx.parsed.i_mean_it:
            await ctx.send(f'Resetting roles, FOR REAL')
        else:
            await ctx.send(f'Resetting roles, dry run')
        for ch in ctx.guild.text_channels:
            for target in ch.overwrites.keys():
                if ctx.parsed.i_mean_it:
                    await ch.set_permissions(target, overwrite=None)
                print(f'Cleared overwrites for {target.name} in {ch.name}')

    @reset.command(
        name='chperms',
        brief='Reset channel perms',
        parser_args=[
            parsers.Arg('name', nargs='?', default='all', help='Channel to edit'),
            parsers.Arg('--i-mean-it', default=False, help='Actually do it', action='store_true'),
        ],
    )
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    @commands.has_permissions(manage_roles=True, manage_channels=True)
    async def reset_chperms(self, ctx: Context):
        guild_def = self.bot.config.guilds.get(ctx.guild.id, None)
        if not guild_def:
            return await ctx.send(f'No definitions for this guild.')
        if not guild_def.text_channels:
            return await ctx.send(f'No channel definitions for this guild.')
        if ctx.parsed.i_mean_it:
            await ctx.send(f'Resetting channel permissions, FOR REAL')
        else:
            await ctx.send(f'Resetting channel permissions, dry run')
        ret_str = ''
        for ch_name, ch_def in guild_def.text_channels.items():
            if ctx.parsed.name != 'all' and ch_name != ctx.parsed.name:
                continue
            channel = discord.utils.get(ctx.guild.text_channels, name=ch_name)
            if not channel:
                ret_str += f'No channel {ch_name}, creating\n'
                if ctx.parsed.i_mean_it:
                    channel = await ctx.guild.create_text_channel(ch_name)
            allow_names = [name for name in ch_def.roles]
            allow_names += [name for name in ch_def.member_names]
            for id_ in ch_def.member_ids:
                if name := guild_def.members.get(id_):
                    allow_names.append(name)
            allowed_rw = []
            allowed_ro = []
            denied = []
            # Do we deny everyone?
            if '@everyone' not in allow_names:
                if ctx.parsed.i_mean_it:
                    await channel.set_permissions(ctx.guild.default_role, overwrite=cfg.DefaultPermissions.deny())
                denied.append('@everyone')
            for r_name in allow_names:
                r = discord.utils.get(ctx.guild.roles, name=r_name)
                if not r:
                    ret_str += f'{r_name} not found in this guild\n'
                # Allow current role access
                if ch_def.read_only:
                    if ctx.parsed.i_mean_it:
                        await channel.set_permissions(r, overwrite=cfg.DefaultPermissions.read_only())
                    allowed_ro.append(r.name)
                else:
                    if ctx.parsed.i_mean_it:
                        await channel.set_permissions(r, overwrite=cfg.DefaultPermissions.read_write())
                    allowed_rw.append(r.name)
            ret_str += f'#{channel}\n'
            if allowed_rw:
                ret_str += f' Allow : {", ".join(allowed_rw)}\n'
            if allowed_ro:
                ret_str += f' RO    : {", ".join(allowed_ro)}\n'
            if denied:
                ret_str += f' Deny  : {", ".join(denied)}\n'

        for p in paginate(ret_str):
            await ctx.send(p)

    @commands.command(name='test')
    async def test(self, ctx: Context):
        return

    @commands.command()
    async def stats(self, ctx: Context):
        embed = emh.embed_init(self.bot, "System Stats")
        # CPU
        embed.title = "CPU"
        embed.description = f"Frequency: {psutil.cpu_freq().current:.0f}MHz\n"
        cpu_dict = {f"Core {i}": {"temp": 0, "usage": 0} for i in range(psutil.cpu_count())}
        for temp in psutil.sensors_temperatures()['coretemp']:
            if temp.label.startswith('Core'):
                cpu_dict[temp.label]['temp'] = f"{temp.current:.0f}C"
        cnt = 0
        for usage in psutil.cpu_percent(percpu=True):
            cpu_dict[f"Core {cnt}"]['usage'] = f"{usage:.0f}%"
            cnt += 1
        for k, v in cpu_dict.items():
            embed.description += f"{k}: {v['usage']}, {v['temp']}\n"
        # RAM
        vm = psutil.virtual_memory()
        ram_str = f"Total: {vm.total/1e6:,.0f}MB\nActive: {vm.active/1e6:,.0f}MB\nAvailable: {vm.available/1e6:,.0f}MB"
        embed.add_field(name="RAM", value=ram_str, inline=False)
        # Network
        net = psutil.net_io_counters(pernic=True)['eth0']
        net_str = f"Sent: {net.bytes_sent/1e3:,.0f}MB\nRecv: {net.bytes_recv/1e3:,.0f}MB"
        embed.add_field(name="Network", value=net_str, inline=False)
        dpy_latency = self.bot.latency*1000
        start = time.perf_counter()
        msg = await ctx.send(embed=embed)
        man_latency = (time.perf_counter()-start)*1000
        embed.add_field(name="Latency", value=f"d.py: {dpy_latency:.2f}ms.\nManual: {man_latency:.2f}ms.", inline=False)
        return await msg.edit(embed=embed)

    @commands.command()
    async def eval(self, ctx: Context, *, body: str):
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': ctx.channel,
            'author': ctx.author,
            'guild': ctx.guild,
            'message': ctx.message,
            '_': self._last_result
        }

        env.update(globals())

        # remove ```py\n```
        if body.startswith('```') and body.endswith('```'):
            body = '\n'.join(body.split('\n')[1:-1])
        # remove `foo`
        else:
            body = body.strip('` \n')

        stdout = StringIO()

        to_compile = f'async def func():\n{indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            await ctx.message.add_reaction('❎')
            return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')

        func = env['func']
        try:
            with redirect_stdout(stdout):
                await func()
        except Exception:
            value = stdout.getvalue()
            await ctx.message.add_reaction('❎')
            await ctx.send(f'```py\n{value}{format_exc()}\n```')
        else:
            value = stdout.getvalue()
            await ctx.message.add_reaction('✅')
            if value:
                if len(value) < 1950:
                    return await ctx.send(f'```py\n{value}\n```')

                ret_str = "```py\n"
                for word in value.split(" "):
                    tmp = word + " "
                    if len(ret_str) + len(tmp) > 1950:
                        await ctx.send(ret_str + "\n```")
                        ret_str = "```py\n"
                    ret_str += tmp
                return await ctx.send(f'{ret_str}\n```')

    @commands.command(name='delete')
    @commands.bot_has_permissions(manage_messages=True)
    async def delete(self, ctx: Context, *args: str):
        await ctx.message.delete()
        del_ids = []
        del_list = []
        for ID in re.findall(r'\d{18}', " ".join(args)):
            del_ids.append(int(ID))
        # No given IDs
        if len(del_ids) == 0:
            # Check if it is simply number of messages
            if len(args) == 1:
                try:
                    del_list = await ctx.channel.history(limit=int(args[0])).flatten()
                except ValueError:
                    return await ctx.send("Not a number.")
            elif len(args) == 2:
                try:
                    num_msg = int(args[0])
                    who = args[1]
                except ValueError:
                    num_msg = int(args[1])
                    who = args[0]
                found = False
                for m in ctx.guild.members:
                    if who.lower() in m.display_name.lower():
                        found = True
                        break
                if found is False:
                    return await ctx.send(f"{who} not found.")
                history = await ctx.channel.history(limit=50).flatten()
                for msg in history:
                    if num_msg <= 0:
                        break
                    if who.lower() in msg.author.display_name.lower():
                        num_msg -= 1
                        del_list.append(msg)
        # Removing until we reach given ID
        elif len(del_ids) == 1:
            async for message in ctx.channel.history(limit=100):
                del_list.append(message)
                if message.id == del_ids[0]:
                    break
        # Remove from ID 0 to ID 1
        elif len(del_ids) == 2:
            start = False
            async for message in ctx.channel.history(limit=100):
                if message.id == del_ids[0]:
                    start = True
                if start:
                    del_list.append(message)
                if message.id == del_ids[1]:
                    break
        else:
            return await ctx.send("Cannot parse input.")
        if len(del_list) > 10:
            msg = await ctx.send(f"Confirm deletion of {len(del_list)}.")
            react_emoji = '✅'
            await msg.add_reaction(react_emoji)

            def check(reaction, user):
                return reaction.message.id == msg.id and str(reaction.emoji) == react_emoji and \
                    user == ctx.author

            try:
                await self.bot.wait_for('reaction_add', timeout=5.0, check=check)
            except asyncio.TimeoutError:
                return await msg.delete()
            else:
                await ctx.channel.delete_messages(del_list)
                return await msg.delete()
        else:
            return await ctx.channel.delete_messages(del_list)

    @commands.command(name='move')
    @commands.bot_has_permissions(manage_messages=True)
    async def move(self, ctx: Context, where: str, who='any', msg_num: int = 1):
        channel = None
        for c in ctx.guild.text_channels:
            if where.lower() == c.name.lower():
                channel = c
                break
        if channel is None:
            return await ctx.send(f"Channel {where} not found.")
        if msg_num <= 0:
            return await ctx.send('Number of messages to be moved must be larger than 0.')
        embed = emh.embed_init(self.bot, "Move Messages")
        if who == 'any':
            history = await ctx.channel.history(limit=msg_num+1, oldest_first=True).flatten()
            for msg in history:
                msg_user_name = msg.author.display_name
                msg_time = msg.created_at.replace(tzinfo=timezone.utc).astimezone(tz=None).strftime("%H:%M - %d/%m/%y")
                if len(msg.embeds) != 0:
                    embed.add_field(name=f"{msg_user_name} {msg_time}", value=msg.embeds[0].url, inline=False)
                elif len(msg.attachments) != 0:
                    embed.add_field(name=f"{msg_user_name} {msg_time}", value=msg.attachments[0].url, inline=False)
                elif msg.content != '':
                    embed.add_field(name=f"{msg_user_name} {msg_time}", value=msg.content, inline=False)
            await channel.send(embed=embed)
            return await ctx.channel.delete_messages(history)
        else:
            found = False
            for m in ctx.guild.members:
                if who.lower() in m.display_name.lower():
                    found = True
                    break
            if found is False:
                return await ctx.send(f"{who} not found.")
            history = await ctx.channel.history(limit=50).flatten()
            msg_list = []
            for msg in history:
                if msg_num <= 0:
                    break
                msg_user_name = msg.author.display_name
                msg_time = msg.created_at.replace(tzinfo=timezone.utc).astimezone(tz=None).strftime("%H:%M - %d/%m/%y")
                if who.lower() in msg_user_name.lower():
                    msg_list.append(msg)
                    msg_num -= 1
                    if len(msg.embeds) != 0:
                        embed.add_field(name=f"{msg_user_name} {msg_time}", value=msg.embeds[0].url, inline=False)
                    elif len(msg.attachments) != 0:
                        embed.add_field(name=f"{msg_user_name} {msg_time}", value=msg.attachments[0].url, inline=False)
                    elif msg.content != '':
                        embed.add_field(name=f"{msg_user_name} {msg_time}", value=msg.content, inline=False)
            tmp = embed.fields
            tmp.reverse()
            embed.clear_fields()
            for f in tmp:
                embed.add_field(name=f.name, value=f.value, inline=False)
            await channel.send(embed=embed)
            return await ctx.channel.delete_messages(msg_list)

    @commands.group(name='reload')
    async def reload(self, _ctx: Context):
        self.logger.info('--- RELOAD START ---')
        self.logger.info(' -- Unloading cogs')
        self.bot.unload_all_extensions()
        self.logger.info(' -- Waiting for cleanup tasks')
        for task in self.bot.cleanup_tasks:
            if not task.done():
                self.logger.info(f' ---- Waiting for {task.get_coro()}')
            await task
        self.logger.info(' -- Loading cogs')
        self.bot.load_all_extensions(logger=self.logger)
        self.logger.info('--- RELOAD END ---')

    @reload.command(name='cog')
    async def reload_cog(self, ctx: Context, cog_name: str):
        try:
            self.bot.unload_extension(f'cogs.{cog_name}')
        except Exception as e:
            await ctx.send(f'Failed to unload {cog_name}: {str(e)}.')
            traceback.print_exc()
            return
        try:
            self.bot.load_extension(f'cogs.{cog_name}')
        except Exception as e:
            await ctx.send(f'Failed to load {cog_name}: {str(e)}.')
            traceback.print_exc()
            return

    @commands.command(name='quit', brief="Kills the bot")
    async def quit(self, _ctx: Context):
        return await self.bot.close()


def setup(bot):
    bot.add_cog(Admin(bot))
