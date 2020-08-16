from .cog import PastaCog
from .pasta import Pasta


def setup(bot):
    bot.add_cog(PastaCog(bot))
