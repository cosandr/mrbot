import asyncio
import logging
import re
from contextlib import asynccontextmanager
from time import perf_counter
from traceback import print_exception
from typing import Union, Iterable

import asyncpg

from ext.internal import User, Guild, Message, Channel

re_key = re.compile(r'Key.*is not present in table \"(\w+)\"\.')


async def create_table(con: Union[asyncpg.pool.Pool, asyncpg.Connection], name: Union[str, Iterable],
                       query: Union[str, Iterable], logger: logging.Logger = None, prefix: str = ''):
    """
    Creates table called `table` if not found according to the given definition.

    :param con: Connection pool to use
    :param name: Table name(s) to check
    :param query: SQL query to run if at least one of the provided names is not found
    :param logger: Logger to use, will print if not provided
    :param prefix: Prefix to use for logging
    """
    start = perf_counter()
    existing = []
    missing = []
    if isinstance(name, str):
        name = (name,)
    if isinstance(query, str):
        query = (query,)
    # Check if all tables already exist
    q = "SELECT to_regclass($1)"
    for n in name:
        result = await con.fetchval(q, n)
        if result is None:
            missing.append(n)
        else:
            existing.append(n)
    status = f'{prefix}{", ".join(existing) if existing else "No"} tables OK'
    if missing:
        for q in query:
            await con.execute(q)
        if existing:
            status += f', missing tables {", ".join(missing)} created in {((perf_counter() - start) * 1000):.3f}ms.'
        else:
            status = f'{prefix}missing tables {", ".join(missing)} created in {((perf_counter() - start) * 1000):.3f}ms.'
    if logger and missing:
        logger.warning(status)
    elif logger and not missing:
        logger.debug(status)
    else:
        print(status)


@asynccontextmanager
async def pg_connection(dsn: str):
    """Async context manager for PSQL database connection"""
    con = await asyncpg.connect(dsn=dsn)
    try:
        yield con
    finally:
        await con.close()


async def try_run_query(con: asyncpg.Connection, q: str, q_args: Iterable, logger: logging.Logger, msg: Message = None,
                        user: User = None, channel: Channel = None, guild: Guild = None, retries=3, retry_coro=None):
    """Try to run INSERT/UPDATE query, attempts to add missing foreign keys if relevant object is available"""
    for _ in range(retries):
        try:
            await con.execute(q, *q_args)
            return True
        except asyncpg.exceptions.InterfaceError as e:
            logger.error('Connection interface error, will retry: %s', str(e))
            continue
        except asyncpg.exceptions.ConnectionDoesNotExistError:
            if asyncio.iscoroutine(retry_coro):
                await retry_coro
                await asyncio.sleep(0.1)
                continue
            raise
        except asyncpg.exceptions.UniqueViolationError as e:
            logger.warning(str(e))
            return False
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            should_continue = await try_foreign_key_add(con, e, logger, msg, user, channel, guild)
            if should_continue:
                continue
            return
        except Exception as e:
            debug_query(q, q_args, e)
            logger.error('Connection exec failed: %s', str(e))
            if asyncio.iscoroutine(retry_coro):
                await retry_coro
                await asyncio.sleep(0.1)
                continue
            raise


async def try_foreign_key_add(con: asyncpg.Connection, e: asyncpg.exceptions.ForeignKeyViolationError, logger: logging.Logger,
                              msg: Message = None, user: User = None, channel: Channel = None, guild: Guild = None) -> bool:
    """Try to add missing foreign key, return False if caller must return or True if they should continue"""
    m = re_key.match(e.detail)
    if not m:
        logger.error('Cannot detect which foreign key is missing: %s', str(e))
        return False
    if msg:
        if not channel:
            channel = msg.channel
        if not guild:
            guild = msg.guild
    if not guild and channel:
        guild = channel.guild
    if m.group(1) == User.psql_table_name:
        if msg and not user:
            user = msg.author
        if not user:
            logger.error('User is missing and cannot be added')
            return False
        logger.warning('User `%s` is missing, will try to add', str(user))
        await ensure_foreign_key(con, user, logger)
        # Add nick if we have guild
        if guild:
            q, q_args = user.to_psql_nick(guild.id)
            try:
                await con.execute(q, *q_args)
            except asyncpg.exceptions.ForeignKeyViolationError:
                # This means the guild is missing, add it and try again
                ok = await ensure_foreign_key(con, guild, logger)
                if ok:
                    await con.execute(q, *q_args)
                else:
                    return False
            logger.info('Updated user nick %s in guild %s', str(user), str(guild))
        return True
    if m.group(1) == Guild.psql_table_name:
        if not guild:
            logger.error('Guild is missing and cannot be added')
            return False
        logger.warning('Guild `%s` is missing, will try to add', str(guild))
        await ensure_foreign_key(con, guild, logger)
        return True
    if m.group(1) == Channel.psql_table_name:
        if not channel:
            logger.error('Channel is missing and cannot be added')
            return False
        logger.warning('Channel `%s` is missing, will try to add', str(channel))
        try:
            await ensure_foreign_key(con, channel, logger)
        except asyncpg.exceptions.ForeignKeyViolationError:
            if guild:
                # This means the guild is missing, add it and try again
                ok = await ensure_foreign_key(con, guild, logger)
                if ok:
                    return await ensure_foreign_key(con, channel, logger)
                return False
            else:
                logger.error('Cannot add channel `%s`, guild is missing', str(channel))
                return False
        return True
    logger.error('Unknown foreign key `%s` is missing', m.group(1))
    return False


async def ensure_foreign_key(con: asyncpg.Connection, obj, logger: logging.Logger):
    """Ensure foreign key is in PSQL table, return True on success"""
    if not obj or not isinstance(obj, (User, Guild, Message, Channel)):
        logger.error('foreign key: object parameter missing or wrong type %s', type(obj))
        return False
    r = await con.fetchval(f'SELECT EXISTS(SELECT 1 FROM {obj.psql_table_name} WHERE id=$1)', obj.id)
    obj_name = obj.__class__.__name__
    if r:
        logger.debug('foreign key of type %s is OK: %s', obj_name, str(obj))
        return True
    q, q_args = obj.to_psql()
    try:
        await con.execute(q, *q_args)
        logger.info('added missing foreign key of type %s: %s', obj_name, str(obj))
        return True
    except Exception as e:
        logger.error('failed to add missing foreign key of type %s (%s): %s', obj_name, str(obj), str(e))
        return False


def debug_query(q: str, q_args: Union[tuple, list], e: Exception):
    """
    Prints debug PSQL query information such as query, filled in query and all arguments.
    Parameters
    ----------
    q: `str`
        Original SQL query
    q_args: `list-like`
        Query arguments as a list or tuple
    e: `Exception`
        The Exception that was raised
    """
    def expand_args(args):
        for i in range(len(args)):
            print(f"{i+1}: {args[i]}")

    print("### PSQL FAILURE ###")
    print_exception(type(e), e, e.__traceback__)
    print(f"--- QUERY\n{q}\n--- FILLED Q\n{fill_query(q, q_args)}\n--- ARGS")
    expand_args(q_args)


def fill_query(q: str, args: list) -> str:
    """Returns PSQL query with filled in values"""
    comp_q = q
    for i in range(len(args)):
        comp_q = comp_q.replace(f"${i+1}", f"{{{i}}}")
    return comp_q.format(*args)
