import asyncio
import itertools
import json
import os
import re

import asyncpg

from cogs.psql_collector import Collector
from cogs.stars import Stars
from cogs.todo import Todo
from config import BotConfig
from ext.internal import Message, User
from .test_bot import TestBot
from .test_plots import TestPlot


class Test:
    def __init__(self, loop: asyncio.AbstractEventLoop, bot: TestBot):
        self.loop = loop
        self.bot = bot
        # Collector depends on users, channels, guilds and messages as well
        self.all_tables = Collector.psql_all_tables.copy()
        self.all_tables.update(Todo.psql_all_tables)
        self.all_tables.update(Stars.psql_all_tables)

    async def run(self):
        # await self.clear_tables(self.bot.pool, drop=True)
        # await self.create_all_tables()
        # await self.copy_tables(num_cons=24, max_elem=1000)
        # await self.insert_config_json_psql()
        # config = await BotConfig.from_psql(dsn=self.bot.config.psql.main, extra=['test', 'windows'])
        # print(config.safe_repr())
        # await self.run_plot()
        await self.asyncpg_tz_converter()

    async def asyncpg_tz_converter(self):
        from datetime import datetime, timezone

        async with self.bot.pool.acquire() as con:
            await con.execute("CREATE TABLE IF NOT EXISTS test_tz(aware timestamptz, naive timestamp, converted timestamptz)")
            naive = datetime.utcnow()
            aware = datetime.now(tz=timezone.utc)
            converted = datetime.utcnow()
            await con.execute("INSERT INTO test_tz (aware, naive, converted) VALUES ($1, $2, $3)", aware, naive, converted)
            aware_new, naive_new, converted_new = await con.fetchrow("SELECT aware, naive, converted FROM test_tz WHERE naive=$1", naive)
        print(aware_new)
        print(naive_new)
        print(converted_new)

    async def insert_config_json_psql(self, live=False):
        """Reads and inserts all .json files in config directory"""
        con = self.bot.pool_live if live else self.bot.pool
        # Ensure table exists
        status = await con.execute(BotConfig.psql_table)
        print(status)
        for file in os.listdir('config'):
            file_name, file_ext = os.path.splitext(file)
            if file_ext != '.json':
                continue
            name_split = file_name.split('_', 1)
            data_type = name_split[0]
            name = name_split[1] if len(name_split) > 1 else 'main'
            with open(os.path.join('config', file), 'r') as f:
                data = json.load(f)
            q = (f'INSERT INTO {BotConfig.psql_table_name} '
                 '(name, type, data) VALUES ($1, $2, $3) '
                 'ON CONFLICT (name, type) DO UPDATE SET data=$3')
            status = await con.execute(q, name, data_type, json.dumps(data))
            print(status)

    def test_emoji(self):
        from emoji import EMOJI_DATA
        all_emoji = set(EMOJI_DATA.keys())
        test_data = {
            r"no emoji here": 0,           # None
            r"Hello 🏃‍♂️": 1,              # Man running
            r"Multiple 🏃‍♂️ emoji 😂": 2,  # Man running, tears of joy
            r"Germany 🇩🇪": 1,              # German flag
            r"👌👀👌👀👌👀👌👀👌👀 good shit go౦ԁ sHit👌 thats ✔ some good👌👌shit right👌👌there👌👌👌 right✔there ✔✔if i do ƽaү so my self 💯 i say so 💯 thats what im talking about right there right there (chorus: ʳᶦᵍʰᵗ ᵗʰᵉʳᵉ) mMMMMᎷМ💯 👌👌 👌НO0ОଠOOOOOОଠଠOoooᵒᵒᵒᵒᵒᵒᵒᵒᵒ👌 👌👌 👌 💯 👌 👀 👀 👀 👌👌Good shit": 39,
        }
        for test_str, expected in test_data.items():
            actual_per_letter = 0
            for word in test_str:
                if word in all_emoji:
                    actual_per_letter += 1
                    print(f'Per letter: {word}')
            actual_per_emoji = 0
            for em in all_emoji:
                if em in test_str:
                    actual_per_emoji += 1
                    print(f'Per emoji: {em}')
            actual_re = 0
            # re_emoji = re.compile(f'({"|".join(all_emoji)})')
            re_emoji = re.compile('(?:\U0001f1e6[\U0001f1e8-\U0001f1ec\U0001f1ee\U0001f1f1\U0001f1f2\U0001f1f4\U0001f1f6-\U0001f1fa\U0001f1fc\U0001f1fd\U0001f1ff])|(?:\U0001f1e7[\U0001f1e6\U0001f1e7\U0001f1e9-\U0001f1ef\U0001f1f1-\U0001f1f4\U0001f1f6-\U0001f1f9\U0001f1fb\U0001f1fc\U0001f1fe\U0001f1ff])|(?:\U0001f1e8[\U0001f1e6\U0001f1e8\U0001f1e9\U0001f1eb-\U0001f1ee\U0001f1f0-\U0001f1f5\U0001f1f7\U0001f1fa-\U0001f1ff])|(?:\U0001f1e9[\U0001f1ea\U0001f1ec\U0001f1ef\U0001f1f0\U0001f1f2\U0001f1f4\U0001f1ff])|(?:\U0001f1ea[\U0001f1e6\U0001f1e8\U0001f1ea\U0001f1ec\U0001f1ed\U0001f1f7-\U0001f1fa])|(?:\U0001f1eb[\U0001f1ee-\U0001f1f0\U0001f1f2\U0001f1f4\U0001f1f7])|(?:\U0001f1ec[\U0001f1e6\U0001f1e7\U0001f1e9-\U0001f1ee\U0001f1f1-\U0001f1f3\U0001f1f5-\U0001f1fa\U0001f1fc\U0001f1fe])|(?:\U0001f1ed[\U0001f1f0\U0001f1f2\U0001f1f3\U0001f1f7\U0001f1f9\U0001f1fa])|(?:\U0001f1ee[\U0001f1e8-\U0001f1ea\U0001f1f1-\U0001f1f4\U0001f1f6-\U0001f1f9])|(?:\U0001f1ef[\U0001f1ea\U0001f1f2\U0001f1f4\U0001f1f5])|(?:\U0001f1f0[\U0001f1ea\U0001f1ec-\U0001f1ee\U0001f1f2\U0001f1f3\U0001f1f5\U0001f1f7\U0001f1fc\U0001f1fe\U0001f1ff])|(?:\U0001f1f1[\U0001f1e6-\U0001f1e8\U0001f1ee\U0001f1f0\U0001f1f7-\U0001f1fb\U0001f1fe])|(?:\U0001f1f2[\U0001f1e6\U0001f1e8-\U0001f1ed\U0001f1f0-\U0001f1ff])|(?:\U0001f1f3[\U0001f1e6\U0001f1e8\U0001f1ea-\U0001f1ec\U0001f1ee\U0001f1f1\U0001f1f4\U0001f1f5\U0001f1f7\U0001f1fa\U0001f1ff])|\U0001f1f4\U0001f1f2|(?:\U0001f1f4[\U0001f1f2])|(?:\U0001f1f5[\U0001f1e6\U0001f1ea-\U0001f1ed\U0001f1f0-\U0001f1f3\U0001f1f7-\U0001f1f9\U0001f1fc\U0001f1fe])|\U0001f1f6\U0001f1e6|(?:\U0001f1f6[\U0001f1e6])|(?:\U0001f1f7[\U0001f1ea\U0001f1f4\U0001f1f8\U0001f1fa\U0001f1fc])|(?:\U0001f1f8[\U0001f1e6-\U0001f1ea\U0001f1ec-\U0001f1f4\U0001f1f7-\U0001f1f9\U0001f1fb\U0001f1fd-\U0001f1ff])|(?:\U0001f1f9[\U0001f1e6\U0001f1e8\U0001f1e9\U0001f1eb-\U0001f1ed\U0001f1ef-\U0001f1f4\U0001f1f7\U0001f1f9\U0001f1fb\U0001f1fc\U0001f1ff])|(?:\U0001f1fa[\U0001f1e6\U0001f1ec\U0001f1f2\U0001f1f8\U0001f1fe\U0001f1ff])|(?:\U0001f1fb[\U0001f1e6\U0001f1e8\U0001f1ea\U0001f1ec\U0001f1ee\U0001f1f3\U0001f1fa])|(?:\U0001f1fc[\U0001f1eb\U0001f1f8])|\U0001f1fd\U0001f1f0|(?:\U0001f1fd[\U0001f1f0])|(?:\U0001f1fe[\U0001f1ea\U0001f1f9])|(?:\U0001f1ff[\U0001f1e6\U0001f1f2\U0001f1fc])|(?:\U0001f3f3\ufe0f\u200d\U0001f308)|(?:\U0001f441\u200d\U0001f5e8)|(?:[\U0001f468\U0001f469]\u200d\u2764\ufe0f\u200d(?:\U0001f48b\u200d)?[\U0001f468\U0001f469])|(?:(?:(?:\U0001f468\u200d[\U0001f468\U0001f469])|(?:\U0001f469\u200d\U0001f469))(?:(?:\u200d\U0001f467(?:\u200d[\U0001f467\U0001f466])?)|(?:\u200d\U0001f466\u200d\U0001f466)))|(?:(?:(?:\U0001f468\u200d\U0001f468)|(?:\U0001f469\u200d\U0001f469))\u200d\U0001f466)|[\u2194-\u2199]|[\u23e9-\u23f3]|[\u23f8-\u23fa]|[\u25fb-\u25fe]|[\u2600-\u2604]|[\u2638-\u263a]|[\u2648-\u2653]|[\u2692-\u2694]|[\u26f0-\u26f5]|[\u26f7-\u26fa]|[\u2708-\u270d]|[\u2753-\u2755]|[\u2795-\u2797]|[\u2b05-\u2b07]|[\U0001f191-\U0001f19a]|[\U0001f1e6-\U0001f1ff]|[\U0001f232-\U0001f23a]|[\U0001f300-\U0001f321]|[\U0001f324-\U0001f393]|[\U0001f399-\U0001f39b]|[\U0001f39e-\U0001f3f0]|[\U0001f3f3-\U0001f3f5]|[\U0001f3f7-\U0001f3fa]|[\U0001f400-\U0001f4fd]|[\U0001f4ff-\U0001f53d]|[\U0001f549-\U0001f54e]|[\U0001f550-\U0001f567]|[\U0001f573-\U0001f57a]|[\U0001f58a-\U0001f58d]|[\U0001f5c2-\U0001f5c4]|[\U0001f5d1-\U0001f5d3]|[\U0001f5dc-\U0001f5de]|[\U0001f5fa-\U0001f64f]|[\U0001f680-\U0001f6c5]|[\U0001f6cb-\U0001f6d2]|[\U0001f6e0-\U0001f6e5]|[\U0001f6f3-\U0001f6f6]|[\U0001f910-\U0001f91e]|[\U0001f920-\U0001f927]|[\U0001f933-\U0001f93a]|[\U0001f93c-\U0001f93e]|[\U0001f940-\U0001f945]|[\U0001f947-\U0001f94b]|[\U0001f950-\U0001f95e]|[\U0001f980-\U0001f991]|\u00a9|\u00ae|\u203c|\u2049|\u2122|\u2139|\u21a9|\u21aa|\u231a|\u231b|\u2328|\u23cf|\u24c2|\u25aa|\u25ab|\u25b6|\u25c0|\u260e|\u2611|\u2614|\u2615|\u2618|\u261d|\u2620|\u2622|\u2623|\u2626|\u262a|\u262e|\u262f|\u2660|\u2663|\u2665|\u2666|\u2668|\u267b|\u267f|\u2696|\u2697|\u2699|\u269b|\u269c|\u26a0|\u26a1|\u26aa|\u26ab|\u26b0|\u26b1|\u26bd|\u26be|\u26c4|\u26c5|\u26c8|\u26ce|\u26cf|\u26d1|\u26d3|\u26d4|\u26e9|\u26ea|\u26fd|\u2702|\u2705|\u270f|\u2712|\u2714|\u2716|\u271d|\u2721|\u2728|\u2733|\u2734|\u2744|\u2747|\u274c|\u274e|\u2757|\u2763|\u2764|\u27a1|\u27b0|\u27bf|\u2934|\u2935|\u2b1b|\u2b1c|\u2b50|\u2b55|\u3030|\u303d|\u3297|\u3299|\U0001f004|\U0001f0cf|\U0001f170|\U0001f171|\U0001f17e|\U0001f17f|\U0001f18e|\U0001f201|\U0001f202|\U0001f21a|\U0001f22f|\U0001f250|\U0001f251|\U0001f396|\U0001f397|\U0001f56f|\U0001f570|\U0001f587|\U0001f590|\U0001f595|\U0001f596|\U0001f5a4|\U0001f5a5|\U0001f5a8|\U0001f5b1|\U0001f5b2|\U0001f5bc|\U0001f5e1|\U0001f5e3|\U0001f5e8|\U0001f5ef|\U0001f5f3|\U0001f6e9|\U0001f6eb|\U0001f6ec|\U0001f6f0|\U0001f930|\U0001f9c0|[#|0-9]\u20e3')
            for m in re_emoji.finditer(test_str):
                actual_re += 1
                print(f'Regex emoji: {m.group()}')
            print(f'-- {test_str} --\nExpected {expected}, letter-by-letter {actual_per_letter}, per emoji {actual_per_emoji}, regex: {actual_re}')

    def test_find_closest_match(self):
        from ext.utils import find_closest_match
        names = ['Andrei', 'dre', 'dr', 'drench', 'ranch', 'never', 'Andrei Costescu',
                 'Andrei The Meme Lord That really loves memes', 'meme lover',
                 'lover of memes', 'mems']
        for name in ('drei', 'memes', 'love', 'ranch', 'cost', '&'*10):
            print('Closest match for {} is {}'.format(name, find_closest_match(name, names)))

    async def run_plot(self):
        t = TestPlot(self.bot)
        await t.msg_plot()

    async def count_emojis(self, pool):
        """Descending order of messages containing emojis in message log"""
        q = f"SELECT u.name, m.content FROM {Message.psql_table_name} m INNER JOIN {User.psql_table_name} u ON (m.user_id = u.id)"
        async with pool.acquire() as con:
            res = await con.fetch(q)
        em_count = {}
        for r in res:
            if not r['content']:
                continue
            match = re.search(r'<:(?P<em>\w+):\d{18}>', r['content'])
            if match:
                em = match.group('em')
                if em not in em_count:
                    em_count[em] = 1
                else:
                    em_count[em] += 1
        for k in sorted(em_count, key=em_count.get, reverse=True):
            print(f'{k}: {em_count[k]}')
        print(len(em_count))

    async def create_all_tables(self):
        from ext.psql import create_table
        names = itertools.chain(*self.all_tables.keys())
        q = "".join(self.all_tables.values())
        await create_table(self.bot.pool, names, q)

    # noinspection PyProtectedMember
    async def copy_tables(self, num_cons: int = 12, max_elem=None):
        src_pool = self.bot.pool_live
        dst_pool = self.bot.pool
        # TODO: Use con._params
        confirm = (f'CONFIRM COPY FROM {src_pool._working_params.database} AS {src_pool._working_params.user} '
                   f'TO {dst_pool._working_params.database} AS {dst_pool._working_params.user}? ')
        if input(confirm) != 'y':
            return
        arg_dict = {}
        for name in itertools.chain(*self.all_tables.keys()):
            q = f'SELECT * FROM {name}'
            if max_elem:
                q += f' LIMIT {max_elem}'
            old = await src_pool.fetch(q)
            if not old:
                continue
            arg_list = []
            for r in old:
                arg_list.append(list(r.values()))
            dollars = ','.join([f'${i}' for i in range(1, len(old[0])+1)])
            arg_names = ','.join(old[0].keys())
            arg_dict[name] = dict(q=f"INSERT INTO {name} ({arg_names}) VALUES ({dollars}) ON CONFLICT DO NOTHING",
                                  args=arg_list)

        connections = []
        print(f'Acquiring {num_cons} connections')
        for n in range(num_cons):
            connections.append(await asyncpg.connect(dsn=dst_pool._connect_args[0]))
        for name, value in arg_dict.items():
            start = 0
            i = 0
            tasks = []
            q = value['q']
            args = value['args']
            if len(args) <= len(connections) * 2:
                print(f'Copying {name} with one connection {len(args)} entries')
                await connections[0].executemany(q, args)
                continue
            for con in connections:
                end = start + int(len(args) / num_cons)
                if i < len(args) % num_cons:
                    end += 1
                print(f'Copying {name} with connection {i} from {start} to {end}')
                tasks.append(loop.create_task(con.executemany(q, args[start:end])))
                start = end
                i += 1
            print('Waiting for tasks')
            await asyncio.gather(*tasks)
        for con in connections:
            await con.close()

    async def clear_tables(self, src_pool: asyncpg.pool.Pool, drop=False):
        names = tuple(itertools.chain(*self.all_tables.keys()))
        # noinspection PyProtectedMember
        confirm = (f'CONFIRM {"DROPPING" if drop else "CLEARING"} {", ".join(names)} FROM {src_pool._working_params.database} '
                   f'AS {src_pool._working_params.user}? ')
        if input(confirm) != 'y':
            return
        async with src_pool.acquire() as con:
            # Reverse so we don't remove foreign keys first
            for n in reversed(names):
                exists = await con.fetchval("SELECT to_regclass($1)", n)
                if not exists:
                    print(f'{n} does not exist')
                    continue
                q = f'DROP TABLE {n} CASCADE' if drop else f'DELETE FROM {n}'
                try:
                    await con.execute(q)
                    print(f'{"Dropped" if drop else "Cleared"} {n}')
                except Exception as e:
                    from ext.psql import debug_query
                    debug_query(q, [], e)


async def main():
    loop = asyncio.get_event_loop()
    bot = TestBot(loop)
    try:
        await bot.setup_hook(con_live=True)
        test = Test(loop, bot)
        await test.run()
    finally:
        await bot.close()


if __name__ == '__main__':
    # Must run with python -m test.test from root dir
    asyncio.run(main())
