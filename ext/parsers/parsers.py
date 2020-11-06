import argparse
import inspect
from typing import Callable, Union

from discord.ext import commands

from ext.context import Context
from .errors import ArgParseError, ArgParseMessageError


class Arg:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class Command(commands.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parser_title = kwargs.pop('parser_title', self.qualified_name)
        self.parser_late_callback = kwargs.pop('parser_late_callback', False)
        cb = kwargs.pop('parser_callback', None)
        if self.parser_late_callback or cb:
            add_help = True
        else:
            add_help = False
        self.parser = ArgumentParser(prog=parser_title, add_help=add_help, allow_abbrev=False)
        if cb:
            self.parser_callback(cb)
            return
        if self.parser_late_callback:
            return
        parser_args = kwargs.pop('parser_args', None)
        if parser_args:
            if not isinstance(parser_args, (list, tuple)):
                raise TypeError('Parser args must be a list of `Arg` objects.')
            for arg in parser_args:
                self.parser.add_argument(*arg.args, **arg.kwargs)

    async def prepare(self, ctx: Context) -> None:
        await super().prepare(ctx)
        if self.parser_late_callback:
            return
        if self.clean_params:
            raise TypeError('Parser command should not have any arguments defined')
        if not isinstance(self.parser, ArgumentParser):
            raise TypeError(f'Command parser is of type {type(self.parser)} instead of ArgumentParser')
        args = ctx.view.buffer[ctx.view.index:ctx.view.end].split()
        ctx.parsed = self.parser.parse_args(args)
        if func := getattr(ctx.parsed, 'func', None):
            await self.parser_func(ctx, func)

    @staticmethod
    async def parser_func(ctx: Context, func: Union[Callable, str]):
        """Call the sub-parser function or coroutine"""
        def check_param():
            if len(inspect.signature(func).parameters) != 1:
                raise TypeError('Parser function must have a single parameter, the Context')

        if isinstance(func, str):
            if not ctx.cog:
                raise TypeError('Function names must be used from cogs')
            if f := getattr(ctx.cog, func, None):
                func = f
            else:
                raise TypeError(f'Cannot find {func} in cog {ctx.cog.name}')
        if inspect.iscoroutine(func) or inspect.iscoroutinefunction(func):
            check_param()
            await func(ctx)
        elif inspect.isfunction(func) or inspect.ismethod(func):
            check_param()
            func(ctx)
        else:
            raise TypeError('Parser function must be a function, method or coroutine')

    def parser_callback(self, cb: Callable):
        """Call the parser callback"""
        if isinstance(cb, staticmethod):
            cb = cb.__func__
        if not inspect.ismethod(cb) and not inspect.isfunction(cb):
            raise TypeError('Parser callback must be a function or method')
        if len(inspect.signature(cb).parameters) != 1:
            raise TypeError('Parser callback must have a single parameter, the parser object')
        cb(self.parser)


class Group(commands.Group, Command):
    def command(self, *args, **kwargs):
        kwargs.setdefault('cls', Command)
        return super().command(*args, **kwargs)


class ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        raise ArgParseMessageError(f'```{message}```')

    def error(self, message):
        raise ArgParseError(f"```\nArgument parsing failure caused by {str(message)}\n{self.format_help()}```")

    def exit(self, *args, **kwargs):
        return

    # noinspection PyProtectedMember
    def format_help(self):
        if self.add_help:
            return super().format_help()
        ret_str = f"{self.prog}\n\n"
        had_nargs = False
        longest = 0
        # Find longest arg
        for action_group in self._action_groups:
            actions = action_group._group_actions
            if len(actions) > 0:
                for act in actions:
                    if len(act.option_strings) >= 2:
                        tmp = len(act.option_strings[1]) + len(act.dest) + 5
                    else:
                        tmp = len(act.dest) + 2
                    if tmp > longest:
                        longest = tmp
        longest += 3
        # Format string
        for action_group in self._action_groups:
            actions = action_group._group_actions
            if len(actions) > 0:
                ret_str += f"{action_group.title}\n"
                for act in actions:
                    tmp = ""
                    # Positional, no --
                    if len(act.option_strings) == 0:
                        tmp += f"  {act.dest}"
                    elif len(act.option_strings) > 0:
                        tmp += f"{act.option_strings[0]}"
                    if len(act.option_strings) >= 2:
                        tmp += f" [{act.option_strings[1]}]"
                    if act.nargs:
                        had_nargs = True
                        tmp += "*"
                    if act.help:
                        ret_str += f"{tmp:{longest}s}{act.help}\n"
                    else:
                        ret_str += f"{tmp}\n"
        if had_nargs:
            ret_str += "Args with * may have spaces"
        return ret_str


def command(name=None, cls=Command, **attrs):
    def decorator(func):
        if isinstance(func, commands.Command):
            raise TypeError('Callback is already a command.')
        return cls(func, name=name, **attrs)

    return decorator


def group(name=None, **attrs):
    return command(name=name, cls=Group, **attrs)
