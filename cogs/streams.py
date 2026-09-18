import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import datetime


class Streams(commands.Cog):
    """
    Stream alerts using Discord Presence detection.
    Detects when a member starts streaming on Twitch/YouTube via their Discord activity
    and sends a notification to a configured channel.
    No external API keys required — uses Discord's built-in presence system.
    """
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.Streams')
        # Track who we've already notified to avoid spam: {guild_id: {user_id: last_notified_timestamp}}
        self._notified: dict[int, dict[int, float]] = {}
        self._cooldown_hours = 6  # Don't notify again within 6 hours

    stream_group = app_commands.Group(
        name="stream",
        description="Stream alert notifications.",
        default_permissions=discord.Permissions(manage_guild=True)
    )

    @stream_group.command(name="add", description="Track a member's streams and notify in a channel.")
    @app_commands.describe(
        member="The Discord member to track",
        channel="Channel to send stream alerts"
    )
    async def stream_add(self, interaction: discord.Interaction,
                          member: discord.Member,
                          channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        # Use their Discord username as the "username" for presence-based tracking
        username = str(member.id)

        try:
            await self.bot.db.execute(
                """INSERT INTO stream_alerts (guild_id, channel_id, platform, username, last_notified)
                   VALUES (?, ?, 'discord', ?, NULL)""",
                interaction.guild.id, channel.id, username
            )
        except Exception:
            await interaction.followup.send(f"❌ {member.mention} is already being tracked.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📡 Stream Alert Added",
            description=(
                f"**Member:** {member.mention}\n"
                f"**Channel:** {channel.mention}\n\n"
                f"When {member.display_name} starts streaming on Discord, "
                f"an alert will be sent automatically."
            ),
            color=discord.Color.purple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @stream_group.command(name="remove", description="Stop tracking a member's streams.")
    @app_commands.describe(member="The member to stop tracking")
    async def stream_remove(self, interaction: discord.Interaction, member: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM stream_alerts WHERE guild_id = ? AND username = ?",
            interaction.guild.id, str(member.id)
        )
        await interaction.response.send_message(f"✅ Stopped tracking {member.mention}.", ephemeral=True)

    @stream_group.command(name="list", description="List all tracked streamers.")
    async def stream_list(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetch_all(
            "SELECT username, channel_id FROM stream_alerts WHERE guild_id = ?",
            interaction.guild.id
        )

        if not rows:
            await interaction.response.send_message("📡 No stream alerts configured.", ephemeral=True)
            return

        embed = discord.Embed(title="📡 Stream Alerts", color=discord.Color.purple())
        lines = []
        for username, channel_id in rows:
            member = interaction.guild.get_member(int(username))
            channel = interaction.guild.get_channel(channel_id)
            member_name = member.mention if member else f"Unknown ({username})"
            channel_name = channel.mention if channel else f"Unknown ({channel_id})"
            lines.append(f"• {member_name} → {channel_name}")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """Detect when a member starts streaming via Discord Presence."""
        if after.bot:
            return

        # Check if they started streaming
        was_streaming = any(
            isinstance(a, discord.Streaming) for a in (before.activities or [])
        )
        is_streaming = None
        for activity in (after.activities or []):
            if isinstance(activity, discord.Streaming):
                is_streaming = activity
                break

        if was_streaming or not is_streaming:
            return  # Already was streaming or not streaming now

        guild_id = after.guild.id
        user_id = after.id

        # Check cooldown
        now = datetime.datetime.now().timestamp()
        guild_notified = self._notified.setdefault(guild_id, {})
        last = guild_notified.get(user_id, 0)
        if now - last < self._cooldown_hours * 3600:
            return

        # Check if this member is tracked
        alert = await self.bot.db.fetch(
            "SELECT channel_id FROM stream_alerts WHERE guild_id = ? AND username = ?",
            guild_id, str(user_id)
        )

        if not alert:
            return

        channel_id = alert[0]
        channel = after.guild.get_channel(channel_id)
        if not channel:
            return

        # Build the alert embed
        embed = discord.Embed(
            title=f"🔴 {after.display_name} is now LIVE!",
            description=is_streaming.details or "Come watch the stream!",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(),
            url=is_streaming.url
        )

        if is_streaming.game:
            embed.add_field(name="Playing", value=is_streaming.game, inline=True)

        if is_streaming.platform:
            embed.add_field(name="Platform", value=is_streaming.platform, inline=True)

        if is_streaming.url:
            embed.add_field(name="Link", value=f"[Watch Stream]({is_streaming.url})", inline=True)

        embed.set_thumbnail(url=after.display_avatar.url)

        if is_streaming.assets and is_streaming.assets.get('large_image'):
            large_img = is_streaming.assets['large_image']
            if large_img.startswith('twitch:'):
                embed.set_image(url=f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{large_img[7:]}-640x360.jpg")

        try:
            await channel.send(
                f"🔴 **{after.display_name}** is live! {is_streaming.url or ''}",
                embed=embed
            )
            # Update cooldown
            guild_notified[user_id] = now
            await self.bot.db.execute(
                "UPDATE stream_alerts SET last_notified = ? WHERE guild_id = ? AND username = ?",
                datetime.datetime.now().isoformat(), guild_id, str(user_id)
            )
            self.logger.info(f"📡 Stream alert sent for {after.display_name} in {after.guild.name}")
        except discord.Forbidden:
            self.logger.warning(f"Cannot send stream alert in {channel.name}")


async def setup(bot):
    await bot.add_cog(Streams(bot))
