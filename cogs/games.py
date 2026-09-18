import discord
from discord.ext import commands
import random
import aiohttp
import html
import asyncio
import datetime
from deep_translator import GoogleTranslator
from typing import Literal

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}  # channel_id: game_data
        self.counting_games = {}  # guild_id: current_number

    async def cog_load(self):
        # Create table if not exists
        await self.bot.db.execute('''
            CREATE TABLE IF NOT EXISTS counting_games (
                guild_id INTEGER PRIMARY KEY,
                current_number INTEGER NOT NULL DEFAULT 0,
                last_user_id INTEGER
            )
        ''')
        # Load active counting games from database
        try:
            rows = await self.bot.db.fetch_all("SELECT guild_id, current_number, last_user_id FROM counting_games")
            for guild_id, current_number, last_user_id in rows:
                self.counting_games[guild_id] = {'number': current_number, 'last_user': last_user_id}
        except Exception as e:
            print(f"Error loading counting games: {e}")

    async def save_counting_game(self, guild_id, number, last_user_id):
        await self.bot.db.execute(
            "INSERT INTO counting_games (guild_id, current_number, last_user_id) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET current_number = excluded.current_number, last_user_id = excluded.last_user_id",
            guild_id, number, last_user_id
        )

    async def update_game_stats(self, user_id, guild_id, game_type, result):
        # Result: 'win', 'loss', 'draw'
        stats = await self.bot.db.fetch("SELECT wins, losses, draws FROM game_stats WHERE user_id = ? AND guild_id = ? AND game_type = ?", user_id, guild_id, game_type)
        
        wins, losses, draws = 0, 0, 0
        if stats:
            wins, losses, draws = stats
        
        if result == 'win': wins += 1
        elif result == 'loss': losses += 1
        elif result == 'draw': draws += 1
        
        await self.bot.db.execute("INSERT OR REPLACE INTO game_stats (user_id, guild_id, game_type, wins, losses, draws) VALUES (?, ?, ?, ?, ?, ?)", user_id, guild_id, game_type, wins, losses, draws)

    @commands.hybrid_group(name="game", description="Play minigames!")
    async def game(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `/game trivia`, `/game rps`, `/game count`, etc.")

    @game.command(name="trivia", description="Play a trivia game.")
    async def trivia(self, ctx, difficulty: Literal["easy", "medium", "hard"] = "medium"):
        """
        Play a trivia game with questions from Open Trivia Database.
        Difficulty: easy, medium, hard
        """
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(f"https://opentdb.com/api.php?amount=1&difficulty={difficulty}&type=multiple") as resp:
                    data = await resp.json()
        except Exception:
            await ctx.send("❌ No pude obtener la pregunta de trivia. Inténtalo otra vez.")
            return

        if data['response_code'] != 0:
            await ctx.send("❌ Error fetching question.")
            return

        question_data = data['results'][0]
        category = question_data['category']
        question = html.unescape(question_data['question'])
        correct_answer = html.unescape(question_data['correct_answer'])
        incorrect_answers = [html.unescape(ans) for ans in question_data['incorrect_answers']]
        
        # Translate to server lang if needed (Simplified for demo)
        # In a real scenario, use self.bot.config.get(ctx.guild.id, 'language')
        
        # Create View
        view = TriviaView(correct_answer, ctx.author, self, ctx.guild.id)
        for ans in incorrect_answers + [correct_answer]:
            view.add_answer(ans)
        view.shuffle_answers()
        
        embed = discord.Embed(title="🧠 Trivia Time!", description=f"**Category:** {category}\n**Difficulty:** {difficulty.capitalize()}\n\n{question}", color=discord.Color.blue())
        embed.set_footer(text="You have 30 seconds!")
        
        await ctx.send(embed=embed, view=view)

    @game.command(name="guess", description="Guess the number game.")
    async def guess(self, ctx):
        """
        Start a guessing game. Guess a number between 1 and 100!
        The bot will listen to your messages in this channel.
        """
        if ctx.channel.id in self.active_games:
            await ctx.send("❌ A game is already active in this channel!")
            return

        number = random.randint(1, 100)
        self.active_games[ctx.channel.id] = {'type': 'guess', 'number': number, 'attempts': 0}
        
        await ctx.send("🔢 I've picked a number between **1** and **100**. Start guessing!")

        def check(m):
            return m.channel == ctx.channel and not m.author.bot and m.content.isdigit()

        try:
            while True:
                msg = await self.bot.wait_for('message', check=check, timeout=30.0)
                guess = int(msg.content)
                self.active_games[ctx.channel.id]['attempts'] += 1
                attempts = self.active_games[ctx.channel.id]['attempts']

                if guess == number:
                    await ctx.send(f"🎉 Correct! **{msg.author.display_name}** guessed it in **{attempts}** attempts!")
                    await self.update_game_stats(msg.author.id, ctx.guild.id, 'guess', 'win')
                    return
                if attempts >= 12:
                    await ctx.send(f"⏰ Demasiados intentos. El número era **{number}**.")
                    return
                elif guess < number:
                    await ctx.send("⬆️ Higher!")
                else:
                    await ctx.send("⬇️ Lower!")
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time's up! The number was **{number}**.")
        finally:
            self.active_games.pop(ctx.channel.id, None)

    @game.command(name="rps", description="Play Rock, Paper, Scissors, Lizard, Spock.")
    async def rps(self, ctx):
        view = RPSView(ctx.author, self, ctx.guild.id)
        embed = discord.Embed(
            title="Piedra · Papel · Tijeras · Lagarto · Spock",
            description="Elige tu arma. Las reglas de Sheldon Cooper aplican.",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=embed, view=view)

    @game.command(name="rpsls", description="Rock Paper Scissors Lizard Spock.")
    async def rpsls(self, ctx):
        await self.rps(ctx)

    @game.command(name="math", description="Solve a math problem.")
    async def math(self, ctx, difficulty: Literal["easy", "medium", "hard"] = "easy"):
        """
        Solve a random math problem. Difficulty: easy, medium, hard
        """
        if ctx.channel.id in self.active_games:
             await ctx.send("❌ A game is active here.")
             return

        if difficulty == "easy":
            a, b = random.randint(1, 20), random.randint(1, 20)
            op = random.choice(['+', '-'])
        elif difficulty == "medium":
            a, b = random.randint(10, 100), random.randint(1, 20)
            op = random.choice(['+', '-', '*'])
        else:
            a, b = random.randint(10, 50), random.randint(10, 50)
            op = '*'
            
        expression = f"{a} {op} {b}"
        result = {"+": a + b, "-": a - b, "*": a * b}[op]
        
        self.active_games[ctx.channel.id] = {'type': 'math', 'answer': result}
        await ctx.send(f"🧮 Solve: **{expression} = ?**")
        
        def check(m):
            return m.channel == ctx.channel and not m.author.bot and m.content.replace('-','').isdigit()
            
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=15.0)
            if int(msg.content) == result:
                await ctx.send(f"✅ Correct **{msg.author.display_name}**!")
                await self.update_game_stats(msg.author.id, ctx.guild.id, 'math', 'win')
            else:
                await ctx.send(f"❌ Wrong! Answer was {result}.")
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time's up! Answer was {result}.")
        
        if ctx.channel.id in self.active_games:
            del self.active_games[ctx.channel.id]

    @game.command(name="startcount", description="Start a counting game in this channel.")
    @commands.has_permissions(manage_guild=True)
    async def startcounting(self, ctx):
        config = self.bot.config.get(ctx.guild.id) or {}
        
        # If already set
        if 'counting_channel' in config:
            await ctx.send(f"❌ Counting channel already set to <#{config['counting_channel']}>")
            return
            
        # Save channel
        self.bot.config.set_config(ctx.guild.id, 'counting_channel', ctx.channel.id)
        
        self.counting_games[ctx.guild.id] = {'number': 0, 'last_user': None}
        await self.save_counting_game(ctx.guild.id, 0, None)
        await ctx.send("🔢 Counting channel set! Start with **1**.")

    @game.command(name="stopcount", description="Stop the counting game.")
    @commands.has_permissions(manage_guild=True)
    async def stopcounting(self, ctx):
        config = self.bot.config.get(ctx.guild.id)
        if not config or 'counting_channel' not in config:
            await ctx.send("❌ No counting channel set.")
            return

        self.bot.config.set_config(ctx.guild.id, 'counting_channel', None)
        
        if ctx.guild.id in self.counting_games:
            del self.counting_games[ctx.guild.id]
            await self.bot.db.execute("DELETE FROM counting_games WHERE guild_id = ?", ctx.guild.id)
            
        await ctx.send("🛑 Counting game stopped.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return
        
        config = self.bot.config.get(message.guild.id)
        if not config: return
        
        channel_id = config.get('counting_channel')
        if channel_id and message.channel.id == int(channel_id):
            if not message.content.isdigit(): return
            
            # Init game memory if restart
            if message.guild.id not in self.counting_games:
                self.counting_games[message.guild.id] = {'number': 0, 'last_user': None}
            
            game = self.counting_games[message.guild.id]
            number = int(message.content)
            
            if number == game['number'] + 1:
                if game['last_user'] == message.author.id:
                    await message.delete()
                    await message.channel.send(f"❌ {message.author.mention}, you can't count twice in a row!", delete_after=3)
                    game['number'] = 0
                    game['last_user'] = None
                    await self.save_counting_game(message.guild.id, 0, None)
                    await message.channel.send("🔢 Count reset to 0! Start again from 1.")
                else:
                    game['number'] = number
                    game['last_user'] = message.author.id
                    await self.save_counting_game(message.guild.id, number, message.author.id)
                    await message.add_reaction("✅")
            else:
                await message.delete()
                await message.channel.send(f"❌ {message.author.mention} broke the chain! The next number was {game['number'] + 1}.", delete_after=3)
                game['number'] = 0
                game['last_user'] = None
                await self.save_counting_game(message.guild.id, 0, None)
                await message.channel.send("🔢 Count reset to 0! Start again from 1.")

    @game.command(name="stats", description="View game statistics.")
    async def gamestats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        stats = await self.bot.db.fetch_all("SELECT game_type, wins, losses, draws FROM game_stats WHERE user_id = ? AND guild_id = ?", member.id, ctx.guild.id)
        
        embed = discord.Embed(title=f"🎮 Game Stats: {member.display_name}", color=discord.Color.purple())
        if not stats:
            embed.description = "No games played yet."
        else:
            for gtype, w, l, d in stats:
                embed.add_field(name=gtype.upper(), value=f"Wins: {w}\nLosses: {l}\nDraws: {d}", inline=True)
        await ctx.send(embed=embed)

    @game.command(name="leaderboard", description="View game leaderboard.")
    async def gameleaderboard(self, ctx, game_type: Literal["trivia", "rps", "guess", "math", "all"] = "all"):
        query = "SELECT user_id, sum(wins) as total_wins FROM game_stats WHERE guild_id = ?"
        params = [ctx.guild.id]
        
        if game_type != "all":
            query += " AND game_type = ?"
            params.append(game_type)
            
        query += " GROUP BY user_id ORDER BY total_wins DESC LIMIT 10"
        
        rows = await self.bot.db.fetch_all(query, *params)
        
        embed = discord.Embed(title=f"🏆 Leaderboard ({game_type.title()})", color=discord.Color.gold())
        
        if not rows:
            embed.description = "No data yet."
        else:
            desc = ""
            for i, (uid, wins) in enumerate(rows, 1):
                desc += f"**{i}.** <@{uid}> - {wins} wins\n"
            embed.description = desc
            
        await ctx.send(embed=embed)

class TriviaView(discord.ui.View):
    def __init__(self, correct_answer, author, games_cog, guild_id, lang='en'):
        super().__init__(timeout=30)
        self.correct_answer = correct_answer
        self.author = author
        self.answered = False
        self.answers = []
        self.games_cog = games_cog
        self.guild_id = guild_id

    def add_answer(self, answer):
        self.answers.append(answer)

    def shuffle_answers(self):
        random.shuffle(self.answers)
        for i, ans in enumerate(self.answers):
            button = discord.ui.Button(label=html.unescape(ans), style=discord.ButtonStyle.secondary, custom_id=f"trivia_{i}")
            button.callback = self.make_callback(ans)
            self.add_item(button)

    def make_callback(self, ans_text):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                return await interaction.response.send_message("Not your game!", ephemeral=True)
            
            if self.answered: return
            self.answered = True
            
            if ans_text == self.correct_answer:
                await interaction.response.send_message("✅ Correct!", ephemeral=True)
                await self.games_cog.update_game_stats(interaction.user.id, self.guild_id, 'trivia', 'win')
                
                # Disable buttons
                for child in self.children:
                    if child.label == self.correct_answer:
                        child.style = discord.ButtonStyle.success
                    else:
                        child.style = discord.ButtonStyle.secondary
                        child.disabled = True
            else:
                await interaction.response.send_message(f"❌ Wrong! It was **{self.correct_answer}**", ephemeral=True)
                await self.games_cog.update_game_stats(interaction.user.id, self.guild_id, 'trivia', 'loss')
                
                # Disable buttons
                for child in self.children:
                    if child.label == self.correct_answer:
                        child.style = discord.ButtonStyle.success
                    elif child.label == ans_text:
                        child.style = discord.ButtonStyle.danger
                    child.disabled = True
            
            await interaction.message.edit(view=self)
            self.stop()
        return callback

RPSLS_WINS = {
    "Rock": {"Scissors", "Lizard"},
    "Paper": {"Rock", "Spock"},
    "Scissors": {"Paper", "Lizard"},
    "Lizard": {"Spock", "Paper"},
    "Spock": {"Scissors", "Rock"},
}


class RPSView(discord.ui.View):
    def __init__(self, author, games_cog, guild_id):
        super().__init__(timeout=45)
        self.author = author
        self.choices = ["Rock", "Paper", "Scissors", "Lizard", "Spock"]
        self.games_cog = games_cog
        self.guild_id = guild_id

    @discord.ui.button(label="Piedra", emoji="🪨", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "Rock")

    @discord.ui.button(label="Papel", emoji="📄", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "Paper")

    @discord.ui.button(label="Tijeras", emoji="✂️", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "Scissors")

    @discord.ui.button(label="Lagarto", emoji="🦎", style=discord.ButtonStyle.secondary)
    async def lizard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "Lizard")

    @discord.ui.button(label="Spock", emoji="🖖", style=discord.ButtonStyle.secondary)
    async def spock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "Spock")

    async def play(self, interaction: discord.Interaction, player_choice):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Not your game!", ephemeral=True)
            return

        bot_choice = random.choice(self.choices)
        if player_choice == bot_choice:
            result_code = "draw"
            result = "Empate."
        elif bot_choice in RPSLS_WINS[player_choice]:
            result_code = "win"
            result = "¡Has ganado!"
        else:
            result_code = "loss"
            result = "Has perdido."

        await self.games_cog.update_game_stats(interaction.user.id, self.guild_id, "rps", result_code)

        embed = interaction.message.embeds[0]
        embed.description = f"Tú: **{player_choice}**\nDabot: **{bot_choice}**\n\n**{result}**"
        if result_code == "win":
            embed.color = discord.Color.green()
        elif result_code == "loss":
            embed.color = discord.Color.red()
        else:
            embed.color = discord.Color.gold()

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

async def setup(bot):
    await bot.add_cog(Games(bot))
