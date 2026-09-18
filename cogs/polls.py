import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import logging

log = logging.getLogger("Dabot.Polls")


class PollView(discord.ui.View):
    def __init__(self, options: list[str], message_id: int, bot, votes: dict = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.options = options
        self.message_id = message_id
        
        if votes is None:
            self.votes = {i: set() for i in range(len(options))}
        else:
            self.votes = {int(k): set(v) for k, v in votes.items()}
            for i in range(len(options)):
                if i not in self.votes:
                    self.votes[i] = set()

        for i, option in enumerate(options):
            count = len(self.votes.get(i, set()))
            button = discord.ui.Button(
                label=f"{option}  ({count})",
                style=discord.ButtonStyle.primary,
                custom_id=f"dabot:poll:{message_id}:{i}"
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

    def _make_callback(self, option_index: int):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            
            # Toggle logic
            has_voted = user_id in self.votes[option_index]
            
            # Remove from all other options
            for idx in self.votes:
                self.votes[idx].discard(user_id)
                
            if not has_voted:
                self.votes[option_index].add(user_id)
                
            # Serialize for DB
            votes_json = json.dumps({str(k): list(v) for k, v in self.votes.items()})
            try:
                await self.bot.db.execute("UPDATE polls SET votes = ? WHERE message_id = ?", votes_json, self.message_id)
            except Exception as e:
                log.error(f"Failed to update poll votes for message {self.message_id}: {e}")

            # Update button labels
            for i, item in enumerate(self.children):
                if isinstance(item, discord.ui.Button):
                    count = len(self.votes[i])
                    option_name = self.options[i]
                    item.label = f"{option_name}  ({count})"

            await interaction.response.edit_message(view=self)
        return callback


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        try:
            rows = await self.bot.db.fetch_all("SELECT message_id, options, votes FROM polls WHERE closed = 0")
            for row in rows:
                message_id = row[0] if not hasattr(row, "keys") else row["message_id"]
                options_str = row[1] if not hasattr(row, "keys") else row["options"]
                votes_str = row[2] if not hasattr(row, "keys") else row["votes"]
                
                options = json.loads(options_str)
                votes = json.loads(votes_str)
                
                view = PollView(options, message_id, self.bot, votes)
                self.bot.add_view(view, message_id=message_id)
        except Exception as e:
            log.error(f"Failed to load persistent polls: {e}")

    # ── Slash command with individual option fields ──────────────────────────
    poll_group = app_commands.Group(name="poll", description="Encuestas")

    @poll_group.command(name="create", description="Create an interactive poll with up to 10 options.")
    @app_commands.describe(
        question="The poll question",
        option1="Option 1 (required)",
        option2="Option 2 (required)",
        option3="Option 3",
        option4="Option 4",
        option5="Option 5",
        option6="Option 6",
        option7="Option 7",
        option8="Option 8",
        option9="Option 9",
        option10="Option 10",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def poll_slash(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str = None,
        option4: str = None,
        option5: str = None,
        option6: str = None,
        option7: str = None,
        option8: str = None,
        option9: str = None,
        option10: str = None,
    ):
        await interaction.response.defer()

        options = [o for o in [option1, option2, option3, option4, option5,
                                option6, option7, option8, option9, option10] if o]

        embed = discord.Embed(
            title=f"📊 {question}",
            description="Click a button to cast your vote!",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(
            text=f"Poll by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )

        message = await interaction.followup.send(embed=embed, wait=True)
        
        options_json = json.dumps(options)
        now_str = datetime.datetime.now().isoformat()
        
        await self.bot.db.execute(
            "INSERT INTO polls (message_id, channel_id, guild_id, question, options, votes, author_id, created_at) VALUES (?, ?, ?, ?, ?, '{}', ?, ?)",
            message.id, interaction.channel_id, interaction.guild_id, question, options_json, interaction.user.id, now_str
        )

        view = PollView(options, message.id, self.bot)
        await message.edit(view=view)

    @poll_slash.error
    async def poll_slash_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need **Manage Messages** permission to create polls.", ephemeral=True
            )

    # ── Prefix command (keeps | separator syntax for backwards compat) ────────
    @commands.command(name="poll", help="Create a poll. Format: !poll Question | Option 1 | Option 2 ...")
    @commands.has_permissions(manage_messages=True)
    async def poll_prefix(self, ctx, *, text: str):
        parts = [p.strip() for p in text.split("|")]

        if len(parts) < 3:
            await ctx.send(
                "❌ Format: `!poll Question? | Option 1 | Option 2 | ...`\n"
                "💡 Tip: As a slash command, `/poll` has individual fields for each option!"
            )
            return

        if len(parts) > 11:
            await ctx.send("❌ Maximum 10 options allowed.")
            return

        question = parts[0]
        options = parts[1:]

        embed = discord.Embed(
            title=f"📊 {question}",
            description="Click a button to cast your vote!",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(
            text=f"Poll by {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url
        )

        message = await ctx.send(embed=embed)
        
        options_json = json.dumps(options)
        now_str = datetime.datetime.now().isoformat()
        
        await self.bot.db.execute(
            "INSERT INTO polls (message_id, channel_id, guild_id, question, options, votes, author_id, created_at) VALUES (?, ?, ?, ?, ?, '{}', ?, ?)",
            message.id, ctx.channel.id, ctx.guild.id, question, options_json, ctx.author.id, now_str
        )

        view = PollView(options, message.id, self.bot)
        await message.edit(view=view)
        
    async def _close_poll(self, message_id: int, channel: discord.TextChannel):
        row = await self.bot.db.fetch("SELECT * FROM polls WHERE message_id = ?", message_id)
        if not row:
            return None, "Poll not found in database."
        
        closed = row[8] if not hasattr(row, "keys") else row["closed"]
        if closed:
            return None, "This poll is already closed."
            
        await self.bot.db.execute("UPDATE polls SET closed = 1 WHERE message_id = ?", message_id)
        
        question = row[3] if not hasattr(row, "keys") else row["question"]
        options_str = row[4] if not hasattr(row, "keys") else row["options"]
        votes_str = row[5] if not hasattr(row, "keys") else row["votes"]
        
        options = json.loads(options_str)
        votes = json.loads(votes_str)
        
        total_votes = sum(len(v) for v in votes.values())
        
        embed = discord.Embed(
            title=f"📊 Results: {question}",
            description=f"Total votes: {total_votes}",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        
        for i, option in enumerate(options):
            count = len(votes.get(str(i), []))
            percentage = (count / total_votes * 100) if total_votes > 0 else 0
            
            bar_length = 20
            filled = int((percentage / 100) * bar_length)
            empty = bar_length - filled
            bar = "█" * filled + "░" * empty
            
            embed.add_field(name=f"{option} - {count} votes ({percentage:.1f}%)", value=f"`{bar}`", inline=False)
            
        try:
            msg = await channel.fetch_message(message_id)
            if msg:
                # Remove buttons by editing view to None
                await msg.edit(view=None)
        except Exception as e:
            log.warning(f"Could not remove view from original poll message {message_id}: {e}")
            
        return embed, None

    @poll_group.command(name="end", description="End a poll and show results with a bar chart embed.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def poll_end_slash(self, interaction: discord.Interaction, message_id: str):
        try:
            m_id = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
            return
            
        embed, error = await self._close_poll(m_id, interaction.channel)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed)
            
    @commands.command(name="poll_close", aliases=["pollclose", "closepoll"], help="Lock a poll and show final results.")
    @commands.has_permissions(manage_messages=True)
    async def poll_close_prefix(self, ctx, message_id: int):
        embed, error = await self._close_poll(message_id, ctx.channel)
        if error:
            await ctx.send(f"❌ {error}")
        else:
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Polls(bot))
