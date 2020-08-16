from .cog import Music


def setup(bot):
    bot.add_cog(Music(bot))
