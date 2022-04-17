from .cog import PastaCog
from .pasta import Pasta


async def setup(bot):
    await bot.add_cog(PastaCog(bot))
