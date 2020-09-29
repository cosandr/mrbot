#!/usr/bin/env python3

import argparse
import os
from typing import Optional

import discord

from config import BotConfig
from mrbot import MrBot

CONFIG: Optional[BotConfig] = None
DSN_ENV = 'CONFIG_DSN'


def json_config(args: argparse.Namespace):
    global CONFIG
    CONFIG = BotConfig.from_json(configs=args.configs, guilds=args.guilds)


def psql_config(args: argparse.Namespace):
    global CONFIG
    if args.dsn:
        dsn = args.dsn
    elif args.env:
        dsn = os.getenv(DSN_ENV, '').strip()
    elif args.file:
        dsn = args.file.read().strip()
        args.file.close()
    else:
        raise RuntimeError('No DSN')

    import asyncio
    CONFIG = asyncio.get_event_loop().run_until_complete(BotConfig.from_psql(dsn=dsn, extra=args.extra))


parser = argparse.ArgumentParser(description='MrBot launcher')

grp_bot = parser.add_argument_group(title='Bot options')
grp_bot.add_argument('--command-prefix', type=str, default='!', help='Change command prefix')
grp_bot.add_argument('--owner-id', type=int, default=227847073607712768, help='Change owner ID')
grp_bot.add_argument('--ext', action='append', help='Override extensions that are loaded')
grp_bot.add_argument('--log-file', type=str, default='mrbot.log', help='Change log file')
grp_bot.add_argument('--debug', action='store_true', help='Log DEBUG to console')

subparsers = parser.add_subparsers(title='Config load', required=True)

parser_json = subparsers.add_parser('json-config', help='Start using JSON config')
parser_json.add_argument('-c', '--configs', action='append', required=True, help='Configs to load, can be used more than once')
parser_json.add_argument('-g', '--guilds', action='append', required=True, help='Guilds to load, can be used more than once')
parser_json.set_defaults(func=json_config)

parser_psql = subparsers.add_parser('psql-config', help='Start using PSQL config')
dsn_grp = parser_psql.add_mutually_exclusive_group()
dsn_grp.add_argument('-c', '--dsn', type=str,
                     help=f'PostgreSQL connection string, database must contain {BotConfig.psql_table_name} table')
dsn_grp.add_argument('--env', action='store_true', help=f'Read DSN from {DSN_ENV} variable')
dsn_grp.add_argument('-f', '--file', type=argparse.FileType('r'), help='Read DSN from file')
parser_psql.add_argument('-e', '--extra', action='append', default=[], help='Extra configs to load')
parser_psql.set_defaults(func=psql_config)


if __name__ == '__main__':
    _args = parser.parse_args()
    _args.func(_args)
    if not CONFIG:
        raise RuntimeError('No config loaded')
    bot = MrBot(
        config=CONFIG,
        command_prefix=_args.command_prefix,
        owner_id=_args.owner_id,
        extension_override=_args.ext,
        log_file_name=_args.log_file,
        log_debug=_args.debug,
        intents=discord.Intents.all(),
    )
    if _args.debug:
        bot.logger.debug('\n%s', CONFIG.safe_repr())
    bot.run()
