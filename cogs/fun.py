import logging
import discord
from discord.ext import commands
import random
import aiohttp
import asyncio
import html
from typing import Literal
from deep_translator import GoogleTranslator

# --- MINIGAME VIEWS ---

class TicTacToeButton(discord.ui.Button):
    def __init__(self, x, y):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        state = view.board[self.y][self.x]
        if state in (view.X, view.O):
            return

        if view.current_player != interaction.user:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if view.current_player == view.X_player:
            self.style = discord.ButtonStyle.danger
            self.label = 'X'
            self.disabled = True
            view.board[self.y][self.x] = view.X
            view.current_player = view.O_player
            content = f"It's {view.O_player.mention}'s turn (O)"
        else:
            self.style = discord.ButtonStyle.success
            self.label = 'O'
            self.disabled = True
            view.board[self.y][self.x] = view.O
            view.current_player = view.X_player
            content = f"It's {view.X_player.mention}'s turn (X)"

        winner = view.check_winner()
        if winner is not None:
            if winner == view.X:
                content = f"{view.X_player.mention} wins!"
            elif winner == view.O:
                content = f"{view.O_player.mention} wins!"
            else:
                content = "It's a tie!"

            for child in view.children:
                child.disabled = True
            
            view.stop()

        await interaction.response.edit_message(content=content, view=view)

class TicTacToeView(discord.ui.View):
    X = -1
    O = 1
    Tie = 2

    def __init__(self, x_player, o_player):
        super().__init__()
        self.X_player = x_player
        self.O_player = o_player
        self.current_player = x_player
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]

        for x in range(3):
            for y in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_winner(self):
        for i in range(3):
            if self.board[i][0] == self.board[i][1] == self.board[i][2] != 0:
                return self.board[i][0]
            if self.board[0][i] == self.board[1][i] == self.board[2][i] != 0:
                return self.board[0][i]

        if self.board[0][0] == self.board[1][1] == self.board[2][2] != 0:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != 0:
            return self.board[0][2]

        if all(i != 0 for row in self.board for i in row):
            return self.Tie

        return None

class RPSView(discord.ui.View):
    def __init__(self, player, opponent=None):
        super().__init__()
        self.player = player
        self.opponent = opponent
        self.player_choice = None
        self.opponent_choice = None

    async def determine_winner(self, interaction):
        choices = {0: "Rock", 1: "Paper", 2: "Scissors"}
        
        # If playing against bot
        if not self.opponent:
            bot_choice_idx = random.randint(0, 2)
            bot_choice = choices[bot_choice_idx]
            user_choice = choices[self.player_choice]
            
            result = self.get_result(self.player_choice, bot_choice_idx)
            
            embed = discord.Embed(title="Rock Paper Scissors", color=discord.Color.blue())
            embed.add_field(name="You", value=user_choice)
            embed.add_field(name="Bot", value=bot_choice)
            embed.description = f"**{result}**"
            
            await interaction.response.edit_message(content=None, embed=embed, view=None)
            return

        # PvP
        if self.player_choice is not None and self.opponent_choice is not None:
             p1 = choices[self.player_choice]
             p2 = choices[self.opponent_choice]
             
             res = self.get_result(self.player_choice, self.opponent_choice)
             if res == "Win": final = f"{self.player.mention} wins!"
             elif res == "Lose": final = f"{self.opponent.mention} wins!"
             else: final = "It's a tie!"
             
             embed = discord.Embed(title="Rock Paper Scissors", color=discord.Color.blue())
             embed.add_field(name=self.player.display_name, value=p1)
             embed.add_field(name=self.opponent.display_name, value=p2)
             embed.description = f"**{final}**"
             
             await interaction.response.edit_message(content=None, embed=embed, view=None)

    def get_result(self, p1, p2):
        if p1 == p2: return "Tie"
        if (p1 == 0 and p2 == 2) or (p1 == 1 and p2 == 0) or (p1 == 2 and p2 == 1):
            return "Win"
        return "Lose"

    @discord.ui.button(label="Rock", style=discord.ButtonStyle.primary, emoji="🪨")
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_choice(interaction, 0)

    @discord.ui.button(label="Paper", style=discord.ButtonStyle.primary, emoji="📄")
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_choice(interaction, 1)

    @discord.ui.button(label="Scissors", style=discord.ButtonStyle.primary, emoji="✂️")
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_choice(interaction, 2)

    async def process_choice(self, interaction, choice: int):
        if interaction.user == self.player:
            self.player_choice = choice
            await interaction.response.send_message("You chose!", ephemeral=True)
        elif interaction.user == self.opponent:
            self.opponent_choice = choice
            await interaction.response.send_message("You chose!", ephemeral=True)
        else:
            await interaction.response.send_message("Not your game.", ephemeral=True)
            return

        if self.opponent:
            if self.player_choice is not None and self.opponent_choice is not None:
                await self.determine_winner(interaction)
        else:
            await self.determine_winner(interaction)

class TriviaView(discord.ui.View):
    def __init__(self, correct_answer, all_answers):
        super().__init__()
        self.correct_answer = correct_answer
        self.value = None
        
        # Shuffle answers and create buttons
        random.shuffle(all_answers)
        for ans in all_answers:
            self.add_item(TriviaButton(ans))

class TriviaButton(discord.ui.Button):
    def __init__(self, label):
        super().__init__(style=discord.ButtonStyle.secondary, label=html.unescape(label))

    async def callback(self, interaction: discord.Interaction):
        view: TriviaView = self.view
        
        if self.label == html.unescape(view.correct_answer):
            self.style = discord.ButtonStyle.success
            view.value = True
            msg = "Correct!"
        else:
            self.style = discord.ButtonStyle.danger
            view.value = False
            msg = f"Wrong! The answer was {html.unescape(view.correct_answer)}"
            
        for child in view.children:
            child.disabled = True
            if child.label == html.unescape(view.correct_answer):
                child.style = discord.ButtonStyle.success
        
        await interaction.response.edit_message(content=f"{interaction.user.mention} answered: {msg}", view=view)
        view.stop()

# --- MAIN COG ---

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info('Fun Cog loaded.')

    @commands.hybrid_group(name="fun", description="Fun commands for everyone!")
    async def fun(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `/fun help` or select a subcommand.")

    @fun.command(name="tictactoe", description="Play Tic-Tac-Toe with a friend.")
    async def tictactoe(self, ctx, opponent: discord.Member):
        if opponent == ctx.author or opponent.bot:
            await ctx.send("You cannot play against yourself or a bot.")
            return

        await ctx.send(f"Tic-Tac-Toe: {ctx.author.mention} vs {opponent.mention}", view=TicTacToeView(ctx.author, opponent))

    @fun.command(name="8ball", description="Ask the magic 8ball a question.")
    async def eight_ball(self, ctx, *, question: str):
        responses = [
            "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes - definitely.",
            "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
            "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
            "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
            "Don't count on it.", "My reply is no.", "My sources say no.",
            "Outlook not so good.", "Very doubtful."
        ]
        await ctx.send(f"🎱 Question: {question}\nAnswer: **{random.choice(responses)}**")

    @fun.command(name="meme", description="Get a random meme.")
    async def meme(self, ctx):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            try:
                # Using a public meme api (example one)
                async with session.get('https://meme-api.com/gimme') as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        embed = discord.Embed(title=data['title'], url=data['postLink'], color=discord.Color.random())
                        embed.set_image(url=data['url'])
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("Could not fetch a meme at the moment.")
            except Exception as e:
                await ctx.send(f"Error fetching meme: {e}")

    @fun.command(name="rate", description="Rate something!")
    async def rate(self, ctx, category: str, *, target: str = "yourself"):
        rating = random.randint(0, 100)
        category = category.lower()
        if target.lower() == "me":
            target = "you"
        
        comments = ["Not bad!", "Wow!", "Oof...", "Incredible!", "Yikes."]
        comment = random.choice(comments)
        
        await ctx.send(f"I rate **{target}**'s **{category}** a **{rating}/100**. {comment}")

    @fun.command(name="confess", description="Send an anonymous confession.")
    async def confess(self, ctx, *, confession: str):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        else:
            try:
                await ctx.message.delete()
            except Exception:
                pass
        embed = discord.Embed(
            title="Confesión anónima",
            description=f'"{confession}"',
            color=discord.Color.pink(),
        )
        embed.set_footer(text="Enviado de forma anónima · Dabot")
        sent = False
        try:
            webhooks = await ctx.channel.webhooks()
            wh = discord.utils.get(webhooks, name="Dabot Confess") or discord.utils.get(webhooks, name="Dabot Ticket Log")
            if not wh:
                wh = await ctx.channel.create_webhook(name="Dabot Confess", reason="Confesiones anónimas")
            await wh.send(
                embed=embed,
                username="Confesión anónima",
                avatar_url=str(ctx.guild.me.display_avatar.url) if ctx.guild and ctx.guild.me else None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            sent = True
        except Exception:
            try:
                await ctx.channel.send(embed=embed)
                sent = True
            except Exception:
                sent = False
        if ctx.interaction:
            if sent:
                await ctx.followup.send("✅ Confesión enviada. Nadie verá que fuiste tú.", ephemeral=True)
            else:
                await ctx.followup.send("❌ No pude publicar la confesión (faltan permisos de webhook).", ephemeral=True)

    @fun.command(name="pet", description="Get a random animal image.")
    async def pet(self, ctx, animal: Literal["dog", "cat", "fox", "perro", "gato", "zorro"] = "dog"):
        animal = animal.lower()
        url = ""
        if animal in ["dog", "perro"]:
            api = "https://random.dog/woof.json"
            key = "url"
        elif animal in ["cat", "gato"]:
            api = "https://api.thecatapi.com/v1/images/search"
            key = None # List result
        elif animal in ["fox", "zorro"]:
            api = "https://randomfox.ca/floof/"
            key = "image"
        else:
            await ctx.send("Supported animals: dog, cat, fox.")
            return

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            try:
                async with session.get(api) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if key:
                            url = data[key]
                        elif isinstance(data, list):
                             url = data[0]['url']
                        
                        embed = discord.Embed(title=f"Here is a random {animal}!", color=discord.Color.random())
                        embed.set_image(url=url)
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("Could not fetch image.")
            except Exception as e:
                await ctx.send(f"Error fetching image: {e}")



    @fun.command(name="ship", description="Calculate compatibility between two users!")
    async def ship(self, ctx, user1: discord.Member, user2: discord.Member = None):
        """
        Calculate love compatibility between two users.
        """
        if user2 is None:
            user2 = ctx.author
        
        # Generate consistent percentage based on user IDs
        seed = user1.id + user2.id
        random.seed(seed)
        compatibility = random.randint(0, 100)
        random.seed()  # Reset seed
        
        # Create ship name
        name1 = user1.display_name[:len(user1.display_name)//2]
        name2 = user2.display_name[len(user2.display_name)//2:]
        ship_name = name1 + name2
        
        # Heart meter
        filled = int(compatibility / 10)
        empty = 10 - filled
        meter = "❤️" * filled + "🖤" * empty
        
        # Compatibility message
        if compatibility >= 90:
            message = "Perfect match! 💕"
        elif compatibility >= 70:
            message = "Great compatibility! 💖"
        elif compatibility >= 50:
            message = "Good potential! 💗"
        elif compatibility >= 30:
            message = "It could work... 💙"
        else:
            message = "Not meant to be... 💔"
        
        embed = discord.Embed(
            title=f"💘 {ship_name}",
            description=f"{user1.mention} 💕 {user2.mention}",
            color=discord.Color.pink()
        )
        embed.add_field(name="Compatibility", value=f"{compatibility}%", inline=False)
        embed.add_field(name="Love Meter", value=meter, inline=False)
        embed.add_field(name="Result", value=message, inline=False)
        
        await ctx.send(embed=embed)
    
    @fun.command(name="hack", description="Hack a user (just for fun!)") 
    async def hack(self, ctx, user: discord.Member):
        """
        Simulate hacking a user (harmless prank).
        """
        if user == ctx.author:
            await ctx.send("❌ You can't hack yourself!")
            return
        
        if user.bot:
            await ctx.send("❌ Nice try, but bots are unhackable! 🤖")
            return
        
        messages = [
            f"🔍 Finding Discord login... `{user.name}#{user.discriminator}`",
            "📡 Connecting to Discord servers...",
            "🔐 Bypassing 2FA authentication...",
            "💾 Downloading user data...",
            f"📧 Email: `{user.name.lower()}@gmail.com`",
            f"🔑 Password: `{'*' * random.randint(8, 16)}`",
            f"📱 IP Address: `{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}`",
            "💰 Stealing Nitro...",
            "🎮 Accessing game library...",
            f"✅ Successfully hacked {user.mention}!"
        ]
        
        embed = discord.Embed(
            title=f"🔓 Hacking {user.display_name}...",
            description="",
            color=discord.Color.red()
        )
        
        msg = await ctx.send(embed=embed)
        
        for message in messages:
            embed.description += f"\n{message}"
            await msg.edit(embed=embed)
            await asyncio.sleep(1.5)
        
        embed.color = discord.Color.green()
        embed.set_footer(text="Just kidding! This is a harmless prank 😄")
        await msg.edit(embed=embed)
    
    @fun.command(name="quote", description="Get an inspirational quote!")
    async def quote(self, ctx, category: Literal["motivational", "success", "life", "wisdom", "random"] = "random"):
        """
        Get an inspirational quote from quotable.io API.
        Categories: motivational, success, life, wisdom, random
        """
        try:
            # Map categories to tags
            tag_map = {
                "motivational": "inspirational",
                "success": "success",
                "life": "life",
                "wisdom": "wisdom",
                "random": ""
            }
            
            tag = tag_map.get(category.lower(), "")
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                url = "https://api.quotable.io/random"
                if tag:
                    url += f"?tags={tag}"
                
                async with session.get(url, ssl=False) as resp:
                    if resp.status != 200:
                        await ctx.send("❌ Failed to fetch quote. Try again!")
                        return
                    
                    data = await resp.json()
                    
                    quote_text = data['content']
                    author = data['author']
                    tags = ', '.join(data.get('tags', []))
                    
                    # Translate if server language is not English
                    server_lang = self.bot.config.get(ctx.guild.id, 'language') or 'en'
                    if server_lang != 'en':
                        try:
                            # Map 'zh' to 'zh-CN' for deep_translator if needed, or rely on auto/google support
                            # profound-translator supports 'zh-CN' and 'zh-TW', typically 'zh' maps to simplified.
                            # We'll use server_lang directly as it typically matches (es, fr, de, it, etc.)
                            target_lang = server_lang
                            if target_lang == 'zh': target_lang = 'zh-CN'
                            
                            translator = GoogleTranslator(source='auto', target=target_lang)
                            quote_text = await asyncio.wait_for(
                                asyncio.get_running_loop().run_in_executor(None, translator.translate, quote_text),
                                timeout=8,
                            )
                        except Exception as e:
                            self.logger.error(f"Translation failed: {e}")
                            # Continue with original text if translation fails
            
            embed = discord.Embed(
                description=f"*\"{quote_text}\"*",
                color=discord.Color.gold()
            )
            embed.set_author(name=f"💭 Quote by {author}")
            if tags:
                embed.set_footer(text=f"Tags: {tags}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error fetching quote: {e}")

async def setup(bot):
    await bot.add_cog(Fun(bot))
