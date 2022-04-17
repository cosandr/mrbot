from .cog import Notifications


async def setup(bot):
    await bot.add_cog(Notifications(bot))
