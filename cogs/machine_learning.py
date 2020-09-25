import logging
import random
from typing import Dict, Tuple, Optional
from urllib.parse import quote

import discord
import numpy as np
from discord.ext import commands

import ext.embed_helpers as emh
from mrbot import MrBot
from ext.checks import open_connection_check
from ext.errors import UnapprovedGuildError
from ext.internal import Message
from ext.parsers import parsers
from ext.utils import find_similar_str, paginate, human_seconds, to_columns_vert


class MachineLearning(commands.Cog, name="Machine Learning"):
    def __init__(self, bot):
        self.bot: MrBot = bot
        self.logger = logging.getLogger(f'{self.bot.logger_name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)

    async def cog_check(self, ctx):
        if await self.bot.is_owner(ctx.author):
            return True
        # Ignore DMs
        if not ctx.guild:
            raise UnapprovedGuildError()
        # Only apply to approved guilds
        else:
            if ctx.guild.id not in self.bot.config.approved_guilds:
                raise UnapprovedGuildError()
        return True

    @parsers.group(
        name='be',
        brief='Machine learned text generator',
        invoke_without_command=True,
        parser_args=[
            parsers.Arg('model', type=str, help='Model to run'),
            parsers.Arg('--words', '-w', default=70, type=int, help='Minimum words to generate'),
            parsers.Arg('--temperature', '-t', default=0.5, type=float),
        ],
    )
    @open_connection_check()
    async def be(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        if parsed.words > 300 and not await self.bot.is_owner(ctx.author):
            return await ctx.send("Too many words requested, keep it under 300.")
        embed = emh.embed_init(self.bot, "Be")
        embed.add_field(name="Model", value=parsed.model, inline=True)
        embed.add_field(name="Words", value=parsed.words, inline=True)
        embed.add_field(name="Temp", value=parsed.temperature, inline=True)
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        msg = await ctx.send(embed=embed)
        params = dict(words=parsed.words, temp=str(parsed.temperature))
        # Send run request
        url = f'/be/run/{quote(parsed.model)}'
        r = await self.bot.brains_get_request(url, params=params)
        if not r.ok:
            return await msg.edit(embed=r.fail_embed(embed, "Server error"))
        generated, num_words = r.data["text"], r.data["words"]
        if any(c in generated for c in ['*', '_', '`']):
            embed.description = f"```\n{generated}```"
        else:
            embed.description = generated
        embed.set_footer(text=f"Completed in {r.time:.2f}s", icon_url=embed.footer.icon_url)
        embed.set_field_at(1, name="Words", value=num_words, inline=True)
        embed.colour = discord.Colour.green()
        return await msg.edit(embed=embed)

    @be.command(
        name='list',
        brief='List available models',
        parser_args=[
            parsers.Arg('filter', nargs='?', default='best', help='Filter output models'),
        ]
    )
    @open_connection_check()
    async def be_list(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        if parsed.filter == 'best':
            r = await self.bot.brains_get_request('/be/list/best')
        else:
            r = await self.bot.brains_get_request('/be/list/all')
        if not r.ok:
            return await ctx.send(r.fail_msg)
        # Process model names, remove exact name information
        all_models: Dict[str, dict] = {}
        for d in r.data:
            if parsed.filter == 'best':
                all_models[d["name"].split("_", 1)[0]] = d
            else:
                all_models[d["name"]] = d
        if parsed.filter not in ('best', 'all'):
            models_keys = list(all_models.keys())
            close_keys = find_similar_str(parsed.filter, models_keys)
            if not close_keys:
                return await ctx.send(f'No models similar to {parsed.filter}')
            # Remove irrelevant entries
            for k in models_keys:
                if k not in close_keys:
                    all_models.pop(k)
        # Find longest model name
        dist = len(max(all_models.keys(), key=len)) + 2
        header = f"{'   Model':{dist}s}{'':3s}{'Loss':6}{'Epoch':7}{'Layers':8}{'Size':6}{'Bidir':7}{'Level':7}{'Type':6}"
        content = ''
        for k, data in all_models.items():
            layers = data['rnn_layers']
            state_size = data['rnn_size']
            loss = data['loss']
            epoch = data['epoch']
            bidir = 'Y' if data['rnn_bidirectional'] else 'N'
            level = 'W' if data['word_level'] else 'C'
            rnn_type = data['rnn_type'].upper()
            content += f"\n{k:{dist}s}{loss:7.2f}{epoch:6d}{layers:7d}{state_size:7d}{'':5s}{bidir}{'':6s}{level}{'':4s}{rnn_type}"

        for p in paginate(content.strip(), header=header):
            await ctx.send(p)

    @parsers.group(
        name='continue',
        brief='Continue a sentence',
        invoke_without_command=True,
        parser_args=[
            parsers.Arg('model_name', default='117M', type=str, help='Model to use'),
            parsers.Arg('raw_text', nargs='*', help='Input text'),
            parsers.Arg('--seed', '-s', default=None, type=int, help='Seed'),
            parsers.Arg('--temperature', '-t', default=0.75, type=float, help='Temperature'),
            parsers.Arg('--top_k', '-d', default=0, type=int, help='Diversity'),
            parsers.Arg('--length', '-w', default=75, type=int, help='Number of words'),
        ],
        usage="""- seed: Integer seed for random number generators, fix seed to reproduce
results
- length: Number of tokens in generated text, if None (default), is
determined by model hyperparameters
- temperature: Float value controlling randomness in boltzmann
distribution. Lower temperature results in less random completions. As the
temperature approaches zero, the model will become deterministic and
repetitive. Higher temperature results in more random completions.
- top_k: Integer value controlling diversity. 1 means only 1 word is
considered for each step (token), resulting in deterministic completions,
while 40 means 40 words are considered at each step. 0 (default) is a
special setting meaning no restrictions. 40 generally is a good value.""",
    )
    @open_connection_check()
    async def gpt2_continue(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        params = vars(parsed)
        params_str = "Model: {model_name}\nWords: {length}\nTemperature: {temperature}\nDiversity: {top_k}\nSeed: {seed}"
        if not parsed.raw_text:
            params.pop('raw_text')
            raw_text = random.choice(list('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'))
        else:
            raw_text = ' '.join(params.pop('raw_text'))
        # Sanity checks
        if parsed.length > 300 and not await self.bot.is_owner(ctx.author):
            return await ctx.send("Too many words requested, keep it under 300.")
        embed = emh.embed_init(self.bot, "Continue")
        embed.add_field(name="Parameters", value=params_str.format(**params), inline=True)
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        msg = await ctx.send(embed=embed)
        # Send run request
        r = await self.bot.brains_post_request('/continue/run', data=dict(raw_text=raw_text, **params))
        if not r.ok:
            return await msg.edit(embed=r.fail_embed(embed, "Server error"))
        # Wrap in code block if it has markdown characters
        if any(c in r.data for c in ['*', '_', '`']):
            embed.description = f"```\n{raw_text} {r.data}```"
        else:
            embed.description = f"*{raw_text}* {r.data}"
        # Get actual parameters used
        params = r.params.copy()
        # Remove params we are not showing
        params.pop('raw_text')
        params.pop('batch_size')
        params['length'] = len(r.data.split())
        embed.set_field_at(0, name="Parameters", value=params_str.format(**params), inline=True)
        embed.set_footer(text=f"Completed in {r.time:.2f}s", icon_url=embed.footer.icon_url)
        embed.colour = discord.Colour.green()
        return await msg.edit(embed=embed)

    @gpt2_continue.command(
        name='list',
        brief='List available models',
        parser_args=[
            parsers.Arg('filter', nargs='?', default='all', help='Filter output models'),
        ]
    )
    @open_connection_check()
    async def gpt2_list(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        r = await self.bot.brains_get_request('/continue/list')
        if not r.ok:
            return await ctx.send(r.fail_msg)
        # Process model names, remove exact name information
        all_models: Dict[str, dict] = r.data
        if parsed.filter != 'all':
            models_keys = list(all_models.keys())
            close_keys = find_similar_str(parsed.filter, models_keys)
            if not close_keys:
                return await ctx.send(f'No models similar to {parsed.filter}')
            # Remove irrelevant entries
            for k in models_keys:
                if k not in close_keys:
                    all_models.pop(k)
        # Find longest model name
        dist = len(max(all_models.keys(), key=len)) + 2
        header = f"{'   Model':{dist}s}{'':3s}{'Steps':8s}{'Time':7s}{'Loss':8s}{'Avg':6s}"
        content = ''
        for k, data in all_models.items():
            counter = data['counter']
            train_time = data['time']/60
            loss = data['loss']
            avg_loss = data['avg']
            content += f"\n{k:{dist}s}{counter:7,d}{train_time:6.0f}m{loss:8.2f}{avg_loss:8.2f}"

        for p in paginate(content.strip(), header=header):
            await ctx.send(p)

    @parsers.command(
        name='hell',
        brief='Demonspawn an object',
        parser_args=[
            parsers.Arg('category', nargs='?', default='random', help='Category'),
            parsers.Arg('--samples', '-s', default=12, type=int, help='Samples'),
            parsers.Arg('--truncation', '-t', default=0.2, type=float, help='Truncation'),
            parsers.Arg('--noise_a', '-na', default=3, type=int, help='Source noise'),
            parsers.Arg('--fps', '-fps', default=1, type=int, help='FPS', choices=range(1, 61)),
            parsers.Arg('--size', '-sz', default=128, type=int, help='GAN size', choices=(128, 256, 512)),
            parsers.Arg('--video', '-v', default=False, help='Process to video', action='store_true'),
        ],
    )
    @open_connection_check()
    async def hell(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        params = vars(parsed)
        params['name_from'] = params.pop('category')
        await self.run_biggan(ctx, 'hell', params)

    @parsers.command(
        name='slerp',
        brief='Slerp things',
        parser_args=[
            parsers.Arg('category', nargs='?', default='random', help='Category'),
            parsers.Arg('--samples', '-s', default=1, type=int, help='Samples'),
            parsers.Arg('--interps', '-i', default=12, type=float, help='Interps'),
            parsers.Arg('--truncation', '-t', default=0.2, type=float, help='Truncation'),
            parsers.Arg('--noise_a', '-na', default=3, type=int, help='Source noise'),
            parsers.Arg('--noise_b', '-nb', default=30, type=int, help='Target noise'),
            parsers.Arg('--fps', '-fps', default=10, type=int, help='FPS', choices=range(1, 61)),
            parsers.Arg('--size', '-sz', default=128, type=int, help='GAN size', choices=(128, 256, 512)),
            parsers.Arg('--video', '-v', default=False, help='Process to video', action='store_true'),
        ],
    )
    @open_connection_check()
    async def slerp(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        params = vars(parsed)
        params['name_from'] = params.pop('category')
        await self.run_biggan(ctx, 'slerp', params)

    @parsers.command(
        name='transform',
        brief='Transform things into other things',
        parser_args=[
            parsers.Arg('name_from', nargs='?', default='random', help='Source category'),
            parsers.Arg('name_to', nargs='?', default='random', help='Target category'),
            parsers.Arg('--samples', '-s', default=1, type=int, help='Samples'),
            parsers.Arg('--interps', '-i', default=12, type=float, help='Interps'),
            parsers.Arg('--truncation', '-t', default=0.2, type=float, help='Truncation'),
            parsers.Arg('--noise_a', '-na', default=0, type=int, help='Source noise'),
            parsers.Arg('--noise_b', '-nb', default=0, type=int, help='Target noise'),
            parsers.Arg('--fps', '-fps', default=10, type=int, help='FPS', choices=range(1, 61)),
            parsers.Arg('--size', '-sz', default=128, type=int, help='GAN size', choices=(128, 256, 512)),
            parsers.Arg('--video', '-v', default=False, help='Process to video', action='store_true'),
        ],
    )
    @open_connection_check()
    async def transform(self, ctx: commands.Context, *args):
        parsed = ctx.command.parser.parse_args(args)
        await self.run_biggan(ctx, 'transform', vars(parsed))

    @commands.command(name='whodis', brief='Machine learned guessing thing')
    @open_connection_check()
    async def whodis(self, ctx, *args):
        msg = await ctx.send('Generating thinking sounds...')
        check_models = {'andrei_3l128bi': 'Andrei',
                        'jens_3l128bi': 'Jens',
                        'stig_2l128bi': 'Stig',
                        'yan_2l128bi': 'Yan'}
        send_data = dict(check_models=list(check_models.keys()), in_str=' '.join(args))
        # Send run request
        r = await self.bot.brains_post_request('/guess/run', data=send_data)
        if not r.ok:
            return await msg.edit(content=f'Thinking sounds generation failed: {r.fail_msg}')
        tmp = 'Many thinking sounds have been performed...'
        for k, v in r.data.items():
            tmp += f"\n{check_models[k]}: {v:.0f}%"
        return await msg.edit(content=tmp)

    @parsers.group(name='imagenet', brief='Image net group', invoke_without_command=False)
    async def imagenet(self, ctx):
        return

    @imagenet.command(
        name='list',
        brief='List categories the bot was trained to recognize',
        parser_args=[
            parsers.Arg('category', nargs='?', default='obj', help='Category for which to list objects'),
            parsers.Arg('--show-categories', default=False, help='List categories instead of objects', action='store_true'),
        ]
    )
    @open_connection_check()
    async def imagenet_list(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        if parsed.show_categories:
            r = await self.bot.brains_get_request('/image_label/list')
        else:
            r = await self.bot.brains_get_request('/image_label/list', params=dict(category=parsed.category))
        if not r.ok:
            return await ctx.send(r.fail_msg)
        if parsed.show_categories:
            return await ctx.send(', '.join(sorted(r.data.keys())))
        for p in paginate(to_columns_vert(r.data[parsed.category], sort=True)):
            await ctx.send(p)

    @imagenet.command(
        name='run',
        brief='Try to classify an image',
        parser_args=[
            parsers.Arg('source', nargs='*', help='User who sent image or message ID'),
            parsers.Arg('--pnas', '-p', default=False, help='Use pnas, no idea what that means anymore', action='store_true'),
            parsers.Arg('--category', '-c', default='obj', type=str, help='What to category to classify image as', choices=('obj', 'subs', 'meme')),
        ],
        usage='Most recent image is used if no user or message ID is specified.'
    )
    @open_connection_check()
    async def imagenet_run(self, ctx, *args):
        parsed = ctx.command.parser.parse_args(args)
        source = ' '.join(parsed.source)
        cat_names = {
            "obj": "object type",
            "subs": "subreddit",
            "meme": "meme quality",
        }
        embed = emh.embed_init(self.bot, f'Guess {cat_names[parsed.category]}')
        embed.title = 'Searching for image'
        if source:
            embed.set_footer(text=f"Searching for image from {parsed.source}.", icon_url=embed.footer.icon_url)
        else:
            embed.set_footer(text=f"Searching for most recent image.", icon_url=embed.footer.icon_url)
        msg: discord.Message = await ctx.send(embed=embed)
        res: Message = await Message.with_url(ctx, source, img_only=True)
        if not res:
            return await emh.embed_img_not_found(msg, embed)
        embed.title = f"{res.author.display_name}'s image found"
        embed.description = 'Feeding the machine.'
        await msg.edit(embed=embed)
        r = await self.bot.brains_post_request('/image_label/run', data=dict(model_type=parsed.category, url=res.first_image))
        if not r.ok:
            return await msg.edit(embed=r.fail_embed(embed))
        results, labels = np.array(r.data['results']), r.data['labels']
        embed.description = f'Mr. Bot thinks this is:\n'
        top_k = results.argsort()[-5:][::-1]
        for i in top_k:
            embed.description += f"{labels[i]}: {results[i]*100:.1f}%\n"
        embed.set_footer(text=f"Completed in {human_seconds(r.time, num_units=1, precision=2)}", icon_url=embed.footer.icon_url)
        return await msg.edit(embed=embed)

    async def run_biggan(self, ctx: commands.Context, cmd: str, params: dict):
        # Get categories
        r = await self.bot.brains_get_request('/biggan/categories')
        if not r.ok:
            return await ctx.send(r.fail_msg)
        categories = r.data
        # Get reverse categories
        r = await self.bot.brains_get_request('/biggan/categories/backwards')
        if not r.ok:
            return await ctx.send(r.fail_msg)
        categories_backwards = r.data
        name_a = params.pop('name_from')
        name_b = params.pop('name_to', None)
        gan_size = params.pop('size')
        embed = emh.embed_init(self.bot, cmd.capitalize())
        # Check max size
        if ctx.author.id != self.bot.owner_id:
            if cmd == 'transform' and params['samples']*params['interps']*gan_size > 8000:
                embed.colour = discord.Colour.red()
                embed.add_field(name="Error", value="Reduce sample, interpolation or size.", inline=False)
                return await ctx.send(embed=embed)
            elif params['samples'] * params['size'] > 8000:
                embed.colour = discord.Colour.red()
                embed.add_field(name="Error", value="Reduce sample or size.", inline=False)
                return await ctx.send(embed=embed)

        if name_a == 'random':
            params['cat_a'], name_a = self.randomize_gan_cat(categories_backwards)
        else:
            params['cat_a'], name_a = self.find_gan_cat(categories, name_a)
        if cmd == 'transform':
            if name_b == 'random':
                params['cat_b'], name_b = self.randomize_gan_cat(categories_backwards)
            else:
                params['cat_b'], name_b = self.find_gan_cat(categories, name_b)

        if params['cat_a'] is None:
            if cmd == 'transform':
                embed.add_field(name="Source category not found", value=name_a, inline=True)
            else:
                embed.add_field(name="Category not found", value=name_a, inline=True)
            embed.colour = discord.Colour.red()
            return await ctx.send(embed=embed)
        if cmd == 'transform' and params['cat_b'] is None:
            embed.add_field(name="Target category not found", value=name_b, inline=True)
            embed.colour = discord.Colour.red()
            return await ctx.send(embed=embed)

        if cmd in ('transform', 'slerp'):
            if cmd == 'transform':
                embed.add_field(name="Source category", value=name_a, inline=True)
                embed.add_field(name="Destination category", value=name_b, inline=True)
            else:
                embed.add_field(name="Category", value=name_a, inline=True)
            params_str = (
                "Source noise: {noise_a}, target noise: {noise_b}\nsamples: {samples}, "
                "interps: {interps}, truncation: {truncation}\n"
                "{fps} FPS {file_fmt}"
            ).format(
                noise_a=params['noise_a'],
                noise_b=params['noise_b'],
                samples=params['samples'],
                interps=params['interps'],
                truncation=params['truncation'],
                fps=params['fps'],
                file_fmt='video' if params['video'] else 'GIF',
            )
        # hell
        else:
            embed.add_field(name="Category", value=name_a, inline=True)
            params_str = (
                "Noise: {noise_a}, samples: {samples}, truncation: {truncation}\n"
                "{fps} FPS {file_fmt}"
            ).format(
                noise_a=params['noise_a'],
                samples=params['samples'],
                truncation=params['truncation'],
                fps=params['fps'],
                file_fmt='video' if params['video'] else 'GIF',
            )
        embed.add_field(name="Parameters", value=params_str, inline=False)
        embed.set_footer(text="Brains", icon_url=embed.footer.icon_url)
        msg = await ctx.send(embed=embed)
        url = f'/biggan/run/{cmd}/{gan_size}'
        await self.bot.brains_image_request(url, msg=msg, embed=embed, params=dict(get_image='true'), data=params)

    @staticmethod
    def find_gan_cat(categories: dict, cat_from: str) -> Tuple[Optional[int], str]:
        # Returns tuple with names if found, otherwise tuple with list of suggestions.
        # Look for category
        name_a = None
        cat_a = None
        for name, num in categories.items():
            if (name_a is None) and (cat_from == name):
                name_a = name
                cat_a = num
            if name_a is not None:
                break
        # Search for closest matches
        if name_a is None:
            ret_str = ", ".join(find_similar_str(cat_from, list(categories)))
            if not ret_str:
                return None, f'Nothing close to {cat_from} found.'
            if len(ret_str) > 500:
                return None, 'Too many suggestions to display, be more specific.'
            return None, f'Suggestions: {ret_str}'
        else:
            return cat_a, name_a

    @staticmethod
    def randomize_gan_cat(categories_backwards: dict) -> Tuple[int, str]:
        cat_a = random.choice(list(categories_backwards.keys()))
        return int(cat_a), categories_backwards[cat_a]


def setup(bot):
    bot.add_cog(MachineLearning(bot))
