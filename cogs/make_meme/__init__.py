from .cog import MakeMeme


async def setup(bot):
    await bot.add_cog(MakeMeme(bot))
