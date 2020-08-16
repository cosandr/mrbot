from .cog import MakeMeme


def setup(bot):
    bot.add_cog(MakeMeme(bot))
