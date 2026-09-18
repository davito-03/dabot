import discord
from discord.ext import commands
from discord import app_commands
import logging


class Quarantine(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')

    async def ensure_table(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS quarantine_config (
                guild_id INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL,
                min_age_days INTEGER NOT NULL DEFAULT 7
            )
        """)

    quarantine_group = app_commands.Group(
        name="quarantine",
        description="Auto-quarantine new accounts based on age.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @quarantine_group.command(name="setup", description="Configure auto-quarantine for new accounts.")
    @app_commands.describe(
        role="The quarantine role to assign to suspicious accounts",
        min_age_days="Minimum account age in days (accounts younger than this get quarantined)"
    )
    async def quarantine_setup(self, interaction: discord.Interaction, role: discord.Role, min_age_days: int = 7):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO quarantine_config (guild_id, role_id, min_age_days) VALUES (?, ?, ?)",
            interaction.guild.id, role.id, min_age_days
        )

        embed = discord.Embed(
            title="✅ Quarantine Configured",
            description=(
                f"**Role:** {role.mention}\n"
                f"**Min Account Age:** {min_age_days} days\n\n"
                f"Accounts younger than **{min_age_days} days** will automatically receive {role.mention} when joining."
            ),
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @quarantine_group.command(name="disable", description="Disable the auto-quarantine system.")
    async def quarantine_disable(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()
        await self.bot.db.execute("DELETE FROM quarantine_config WHERE guild_id = ?", interaction.guild.id)
        await interaction.followup.send("✅ Quarantine system disabled.", ephemeral=True)

    @quarantine_group.command(name="release", description="Manually release a member from quarantine.")
    @app_commands.describe(member="The member to release from quarantine")
    async def quarantine_release(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        config = await self.bot.db.fetch(
            "SELECT role_id FROM quarantine_config WHERE guild_id = ?", interaction.guild.id
        )
        if not config:
            await interaction.followup.send("❌ Quarantine is not configured.", ephemeral=True)
            return

        role = interaction.guild.get_role(config[0])
        if not role:
            await interaction.followup.send("❌ Quarantine role not found.", ephemeral=True)
            return

        if role not in member.roles:
            await interaction.followup.send(f"❌ {member.mention} does not have the quarantine role.", ephemeral=True)
            return

        await member.remove_roles(role, reason=f"Manual quarantine release by {interaction.user}")
        await interaction.followup.send(f"✅ Released {member.mention} from quarantine.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        await self.ensure_table()
        config = await self.bot.db.fetch(
            "SELECT role_id, min_age_days FROM quarantine_config WHERE guild_id = ?", member.guild.id
        )
        if not config:
            return

        role_id, min_age_days = config[0], config[1]

        # Calculate account age
        import datetime
        account_age = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days

        if account_age < min_age_days:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason=f"New account ({account_age}d old, min {min_age_days}d)")
                    self.logger.info(
                        f"[Quarantine] Applied to {member} ({account_age}d old) in {member.guild.name}"
                    )

                    # Log to mod channel if configured
                    config_data = self.bot.config.get(member.guild.id)
                    if config_data:
                        channel_id = config_data.get('logs', {}).get('joins')
                        if channel_id:
                            channel = member.guild.get_channel(int(channel_id))
                            if channel:
                                embed = discord.Embed(
                                    title="🚨 New Account Quarantined",
                                    description=(
                                        f"**User:** {member.mention} ({member.id})\n"
                                        f"**Account Age:** {account_age} days\n"
                                        f"**Minimum Required:** {min_age_days} days\n"
                                        f"**Role:** {role.mention}"
                                    ),
                                    color=discord.Color.red()
                                )
                                await channel.send(embed=embed)
                except discord.Forbidden:
                    self.logger.warning(f"[Quarantine] No permission to assign role in {member.guild.name}")


async def setup(bot):
    await bot.add_cog(Quarantine(bot))
