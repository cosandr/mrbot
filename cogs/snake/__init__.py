from .cog import SnakeCog


def setup(bot):
    bot.add_cog(SnakeCog(bot))
