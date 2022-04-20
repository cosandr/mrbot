from __future__ import annotations

import asyncio
import itertools
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from jellyfish import jaro_winkler_similarity

import ext.embed_helpers as emh
from ext.context import Context
from ext.psql import create_table
from ext.utils import fmt_timedelta, human_large_num, str_or_none
from . import utils as pu

if TYPE_CHECKING:
    from mrbot import MrBot


class PepeCoins(commands.Cog, name="Pepe Coins"):
    # Postgres
    psql_table_name = 'pepecoins'
    psql_table = f"""
        CREATE TABLE {psql_table_name} (
            player  pepe_player NOT NULL,
            stats   pepe_stats,
            units   pepe_units,
            updated TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE OR REPLACE FUNCTION update_{psql_table_name}() RETURNS trigger AS $$
        BEGIN
            NEW.updated=now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS trigger_update_{psql_table_name} ON {psql_table_name};
        CREATE TRIGGER trigger_update_{psql_table_name} BEFORE insert OR update ON {psql_table_name}
            FOR EACH ROW EXECUTE FUNCTION update_{psql_table_name}();
        CREATE UNIQUE INDEX unique_player_id ON {psql_table_name}(((player).id));
    """
    psql_all_tables = {(psql_table_name,): psql_table}
    con = None                        # Pool connection
    add_coins = f"UPDATE {psql_table_name} SET player.coins=(player).coins+$1 WHERE (player).id=$2"
    rem_coins = f"UPDATE {psql_table_name} SET player.coins=(player).coins-$1 WHERE (player).id=$2"
    # GAMBLING
    claim_base = 4000                 # How many pepe points to add per claim
    claim_wait = timedelta(hours=10)  # Time before you can claim more pepe coins
    claim_reset = timedelta(days=1)   # Time after we reset streak
    bet_wait = 10                     # Time to wait for others to bet
    # GAME
    info_time = 20                    # How many seconds the info embed is updated for

    def __init__(self, bot):
        self.bot: MrBot = bot
        # --- Logger ---
        self.logger = logging.getLogger(f'{self.bot.logger.name}.{self.__class__.__name__}')
        self.logger.setLevel(logging.DEBUG)
        # --- Logger ---
        self.bets = {}
        self.bet_players = {}

    async def cog_load(self):
        await self.bot.sess_ready.wait()
        names = itertools.chain(*self.psql_all_tables.keys())
        q = self.psql_all_tables.values()
        async with self.bot.psql_lock:
            await pu.match_sql(self.bot.pool)
            await create_table(self.bot.pool, names, q, self.logger)

    # GAME FUNCTIONS
    @commands.command(
        brief="Buy more coin producing stuff",
        usage="1. Item you're buying\n2. Amount, default is 1.")
    async def buy(self, ctx: Context, what: str, amount: int = 1):
        # Interpret input
        if what in 'midget':
            what = 'midget' if amount == 1 else 'midgets'
            unit = "midget"
        elif what in 'worker':
            what = 'worker' if amount == 1 else 'workers'
            unit = "worker"
        elif what in 'factory':
            what = 'factory' if amount == 1 else 'factories'
            unit = "factory"
        else:
            await ctx.send(f"The item you are trying to buy couldn't be found.")
            return
        await self.buy_upgrade(ctx, what, unit, amount, upgrade=False)

    @commands.command(name='upgrade', brief='Upgrade your coin factories',
                      usage="1. Item to upgrade.\n")
    async def upgrade(self, ctx: Context, what: str, amount: int = 1):
        # Interpret input
        if what in 'midget':
            what = 'midget' if amount == 1 else 'midgets'
            unit = "midget"
        elif what in 'worker':
            what = 'worker' if amount == 1 else 'workers'
            unit = "worker"
        elif what in 'factory':
            what = 'factory' if amount == 1 else 'factories'
            unit = "factory"
        else:
            return await ctx.send(f"The unit you are trying to upgrade couldn't be found.")
        await self.buy_upgrade(ctx, what, unit, amount, upgrade=True)

    # GAME INFO
    @commands.command(brief="Real time display of game stats")
    async def prodinfo(self, ctx: Context):
        msg = await ctx.send(f"Coin production display for {ctx.author.display_name}")
        asyncio.create_task(self.game_task(ctx.author.id, msg))

    @commands.command(brief='Display game stats')
    async def gamestats(self, ctx: Context):
        tmp = ''
        async with self.bot.pool.acquire() as con:
            q = f"SELECT * FROM {self.psql_table_name}"
            results = await con.fetch(q)
        for p in results:
            tmp += f"{p['player']['name']}, coins: {p['stats']['tcoins']:,}, CPD: {human_large_num(pu.cps(p['units'])*86400)}\n"
            for k, v in dict(p['units']).items():
                if v['count'] != 0:
                    tmp += f"-- {k}: {v['count']} level {v['level']}\n"
        return await ctx.send(f"```{tmp}```")

    # GAMBLING FUNCTIONS
    @commands.command(brief='First player chooses bet amount and roll limit')
    async def deathroll(self, ctx: Context, roll_lim: int):
        # Roll up to roll_lim, then roll up to generated number under you get 1. Person who gets 1 wins.
        if roll_lim <= 0:
            return await ctx.send('Maximum roll must be larger than 0.')
        get_p = await self.con.prepare(f"SELECT (player).name,(player).id,(player).coins FROM {self.psql_table_name} WHERE (player).id=$1")
        p_one = await get_p.fetchrow(ctx.author.id)
        if not p_one:
            await self.add_new_player(self.con, player=dict(name=ctx.author.display_name, id=ctx.author.id, coins=0))
            await ctx.send(f"New player {ctx.author.display_name} added with 0 coins.")
            return
        if p_one['coins'] < roll_lim:
            return await ctx.send(f"{p_one['name']} cannot bet {human_large_num(roll_lim)} coins, balance {human_large_num(p_one['coins'])}.")
        # Embed setup
        embed = emh.embed_init(self.bot, "Deathroll")
        embed.title = "Game waiting to start"
        embed.description = "Type join to enter the game."
        players_str = f"{p_one['name']} has bet {human_large_num(roll_lim)} coins."
        embed.add_field(name="Joined players", value=players_str, inline=False)
        msg = await ctx.send(embed=embed)

        # Message check, cannot be OP/Bot.
        def pred(m):
            return ((m.author.id != ctx.author.id) and
                    (m.author.id != self.bot.user.id) and
                    (m.content.lower() == 'join'))

        try:
            msg = await self.bot.wait_for('message', check=pred, timeout=10.0)
            p_two = await get_p.fetchrow(msg.author.id)
            if not p_two:
                await self.add_new_player(self.con, player=dict(name=msg.author.display_name, id=msg.author.id, coins=0))
                await ctx.send(f"New player {msg.author.display_name} added with 0 coins.")
                return
            if p_two['coins'] < roll_lim:
                return await ctx.send(f"{p_two['name']} cannot bet {human_large_num(roll_lim)} coins, balance {human_large_num(p_two['coins'])}.")
            # Game start embed edit
            players_str += f"\n{p_two['name']} has bet {human_large_num(roll_lim)} coins."
            embed.set_field_at(0, name="Joined players", value=players_str)
            embed.title = 'Game starting'
            embed.description = ''
            msg = await msg.edit(embed=embed)
            await asyncio.sleep(3)
            embed.clear_fields()
            embed.title = 'Rolling'
            # First roll
            p_one_roll = random.randint(1, roll_lim)
            p_two_roll = random.randint(1, p_one_roll)
            embed.description += f"{p_one['name']} rolled: {p_one_roll:,}, " + \
                                 f"{p_two['name']} rolled: {p_two_roll:,}\n"
            msg = await msg.edit(embed=embed)
            while True:
                p_one_roll = random.randint(1, p_two_roll)
                if p_one_roll == 1:
                    break
                p_two_roll = random.randint(1, p_one_roll)
                if p_two_roll == 1:
                    break
                await asyncio.sleep(1)
                embed.description += f"{p_one['name']} rolled: {p_one_roll:,}, " + \
                                     f"{p_two['name']} rolled: {p_two_roll:,}\n"
                msg = await msg.edit(embed=embed)
            embed.title = 'Game results'
            # OP wins
            if p_two_roll == 1:
                await self.con.execute(self.add_coins, roll_lim, p_one['id'])
                await self.con.execute(self.rem_coins, roll_lim, p_two['id'])
                p_one = await get_p.fetchrow(p_one['id'])
                p_two = await get_p.fetchrow(p_two['id'])
                embed.description += f"{p_one['name']} won {human_large_num(roll_lim)} coins by rolling {p_one_roll}, " + \
                                     f"balance {human_large_num(p_one['coins'])}.\n{p_two['name']} " + \
                                     f"lost {human_large_num(roll_lim)} coins by rolling {p_two_roll}, balance {human_large_num(p_two['coins'])}.\n"
                msg = await msg.edit(embed=embed)
                return
            # Joined player wins
            await self.con.execute(self.rem_coins, roll_lim, p_one['id'])
            await self.con.execute(self.add_coins, roll_lim, p_two['id'])
            p_one = await get_p.fetchrow(p_one['id'])
            p_two = await get_p.fetchrow(p_two['id'])
            embed.description += f"{p_two['name']} won {human_large_num(roll_lim)} coins by rolling {p_two_roll}, " + \
                                 f"balance {human_large_num(p_two['coins'])}.\n{p_one['name']} " + \
                                 f"lost {human_large_num(roll_lim)} coins by rolling {p_one_roll}, balance {human_large_num(p_one['coins'])}.\n"
            await msg.edit(embed=embed)
            return

        except asyncio.TimeoutError:
            embed.title = 'Game cancelled'
            embed.description = 'Nobody else joined the deathroll.'
            embed.clear_fields()
            return await msg.edit(embed=embed)

    @commands.command(
        name="bet",
        brief="Bet on given number of coins",
        usage="1. Number of coins to bet.\nEveryone that has enough coins can then join by calling !bet themselves.",
    )
    async def bet(self, ctx: Context, bet_coins=None):
        if bet_coins is None:
            bet_coins = self.gamble_calc(ctx.guild.id, 'bet', max)
        try:
            bet_coins = int(bet_coins)
            if bet_coins <= 0:
                return await ctx.send('Coin amount must be larger than 0.')
        except Exception:
            return await ctx.send('Number input required.')
        get_p = f"SELECT (player).name,(player).coins FROM {self.psql_table_name} WHERE (player).id=$1"
        p = await self.con.fetchrow(get_p, ctx.author.id)
        if bet_coins > p['coins']:
            return await ctx.send(f"{p['name']}'s balance is {human_large_num(p['coins'])}, cannot bet {human_large_num(bet_coins)}.")
        if ctx.guild.id not in self.bets:
            self.bets[ctx.guild.id] = {}
            self.bet_players[ctx.guild.id] = {}
        if ctx.author.id in self.bets[ctx.guild.id]:
            return await ctx.send(f"{p['name']} has already bet in this game.")
        bet_sum = self.gamble_calc(ctx.guild.id, 'bet', sum)
        # We are the first player.
        if bet_sum is None or bet_sum == 0:
            # Check if rolled number already exists.
            invalid = True
            rolled = 0
            while invalid:
                rolled = random.randint(1, 100)
                invalid = self.check_rolls(ctx.guild.id, rolled)
            self.bets[ctx.guild.id][ctx.author.id] = {'bet': bet_coins, 'roll': rolled}
            # Clean up from last game.
            embed = emh.embed_init(self.bot, "Bet")
            # Add countdown field
            embed.add_field(name="Countdown", value=f"Seconds remaining: {self.bet_wait}.", inline=False)
            # This string tracks joined players.
            self.bet_players[ctx.guild.id] = f"{ctx.author.display_name} bet {human_large_num(bet_coins)}."
            embed.add_field(name=f"Joined players", value=self.bet_players[ctx.guild.id], inline=False)
            msg = await ctx.send(embed=embed)
            asyncio.create_task(self.bet_task(ctx.guild.id, embed, msg))
            return

        bet_max = self.gamble_calc(ctx.guild.id, 'bet', max)
        if bet_coins != bet_max:
            await ctx.send(f"{ctx.author.display_name} must bet {human_large_num(bet_max)} coins.")
            return
        invalid = True
        rolled = 0
        while invalid:
            rolled = random.randint(1, 100)
            invalid = self.check_rolls(ctx.guild.id, rolled)
        self.bet_players[ctx.guild.id] += f"{ctx.author.display_name} bet {human_large_num(bet_coins)}."
        self.bets[ctx.guild.id][ctx.author.id] = {'bet': bet_coins, 'roll': rolled}
        return

    @commands.command(brief='Claim pepe coins every 10 hours')
    async def claim(self, ctx: Context):
        embed = self.pepecoins_embed_init(ctx.author)
        claim_amount = self.claim_base
        has_claimed = False
        async with self.bot.pool.acquire() as con:
            q = f"SELECT (stats).claim_time,(stats).streak FROM {self.psql_table_name} WHERE (player).id=$1"
            res = await con.fetchrow(q, ctx.author.id)
            # Player doesn't exist
            if not res:
                await self.add_new_player(
                    con,
                    player=dict(name=ctx.author.display_name, id=ctx.author.id, coins=self.claim_base),
                    stats=dict(claim_time=datetime.now(timezone.utc)),
                )
                has_claimed = True
            q = f"UPDATE {self.psql_table_name} SET player.coins=(player).coins+$2, stats.claim_time=$3, stats.streak=$4 WHERE (player).id=$1"
            # Player never claimed before
            if not has_claimed and not res['claim_time']:
                await con.execute(q, ctx.author.id, claim_amount, datetime.now(timezone.utc), 1)
                has_claimed = True
            elif not has_claimed:
                delta_dt = datetime.now(timezone.utc) - res['claim_time']
                if delta_dt >= self.claim_reset:
                    await con.execute(q, ctx.author.id, self.claim_base, datetime.now(timezone.utc), 1)
                    has_claimed = True
                elif delta_dt >= self.claim_wait:
                    claim_amount = int(self.claim_base*(1.05**res['streak']))
                    await con.execute(q, ctx.author.id, claim_amount, datetime.now(timezone.utc), res['streak']+1)
                    has_claimed = True
            q = f"SELECT (player).coins,(stats).streak,(stats).claim_time FROM {self.psql_table_name} WHERE (player).id=$1"
            res = await con.fetchrow(q, ctx.author.id)
            if has_claimed:
                embed.colour = discord.Colour.green()
                embed.set_footer(text="Claim successful", icon_url=embed.footer.icon_url)
                embed.add_field(name="Coins", value=f"{human_large_num(res['coins'])}", inline=True)
                embed.add_field(name="Claim", value=f"Streak: {res['streak']}\nClaimed: {human_large_num(claim_amount)}", inline=False)
                await ctx.send(embed=embed)
            else:
                wait_td = (res['claim_time'] + self.claim_wait) - datetime.now(timezone.utc)
                embed.colour = discord.Colour.red()
                embed.set_footer(text="Claim failed", icon_url=embed.footer.icon_url)
                embed.add_field(name="Coins", value=f"{human_large_num(res['coins'])}", inline=True)
                embed.add_field(name="Claim", value=f"Streak: {res['streak']}\nClaim in: {fmt_timedelta(wait_td)}", inline=False)
                await ctx.send(embed=embed)

    @commands.command(
        name="transfer",
        brief='Transfer given amount to user',
        usage="1. Number of coins to transfer.\n2. User to transfer coins to.",
    )
    async def transfer(self, ctx: Context, amount: int, *, username: str):
        embed = self.pepecoins_embed_init(ctx.author)
        q = f"SELECT (player).name,(player).id,(player).coins FROM {self.psql_table_name} WHERE (player).id=$1"
        send_p = await self.con.fetchrow(q, ctx.author.id)
        if not send_p:
            await self.add_new_player(self.con, player=dict(name=ctx.author.display_name, id=ctx.author.id, coins=0))
            await ctx.send(f"New player {ctx.author.display_name} added with 0 coins.")
            return
        embed.add_field(name="Sender Coins", value=f"{human_large_num(send_p['coins'])}", inline=True)
        if amount <= 0:
            embed.colour = discord.Colour.red()
            embed.set_footer(text="Transfer failed", icon_url=embed.footer.icon_url)
            embed.add_field(name="Transfer amount error", value=f"Must be larger than 0.", inline=True)
            await ctx.send(embed=embed)
            return
        if amount > send_p['coins']:
            embed.colour = discord.Colour.red()
            embed.set_footer(text="Transfer failed", icon_url=embed.footer.icon_url)
            embed.add_field(name="Transfer amount error", value=f"You don't have {human_large_num(amount)} coins.", inline=True)
            await ctx.send(embed=embed)
            return
        embed.add_field(name="Transfer amount", value=f"{human_large_num(amount)}", inline=True)
        recv_p = await self.find_similar_player(self.con, username)
        if not recv_p:
            embed.colour = discord.Colour.red()
            embed.set_footer(text="Transfer failed", icon_url=embed.footer.icon_url)
            embed.add_field(name="Recipient Error", value=f"{username} not found.", inline=False)
            await ctx.send(embed=embed)
            return
        if send_p['id'] == recv_p['id']:
            embed.colour = discord.Colour.red()
            embed.set_footer(text="Transfer failed", icon_url=embed.footer.icon_url)
            embed.add_field(name="Recipient Error", value="You cannot send coins to yourself.", inline=False)
            await ctx.send(embed=embed)
            return
        if not ctx.guild.get_member(recv_p['id']):
            embed.colour = discord.Colour.red()
            embed.set_footer(text="Transfer failed", icon_url=embed.footer.icon_url)
            embed.add_field(name="Recipient Error", value="Recipient must be in the same guild as sender.", inline=False)
            await ctx.send(embed=embed)
            return
        await self.con.execute(self.rem_coins, amount, send_p['id'])
        await self.con.execute(self.add_coins, amount, recv_p['id'])
        send_p = await self.con.fetchrow(q, send_p['id'])
        recv_p = await self.con.fetchrow(q, recv_p['id'])
        embed.colour = discord.Colour.green()
        embed.set_footer(text="Transfer complete", icon_url=embed.footer.icon_url)
        embed.add_field(name="Recipient", value=f"Name: {recv_p['name']}\nCoins: {human_large_num(recv_p['coins'])}", inline=False)
        embed.set_field_at(0, name="Sender Coins", value=f"{human_large_num(send_p['coins'])}", inline=True)
        return await ctx.send(embed=embed)

    @commands.command(brief="Display every players' balance")
    async def bal(self, ctx: Context):
        tmp = ''
        async with self.bot.pool.acquire() as con:
            q = f"SELECT (player).name,(player).coins FROM {self.psql_table_name} ORDER BY (player).coins DESC"
            results = await con.fetch(q)
        for p in results:
            tmp += f"{p['name']}: {human_large_num(p['coins'])}\n"
        return await ctx.send(f"```{tmp}```")

    # BACKGROUND TASKS
    async def bet_task(self, guild_id, embed, msg):
        for i in range(self.bet_wait, 0, -1):
            embed.set_field_at(0, name="Countdown", value=f"Seconds remaining: {i}.", inline=False)
            embed.set_field_at(1, name=f"Joined players", value=self.bet_players[guild_id], inline=False)
            msg = await msg.edit(embed=embed)
            await asyncio.sleep(1)
        # Bet ended
        bet_max = self.gamble_calc(guild_id, 'bet', max)
        bet_sum = self.gamble_calc(guild_id, 'bet', sum)
        # Sum equals max if only one player joined.
        if bet_sum == bet_max:
            embed.title = 'Nobody else bet, game cancelled.'
            embed.clear_fields()
            msg = await msg.edit(embed=embed)
        else:
            result_str = ''
            roll_max = self.gamble_calc(guild_id, 'roll', max)
            con = await self.bot.pool.acquire()
            get_p = f"SELECT (player).name,(player).id,(player).coins FROM {self.psql_table_name} WHERE (player).id=$1"
            for k, v in self.bets[guild_id].items():
                if v['roll'] == roll_max:
                    coins_won = bet_sum - v['bet']
                    await con.execute(self.add_coins, k)
                    p = await con.fetchrow(get_p, k)
                    result_str += f"{p['name']} has won {human_large_num(coins_won)} coins by rolling " + \
                                  f"{v['roll']:,}, balance {human_large_num(p['coins'])}.\n"
                elif (v['roll'] != 0) and (v['roll'] != roll_max):
                    await con.execute(self.rem_coins, k)
                    p = await con.fetchrow(get_p, k)
                    result_str += f"{p['name']} has lost {human_large_num(v['bet'])} coins by rolling " +\
                                  f"{v['roll']:,}, balance {human_large_num(p['coins'])}.\n"
            embed.title = 'Game results'
            embed.clear_fields()
            embed.description = result_str
            await msg.edit(embed=embed)
            await self.bot.pool.release(con)
        self.clean_after_bet(guild_id)

    async def game_task(self, p_id, msg):
        self.logger.info(f"Info start for {p_id}.")
        embed = emh.embed_init(self.bot, "Production Display")
        con = await self.bot.pool.acquire()
        p = await con.fetchrow(f"SELECT (stats).tcoins,(stats).last_tick,units FROM {self.psql_table_name} WHERE (player).id=$1", p_id)
        tmp_coins = p['tcoins']
        for _ in range(3):
            (cost_dict, gen_dict, spent_dict, cps) = pu.prod_calc(p['units'])
            tmp_coins += cps
            embed.clear_fields()
            embed.title = f"Display running..."
            embed.add_field(
                name='Coins',
                value=f"Amount: {tmp_coins:,.0f}\nCPS: {cps:,.0f}\nCPD: {cps*86400:,.0f}"
            )
            for k, v in pu.unit_param.items():
                embed.add_field(
                    name=f"{v['name']}",
                    value=(f"Amount: {p['units'][k]['count']}\nLevel: {p['units'][k]['level']}\n"
                           f"CPD from unit: {gen_dict[k]['unit']*86400:,.0f}\nCPD from upgrades: {gen_dict[k]['level']*86400:,.0f}\n"
                           f"Next unit cost: {cost_dict[k]['unit']:,.0f}\nNext upgrade cost: {cost_dict[k]['level']:,.0f}\n"
                           f"Spent on units: {spent_dict[k]['unit']:,.0f}\nSpent on upgrades: {spent_dict[k]['level']:,.0f}")
                )
            msg = await msg.edit(embed=embed)
            await asyncio.sleep(1)
        await con.execute(f"UPDATE {self.psql_table_name} SET stats.tcoins=(stats).tcoins+$2,stats.last_tick=$3 WHERE (player).id=$1",
                          p_id, pu.tick(p), datetime.now(timezone.utc))
        await self.bot.pool.release(con)
        self.logger.info(f"Info end for {p_id}.")
        embed.title = f"Display stopped."
        await msg.edit(embed=embed)

    # DEBUG FUNCTIONS
    @commands.group(hidden=True)
    @commands.is_owner()
    async def pd(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            return await ctx.list_group_subcmds()

    @pd.command(hidden=True)
    async def cost(self, ctx: Context, amount: int = 10, ucount: int = 0, lcount: int = 0):
        tmp = f"Costs for {amount} units/upgrades, starting from {ucount} units and {lcount} levels.\n"
        total_u = 0
        total_l = 0
        for v in pu.unit_param.values():
            r = v['r']
            ucost = (((r**ucount)*((r**amount)-1))/(r-1))*v['buy']
            lcost = (((v['ur']**lcount)*((v['ur']**amount)-1))/(v['ur']-1))*v['ucost']
            tmp += f"{v['name']}:\nUnit: {ucost:,.0f}\nLevel: {lcost:,.0f}\n"
            total_l += lcost
            total_u += ucost
        tmp += f"Total unit cost: {total_u:,.0f}\nTotal Upgrade cost: {total_l:,.0f}"
        return await ctx.send(tmp)

    @bet.before_invoke
    @prodinfo.before_invoke
    @deathroll.before_invoke
    @transfer.before_invoke
    async def get_pool_con(self, _ctx: Context):
        if not self.con:
            self.con = await self.bot.pool.acquire()

    @bet.after_invoke
    @prodinfo.after_invoke
    @deathroll.after_invoke
    @transfer.after_invoke
    async def release_pool_con(self, _ctx: Context):
        if self.con:
            await self.bot.pool.release(self.con)
            self.con = None

    # HELPER FUNCTIONS
    def gamble_calc(self, guild, check, op):
        active_players = self.bets.get(guild, None)
        if not active_players:
            return None
        return op([v[check] for v in active_players.values()])

    def check_rolls(self, guild, val):
        # Returns true if val is found.
        active_players = self.bets.get(guild, None)
        if not active_players:
            return None
        for v in active_players.values():
            if v['roll'] == val:
                return True
        return False

    def clean_after_bet(self, guild):
        active_players = self.bets.get(guild, None)
        if not active_players:
            return None
        rem_list = []
        for p, v in active_players.items():
            if v['bet'] > 0:
                rem_list.append(p)
        for r in rem_list:
            del active_players[r]

    def pepecoins_embed_init(self, usr):
        embed = discord.Embed()
        embed.colour = discord.Colour.dark_blue()
        embed.set_author(name=usr.display_name, icon_url=str_or_none(usr.avatar))
        embed.set_footer(icon_url=str_or_none(self.bot.user.avatar))
        return embed

    async def add_new_player(self, con, player, stats=None, units=None):
        if stats is None:
            stats = {}
        if units is None:
            units = {}
        sql_stats = pu.stats_struc
        sql_stats.update(stats)
        sql_units = pu.units_struc
        sql_units.update(units)
        q = f"INSERT INTO {self.psql_table_name} (player, stats, units) VALUES ($1, $2, $3)"
        await con.execute(q, player, sql_stats, sql_units)
        self.logger.info(f"New player ID {player['id']} added.")

    async def find_similar_player(self, con, name: str):
        results = await con.fetch(f"SELECT * FROM {self.psql_table_name}")
        for res in results:
            if ((jaro_winkler_similarity(name, res['player']['name']) > 0.8) or
                    name in res['player']['name']):
                q = f"SELECT (player).id,(player).name,(player).coins FROM {self.psql_table_name} WHERE (player).id=$1"
                return await con.fetchrow(q, res['player']['id'])
        return None

    async def buy_upgrade(self, ctx: Context, what: str, unit: str, amount: int, upgrade=False):
        async with self.bot.pool.acquire() as con:
            q = f"SELECT (stats).tcoins,(units).{unit} FROM {self.psql_table_name} WHERE (player).id=$1"
            res = await con.fetchrow(q, ctx.author.id)
            # Player doesn't exist
            if not res:
                await self.add_new_player(con, player=dict(name=ctx.author.display_name, id=ctx.author.id, coins=0))
                await ctx.send(f"New player {ctx.author.display_name} added with 0 coins.")
                return
            if upgrade:
                if res[unit]['count'] == 0:
                    return await ctx.send(f"{ctx.author.display_name} has no {what} to upgrade.")
                cost = pu.upgrade_cost(unit, dict(res[unit]), amount)
                q_update = f"UPDATE {self.psql_table_name} SET stats.tcoins=(stats).tcoins-$1,units.{unit}.level=(units).{unit}.level+$2 WHERE (player).id=$3"
            else:
                cost = pu.buy_cost(unit, dict(res[unit]), amount)
                q_update = f"UPDATE {self.psql_table_name} SET stats.tcoins=(stats).tcoins-$1,units.{unit}.count=(units).{unit}.count+$2 WHERE (player).id=$3"
            if cost > res['tcoins']:
                await ctx.send(f"{ctx.author.display_name} has {human_large_num(res['tcoins'])} coins but needs {human_large_num(cost)} coins to buy {amount} {what}.")
                return
            await con.execute(q_update, cost, amount, ctx.author.id)
            q = f"SELECT (stats).tcoins,units FROM {self.psql_table_name} WHERE (player).id=$1"
            res = await con.fetchrow(q, ctx.author.id)
            return await ctx.send((f"{ctx.author.display_name} has {'upgrade' if upgrade else 'bought'} {amount} {what} for {human_large_num(cost)} coins."
                                   f"Coins: {human_large_num(res['tcoins'])}\nCPD: {human_large_num(pu.cps(res['units'])*86400)}"))
