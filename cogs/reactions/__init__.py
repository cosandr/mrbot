from .config import ReactionsConfig
from .reactions import Reactions


def setup(bot):
    bot.add_cog(Reactions(bot))
