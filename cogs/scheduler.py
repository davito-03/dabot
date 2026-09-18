import discord
from discord.ext import commands, tasks
import datetime

class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_scheduled_messages.start()

    @commands.hybrid_group(name="schedule", description="📅 Scheduling commands.")
    async def schedule_group(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="📅 Scheduler Commands", description=(
                "`/schedule add <channel> <time> <message>` — Schedule a message to be sent later\n"
                "`/schedule list` — View all scheduled messages\n"
                "`/schedule cancel <message_id>` — Cancel a scheduled message"
            ), color=discord.Color.blue())
            await ctx.send(embed=embed)
    
    def cog_unload(self):
        self.check_scheduled_messages.cancel()
    
    @tasks.loop(minutes=1)
    async def check_scheduled_messages(self):
        """Check for scheduled messages that need to be sent."""
        now = datetime.datetime.now().isoformat()
        
        messages = await self.bot.db.fetch_all(
            "SELECT id, guild_id, channel_id, message, created_by FROM scheduled_messages WHERE scheduled_time <= ?",
            now
        )
        
        for msg_id, guild_id, channel_id, message, created_by in messages:
            guild = self.bot.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        from utils.abuse import guard as abuse_guard
                        ag = abuse_guard(self.bot)
                        if ag and not await ag.allow_outbound(
                            guild=guild,
                            actor_id=created_by,
                            dest_id=channel_id,
                            text=message or "",
                            kind="schedule",
                        ):
                            await self.bot.db.execute(
                                "DELETE FROM scheduled_messages WHERE id = ?",
                                msg_id,
                            )
                            continue
                        embed = discord.Embed(
                            description=message,
                            color=discord.Color.blue(),
                            timestamp=datetime.datetime.now()
                        )
                        embed.set_footer(text=f"Scheduled message • ID: {msg_id}")
                        await channel.send(embed=embed)
                    except:
                        pass
            
            # Delete the scheduled message
            await self.bot.db.execute(
                "DELETE FROM scheduled_messages WHERE id = ?",
                msg_id
            )
    
    @check_scheduled_messages.before_loop
    async def before_check_scheduled_messages(self):
        await self.bot.wait_until_ready()
    
    @schedule_group.command(name="add", description="Schedule a message to be sent later.")
    @commands.has_permissions(manage_messages=True)
    async def schedule_add(self, ctx, channel: discord.TextChannel, time: str, *, message: str):
        """
        Schedule a message to be sent at a specific time.
        Time format: 10m, 2h, 1d (from now)
        """
        import re
        
        # Parse time
        time_units = {'m': 60, 'h': 3600, 'd': 86400}
        match = re.match(r'(\d+)([mhd])', time.lower())
        
        if not match:
            await ctx.send("❌ Invalid time format. Use: 10m, 2h, 1d")
            return
        
        amount, unit = match.groups()
        seconds = int(amount) * time_units[unit]
        
        scheduled_time = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        created_at = datetime.datetime.now()
        
        # Save to database
        msg_id = await self.bot.db.execute(
            "INSERT INTO scheduled_messages (guild_id, channel_id, message, scheduled_time, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ctx.guild.id, channel.id, message, scheduled_time.isoformat(), ctx.author.id, created_at.isoformat()
        )
        
        embed = discord.Embed(
            title="⏰ Message Scheduled",
            description=f"Message will be sent in **{time}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(scheduled_time.timestamp())}:R>", inline=True)
        embed.add_field(name="Message ID", value=f"`{msg_id}`", inline=True)
        embed.add_field(name="Message Preview", value=message[:100] + ("..." if len(message) > 100 else ""), inline=False)
        
        await ctx.send(embed=embed)
    
    @schedule_group.command(name="list", description="View all scheduled messages.")
    @commands.has_permissions(manage_messages=True)
    async def schedule_list(self, ctx):
        """
        View all scheduled messages for this server.
        """
        messages = await self.bot.db.fetch_all(
            "SELECT id, channel_id, message, scheduled_time, created_by FROM scheduled_messages WHERE guild_id = ? ORDER BY scheduled_time ASC",
            ctx.guild.id
        )
        
        if not messages:
            await ctx.send("📅 No scheduled messages.")
            return
        
        embed = discord.Embed(
            title="📅 Scheduled Messages",
            description=f"Total: {len(messages)}",
            color=discord.Color.blue()
        )
        
        for msg_id, channel_id, message, scheduled_time, created_by in messages[:10]:
            channel = ctx.guild.get_channel(channel_id)
            channel_name = channel.mention if channel else f"Deleted Channel ({channel_id})"
            
            try:
                dt = datetime.datetime.fromisoformat(scheduled_time)
                time_str = f"<t:{int(dt.timestamp())}:R>"
            except:
                time_str = "Unknown"
            
            embed.add_field(
                name=f"ID: {msg_id}",
                value=f"**Channel:** {channel_name}\n**Time:** {time_str}\n**Message:** {message[:50]}...",
                inline=False
            )
        
        if len(messages) > 10:
            embed.set_footer(text=f"Showing 10 of {len(messages)} scheduled messages")
        
        await ctx.send(embed=embed)
    
    @schedule_group.command(name="cancel", description="Cancel a scheduled message.")
    @commands.has_permissions(manage_messages=True)
    async def schedule_cancel(self, ctx, message_id: int):
        """
        Cancel a scheduled message by its ID.
        """
        result = await self.bot.db.fetch(
            "SELECT id FROM scheduled_messages WHERE id = ? AND guild_id = ?",
            message_id, ctx.guild.id
        )
        
        if not result:
            await ctx.send(f"❌ No scheduled message found with ID `{message_id}`.")
            return
        
        await self.bot.db.execute(
            "DELETE FROM scheduled_messages WHERE id = ?",
            message_id
        )
        
        await ctx.send(f"✅ Cancelled scheduled message `{message_id}`.")

async def setup(bot):
    await bot.add_cog(Scheduler(bot))
