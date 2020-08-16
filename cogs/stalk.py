import logging
from datetime import datetime, timezone

import dateparser
from discord.ext import commands

from mrbot import MrBot
from cogs.psql_collector import Collector
from ext.internal import Channel, Guild, Message, User
from ext.parsers import parsers
from ext.utils import human_timedelta_short, transparent_embed


class Stalk(commands.Cog, name="Stalk"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger_name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.stalk_dict = {
            'status': {
                'online': 'Went online {0}',
                'offline': 'Went offline {0}',
                'activity': 'Activity {0}',
                'mobile': 'On mobile? {0}',
            },
            'msg': {
                'time': 'Last message {0}',
                'channel': {
                    'name': '-- Channel: {0}',
                },
                'guild': {
                    'name': '-- Guild: {0}',
                },
            },
            'typed': {
                'time': 'Typed {0}',
                'channel': {
                    'name': '-- Channel: {0}',
                },
                'guild': {
                    'name': '-- Guild: {0}',
                },
            },
            'vc': {
                'start': 'Joined voice {0}',
                'stop': 'Left voice {0}',
                'channel': {
                    'name': '-- Channel: {0}',
                },
                'guild': {
                    'name': '-- Guild: {0}',
                },
            },
        }

    @parsers.command(
        name='stalk',
        brief='Display user stats',
        parser_args=[
            parsers.Arg('user', nargs='+', help='Filter by user'),
            parsers.Arg('--absolute', default=False, help='Use absolute times', action='store_true'),
        ],
    )
    async def stalk(self, ctx, *args: str):
        parsed = ctx.command.parser.parse_args(args)
        search_user = ' '.join(parsed.user)
        int_user = await User.from_search(ctx, search=search_user, with_nick=True)
        user = await int_user.to_discord(ctx)
        if not user:
            return await ctx.send(f'Cannot find user {search_user}')
        embed = transparent_embed()
        time_format = '%H:%M:%S - %d.%m.%y'
        embed.title = f"Stalking {user.name}#{user.discriminator}\n"
        if parsed.absolute:
            embed.set_footer(text="Time is in UTC, date format dd.mm.yy", icon_url=str(self.bot.user.avatar_url))
            embed.description = f"User created: {user.created_at.strftime(time_format)}\n"
            if hasattr(user, 'joined_at'):
                embed.description += f"Joined guild: {user.joined_at.strftime(time_format)}\n"
        else:
            embed.description = f"User created: {human_timedelta_short(user.created_at)}\n"
            if hasattr(user, 'joined_at'):
                embed.description += f"Joined guild: {human_timedelta_short(user.joined_at)}\n"
        embed.set_thumbnail(url=user.avatar_url)
        result_dict = {'status': dict(online=int_user.online, offline=int_user.offline,
                                      activity=int_user.activity, mobile='Yes' if int_user.mobile else 'No')}
        # Latest message
        async with self.bot.pool.acquire() as con:
            q = Message.make_psql_query(with_channel=True, with_guild=True, where='user_id=$1 ORDER BY time DESC LIMIT 1')
            res = await con.fetchrow(q, user.id)
            if res:
                msg: Message = await Message.from_psql_res(res)
                result_dict['msg'] = dict(time=msg.time, channel=msg.channel.to_dict(), guild=msg.guild.to_dict() if msg.guild else None)

        # Last typed
        async with self.bot.pool.acquire() as con:
            q = ('SELECT t.time, t.ch_id, t.guild_id, c.name AS ch_name, g.name AS guild_name '
                 f'FROM {Collector.psql_table_name_typed} t '
                 f'INNER JOIN {Channel.psql_table_name} c ON (t.ch_id = c.id) '
                 f'LEFT JOIN {Guild.psql_table_name} g ON (t.guild_id = g.id) '
                 'WHERE t.user_id=$1')
            res = await con.fetchrow(q, user.id)
            if res:
                channel: Channel = Channel.from_psql_res(res, prefix='ch_')
                guild: Guild = Guild.from_psql_res(res, prefix='guild_')
                result_dict['typed'] = dict(time=res['time'], channel=channel.to_dict(),
                                            guild=guild.to_dict() if guild else None)

        # Last voice channel
        async with self.bot.pool.acquire() as con:
            q = ('SELECT v.connect, v.disconnect, v.ch_id, v.guild_id, c.name AS ch_name, g.name AS guild_name '
                 f'FROM {Collector.psql_table_name_voice} v '
                 f'INNER JOIN {Channel.psql_table_name} c ON (v.ch_id = c.id) '
                 f'LEFT JOIN {Guild.psql_table_name} g ON (v.guild_id = g.id) '
                 'WHERE v.user_id=$1')
            res = await con.fetchrow(q, user.id)
            if res:
                channel: Channel = Channel.from_psql_res(res, prefix='ch_')
                guild: Guild = Guild.from_psql_res(res, prefix='guild_')
                result_dict['vc'] = dict(start=res['connect'], stop=res['disconnect'], channel=channel.to_dict(),
                                         guild=guild.to_dict() if guild else None)

        def walk_dict(in_dict, ref, ret_str: str):
            for k, v in in_dict.items():
                if v is None or k not in ref:
                    continue
                if isinstance(v, datetime):
                    if parsed.absolute:
                        ret_str += f'{ref[k].format(v.strftime(time_format))}\n'
                    else:
                        ret_str += f'{ref[k].format(human_timedelta_short(v))}\n'
                elif isinstance(v, str):
                    ret_str += f'{ref[k].format(v)}\n'
                else:
                    ret_str = walk_dict(v, ref[k], ret_str)
            return ret_str

        embed.description += walk_dict(result_dict, self.stalk_dict, '')
        await ctx.send(embed=embed)

    @parsers.command(
        name='cmdstats',
        brief='Display command stats',
        parser_args=[
            parsers.Arg('--user', '-u', default=None, nargs='*', help='Filter by user'),
            parsers.Arg('--since', '-s', default=None, help='Since relative time'),
            parsers.Arg('--limit', '-l', default=10, help='Max number of commands', type=int),
            parsers.Arg('--with-test', default=False, help='Include test channel', action='store_true'),
            parsers.Arg('--all-bots', default=False, help='Show commands by all bots', action='store_true'),
        ],
    )
    async def cmdstats(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        user = None
        q = 'SELECT name, COUNT(1) AS count FROM command_log '
        title = 'Top {0} most used commands'
        q_args = [parsed.limit]
        if parsed.user:
            search_user = ' '.join(parsed.user)
            user: User = await User.from_search(ctx, search=search_user)
            if not user:
                return await ctx.send(f'No user {search_user} found')
            q_args.append(user.id)
            if 'WHERE' not in q:
                q += f'WHERE user_id=${len(q_args)} '
            else:
                q += f'AND user_id=${len(q_args)} '
            title += f' by {user.display_name}'
        if parsed.since:
            since: datetime = dateparser.parse(parsed.since)
            if not since:
                return await ctx.send('Cannot parse date/time')
            title += f' since {parsed.since} ago'
            # Convert to UTC and make timezone naive again
            q_args.append(since.astimezone(tz=timezone.utc).replace(tzinfo=None))
            if 'WHERE' not in q:
                q += f'WHERE time > ${len(q_args)} '
            else:
                q += f'AND time > ${len(q_args)} '
        else:
            title += ' of all time'
        if not parsed.with_test:
            if 'WHERE' not in q:
                q += 'WHERE ch_id != 422473204515209226 '
            else:
                q += 'AND ch_id != 422473204515209226 '
        else:
            title += ', including test channel'
        if not parsed.all_bots:
            q_args.append(self.bot.user.id)
            if 'WHERE' not in q:
                q += f'WHERE bot_id=${len(q_args)} '
            else:
                q += f'AND bot_id=${len(q_args)} '
        else:
            title += ', including other bots'
        q += 'GROUP BY name ORDER BY count DESC LIMIT $1'
        async with self.bot.pool.acquire() as con:
            try:
                results = await con.fetch(q, *q_args)
            except Exception as e:
                await ctx.send(e)
                return
        if len(results) == 0:
            if user:
                await ctx.send(f'{user.display_name} has not used any commands.')
            else:
                await ctx.send('No commands have been used.')
            return
        ret_str = ''
        title = title.format(len(results))
        for i in range(len(results)):
            res = results[i]
            ret_str += f"{i+1}. {res['name']}: {res['count']}\n"
        if len(ret_str) + len(title) < 1950:
            await ctx.send(f"{title}\n```{ret_str}```")
        else:
            lines = ret_str.split('\n')
            ret_str = f"{title}\n```"
            for line in lines:
                if len(ret_str) + len(line) > 1950:
                    await ctx.send(f"{ret_str}```")
                    ret_str = "```"
                ret_str += f"{line} "
            await ctx.send(f"{ret_str}```")
        return


def setup(bot):
    bot.add_cog(Stalk(bot))
