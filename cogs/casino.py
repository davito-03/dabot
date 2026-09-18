import discord
from discord.ext import commands
import random
import asyncio

class Casino(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}  # user_id: game_data

    async def _wallet(self, user_id, guild_id, delta=None):
        eco = self.bot.get_cog("Economy")
        if not eco or not guild_id:
            return 0
        if delta is None:
            w, _ = await eco.get_balance(user_id, guild_id)
            return w
        await eco.update_balance(user_id, delta, "wallet", guild_id)
        return None

    @commands.hybrid_group(name="casino", description="🎰 Casino games!")
    async def casino(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="🎰 Casino Games", description=(
                "`/casino blackjack <bet>` — Play blackjack\n"
                "`/casino slots <bet>` — Slot machine\n"
                "`/casino roulette <bet> <choice>` — Roulette\n"
                "`/casino horserace <bet> <horse>` — Horse racing\n"
                "`/casino poker <bet>` — Video poker"
            ), color=discord.Color.gold())
            await ctx.send(embed=embed)
    
    # ==================== BLACKJACK ====================
    
    def create_deck(self):
        """Create a standard 52-card deck."""
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        deck = [{'rank': rank, 'suit': suit} for suit in suits for rank in ranks]
        random.shuffle(deck)
        return deck
    
    def card_value(self, card):
        """Get the value of a card."""
        if card['rank'] in ['J', 'Q', 'K']:
            return 10
        elif card['rank'] == 'A':
            return 11
        else:
            return int(card['rank'])
    
    def hand_value(self, hand):
        """Calculate the value of a hand."""
        value = sum(self.card_value(card) for card in hand)
        aces = sum(1 for card in hand if card['rank'] == 'A')
        
        while value > 21 and aces:
            value -= 10
            aces -= 1
        
        return value
    
    def card_str(self, card):
        """Convert card to string."""
        return f"{card['rank']}{card['suit']}"
    
    @casino.command(name="blackjack", description="Play blackjack!")
    async def casino_blackjack(self, ctx, bet: int):
        """Play a game of blackjack."""
        if ctx.author.id in self.active_games:
            await ctx.send("❌ You already have an active game of blackjack! Complete that one first.")
            return

        if bet < 10:
            await ctx.send("❌ Minimum bet is 10 coins!")
            return
        
        if not ctx.guild:
            return await ctx.send("El casino es por servidor.")
        wallet = await self._wallet(ctx.author.id, ctx.guild.id)
        if wallet < bet:
            await ctx.send("❌ You don't have enough coins!")
            return
        await self._wallet(ctx.author.id, ctx.guild.id, -bet)
        
        # Create deck and deal
        deck = self.create_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]
        
        # Store game state
        self.active_games[ctx.author.id] = {
            'deck': deck,
            'player_hand': player_hand,
            'dealer_hand': dealer_hand,
            'bet': bet,
            'channel': ctx.channel.id,
            'guild_id': ctx.guild.id
        }
        
        # Check for blackjack
        player_value = self.hand_value(player_hand)
        dealer_value = self.hand_value(dealer_hand)
        
        if player_value == 21:
            # Player blackjack
            winnings = int(bet * 2.5)
            await self._wallet(ctx.author.id, ctx.guild.id, winnings)
            
            embed = discord.Embed(title="🃏 Blackjack!", color=discord.Color.gold())
            embed.add_field(name="Your Hand", value=f"{' '.join(self.card_str(c) for c in player_hand)} = **21**", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{' '.join(self.card_str(c) for c in dealer_hand)} = {dealer_value}", inline=False)
            embed.add_field(name="Result", value=f"🎉 **BLACKJACK!** You won **{winnings}** coins!", inline=False)
            
            del self.active_games[ctx.author.id]
            await ctx.send(embed=embed)
            return
        
        # Show initial hands
        embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.blue())
        embed.add_field(name="Your Hand", value=f"{' '.join(self.card_str(c) for c in player_hand)} = **{player_value}**", inline=False)
        embed.add_field(name="Dealer Hand", value=f"{self.card_str(dealer_hand[0])} 🎴 = **?**", inline=False)
        embed.set_footer(text=f"Bet: {bet} coins")
        
        view = BlackjackView(self, ctx.author.id)
        await ctx.send(embed=embed, view=view)
    
    async def blackjack_hit(self, interaction, user_id):
        """Player hits."""
        game = self.active_games.get(user_id)
        if not game:
            await interaction.response.send_message("❌ No active game!", ephemeral=True)
            return
        
        # Draw card
        card = game['deck'].pop()
        game['player_hand'].append(card)
        
        player_value = self.hand_value(game['player_hand'])
        
        if player_value > 21:
            # Bust
            embed = discord.Embed(title="🃏 Blackjack - Bust!", color=discord.Color.red())
            embed.add_field(name="Your Hand", value=f"{' '.join(self.card_str(c) for c in game['player_hand'])} = **{player_value}**", inline=False)
            embed.add_field(name="Result", value=f"💥 **BUST!** You lost **{game['bet']}** coins!", inline=False)
            
            del self.active_games[user_id]
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            # Update hand
            embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.blue())
            embed.add_field(name="Your Hand", value=f"{' '.join(self.card_str(c) for c in game['player_hand'])} = **{player_value}**", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{self.card_str(game['dealer_hand'][0])} 🎴 = **?**", inline=False)
            embed.set_footer(text=f"Bet: {game['bet']} coins")
            
            view = BlackjackView(self, user_id)
            await interaction.response.edit_message(embed=embed, view=view)
    
    async def blackjack_stand(self, interaction, user_id):
        """Player stands."""
        game = self.active_games.get(user_id)
        if not game:
            await interaction.response.send_message("❌ No active game!", ephemeral=True)
            return
        
        # Dealer plays
        while self.hand_value(game['dealer_hand']) < 17:
            game['dealer_hand'].append(game['deck'].pop())
        
        player_value = self.hand_value(game['player_hand'])
        dealer_value = self.hand_value(game['dealer_hand'])
        
        # Determine winner
        if dealer_value > 21:
            result = "win"
            message = f"🎉 Dealer busts! You won **{game['bet'] * 2}** coins!"
            winnings = game['bet'] * 2
        elif player_value > dealer_value:
            result = "win"
            message = f"🎉 You win! You won **{game['bet'] * 2}** coins!"
            winnings = game['bet'] * 2
        elif player_value < dealer_value:
            result = "loss"
            message = f"😢 Dealer wins! You lost **{game['bet']}** coins!"
            winnings = 0
        else:
            result = "push"
            message = f"🤝 Push! You get your **{game['bet']}** coins back!"
            winnings = game['bet']
        
        # Update balance
        if winnings > 0:
            await self._wallet(interaction.user.id, game.get("guild_id") or (interaction.guild.id if interaction.guild else 0), winnings)
        
        # Show result
        embed = discord.Embed(title="🃏 Blackjack - Result", color=discord.Color.gold() if result == "win" else discord.Color.red())
        embed.add_field(name="Your Hand", value=f"{' '.join(self.card_str(c) for c in game['player_hand'])} = **{player_value}**", inline=False)
        embed.add_field(name="Dealer Hand", value=f"{' '.join(self.card_str(c) for c in game['dealer_hand'])} = **{dealer_value}**", inline=False)
        embed.add_field(name="Result", value=message, inline=False)
        
        del self.active_games[user_id]
        await interaction.response.edit_message(embed=embed, view=None)
    
    # ==================== SLOTS ====================
    
    @casino.command(name="slots", description="Play the slot machine!")
    async def casino_slots(self, ctx, bet: int):
        """Play the slot machine."""
        if bet < 5:
            await ctx.send("❌ Minimum bet is 5 coins!")
            return
        
        if not ctx.guild:
            return await ctx.send("El casino es por servidor.")
        wallet = await self._wallet(ctx.author.id, ctx.guild.id)
        if wallet < bet:
            await ctx.send("❌ You don't have enough coins!")
            return
        await self._wallet(ctx.author.id, ctx.guild.id, -bet)
        
        # Slot symbols
        symbols = ['🍒', '🍋', '🍊', '🍇', '🔔', '💎', '7️⃣']
        weights = [30, 25, 20, 15, 7, 2, 1]  # Weighted probabilities
        
        # Spin
        result = random.choices(symbols, weights=weights, k=3)
        
        # Calculate winnings
        if result[0] == result[1] == result[2]:
            # All three match
            if result[0] == '7️⃣':
                multiplier = 50
                message = "🎰 **JACKPOT!!!** 7️⃣7️⃣7️⃣"
            elif result[0] == '💎':
                multiplier = 25
                message = "💎 **TRIPLE DIAMONDS!**"
            elif result[0] == '🔔':
                multiplier = 15
                message = "🔔 **TRIPLE BELLS!**"
            else:
                multiplier = 10
                message = "🎉 **THREE OF A KIND!**"
        elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
            # Two match
            multiplier = 2
            message = "✨ Two matching!"
        else:
            # No match
            multiplier = 0
            message = "😢 No match..."
        
        winnings = bet * multiplier
        
        if winnings > 0:
            await self._wallet(ctx.author.id, ctx.guild.id, winnings)
        
        # Display result
        embed = discord.Embed(title="🎰 Slot Machine", color=discord.Color.gold() if multiplier >= 10 else discord.Color.blue())
        embed.add_field(name="Result", value=f"**{result[0]} {result[1]} {result[2]}**", inline=False)
        embed.add_field(name="Outcome", value=message, inline=False)
        
        if winnings > 0:
            embed.add_field(name="Winnings", value=f"💰 **+{winnings}** coins! (x{multiplier})", inline=False)
        else:
            embed.add_field(name="Loss", value=f"💸 **-{bet}** coins", inline=False)
        
        await ctx.send(embed=embed)
    
    # ==================== ROULETTE ====================
    
    @casino.command(name="roulette", description="Play roulette!")
    async def casino_roulette(self, ctx, bet: int, choice: str):
        """
        Play roulette.
        Choices: red, black, green, odd, even, or a number (0-36)
        """
        if bet < 10:
            await ctx.send("❌ Minimum bet is 10 coins!")
            return
        
        if not ctx.guild:
            return await ctx.send("El casino es por servidor.")
        wallet = await self._wallet(ctx.author.id, ctx.guild.id)
        if wallet < bet:
            await ctx.send("❌ You don't have enough coins!")
            return
        await self._wallet(ctx.author.id, ctx.guild.id, -bet)
        
        # Spin the wheel
        number = random.randint(0, 36)
        
        # Determine color
        if number == 0:
            color = 'green'
        elif number in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]:
            color = 'red'
        else:
            color = 'black'
        
        # Check win
        choice = choice.lower()
        won = False
        multiplier = 0
        
        if choice == str(number):
            won = True
            multiplier = 35
            message = f"🎯 **EXACT NUMBER!** You hit {number}!"
        elif choice == color:
            won = True
            multiplier = 2 if color == 'green' else 1
            message = f"✅ Correct color! ({color.upper()})"
        elif choice == 'odd' and number % 2 == 1 and number != 0:
            won = True
            multiplier = 1
            message = f"✅ Correct! {number} is ODD!"
        elif choice == 'even' and number % 2 == 0 and number != 0:
            won = True
            multiplier = 1
            message = f"✅ Correct! {number} is EVEN!"
        else:
            message = f"❌ Wrong! The ball landed on {number} ({color})"
        
        winnings = bet * (multiplier + 1) if won else 0
        
        if winnings > 0:
            await self._wallet(ctx.author.id, ctx.guild.id, winnings)
        
        # Display result
        color_emoji = '🟢' if color == 'green' else '🔴' if color == 'red' else '⚫'
        
        embed = discord.Embed(title="🎡 Roulette", color=discord.Color.green() if won else discord.Color.red())
        embed.add_field(name="Result", value=f"{color_emoji} **{number}** ({color.upper()})", inline=False)
        embed.add_field(name="Your Bet", value=f"{choice.upper()}", inline=True)
        embed.add_field(name="Outcome", value=message, inline=False)
        
        if winnings > 0:
            embed.add_field(name="Winnings", value=f"💰 **+{winnings}** coins! (x{multiplier + 1})", inline=False)
        else:
            embed.add_field(name="Loss", value=f"💸 **-{bet}** coins", inline=False)
        
        await ctx.send(embed=embed)
    
    # ==================== HORSE RACING ====================
    
    @casino.command(name="horserace", description="Bet on a horse race!")
    async def casino_horserace(self, ctx, bet: int, horse: int):
        """
        Bet on a horse race.
        Choose a horse (1-5)
        """
        if horse < 1 or horse > 5:
            await ctx.send("❌ Choose a horse between 1 and 5!")
            return
        
        if bet < 20:
            await ctx.send("❌ Minimum bet is 20 coins!")
            return
        
        if not ctx.guild:
            return await ctx.send("El casino es por servidor.")
        wallet = await self._wallet(ctx.author.id, ctx.guild.id)
        if wallet < bet:
            await ctx.send("❌ You don't have enough coins!")
            return
        await self._wallet(ctx.author.id, ctx.guild.id, -bet)
        
        # Horse names and emojis
        horses = {
            1: ("Thunder", "🐎"),
            2: ("Lightning", "🏇"),
            3: ("Storm", "🐴"),
            4: ("Blaze", "🦄"),
            5: ("Spirit", "🎠")
        }
        
        # Simulate race
        positions = [0, 0, 0, 0, 0]
        finish_line = 10
        
        embed = discord.Embed(title="🏁 Horse Race Starting!", color=discord.Color.blue())
        embed.add_field(name="Your Bet", value=f"Horse #{horse} - {horses[horse][0]} {horses[horse][1]}", inline=False)
        
        msg = await ctx.send(embed=embed)
        
        await asyncio.sleep(1)
        
        # Race animation
        while max(positions) < finish_line:
            for i in range(5):
                positions[i] += random.randint(0, 2)
            
            race_display = ""
            for i in range(5):
                track = "━" * positions[i] + horses[i+1][1] + "━" * (finish_line - positions[i])
                race_display += f"**{i+1}.** {track} {horses[i+1][0]}\n"
            
            embed = discord.Embed(title="🏁 Horse Race!", description=race_display, color=discord.Color.blue())
            await msg.edit(embed=embed)
            await asyncio.sleep(0.8)
        
        # Determine winner
        winner = positions.index(max(positions)) + 1
        
        if winner == horse:
            winnings = bet * 4
            await self._wallet(ctx.author.id, ctx.guild.id, winnings)
            
            embed = discord.Embed(title="🏁 Horse Race - Winner!", color=discord.Color.gold())
            embed.add_field(name="Winner", value=f"🏆 Horse #{winner} - {horses[winner][0]} {horses[winner][1]}", inline=False)
            embed.add_field(name="Result", value=f"🎉 **YOU WON!** +{winnings} coins! (x4)", inline=False)
        else:
            embed = discord.Embed(title="🏁 Horse Race - Finished", color=discord.Color.red())
            embed.add_field(name="Winner", value=f"🏆 Horse #{winner} - {horses[winner][0]} {horses[winner][1]}", inline=False)
            embed.add_field(name="Result", value=f"😢 You lost {bet} coins", inline=False)
        
        await msg.edit(embed=embed)
    
    # ==================== POKER (Simplified) ====================
    
    @casino.command(name="poker", description="Play video poker!")
    async def casino_poker(self, ctx, bet: int):
        """Play video poker (5-card draw)."""
        if bet < 15:
            await ctx.send("❌ Minimum bet is 15 coins!")
            return
        
        if not ctx.guild:
            return await ctx.send("El casino es por servidor.")
        wallet = await self._wallet(ctx.author.id, ctx.guild.id)
        if wallet < bet:
            await ctx.send("❌ You don't have enough coins!")
            return
        await self._wallet(ctx.author.id, ctx.guild.id, -bet)
        
        # Deal 5 cards
        deck = self.create_deck()
        hand = [deck.pop() for _ in range(5)]
        
        # Evaluate hand
        result = self.evaluate_poker_hand(hand)
        
        # Payouts
        payouts = {
            'Royal Flush': 250,
            'Straight Flush': 50,
            'Four of a Kind': 25,
            'Full House': 9,
            'Flush': 6,
            'Straight': 4,
            'Three of a Kind': 3,
            'Two Pair': 2,
            'Pair (Jacks or Better)': 1,
            'Nothing': 0
        }
        
        multiplier = payouts.get(result, 0)
        winnings = bet * multiplier
        
        if winnings > 0:
            await self._wallet(ctx.author.id, ctx.guild.id, winnings)
        
        # Display result
        hand_str = ' '.join(self.card_str(c) for c in hand)
        
        embed = discord.Embed(title="🃏 Video Poker", color=discord.Color.gold() if multiplier >= 9 else discord.Color.blue())
        embed.add_field(name="Your Hand", value=hand_str, inline=False)
        embed.add_field(name="Result", value=f"**{result}**", inline=False)
        
        if winnings > 0:
            embed.add_field(name="Winnings", value=f"💰 **+{winnings}** coins! (x{multiplier})", inline=False)
        else:
            embed.add_field(name="Loss", value=f"💸 **-{bet}** coins", inline=False)
        
        await ctx.send(embed=embed)
    
    def evaluate_poker_hand(self, hand):
        """Evaluate a poker hand."""
        ranks = [card['rank'] for card in hand]
        suits = [card['suit'] for card in hand]
        
        # Convert face cards to numbers
        rank_values = {'A': 14, 'K': 13, 'Q': 12, 'J': 11}
        for i, rank in enumerate(ranks):
            if rank in rank_values:
                ranks[i] = rank_values[rank]
            else:
                ranks[i] = int(rank)
        
        ranks.sort()
        
        # Check for flush
        is_flush = len(set(suits)) == 1
        
        # Check for straight
        is_straight = ranks == list(range(min(ranks), max(ranks) + 1))
        
        # Check for royal flush (A, K, Q, J, 10)
        if is_flush and is_straight and ranks == [10, 11, 12, 13, 14]:
            return 'Royal Flush'
        
        # Check for straight flush
        if is_flush and is_straight:
            return 'Straight Flush'
        
        # Count rank occurrences
        rank_counts = {}
        for rank in ranks:
            rank_counts[rank] = rank_counts.get(rank, 0) + 1
        
        counts = sorted(rank_counts.values(), reverse=True)
        
        # Four of a kind
        if counts == [4, 1]:
            return 'Four of a Kind'
        
        # Full house
        if counts == [3, 2]:
            return 'Full House'
        
        # Flush
        if is_flush:
            return 'Flush'
        
        # Straight
        if is_straight:
            return 'Straight'
        
        # Three of a kind
        if counts == [3, 1, 1]:
            return 'Three of a Kind'
        
        # Two pair
        if counts == [2, 2, 1]:
            return 'Two Pair'
        
        # Pair (Jacks or better)
        if counts == [2, 1, 1, 1]:
            pair_rank = [rank for rank, count in rank_counts.items() if count == 2][0]
            if pair_rank >= 11:
                return 'Pair (Jacks or Better)'
        
        return 'Nothing'

class BlackjackView(discord.ui.View):
    def __init__(self, casino_cog, user_id):
        super().__init__(timeout=60)
        self.casino_cog = casino_cog
        self.user_id = user_id

    async def on_timeout(self):
        game = self.casino_cog.active_games.pop(self.user_id, None)
        if not game:
            return
        try:
            await self.casino_cog._wallet(self.user_id, game.get("guild_id"), game.get("bet", 0))
        except Exception:
            pass
    
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return
        
        await self.casino_cog.blackjack_hit(interaction, self.user_id)
    
    @discord.ui.button(label="Stand", style=discord.ButtonStyle.success, emoji="✋")
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return
        
        await self.casino_cog.blackjack_stand(interaction, self.user_id)

async def setup(bot):
    await bot.add_cog(Casino(bot))
