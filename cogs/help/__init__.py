from .help_cog import Help


def setup(bot):
    bot.add_cog(Help(bot))
