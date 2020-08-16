import aiohttp
import discord


class Response:
    """Parse Discord Brains API responses"""
    def __init__(self, data=None, params=None, error='', time=0, status=200, reason='OK'):
        # An error string
        self.error: str = error
        # How long the request took to complete
        self.time: float = time
        # Return data, probably a dict or string
        self.data = data
        # The parameters used by the function that was run
        self.params: dict = params
        self.status: int = status
        self.reason: str = reason

    @property
    def ok(self) -> bool:
        """Returns True if status is between 200 and 300"""
        return 200 <= self.status < 300

    @property
    def fail_msg(self) -> str:
        """Returns error string if it exists, otherwise status code + reason"""
        if self.error:
            return self.error
        return f'{self.status} {self.reason}'

    def fail_embed(self, embed: discord.Embed, name='Error') -> discord.Embed:
        embed.colour = discord.Colour.red()
        embed.set_footer()
        embed.clear_fields()
        embed.add_field(name=name, value=self.fail_msg, inline=True)
        return embed

    @classmethod
    async def from_resp(cls, resp: aiohttp.ClientResponse):
        try:
            data = await resp.json()
            return cls(
                data=data.get('data'),
                params=data.get('params'),
                error=data.get('error'),
                time=data.get('time'),
                status=resp.status,
                reason=resp.reason,
            )
        except Exception as e:
            return cls(
                error=str(e),
                status=500,
            )
