import logging

from mrbot import MrBot
from config import BotConfig

bot = MrBot(
    config=BotConfig.from_json(
        secrets=['config/secrets.json', 'config/secrets_test.json'],
        paths=['config/paths.json'],
        guilds=['config/guild_mine.json'],
    ),
    command_prefix="'",
    owner_id=227847073607712768,
    log_file_name='discord-test.log',
    # extension_override=[
    #     'cogs.admin',
    #     'cogs.error_handler',
    #     'cogs.insults',
    # ],
    help_command=None,
)
# Set DEBUG logging level for console handler
for h in bot.logger.handlers:
    if isinstance(h, logging.StreamHandler):
        h.setLevel(logging.DEBUG)

bot.run()
