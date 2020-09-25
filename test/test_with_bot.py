import asyncio
import platform
import unittest

from mrbot import MrBot
from config import BotConfig
from ext.internal import Message


class InternalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loop = asyncio.get_event_loop()
        with open('config/.dsn_test', 'r') as f:
            dsn = f.read().strip()
        extra = ['test']
        if platform.system() == 'Windows':
            extra.append('windows')
        config = cls.loop.run_until_complete(BotConfig.from_psql(dsn=dsn, extra=extra))
        cls.bot = MrBot(
            command_prefix="'",
            owner_id=227847073607712768,
            config=config,
        )
        cls.bot_started = False

    # noinspection PyUnresolvedReferences
    @classmethod
    def tearDownClass(cls) -> None:
        print('Tests ended, closing bot')
        cls.loop.run_until_complete(cls.bot.close())

    def ensure_bot(self):
        if not self.bot_started:
            print('Starting bot')
            self.loop.create_task(self.bot.start(self.bot.config.token))
            self.loop.run_until_complete(self._wait_connect())
            self.bot_started = True
        else:
            self.loop.run_until_complete(self._wait_connect())

    async def _wait_connect(self):
        await self.bot.connect_task
        await self.bot.wait_until_ready()

    def test_message_from_user(self):
        res = self.loop.run_until_complete(self._test_message_from_user())
        self.assertTrue(res)

    async def _test_message_from_user(self):
        await self.ensure_bot()
        user_id=227847073607712768
        ch_id = 422473204515209226
        msg = await Message.from_user_id(ctx=self.bot, user_id=user_id, ch_id=ch_id)
        print(repr(msg))
        if msg:
            return True
        return False


if __name__ == '__main__':
    unittest.main()
