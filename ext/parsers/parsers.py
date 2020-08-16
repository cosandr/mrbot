from argparse import ArgumentParser

from discord.ext import commands

from .errors import ArgParseError


class Arg:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class Command(commands.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parser_title = kwargs.pop('parser_title', None)
        if parser_title is None:
            parser_title = self.qualified_name
        self.parser = Arguments(prog=parser_title, add_help=False, allow_abbrev=False)
        parser_args = kwargs.pop('parser_args', None)
        if parser_args:
            if not isinstance(parser_args, (list, tuple)):
                raise TypeError('Parser args must be a list of `Arg` objects.')
            for arg in parser_args:
                self.parser.add_argument(*arg.args, **arg.kwargs)


class Group(commands.Group, Command):
    def command(self, *args, **kwargs):
        kwargs.setdefault('cls', Command)
        return super().command(*args, **kwargs)


class Arguments(ArgumentParser):
    def format_help(self):
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

    def error(self, message):
        raise ArgParseError(f"```\nArgument parsing failure caused by {str(message)}\n{self.format_help()}```")


def command(name=None, cls=Command, **attrs):
    def decorator(func):
        if isinstance(func, commands.Command):
            raise TypeError('Callback is already a command.')
        return cls(func, name=name, **attrs)

    return decorator


def group(name=None, **attrs):
    return command(name=name, cls=Group, **attrs)
