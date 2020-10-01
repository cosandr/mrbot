from __future__ import annotations

from typing import TYPE_CHECKING, List, Set

from discord.ext import commands

from ext import parsers
from ext.context import Context
from ext.utils import find_similar_str

if TYPE_CHECKING:
    from mrbot import MrBot


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot: MrBot = bot
        self._original_help_command = bot.help_command
        bot.help_command = None

    def cog_unload(self):
        self.bot.help_command = self._original_help_command

    @parsers.command(
        name='help',
        hidden=True,
        parser_args=[
            parsers.Arg('commands', nargs='*', help='Command to get help for'),
            parsers.Arg('--hidden', default=False, action='store_true', help='Show hidden commands [owner only]'),
        ],
    )
    async def help(self, ctx: Context):
        search_commands: List[str] = ctx.parsed.commands
        show_hidden = False
        owner_called = await self.bot.is_owner(ctx.author)
        if ctx.parsed.hidden:
            if owner_called:
                show_hidden = True
            else:
                await ctx.send("Warning: Non-owner request for hidden commands ignored.")

        # Command requested
        if search_commands:
            req_cmd = search_commands[0]
            # Look for exact matches
            for cmd in self.bot.commands:
                if cmd.hidden and not owner_called:
                    continue
                # Check if command is found directly.
                if cmd.name == search_commands[0]:
                    if isinstance(cmd, parsers.Command):
                        cmd_help_msg = f'\n```{cmd.parser.format_help()}```'
                    else:
                        cmd_help_msg = cmd.signature if cmd.usage is None else "\n" + cmd.usage
                    # Sub-command was also requested, look for it directly.
                    if len(search_commands) > 1:
                        req_subcmd = search_commands[1]
                        if isinstance(cmd, commands.GroupMixin):
                            for sub_cmd in cmd.commands:
                                if sub_cmd.hidden and not owner_called:
                                    continue
                                if sub_cmd.name == req_subcmd:
                                    if isinstance(sub_cmd, parsers.Command):
                                        sub_help_msg = f'\n```{sub_cmd.parser.format_help()}```'
                                    else:
                                        sub_help_msg = sub_cmd.signature if sub_cmd.usage is None else "\n" + sub_cmd.usage
                                    return await ctx.send(f"`{ctx.prefix}{req_cmd} {req_subcmd}` usage:{sub_help_msg}")
                            # Didn't find sub-command for this group
                            return await ctx.send(f"No command `{ctx.prefix}{req_subcmd}` found in group `{req_cmd}`.")
                        return await ctx.send(f"`{ctx.prefix}{req_cmd}` is not a group, command usage:{cmd_help_msg}")
                    # No sub-command requested, add parser help if needed
                    # Check if command is group and also show all sub-commands.
                    if isinstance(cmd, commands.GroupMixin):
                        if cmd.invoke_without_command:
                            tmp = f"`{ctx.prefix}{req_cmd}` usage:{cmd_help_msg}\nSubcommands available:\n"
                        else:
                            tmp = f"`{ctx.prefix}{req_cmd}` cannot be called directly, subcommands available:\n"
                        for sub_cmd in cmd.commands:
                            if not owner_called and sub_cmd.hidden:
                                continue
                            sub_help_msg = sub_cmd.signature if not sub_cmd.brief else sub_cmd.brief
                            tmp += f"`{ctx.prefix}{req_cmd} {sub_cmd.name}`: {sub_help_msg}\n"
                        return await ctx.send(tmp)
                    else:
                        return await ctx.send(f"`{ctx.prefix}{req_cmd}` usage:\n{cmd_help_msg}")

            meant: Set[str] = set()
            check_against: List[str] = []
            # Look for loose matches
            for cmd in self.bot.commands:
                # Don't suggest hidden commands to regular users
                if not owner_called and cmd.hidden:
                    continue
                check_against.append(cmd.name)
                # Include group in suggestion
                if isinstance(cmd, commands.GroupMixin):
                    group_check = [c.name for c in cmd.commands]
                    for check in search_commands:
                        # Include main command name in suggestions
                        for m in find_similar_str(check, group_check):
                            meant.add(f'{cmd.name} {m}')
                # Check regular commands
            for check in search_commands:
                for m in find_similar_str(check, check_against):
                    meant.add(m)
                # Once we get here, we have a list of suggestions, format and return it.
            if not meant:
                return await ctx.send(f'`{ctx.prefix}{req_cmd}` not found, see {ctx.prefix}help.')
            return await ctx.send(f"`{ctx.prefix}{req_cmd}` not found, did you mean: {', '.join(meant)}?")
        # No commands, print all
        else:
            # Otherwise continue to print all of them.
            # Storing each cog and its commands in a list.
            cmd_dict = {cog: [] for cog in self.bot.cogs}
            longest_name = 0
            for cmd in self.bot.commands:
                if cmd.hidden and show_hidden:
                    cmd_dict[cmd.cog_name].append({'name': cmd.name + '*', 'brief': cmd.brief, 'subcmds': []})
                elif not cmd.hidden:
                    cmd_dict[cmd.cog_name].append({'name': cmd.name, 'brief': cmd.brief, 'subcmds': []})
                else:
                    continue
                if len(cmd.name) > longest_name:
                    longest_name = len(cmd.name)
                if isinstance(cmd, commands.GroupMixin):
                    for sub_cmd in cmd.commands:
                        if sub_cmd.hidden and show_hidden:
                            cmd_dict[cmd.cog_name][-1]['subcmds'].append(
                                {'name': sub_cmd.name + '*', 'brief': sub_cmd.brief})
                        elif not sub_cmd.hidden:
                            cmd_dict[cmd.cog_name][-1]['subcmds'].append({'name': sub_cmd.name, 'brief': sub_cmd.brief})
                        else:
                            continue
                        if len(sub_cmd.name) > longest_name:
                            longest_name = len(sub_cmd.name)
            ret_str = f"See {ctx.prefix}help [cmd] for more detailed help.\n"
            longest_name += 3
            for cog in sorted(cmd_dict):
                cmds = cmd_dict[cog]
                if len(cmds) == 0:
                    continue
                tmp = f"--- {cog} Module ---\n"
                for cmd in sorted(cmds, key=lambda c: c['name']):
                    tmp += f"-{cmd['name']:{longest_name}s}{cmd['brief']}\n"
                    # Add subcommands
                    for sub_cmd in sorted(cmd['subcmds'], key=lambda sc: sc['name']):
                        tmp += f"--{sub_cmd['name']:{longest_name - 1}s}{sub_cmd['brief']}\n"
                if len(ret_str) + len(tmp) > 1900:
                    await ctx.send("```" + ret_str + "```")
                    ret_str = ''
                ret_str += tmp
            return await ctx.send("```" + ret_str + "```")
