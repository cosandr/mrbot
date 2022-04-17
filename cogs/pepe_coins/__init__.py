from .cog import PepeCoins


async def setup(bot):
    await bot.add_cog(PepeCoins(bot))
