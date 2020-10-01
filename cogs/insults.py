import itertools
import logging
from typing import Union

from discord.ext import commands

from ext import parsers
from ext.internal import User
from ext.psql import create_table, try_run_query, ensure_foreign_key
from mrbot import MrBot


class Insults(commands.Cog, name="Insults"):
    psql_table_name = 'insults'
    psql_table = f"""
        CREATE TABLE IF NOT EXISTS {psql_table_name} (
            src_id     BIGINT REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            not_src_id BIGINT REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            dst_id     BIGINT NOT NULL REFERENCES {User.psql_table_name} (id) ON DELETE CASCADE,
            content    TEXT NOT NULL,
            CONSTRAINT chk_missing_src CHECK (src_id IS NOT NULL OR not_src_id IS NOT NULL),
            UNIQUE (src_id, not_src_id, dst_id)
        );
    """
    psql_all_tables = User.psql_all_tables.copy()
    psql_all_tables.update({(psql_table_name,): psql_table})

    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.bot.loop.create_task(self.async_init())

    async def async_init(self):
        await self.bot.connect_task
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await create_table(self.bot.pool, names, q, self.logger)

    @parsers.group(name='insult', aliases=['fuck'], brief='Are you mad at someone?', invoke_without_command=True)
    async def insult(self, ctx: commands.Context, victim: Union[int, str]):
        if victim == 'me':
            target = User.from_discord(ctx.author)
        elif victim == 'you':
            target = User.from_discord(self.bot.user)
        else:
            target = await User.from_search(ctx, victim, with_nick=True)
        if not target:
            return await ctx.send(f'No user {victim} found.')
        q = (f'SELECT content FROM {self.psql_table_name} WHERE '
             '(src_id=$1 OR src_id is NULL) '
             'AND (not_src_id is NULL OR not_src_id!=$1) '
             'AND dst_id=$2')
        res = await self.bot.pool.fetchval(q, ctx.author.id, target.id)
        if not res:
            return await ctx.send(f'You have no insult for {target.display_name}.')
        await ctx.send(res)

    @insult.command(
        name='add',
        brief='Add a new insult',
        parser_args=[
            parsers.Arg('victim', type=str, help='Victim name or ID'),
            parsers.Arg('content', nargs='+', help='Insult content'),
            parsers.Arg('-ns', '--not_source', type=str, help='Use this insult when it is not used by specified user'),
            parsers.Arg('-s', '--source', type=str, help='Use this insult when it is used by specified user', default='me'),
        ],
    )
    async def insult_add(self, ctx: commands.Context, *args):
        parsed = ctx.command.parser.parse_args(args)
        content = ' '.join(parsed.content)
        if parsed.not_source:
            src = await User.from_search(ctx, parsed.not_source, with_nick=True)
        elif parsed.source == 'me':
            src = User.from_discord(ctx.author)
        else:
            src = await User.from_search(ctx, parsed.source, with_nick=True)
        if not src:
            return await ctx.send(f'No user {parsed.source} found.')
        target = await User.from_search(ctx, parsed.victim, with_nick=True)
        if not target:
            return await ctx.send(f'No user {parsed.victim} found.')
        async with self.bot.pool.acquire() as con:
            src_str = 'src_id'
            if parsed.not_source:
                src_str = 'not_src_id'
            q = f'SELECT content FROM {self.psql_table_name} WHERE {src_str}=$1 AND dst_id=$2'
            q_args = [src.id, target.id]
            exists = await con.fetchval(q, *q_args)
            if exists:
                if parsed.not_source:
                    return await ctx.send((f'An insult for {target.display_name} when it is not used '
                                           f'by {src.display_name} already exists```\n{exists}```'))
                return await ctx.send((f'An insult for {target.display_name} when it is used '
                                       f'by {src.display_name} already exists```\n{exists}```'))
            q = f'INSERT INTO {self.psql_table_name} ({src_str}, dst_id, content) VALUES ($1, $2, $3)'
            q_args.append(content)
            await ensure_foreign_key(con, src, self.logger)
            await try_run_query(con, q, q_args, self.logger, user=target)
        if parsed.not_source:
            return await ctx.send((f'Added insult for {target.display_name} when it is not used '
                                   f'by {src.display_name}```\n{content}```'))
        return await ctx.send((f'Added insult for {target.display_name} when it is used '
                               f'by {src.display_name}```\n{content}```'))


def setup(bot):
    bot.add_cog(Insults(bot))
