from .cog import Notifications


def setup(bot):
    bot.add_cog(Notifications(bot))
