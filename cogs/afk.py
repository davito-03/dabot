import discord
from discord.ext import commands
from discord import app_commands
import datetime

class AFK(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # {user_id: {"reason": str, "since": datetime}}
        self.afk_users: dict[int, dict] = {}

    @app_commands.command(name="afk", description="Set yourself as AFK. The bot will notify people who mention you.")
    @app_commands.describe(reason="Why are you AFK? (optional)")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK"):
        user_id = interaction.user.id
        self.afk_users[user_id] = {
            "reason": reason,
            "since": datetime.datetime.now()
        }
        embed = discord.Embed(
            description=f"💤 **{interaction.user.display_name}** is now AFK: *{reason}*",
            color=discord.Color.greyple()
        )
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id

        # ── Remove AFK if the user themselves sends a message ──────────────
        if user_id in self.afk_users:
            afk_data = self.afk_users.pop(user_id)
            since = afk_data["since"]
            delta = datetime.datetime.now() - since
            minutes = int(delta.total_seconds() // 60)
            duration_str = f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60}m"

            try:
                await message.channel.send(
                    f"👋 Welcome back, {message.author.mention}! "
                    f"You were AFK for **{duration_str}**.",
                    delete_after=8
                )
            except discord.Forbidden:
                pass

        # ── Notify if someone mentions an AFK user ─────────────────────────
        notified = set()
        for mentioned in message.mentions:
            if mentioned.id in self.afk_users and mentioned.id not in notified:
                afk_data = self.afk_users[mentioned.id]
                since = afk_data["since"]
                delta = datetime.datetime.now() - since
                minutes = int(delta.total_seconds() // 60)
                duration_str = f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60}m"

                embed = discord.Embed(
                    description=(
                        f"💤 **{mentioned.display_name}** is AFK: *{afk_data['reason']}*\n"
                        f"⏱️ Since {duration_str} ago"
                    ),
                    color=discord.Color.greyple()
                )
                try:
                    await message.channel.send(embed=embed, delete_after=10)
                except discord.Forbidden:
                    pass
                notified.add(mentioned.id)


async def setup(bot):
    await bot.add_cog(AFK(bot))
