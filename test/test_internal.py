import asyncio
import itertools
import random
import time
import unittest
from datetime import datetime, timedelta
from typing import List

import asyncpg

from ext.internal import Message, User, Channel, Guild
from ext.psql import create_table
from test.mock_bot import TestBot


class InternalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loop = asyncio.get_event_loop()
        cls.bot = TestBot(cls.loop)
        cls.loop.run_until_complete(cls.bot.async_init())
        # Ensure all tables exist
        names = [
            Guild.psql_table_name, Channel.psql_table_name, User.psql_table_name,
            User.psql_table_name_nicks, Message.psql_table_name, Message.psql_table_name_edits,
        ]
        q = f'{Guild.psql_table} {Channel.psql_table} {User.psql_table} {Message.psql_table}'
        cls.loop.run_until_complete(create_table(cls.bot.pool, name=names, query=q))

    # noinspection PyUnresolvedReferences
    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.bot.close())

    @staticmethod
    def generate_users(num_users: int):
        """Generate users with unique IDs"""
        users = []
        added = set()
        while len(added) < num_users:
            user_id = random.randint(100, 999)
            if user_id in added:
                continue
            added.add(user_id)
            users.append(User(id_=user_id, name=f'User {len(added)}'))
        return users

    @staticmethod
    def generate_guilds(num_guilds: int):
        """Generate guilds with unique IDs"""
        guilds = []
        added = set()
        while len(added) < num_guilds:
            guild_id = random.randint(100, 999)
            if guild_id in added:
                continue
            added.add(guild_id)
            guilds.append(Guild(id_=guild_id, name=f'Guild {len(added)}'))
        return guilds

    @staticmethod
    def add_nicks_to_users(users: List[User], guilds: List[Guild], skip_nick: int = 0):
        """Adds nicks to provided users

        :param users: List of users
        :param guilds: List of guilds
        :param skip_nick: Do not add nicks to this many users"""
        skipped = 0
        for u in users:
            if skipped < skip_nick:
                skipped += 1
                continue
            for g in guilds:
                r_num = random.randint(0, 100)
                if 30 <= r_num:
                    u.all_nicks[g.id] = f'Nick for guild {g.id}'
        return users

    @staticmethod
    async def psql_insert_users(con: asyncpg.Connection, users: List[User]):
        """Inserts users in list"""
        for u in users:
            q, q_args = u.to_psql()
            await con.execute(q, *q_args)

    @staticmethod
    async def psql_insert_guilds(con: asyncpg.Connection, guilds: List[Guild], users: List[User] = None):
        """Insert guilds, optionally add user nick names"""
        for g in guilds:
            q, q_args = g.to_psql()
            await con.execute(q, *q_args)
            if not users:
                continue
            for u in users:
                q, q_args = u.to_psql_nick(g.id)
                await con.execute(q, *q_args)

    @staticmethod
    async def psql_delete_users(con: asyncpg.Connection, users: List[User]):
        """Delete users in list"""
        for u in users:
            q = f'DELETE FROM {User.psql_table_name_nicks} WHERE user_id=$1'
            await con.execute(q, u.id)
            q = f'DELETE FROM {User.psql_table_name} WHERE id=$1'
            await con.execute(q, u.id)

    @staticmethod
    async def psql_delete_guilds(con: asyncpg.Connection, guilds: List[Guild]):
        """Delete guilds in list"""
        for g in guilds:
            q = f'DELETE FROM {Guild.psql_table_name} WHERE id=$1'
            await con.execute(q, g.id)

    def test_user_with_nicks(self):
        self.loop.run_until_complete(self._test_user_with_nicks())

    async def _test_user_with_nicks(self):
        num_guilds = 10
        num_users = 20
        # How many users won't have any nicknames at all
        skip_nick = int(num_users / 10)
        guilds = self.generate_guilds(num_guilds)
        users = self.add_nicks_to_users(self.generate_users(num_users), guilds, skip_nick)
        guilds_str = '\n'.join([repr(g) for g in guilds])
        users_str = '\n'.join([repr(u) for u in users])
        print(f'Test guilds:\n{guilds_str}')
        print(f'Test users:\n{users_str}')
        async with self.bot.pool.acquire() as con:
            # Add users
            await self.psql_insert_users(con, users)
            # Add guilds and nicks
            await self.psql_insert_guilds(con, guilds, users)
            # Verify
            ok = []
            failed = []
            for u in users:
                r = await con.fetchrow(User.make_psql_query(with_all_nicks=True, where='id=$1'), u.id)
                if not r:
                    print(f'ERROR: No user with ID {u.id} in PSQL')
                    failed.append(u)
                    continue
                psql_u = User.from_psql_res(r)
                # These should be equal
                if u.id == psql_u.id:
                    if u == psql_u:
                        ok.append(u)
                    else:
                        failed.append(psql_u)
            await self.psql_delete_users(con, users)
            # Delete test guilds
            await self.psql_delete_guilds(con, guilds)
        for u in ok:
            print(f'OK: {repr(u)}')
        for u in failed:
            print(f'Expected: {repr(u)}\nGot{repr(psql_u)}')
        self.assertFalse(failed)

    def test_user_from_search(self):
        self.loop.run_until_complete(self._test_user_from_search())

    async def _test_user_from_search(self):
        for search in ('andrei', 'dre', 'jens', 'jonas', 'jost', 'yan', 'test nick',
                       159883083531681792, 159883083531681732, 227847073607712768):
            if isinstance(search, int):
                for guild_id in (422101180236300304, None, 123, 321321):
                    start = time.perf_counter()
                    u = await User.from_search(self.bot, search, guild_id=guild_id, with_nick=True)
                    print(f'-> {search} [guild {guild_id}] found in {((time.perf_counter() - start) * 1000):.2f}ms')
                    print(repr(u))
            else:
                start = time.perf_counter()
                u = await User.from_search(self.bot, search, with_nick=True)
                print(f'-> {search} found in {((time.perf_counter() - start) * 1000):.2f}ms')
                print(repr(u))

    def test_user_make_query(self):
        self.loop.run_until_complete(self._test_user_make_query())

    async def _test_user_make_query(self):
        q_args = [159883083531681792]
        async with self.bot.pool.acquire() as con:
            print('All users, array nicks')
            q = User.make_psql_query(with_all_nicks=True)
            res = await con.fetch(q)
            print(res)
            print('One user')
            q = User.make_psql_query(with_nick=True, where='id=$1')
            res = await con.fetchrow(q, *q_args)
            print(res)

    def test_user_from_id(self):
        self.loop.run_until_complete(self._test_user_from_id())

    async def _test_user_from_id(self):
        user_id = 159883083531681792
        guild_id = 422101180236300304
        async with self.bot.pool.acquire() as con:
            u = await User.from_id(self.bot, user_id=user_id, guild_id=guild_id)

    def test_user_eq(self):
        u1 = User(100, name='User 1')
        u2 = User(100, name='User 1')
        self.assertEqual(u1, u2)
        dt = datetime.utcnow()
        u1 = User(100, name='User', status_time=dt, online=True)
        u2 = User(100, name='User', status_time=dt, online=True)
        self.assertEqual(u1, u2)
        u1 = User(id_=111, name='User', discriminator=1, avatar='avatar', all_nicks={101: 'nick'},
                  activity='activity', activity_time=datetime(2020, 9, 11, 22, 40),
                  online=True, mobile=False, status_time=datetime(2020, 9, 11, 22, 40))
        u2 = User(id_=111, name='User', discriminator=1, avatar='avatar', all_nicks={101: 'nick'},
                  activity='activity', activity_time=datetime(2020, 9, 11, 22, 40),
                  online=True, mobile=False, status_time=datetime(2020, 9, 11, 22, 40))
        self.assertEqual(u1, u2)
        u2 = User(id_=111, name='User', discriminator=1, avatar='avatar', all_nicks={101: 'nick'},
                  activity='activity', activity_time=datetime(2020, 9, 11, 22, 50),
                  online=True, mobile=False, status_time=datetime(2020, 9, 11, 22, 40))
        self.assertNotEqual(u1, u2)
        u2 = User(id_=111, name='User', discriminator=1, avatar='avatar', all_nicks={101: 'nick'},
                  activity='activity', activity_time=datetime(2020, 9, 11, 22, 40),
                  online=True, mobile=False, status_time=datetime(2020, 9, 11, 22, 50))
        self.assertNotEqual(u1, u2)

    def test_user_diff(self):
        u1 = User(100, name='User 1')
        u2 = User(100, name='User 2')
        self.assertSetEqual(u1.diff(u2), {'name'})
        dt = datetime.utcnow()
        dt_later = dt + timedelta(seconds=10)
        u1 = User(100, name='User', status_time=dt, online=True)
        u2 = User(100, name='User', status_time=dt, online=True)
        self.assertSetEqual(u1.diff(u2), set())
        u1 = User(100, name='User', status_time=dt, online=True)
        u2 = User(100, name='User', status_time=dt_later, online=True)
        self.assertSetEqual(u1.diff(u2), {'status_time'})
        u1 = User(100, name='User', status_time=dt, online=True)
        u2 = User(100, name='User')
        self.assertSetEqual(u1.diff(u2), {'online', 'status_time'})

    def test_jump_url_from_psql(self):
        self.loop.run_until_complete(self._test_jump_url_from_psql())

    async def _test_jump_url_from_psql(self):
        async with self.bot.pool.acquire() as con:
            url = await Message.jump_url_from_psql(con, 681131219320176686)
        self.assertRegex(url, r'https://discordapp.com/channels/.*')

    def test_message_edit(self):
        self.loop.run_until_complete(self._test_message_edit())

    async def _test_message_edit(self):
        test_content = 'test message 1'
        test_edited = 'edited message 1'
        msg = Message(
            id_=123,
            time_=datetime.utcnow(),
            content=test_content,
            author=User(id_=153882790599852032),
            channel=Channel(id_=422101180236300306),
        )
        q_get_msg = f'SELECT content FROM {Message.psql_table_name} WHERE msg_id=$1'
        q_get_edits = f'SELECT content FROM {Message.psql_table_name_edits} WHERE msg_id=$1'
        async with self.bot.pool.acquire() as con:
            # Insert message
            q, q_args = msg.to_psql()
            await con.execute(q, *q_args)
            # Verify content
            r = await con.fetchval(q_get_msg, msg.id)
            self.assertEqual(r, test_content, msg='Inserted message has wrong content')
            # Change message content
            msg.content = test_edited
            q, q_args = msg.to_psql()
            await con.execute(q, *q_args)
            # Verify content
            r = await con.fetchval(q_get_msg, msg.id)
            self.assertEqual(r, test_edited, msg='Edited message has wrong content')
            # Verify old message is in edited table
            r = await con.fetchval(q_get_edits, msg.id)
            self.assertEqual(r, test_content, msg='Original message has wrong content')
            # Cleanup
            await con.execute(f'DELETE FROM {Message.psql_table_name} WHERE msg_id=$1', msg.id)
            # Ensure the edits are deleted as well
            r = await con.fetch(q_get_edits, msg.id)
            self.assertFalse(r, msg='Edited message not deleted')

    def test_message_from_psql(self):
        self.loop.run_until_complete(self._test_message_from_psql())

    async def _test_message_from_psql(self):
        try_ids = {
            554762832961470474: True,
            554762832961470471: False,
            682992085418115076: True,
            682695511584669708: True,
            682695511584669732: False,
        }
        args = ['with_author', 'with_channel', 'with_guild', 'with_nick']
        args_list = [dict(zip(args, x)) for x in itertools.product([True, False], repeat=len(args))]
        async with self.bot.pool.acquire() as con:
            for id_, expected in try_ids.items():
                for arg in args_list:
                    msg = await Message.from_psql(con, id_, **arg)
                    self.assertFalse(not msg and expected, msg=f'Expected a message with ID {id_}\n\tARGS: {arg}')
                    self.assertFalse(msg and not expected, msg=f'Did not expect a message with ID {id_}\n\tARGS: {arg}\n{repr(msg)}')


if __name__ == '__main__':
    unittest.main()
