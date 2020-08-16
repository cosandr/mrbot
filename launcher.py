#!/usr/bin/env python3

import config as cfg
from mrbot import MrBot

if __name__ == '__main__':
    config = cfg.BotConfig.from_json(
        secrets='config/secrets.json',
        paths='config/paths.json',
        guilds='config/guild_mine.json',
    )
    bot = MrBot(command_prefix="!", owner_id=227847073607712768, help_command=None, config=config)
    bot.run()
