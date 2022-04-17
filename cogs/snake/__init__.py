from .cog import SnakeCog


async def setup(bot):
    await bot.add_cog(SnakeCog(bot))
