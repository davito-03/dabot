import logging
import discord
from discord.ext import commands
import random
import datetime
import asyncio
from utils.helpers import tr

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')
        self._economy_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info('Economy Cog loaded.')

    def _symbol(self, guild_id):
        try:
            return self.bot.config.get(guild_id, "economy.currency_symbol") or "🦞"
        except Exception:
            return "🦞"

    def _t(self, ctx, key, fallback="", **kwargs):
        guild_id = getattr(getattr(ctx, "guild", None), "id", None)
        return tr(self.bot, guild_id, key, fallback, **kwargs)

    async def get_balance(self, user_id, guild_id=None):
        if guild_id is None:
            return 0, 0
        result = await self.bot.db.fetch(
            "SELECT balance, bank FROM guild_economy WHERE user_id = ? AND guild_id = ?",
            user_id, guild_id
        )
        if not result:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO guild_economy (user_id, guild_id, balance, bank) VALUES (?, ?, 0, 0)",
                user_id, guild_id
            )
            return 0, 0
        return result[0] or 0, result[1] or 0

    async def update_balance(self, user_id, amount, mode="wallet", guild_id=None):
        if guild_id is None:
            return
        column = {"wallet": "balance", "bank": "bank"}.get(mode)
        if not column:
            return
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            await db.execute(
                "INSERT OR IGNORE INTO guild_economy (user_id, guild_id, balance, bank) VALUES (?, ?, 0, 0)",
                (user_id, guild_id),
            )
            await db.execute(
                f"UPDATE guild_economy SET {column} = MAX(0, {column} + ?) WHERE user_id = ? AND guild_id = ?",
                (amount, user_id, guild_id),
            )
            await db.commit()

    async def _move_money(self, user_id, amount, source, target, guild_id):
        if amount <= 0 or source not in {"balance", "bank"} or target not in {"balance", "bank"}:
            return False
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            try:
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    "INSERT OR IGNORE INTO guild_economy (user_id, guild_id, balance, bank) VALUES (?, ?, 0, 0)",
                    (user_id, guild_id),
                )
                cur = await db.execute(
                    f"UPDATE guild_economy SET {source} = {source} - ?, {target} = {target} + ? WHERE user_id = ? AND guild_id = ? AND {source} >= ?",
                    (amount, amount, user_id, guild_id, amount),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    return False
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                raise

    async def _settle_gamble(self, user_id, amount, won, guild_id):
        """Apply one wager atomically, requiring the stake to exist at commit time."""
        if amount <= 0:
            return False
        delta = amount if won else -amount
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            try:
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    "INSERT OR IGNORE INTO guild_economy (user_id, guild_id, balance, bank) VALUES (?, ?, 0, 0)",
                    (user_id, guild_id),
                )
                cur = await db.execute(
                    "UPDATE guild_economy SET balance = balance + ? WHERE user_id = ? AND guild_id = ? AND balance >= ?",
                    (delta, user_id, guild_id, amount),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    return False
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                raise

    # --- Main Economy Group ---
    @commands.hybrid_group(name="eco", description="Economy commands.")
    async def eco(self, ctx):
        if ctx.invoked_subcommand is None:
             await ctx.send(self._t(ctx, "common.command_help", "Use `/eco balance`, `/eco work`, `/eco shop`, etc."))

    @eco.command(name="balance", aliases=["bal", "money"], description="Saldo de este servidor.")
    async def balance(self, ctx, member: discord.Member = None):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        member = member or ctx.author
        s = self._symbol(ctx.guild.id)
        wallet, bank = await self.get_balance(member.id, ctx.guild.id)
        embed = discord.Embed(
            title=self._t(ctx, "economy.balance_title", "Balance of {member}", member=member.display_name),
            description=self._t(ctx, "economy.balance_description", "Economy of **{guild}** (not shared with other servers).", guild=ctx.guild.name),
            color=discord.Color.from_str("#00FF88"),
        )
        embed.add_field(name=self._t(ctx, "economy.wallet", "Wallet"), value=f"{s} {wallet}", inline=True)
        embed.add_field(name=self._t(ctx, "economy.bank", "Bank"), value=f"{s} {bank}", inline=True)
        embed.add_field(name=self._t(ctx, "economy.total", "Total"), value=f"{s} {wallet + bank}", inline=True)
        await ctx.send(embed=embed)

    @eco.command(name="deposit", aliases=["dep"], description="Deposit money into your bank.")
    async def deposit(self, ctx, amount: str):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        wallet, bank = await self.get_balance(ctx.author.id, ctx.guild.id)
        
        if amount.lower() == "all":
            amount_int = wallet
        else:
            try:
                amount_int = int(amount)
            except ValueError:
                await ctx.send(self._t(ctx, "common.valid_amount", "Please enter a valid amount."))
                return

        if amount_int <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return

        if wallet < amount_int:
            await ctx.send(self._t(ctx, "common.insufficient_wallet", "You don't have enough money in your wallet."))
            return

        if not await self._move_money(ctx.author.id, amount_int, "balance", "bank", ctx.guild.id):
            await ctx.send(self._t(ctx, "common.insufficient_wallet", "You don't have enough money in your wallet."))
            return
        s = self._symbol(ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.deposit", "Deposited {symbol} {amount} into this server's bank.", symbol=s, amount=amount_int))

    @eco.command(name="withdraw", aliases=["with"], description="Withdraw money from your bank.")
    async def withdraw(self, ctx, amount: str):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        wallet, bank = await self.get_balance(ctx.author.id, ctx.guild.id)

        if amount.lower() == "all":
            amount_int = bank
        else:
            try:
                amount_int = int(amount)
            except ValueError:
                await ctx.send(self._t(ctx, "common.valid_amount", "Please enter a valid amount."))
                return

        if amount_int <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return
            
        if bank < amount_int:
            await ctx.send(self._t(ctx, "common.insufficient_bank", "You don't have enough money in your bank."))
            return

        if not await self._move_money(ctx.author.id, amount_int, "bank", "balance", ctx.guild.id):
            await ctx.send(self._t(ctx, "common.insufficient_bank", "You don't have enough money in your bank."))
            return
        s = self._symbol(ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.withdraw", "Withdrew {symbol} {amount} from this server's bank.", symbol=s, amount=amount_int))

    @eco.command(name="work", description="Work to earn money.")
    @commands.cooldown(1, 3600, commands.BucketType.member)
    async def work(self, ctx):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        earnings = random.randint(50, 200)
        jobs = ["Programmer", "Chef", "Driver", "Artist", "Teacher"]
        job = random.choice(jobs)
        s = self._symbol(ctx.guild.id)
        await self.update_balance(ctx.author.id, earnings, "wallet", ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.work", "You worked as a **{job}** in **{guild}** and earned **{symbol} {amount}**.", job=job, guild=ctx.guild.name, symbol=s, amount=earnings))

    @eco.command(name="daily", description="Claim your daily reward.")
    @commands.cooldown(1, 86400, commands.BucketType.member)
    async def daily(self, ctx):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        amount = 500
        s = self._symbol(ctx.guild.id)
        await self.update_balance(ctx.author.id, amount, "wallet", ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.daily", "Daily reward for **{guild}**: **{symbol} {amount}**.", guild=ctx.guild.name, symbol=s, amount=amount))

    @eco.command(name="crime", description="Commit a crime safely.")
    @commands.cooldown(1, 43200, commands.BucketType.member)
    async def crime(self, ctx):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        s = self._symbol(ctx.guild.id)
        chance = random.randint(1, 100)
        if chance > 40:
            earnings = random.randint(300, 800)
            await self.update_balance(ctx.author.id, earnings, "wallet", ctx.guild.id)
            await ctx.send(self._t(ctx, "economy.crime_success", "The crime succeeded: **{symbol} {amount}**.", symbol=s, amount=earnings))
        else:
            fine = random.randint(100, 300)
            wallet, _ = await self.get_balance(ctx.author.id, ctx.guild.id)
            actual_fine = min(fine, wallet)
            if actual_fine > 0:
                await self.update_balance(ctx.author.id, -actual_fine, "wallet", ctx.guild.id)
            await ctx.send(self._t(ctx, "economy.crime_caught", "You were caught. Fine: **{symbol} {amount}**.", symbol=s, amount=actual_fine))

    @eco.command(name="coinflip", aliases=["cf"], description="Flip a coin to gamble.")
    async def coinflip(self, ctx, choice: str, amount: int):
        if amount <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return

        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        choice = choice.lower()
        if choice not in ["heads", "tails", "cara", "cruz"]:
            await ctx.send(self._t(ctx, "common.invalid_coin", "Please specify heads/cara or tails/cruz."))
            return

        outcome = random.choice(["heads", "tails"])
        user_choice_map = {"cara": "heads", "cruz": "tails", "heads": "heads", "tails": "tails"}
        mapped_choice = user_choice_map[choice]
        
        s = self._symbol(ctx.guild.id)
        won = mapped_choice == outcome
        if not await self._settle_gamble(ctx.author.id, amount, won, ctx.guild.id):
            await ctx.send(self._t(ctx, "common.insufficient_money", "You don't have enough money."))
            return
        if won:
            await ctx.send(self._t(ctx, "economy.coin_win", "It landed on **{outcome}**. You won **{symbol} {amount}**.", outcome=outcome, symbol=s, amount=amount))
        else:
            await ctx.send(self._t(ctx, "economy.coin_loss", "It landed on **{outcome}**. You lost **{symbol} {amount}**.", outcome=outcome, symbol=s, amount=amount))

    @eco.command(name="dice", description="Roll a dice.")
    async def dice(self, ctx, amount: int):
        if amount <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return

        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        user_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)
        
        msg = self._t(ctx, "economy.dice_user", "You rolled: **{roll}**\nBot rolled: **{bot_roll}**\n", roll=user_roll, bot_roll=bot_roll)
        
        s = self._symbol(ctx.guild.id)
        if user_roll > bot_roll:
            won = True
            msg += self._t(ctx, "economy.dice_win", "You won **{symbol} {amount}**.", symbol=s, amount=amount)
        elif user_roll < bot_roll:
            won = False
            msg += self._t(ctx, "economy.dice_loss", "You lost **{symbol} {amount}**.", symbol=s, amount=amount)
        else:
            msg += self._t(ctx, "economy.dice_draw", "Draw, your money is returned.")
            await ctx.send(msg)
            return
        if not await self._settle_gamble(ctx.author.id, amount, won, ctx.guild.id):
            await ctx.send(self._t(ctx, "common.insufficient_money", "You don't have enough money."))
            return
        await ctx.send(msg)

    @eco.command(name="shop", description="View the shop.")
    async def shop(self, ctx):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        s = self._symbol(ctx.guild.id)
        items = await self.bot.db.fetch_all(
            "SELECT item_name, price, description FROM guild_shop WHERE guild_id = ?",
            ctx.guild.id
        )
        embed = discord.Embed(title=self._t(ctx, "economy.shop_title", "{guild} shop", guild=ctx.guild.name), color=discord.Color.blue())
        if not items:
            embed.description = self._t(ctx, "economy.shop_empty", "This server's shop is empty. An admin can use `/ecoadmin additem`.")
        else:
            for name, price, desc in items:
                embed.add_field(name=f"{name.title()} ({s} {price})", value=desc or "—", inline=False)
        await ctx.send(embed=embed)

    @eco.command(name="buy", description="Buy an item from the shop.")
    async def buy(self, ctx, item_name: str, quantity: int = 1):
        item_name = item_name.lower()
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        item = await self.bot.db.fetch(
            "SELECT price FROM guild_shop WHERE guild_id = ? AND item_name = ?",
            ctx.guild.id, item_name
        )
        if not item:
            await ctx.send(self._t(ctx, "common.not_in_shop", "That item is not in this server's shop."))
            return

        price = item[0]
        if quantity <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Quantity must be positive."))
            return

        cost = price * quantity
        s = self._symbol(ctx.guild.id)
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cur = await db.execute(
                    "UPDATE guild_economy SET balance = balance - ? WHERE user_id = ? AND guild_id = ? AND balance >= ?",
                    (cost, ctx.author.id, ctx.guild.id, cost),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    await ctx.send(self._t(ctx, "economy.need_for_purchase", "You need **{symbol} {cost}** to buy {quantity}x {item}.", symbol=s, cost=cost, quantity=quantity, item=item_name))
                    return
                await db.execute(
                    "INSERT INTO guild_inventory (user_id, guild_id, item_name, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + excluded.quantity",
                    (ctx.author.id, ctx.guild.id, item_name, quantity),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        await ctx.send(self._t(ctx, "economy.purchase", "You bought {quantity}x **{item}** for **{symbol} {cost}**.", quantity=quantity, item=item_name, symbol=s, cost=cost))

    @eco.command(name="give", aliases=["pay"], description="Give money to another user.")
    async def give(self, ctx, member: discord.Member, amount: int):
        if amount <= 0:
            await ctx.send("❌ " + self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ " + self._t(ctx, "common.self_money", "You cannot give money to yourself."))
            return
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        s = self._symbol(ctx.guild.id)
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            try:
                await db.execute("BEGIN IMMEDIATE")
                for uid in (ctx.author.id, member.id):
                    await db.execute(
                        "INSERT OR IGNORE INTO guild_economy (user_id, guild_id, balance, bank) VALUES (?, ?, 0, 0)",
                        (uid, ctx.guild.id),
                    )
                cur = await db.execute(
                    "UPDATE guild_economy SET balance = balance - ? WHERE user_id = ? AND guild_id = ? AND balance >= ?",
                    (amount, ctx.author.id, ctx.guild.id, amount),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    await ctx.send("❌ " + self._t(ctx, "common.insufficient_money", "You don't have enough money!"))
                    return
                await db.execute(
                    "UPDATE guild_economy SET balance = balance + ? WHERE user_id = ? AND guild_id = ?",
                    (amount, member.id, ctx.guild.id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        await ctx.send(self._t(ctx, "economy.give_money", "💸 {author} gave **{symbol} {amount}** to {member} in this server.", author=ctx.author.mention, symbol=s, amount=amount, member=member.mention))

    @eco.command(name="giveitem", description="Give an item to another user.")
    async def giveitem(self, ctx, member: discord.Member, *, item_name: str):
        if member.id == ctx.author.id:
            return await ctx.send("❌ " + self._t(ctx, "common.self_item", "You cannot give items to yourself."))
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        item_name = item_name.lower().strip()
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cur = await db.execute(
                    "UPDATE guild_inventory SET quantity = quantity - 1 WHERE user_id = ? AND guild_id = ? AND item_name = ? AND quantity >= 1",
                    (ctx.author.id, ctx.guild.id, item_name),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    return await ctx.send("❌ " + self._t(ctx, "common.insufficient_money", "You don't have enough **{item}**.", item=item_name))
                await db.execute(
                    "DELETE FROM guild_inventory WHERE user_id = ? AND guild_id = ? AND item_name = ? AND quantity <= 0",
                    (ctx.author.id, ctx.guild.id, item_name),
                )
                await db.execute(
                    "INSERT INTO guild_inventory (user_id, guild_id, item_name, quantity) VALUES (?, ?, ?, 1) ON CONFLICT(user_id, guild_id, item_name) DO UPDATE SET quantity = quantity + excluded.quantity",
                    (member.id, ctx.guild.id, item_name),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        await ctx.send(self._t(ctx, "economy.give_item", "📦 {author} gave 1 **{item}** to {member}.", author=ctx.author.mention, item=item_name, member=member.mention))

    @eco.command(name="inventory", aliases=["inv"], description="Check your inventory.")
    async def inventory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        items = await self.bot.db.fetch_all(
            "SELECT item_name, quantity FROM guild_inventory WHERE user_id = ? AND guild_id = ?",
            member.id, ctx.guild.id
        )
        if not items:
            await ctx.send(self._t(ctx, "common.empty_inventory", "{member} has an empty inventory.", member=member.display_name))
            return
        embed = discord.Embed(title=self._t(ctx, "economy.inventory_title", "Inventory - {member}", member=member.display_name), color=discord.Color.blue())
        for name, qty in items:
            embed.add_field(name=name.title(), value=f"x{qty}", inline=True)
        await ctx.send(embed=embed)

    # --- Admin Economy Group ---
    @eco.command(name="top", description="Ranking de dinero de este servidor.")
    async def eco_top(self, ctx):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        s = self._symbol(ctx.guild.id)
        rows = await self.bot.db.fetch_all(
            "SELECT user_id, balance + bank AS total FROM guild_economy WHERE guild_id = ? ORDER BY total DESC LIMIT 10",
            ctx.guild.id
        )
        embed = discord.Embed(title=self._t(ctx, "economy.top_title", "💰 Economy · {guild}", guild=ctx.guild.name), color=discord.Color.from_str("#00FF88"))
        lines = []
        for i, (uid, total) in enumerate(rows or [], 1):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"ID {uid}"
            lines.append(f"**{i}.** {name} · {s} {total}")
        embed.description = "\n".join(lines) or self._t(ctx, "economy.top_empty", "Nobody has earned money here yet.")
        await ctx.send(embed=embed)

    @commands.hybrid_group(name="ecoadmin", description="Admin economy commands.")
    @commands.has_permissions(administrator=True)
    async def ecoadmin(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send(self._t(ctx, "common.admin_command_help", "Use `/ecoadmin additem`, `/ecoadmin setmoney`, etc."))

    @ecoadmin.command(name="additem")
    async def additem(self, ctx, name: str, price: int, *, description: str):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        if price < 0:
            await ctx.send(self._t(ctx, "common.nonnegative_amount", "Price cannot be negative."))
            return
        name = name.lower()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO guild_shop (guild_id, item_name, price, description) VALUES (?, ?, ?, ?)",
            ctx.guild.id, name, price, description
        )
        s = self._symbol(ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.item_added", "Item **{item}** added to this server's shop · {symbol} {price}.", item=name, symbol=s, price=price))

    @ecoadmin.command(name="removeitem")
    async def removeitem(self, ctx, name: str):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        name = name.lower()
        await self.bot.db.execute("DELETE FROM guild_shop WHERE guild_id = ? AND item_name = ?", ctx.guild.id, name)
        await ctx.send(self._t(ctx, "economy.item_removed", "Item **{item}** removed from this server's shop.", item=name))

    @ecoadmin.command(name="addmoney")
    async def addmoney(self, ctx, member: discord.Member, amount: int):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        if amount <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return
        await self.update_balance(member.id, amount, "wallet", ctx.guild.id)
        s = self._symbol(ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.money_added", "Added **{symbol} {amount}** to {member} in **{guild}**.", symbol=s, amount=amount, member=member.mention, guild=ctx.guild.name))

    @ecoadmin.command(name="removemoney")
    async def removemoney(self, ctx, member: discord.Member, amount: int):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        if amount <= 0:
            await ctx.send(self._t(ctx, "common.positive_amount", "Amount must be positive."))
            return
        await self.update_balance(member.id, -amount, "wallet", ctx.guild.id)
        s = self._symbol(ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.money_removed", "Removed **{symbol} {amount}** from {member} in this server.", symbol=s, amount=amount, member=member.mention))

    @ecoadmin.command(name="setmoney")
    async def setmoney(self, ctx, member: discord.Member, amount: int, type: str = "wallet"):
        if not ctx.guild:
            return await ctx.send(self._t(ctx, "common.no_guild_economy", "The economy is per server. Use this command inside a server."))
        if amount < 0:
            await ctx.send(self._t(ctx, "common.nonnegative_amount", "Amount must not be negative."))
            return
        column_map = {"wallet": "balance", "bank": "bank"}
        column = column_map.get(type.lower())
        if not column:
            await ctx.send(self._t(ctx, "common.invalid_type", "Type must be 'wallet' or 'bank'."))
            return
        async with self._economy_lock:
            db = await self.bot.db._get_conn()
            try:
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    "INSERT OR IGNORE INTO guild_economy (user_id, guild_id, balance, bank) VALUES (?, ?, 0, 0)",
                    (member.id, ctx.guild.id),
                )
                await db.execute(
                    f"UPDATE guild_economy SET {column} = ? WHERE user_id = ? AND guild_id = ?",
                    (amount, member.id, ctx.guild.id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        s = self._symbol(ctx.guild.id)
        await ctx.send(self._t(ctx, "economy.money_set", "{member} now has **{symbol} {amount}** in their {type} in this server.", member=member.mention, symbol=s, amount=amount, type=type))

    @work.error
    @daily.error
    @crime.error
    async def command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            import math
            minutes = math.ceil(error.retry_after / 60)
            if minutes > 60:
                hours = math.ceil(minutes / 60)
                await ctx.send(self._t(ctx, "common.cooldown_hours", "You can use this command again in {hours} hours.", hours=hours))
            else:
                 await ctx.send(self._t(ctx, "common.cooldown_minutes", "You can use this command again in {minutes} minutes.", minutes=minutes))
        else:
            raise error

async def setup(bot):
    await bot.add_cog(Economy(bot))
