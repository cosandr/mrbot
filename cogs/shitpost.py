import os
import random
import time
import uuid

import discord
import numpy as np
from PIL import (Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont,
                 ImageOps)
from discord.ext import commands
from emoji import EMOJI_UNICODE

import ext.embed_helpers as emh
from ext.checks import open_connection_check
from ext.internal import Message
from ext.parsers import parsers
from ext.utils import find_url_type, bytes_from_url, transparent_embed


class Shitpost(commands.Cog, name='Shitposting'):
    def __init__(self, bot):
        self.bot = bot
        self.all_emoji = list(EMOJI_UNICODE.values())

    @commands.command(name='father', brief="Bustin' games", aliases=['textbuster', 'madeby'])
    async def post_gamebuster_image(self, ctx: commands.Context):
        # Transparent embed
        embed = transparent_embed()
        embed.set_image(url='https://cdn.discordapp.com/attachments/425792779294212147/699648132253745262/dre.jpg')
        await ctx.send(embed=embed)

    @commands.command(name='ascii', brief='Transform image into ASCII art',
        usage=("1. User who sent image or message ID.\nTakes most recent image if nobody is specified.\n"
               "This thing tries to generate ASCII art from input images."))
    async def ascii(self, ctx, msg_id=None, char_x=150):
        embed = emh.embed_init(self.bot, "ASCII")
        embed.add_field(name="Characters", value=char_x, inline=True)
        embed.add_field(name="Resolution", value=char_x*12, inline=True)
        if msg_id:
            embed.set_footer(text=f"Searching for image from {msg_id}.", icon_url=embed.footer.icon_url)
        else:
            embed.set_footer(text=f"Searching for most recent image.", icon_url=embed.footer.icon_url)
        msg: discord.Message = await ctx.send(embed=embed)
        res: Message = await Message.with_url(ctx, msg_id, img_only=True, skip_id=self.bot.user.id)
        if not res:
            return await emh.embed_img_not_found(msg, embed)
        else:
            img = Image.open(await bytes_from_url(res.first_image, self.bot.aio_sess))
            embed.set_footer(text=f"ASCII'ing {res.author.display_name}'s image.", icon_url=embed.footer.icon_url)
            await msg.edit(embed=embed)
        # Prevent large images for anyone except owner.
        if ((char_x > 500) or (char_x < 10)) and (ctx.author.id != self.bot.owner_id):
            char_x = 150
        embed, filename, start = await self.bot.loop.run_in_executor(None, lambda: self.img_ascii(img, char_x, embed))
        embed.title = f"{res.author.display_name}'s image has been ASCII'd."
        return await emh.embed_img_with_time(ctx, msg, embed, filename, time.perf_counter()-start)

    @commands.command(name='ruin', brief='Ruin an image',
        usage=("1. User who sent image or message ID.\nTakes most recent image if nobody is specified.\n"
               "Applies a bunch of garbage effects in an attempt to output a terrible picture."))
    async def ruin(self, ctx, msg_id=None):
        embed = emh.embed_init(self.bot, "Ruin")
        if msg_id:
            embed.set_footer(text=f"Searching for image from {msg_id}.", icon_url=embed.footer.icon_url)
        else:
            embed.set_footer(text=f"Searching for most recent image.", icon_url=embed.footer.icon_url)
        msg: discord.Message = await ctx.send(embed=embed)
        res: Message = await Message.with_url(ctx, msg_id, img_only=True)
        if not res:
            return await emh.embed_img_not_found(msg, embed)
        else:
            img = Image.open(await bytes_from_url(res.first_image, self.bot.aio_sess))
            start = time.perf_counter()
            filename = await self.bot.loop.run_in_executor(None, lambda: self.img_ruin(img))
            embed.title = f"{res.author.display_name}'s image has been ruined"
            embed.description = "Mr. Bot hopes you are satisfied with the result."
            return await emh.embed_img_with_time(ctx, msg, embed, filename, time.perf_counter()-start)

    @commands.command(name='shitpost', brief='Rate shitpost quality, now more smarterer',
        usage=("1. User who sent image or message ID.\nTakes most recent image if nobody is specified.\n"
               "Uses TensorFlow M A C H I N E  L E A R N I N G to rate an image."))
    @open_connection_check()
    async def shitpost(self, ctx, msg_id=None):
        embed = emh.embed_init(self.bot, "Rate shitpost")
        if msg_id:
            embed.set_footer(text=f"Searching for image from {msg_id}.", icon_url=embed.footer.icon_url)
        else:
            embed.set_footer(text=f"Searching for most recent image.", icon_url=embed.footer.icon_url)
        msg: discord.Message = await ctx.send(embed=embed)
        res: Message = await Message.with_url(ctx, msg_id, img_only=False)
        if not res:
            return await emh.embed_img_not_found(msg, embed)
        url_type = find_url_type(res.first_url)
        if url_type == 'image':
            embed.set_footer(text=f"Image found", icon_url=embed.footer.icon_url)
            embed.title = f"{res.author.display_name}'s image rating"
            embed.description = await self.img_rate(res.first_url, pnas=False)
            return await msg.edit(embed=embed)
        elif url_type == 'twitch':
            embed.set_footer(text=f"Twitch URL found", icon_url=embed.footer.icon_url)
            embed.title = 'TWITCH LINK DETECTED'
            embed.description = f"{'<:REE:485740755302875136>'*4}\n{'<:REE:485740755302875136>'*4}\n{'<:REE:485740755302875136>'*4}\n"
            return await msg.edit(embed=embed)
        elif url_type == 'youtube':
            embed.set_footer(text=f"YouTube URL found", icon_url=embed.footer.icon_url)
            embed.title = 'YOUTUBE LINK DETECTED'
            embed.description = f"Mr. Bot believes {res.author.display_name}'s link is likely a song nobody cares about."
            return await msg.edit(embed=embed)
        else:
            embed.set_footer(text=f"URL found", icon_url=embed.footer.icon_url)
            embed.title = 'Unknown link'
            embed.description = f"Mr. Bot doesn't have any opinion about {res.author.display_name}'s link."
            return await msg.edit(embed=embed)

    @commands.command(name='dyingtext', brief='yOU cAn SPeciFy uSEr tOo',
        usage="1. User who sent the message or the message ID.\nTakes the most recent message if no arugment is given.")
    async def dyingtext(self, ctx, msg_id='any'):
        try:
            msg_id = int(msg_id)
            try:
                history = await ctx.fetch_message(msg_id)
            except discord.errors.NotFound:
                return await ctx.send(f"No message with ID {msg_id} found.")
            msg = history.content
        except ValueError:
            if msg_id.lower() == 'any':
                msg = ''
                history = ctx.history(limit=10, before=ctx.message.created_at)
                async for m in history:
                    if m.author != self.bot.user:
                        msg = m.content
                        break
                if msg == '':
                    return await ctx.send("No message found.")
            else:
                msg = ''
                history = ctx.history(limit=20, before=ctx.message.created_at)
                async for m in history:
                    if msg_id.lower() in m.author.display_name.lower():
                        msg = m.content
                        break
                if msg == '':
                    return await ctx.send("No message found.")

        return await ctx.send(self.kill_text(msg)[0:2000])

    @commands.command(name='shitgen', brief='Advanced technology, optionally specify length',
        usage="1. Number of words to use when generating shitpost.")
    async def shitgen(self, ctx, length=None):
        if length is None:
            length = 30
        else:
            try:
                length = int(length)
            except ValueError:
                length = 30
        history = ctx.history(limit=30, before=ctx.message.created_at)
        msg_src = ''
        async for msg in history:
            if msg.author != self.bot.user:
                # Ignore URLs
                if not msg.content.startswith('http'):
                    msg_src += msg.content + " "

        tmp = self.kill_text(msg_src)
        word_list = tmp.split(' ')
        random.shuffle(word_list)
        num_emoji = 0
        ret_str = ''
        if (length < 0) or (length > 100):
            length = 30
        # Add emojis
        while num_emoji < length:
            if random.randint(0, 100) > 10:
                emoji_str = random.choice(self.all_emoji)
            else:
                emoji_str = str(self.bot.emojis[random.randint(0, len(self.bot.emojis)-1)])
            if num_emoji >= len(word_list):
                break
            if emoji_str not in word_list:
                if random.randint(0, 100) > 50:
                    ret_str += emoji_str + word_list[num_emoji] + " "
                    num_emoji += 1
                else:
                    ret_str += word_list[num_emoji] + " "
                    num_emoji += 1
        return await ctx.send(ret_str[0:2000])

    @parsers.command(
        name='gif',
        brief='Use noise 3D to generate gif',
        parser_title='3D Noise Generator',
        parser_args=[
            parsers.Arg('--width', '-w', type=int, default=100),
            parsers.Arg('--height', '-h', type=int, default=100),
            parsers.Arg('--octaves', '-o', type=int, default=5),
            parsers.Arg('--scale', '-s', type=float, default=1/20),
            parsers.Arg('--timescale', '-ts', type=int, default=10),
            parsers.Arg('--persistence', '-p', type=float, default=0.3),
            parsers.Arg('--lacunarity', '-l', type=float, default=2.0),
            parsers.Arg('--video', '-v', default=False, action='store_true'),
            parsers.Arg('-fps', type=int, default=24),
            parsers.Arg('-frames', type=int, default=10),
        ],
    )
    @open_connection_check()
    async def gif(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        params = vars(parsed)
        # Replace some keys
        params['w'] = params.pop('width')
        params['h'] = params.pop('height')
        embed = emh.embed_init(self.bot, "Noise 3D")
        # Maximum limit due to time constraints
        if ctx.author.id != self.bot.owner_id and params['frames'] * params['w'] * params['h'] > 30e6:
            embed.colour = discord.Colour.red()
            embed.add_field(name="Error",
                            value="Please be reasonable with your resolution and/or frame count. Maximum allowed is 30e6 (WxHxF).",
                            inline=False)
            return await ctx.send(embed=embed)
        if params['fps'] <= 0:
            params['fps'] = 24
        fmt_params = params.copy()
        fmt_params.pop('video')
        fmt_params['file_fmt'] = 'video' if params['video'] else 'GIF'
        params_str = (
            "{w}x{h} Octaves: {octaves} Persistence: {persistence:.1f} Scale: {scale:.1f} Timescale: {timescale} "
            "Lacunarity: {lacunarity} FPS: {fps} Frames: {frames} {file_fmt}"
        )
        embed.add_field(name="Parameters", value=params_str.format(**fmt_params), inline=False)
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        msg = await ctx.send(embed=embed)
        await self.bot.brains_image_request('/noise/run/gif', msg=msg, embed=embed, data=params)

    @parsers.command(
        name='noise',
        brief='Generates perlin noise. See help for options',
        parser_title='2D Noise Generator',
        parser_args=[
            parsers.Arg('--width', '-w', type=int, default=640),
            parsers.Arg('--height', '-h', type=int, default=480),
            parsers.Arg('--octaves', '-o', type=int, default=10),
            parsers.Arg('--scale', '-s', type=float, default=1/50),
            parsers.Arg('--persistence', '-p', type=float, default=0.3),
            parsers.Arg('--red', '-r', type=int, default=255),
            parsers.Arg('--green', '-g', type=int, default=50),
            parsers.Arg('--blue', '-b', type=int, default=255),
            parsers.Arg('--x_rep', '-xr', type=int, default=100),
            parsers.Arg('--y_rep', '-yr', type=int, default=100),
            parsers.Arg('--colour', '-c', type=str, default='rgb'),
        ],
    )
    @open_connection_check()
    async def noise(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        params = vars(parsed)
        # Replace some keys
        params['w'] = params.pop('width')
        params['h'] = params.pop('height')
        params['r'] = params.pop('red')
        params['g'] = params.pop('green')
        params['b'] = params.pop('blue')
        embed = emh.embed_init(self.bot, "Noise 2D")
        # Maximum limit due to time constraints
        if ctx.author.id != self.bot.owner_id and params['w'] * params['h'] > 30e6:
            embed.colour = discord.Colour.red()
            embed.add_field(name="Error",
                            value="Please be reasonable with your resolution. Maximum allowed is 30e6 (WxH).",
                            inline=False)
            return await ctx.send(embed=embed)
        embed = emh.embed_init(self.bot, "Noise 2D")
        params_str = ("{w}x{h} Octaves: {octaves} Persistence: {persistence:.1f} Scale: {scale:.1f} "
                      "RGB: {r},{g},{b} Xrep: {x_rep} Yrep: {y_rep} Color: {colour}")
        embed.add_field(name="Parameters", value=params_str.format(**params), inline=False)
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        msg = await ctx.send(embed=embed)
        await self.bot.brains_image_request('/noise/run/image', msg=msg, embed=embed, data=params)

    @staticmethod
    def kill_text(msg: str) -> str:
        msg = msg.replace("!", "")
        msg = msg.replace("*", "")
        msg_list = list(msg)
        for i in range(0, len(msg)):
            letter = msg_list[i]
            # Do we make lower case?
            if random.randint(0, 10) > 5:
                # Do we italize?
                if (random.randint(0, 10) > 5) and (letter != ' ') and ('*' not in msg_list[i-1]) and (letter != '\n'):
                    if random.randint(0, 10) > 5:
                        msg_list[i] = f"*{letter.lower()}*"
                    else:
                        msg_list[i] = f"**{letter.lower()}**"
                else:
                    msg_list[i] = letter.lower()
            else:
                if (random.randint(0, 10) > 5) and (letter != ' ') and ('*' not in msg_list[i-1]) and (letter != '\n'):
                    if random.randint(0, 10) > 5:
                        msg_list[i] = f"*{letter.upper()}*"
                    else:
                        msg_list[i] = f"**{letter.upper()}**"
                else:
                    msg_list[i] = letter.upper()

        return "".join(msg_list)

    def img_ascii(self, img: Image, char_x: int, embed: discord.Embed):
        """ASCII'fy an image"""
        start = time.perf_counter()
        char_y = int(char_x*(img.height/img.width))
        img = img.convert('L')
        img = img.resize((char_x, char_y))
        img_arr = np.array(img.getdata())
        img_arr = np.reshape(img_arr, (char_y, char_x))
        # From brightest to darkest
        asciichars = ['@', '%', '#', '*', '+', '=', '-', ':', '.', ' ']
        # random.shuffle(asciichars)
        # Generate list of pixel thresholds
        thresholds = np.linspace(220, 0, len(asciichars), dtype=np.uint8)
        ret_str = ""
        for x in range(char_y):
            for y in range(char_x):
                for i in range(len(asciichars)):
                    if (img_arr[x][y]) >= thresholds[i]:
                        ret_str += f"{asciichars[i]:2s}"
                        break
            ret_str += '\n'
        img_draw = Image.new("RGB", (char_x*12, char_y*12))
        draw = ImageDraw.Draw(img_draw)
        font = ImageFont.truetype(f'{self.bot.config.data}/fonts/consola.ttf', 10)
        draw.text((0, 0), ret_str, font=font)
        filename = f"ascii_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(self.bot.config.upload, filename)
        img_draw.save(filepath, format='jpeg')
        os.chmod(filepath, 0o644)
        embed.set_field_at(0, name="Characters", value=f"{char_x}x{char_y}", inline=True)
        embed.set_field_at(1, name="Resolution", value=f"{img_draw.width}x{img_draw.height}", inline=True)
        return embed, filename, start

    def img_ruin(self, img: Image) -> str:
        # Start image brains.
        img_out = img.filter(ImageFilter.EDGE_ENHANCE_MORE)  # kinda like sharpen
        img_out = img_out.filter(ImageFilter.BoxBlur(random.randint(1, 5)))
        img_out = img_out.filter(ImageFilter.MinFilter(random.randrange(3, 11+1, 2)))
        enhancer = ImageEnhance.Sharpness(img_out)
        factor = random.randint(200, 500)
        img_out = enhancer.enhance(factor)
        # Sometimes flip the image
        if random.randint(1, 50) > 40:
            img_out = ImageOps.mirror(img_out)
        # Make it trash resolution
        img_out = img_out.resize((int(img.width/random.randint(2, 5)), int(img.height/random.randint(2, 5))))
        img_out = img_out.resize((img.width, img.height))
        # Start saving and sending process
        filename = f"ruined_{uuid.uuid4().hex}.{img.format}"
        filepath = os.path.join(self.bot.config.upload, filename)
        img_out.save(filepath, format=img.format)
        os.chmod(filepath, 0o644)
        return filename

    async def img_rate(self, url, pnas):
        r = await self.bot.brains_post_request('/image_label/run', data=dict(model_type='meme', url=url, pnas=pnas))
        if not r.ok:
            return await r.fail_msg
        results, labels = np.array(r.data['results']), r.data['labels']
        top_k = results.argsort()[-3:][::-1]
        tmp = labels[top_k[0]]
        if tmp.startswith('a') or tmp.startswith('u'):
            return f'Mr. Bot thinks this is an {tmp} shitpost.'
        return f'Mr. Bot thinks this is a {tmp} shitpost.'


def setup(bot):
    bot.add_cog(Shitpost(bot))
