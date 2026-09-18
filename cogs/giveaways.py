import discord
from discord.ext import commands, tasks
import datetime
import json
import asyncio

class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_giveaways.start()

    async def cog_load(self):
        self.bot.add_view(GiveawayView(self.bot))

    @commands.hybrid_group(name="giveaway", aliases=["g"], description="🎉 Giveaway system commands.")
    async def giveaway(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="🎉 Giveaway Commands", description=(
                "`/giveaway start <time> <winners> <prize>` — Start a giveaway\n"
                "`/giveaway end <msg_id>` — End a giveaway early\n"
                "`/giveaway reroll <msg_id>` — Reroll winners\n"
                "`/giveaway list` — List active giveaways\n"
                "`/giveaway info <msg_id>` — Detailed giveaway info"
            ), color=discord.Color.purple())
            await ctx.send(embed=embed)
    
    def cog_unload(self):
        self.check_giveaways.cancel()
    
    @tasks.loop(minutes=1)
    async def check_giveaways(self):
        """Check for giveaways that need to end."""
        now = datetime.datetime.now().isoformat()
        
        giveaways = await self.bot.db.fetch_all(
            "SELECT * FROM giveaways WHERE ended = 0 AND end_time <= ?",
            now
        )
        
        for giveaway in giveaways:
            await self.end_giveaway(giveaway)
    
    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()
    
    async def end_giveaway(self, giveaway_data):
        """End a giveaway and select winners."""
        giveaway_id, guild_id, channel_id, message_id, prize, winners_count, end_time, host_id, requirements, participants_json, ended = giveaway_data
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        
        try:
            message = await channel.fetch_message(message_id)
        except:
            return
        
        # Parse participants
        try:
            participants = json.loads(participants_json) if participants_json else []
        except:
            participants = []
        
        # Select winners
        import random
        if len(participants) == 0:
            winners = []
        elif len(participants) <= winners_count:
            winners = participants
        else:
            winners = random.sample(participants, winners_count)
        
        # Update database
        await self.bot.db.execute(
            "UPDATE giveaways SET ended = 1 WHERE id = ?",
            giveaway_id
        )
        
        # Update embed
        embed = discord.Embed(
            title=f"🎉 {prize}",
            description="**🏁 Giveaway Ended!**",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🎯 Hosted by", value=f"<@{host_id}>", inline=True)
        embed.add_field(name="🎟️ Total Entries", value=f"**{len(participants)}**", inline=True)
        
        if winners:
            winner_mentions = [f"<@{w}>" for w in winners]
            embed.add_field(name="🏆 Winners", value="\n".join(winner_mentions), inline=False)
        else:
            embed.add_field(name="🏆 Winners", value="No valid entries", inline=False)
        
        embed.set_footer(text="Giveaway ended")
        await message.edit(embed=embed, view=None)
        
        # Announce winners
        if winners:
            winner_mentions = [f"<@{w}>" for w in winners]
            await channel.send(f"🎉 Congratulations {', '.join(winner_mentions)}! You won **{prize}**!")
            
            # DM winners
            for winner_id in winners:
                user = guild.get_member(winner_id)
                if user:
                    try:
                        from utils.abuse import guard as abuse_guard
                        ag = abuse_guard(self.bot)
                        prize_text = str(prize or "")
                        if ag and not await ag.allow_outbound(
                            guild=guild,
                            actor_id=host_id,
                            dest_id=winner_id,
                            text=prize_text,
                            kind="giveaway_dm",
                        ):
                            continue
                        dm_embed = discord.Embed(
                            title="🎉🏆 You Won a Giveaway!",
                            description=f"Congratulations! You won **{prize}** in **{guild.name}**!",
                            color=discord.Color.gold(),
                            timestamp=discord.utils.utcnow()
                        )
                        dm_embed.set_footer(text=f"Hosted by member #{host_id}")
                        await user.send(embed=dm_embed)
                    except:
                        pass
    
    @giveaway.command(name="start", description="Start a giveaway!")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_start(self, ctx, duration: str, winners: int, min_level: int = 0, *, prize: str):
        """
        Start a giveaway.
        Duration: 10m, 2h, 1d
        """
        import re
        
        # Parse duration
        time_units = {'m': 60, 'h': 3600, 'd': 86400}
        match = re.match(r'(\d+)([mhd])', duration.lower())
        
        if not match:
            await ctx.send("❌ Invalid duration format. Use: 10m, 2h, 1d")
            return
        
        amount, unit = match.groups()
        seconds = int(amount) * time_units[unit]
        
        end_time = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        
        # Duration string for display
        dur_display = f"{amount}{'min' if unit == 'm' else ('hr' if unit == 'h' else 'day')}{'s' if int(amount) > 1 else ''}"
        
        # Create embed
        embed = discord.Embed(
            title=f"🎉 {prize}",
            description=(
                f"Click the button below to enter!\n\n"
                f"⏰ **Ends:** <t:{int(end_time.timestamp())}:R>\n"
                f"🏆 **Winners:** {winners}\n"
                f"🎯 **Hosted by:** {ctx.author.mention}"
            ),
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=end_time
        )
        
        # Add requirements
        reqs = {}
        if min_level > 0:
            reqs['min_level'] = min_level
            embed.add_field(name="📋 Requirements", value=f"Level {min_level}+", inline=True)
            
        embed.add_field(name="🎟️ Entries", value="0", inline=True)
        embed.set_footer(text=f"Duration: {dur_display} • Ends at")
        
        view = GiveawayView(self.bot)
        msg = await ctx.send(embed=embed, view=view)
        
        # Save to database
        await self.bot.db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners_count, end_time, host_id, requirements, participants, ended) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ctx.guild.id, ctx.channel.id, msg.id, prize, winners, end_time.isoformat(), ctx.author.id, json.dumps(reqs), "[]", 0
        )
    
    @giveaway.command(name="end", description="End a giveaway early.")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx, message_id: str):
        """End a giveaway early by message ID."""
        try:
            msg_id = int(message_id)
        except:
            await ctx.send("❌ Invalid message ID!")
            return
        
        giveaway = await self.bot.db.fetch(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ? AND ended = 0",
            msg_id, ctx.guild.id
        )
        
        if not giveaway:
            await ctx.send("❌ No active giveaway found with that message ID!")
            return
        
        await self.end_giveaway(giveaway)
        await ctx.send("✅ Giveaway ended!")
    
    @giveaway.command(name="reroll", description="Reroll giveaway winners.")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, ctx, message_id: str):
        """Reroll winners for a giveaway."""
        try:
            msg_id = int(message_id)
        except:
            await ctx.send("❌ Invalid message ID!")
            return
        
        giveaway = await self.bot.db.fetch(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ?",
            msg_id, ctx.guild.id
        )
        
        if not giveaway:
            await ctx.send("❌ No giveaway found with that message ID!")
            return
        
        giveaway_id, guild_id, channel_id, message_id, prize, winners_count, end_time, host_id, requirements, participants_json, ended = giveaway
        
        # Parse participants
        try:
            participants = json.loads(participants_json) if participants_json else []
        except:
            participants = []
        
        if len(participants) == 0:
            await ctx.send("❌ No participants to reroll!")
            return
        
        # Select new winners
        import random
        if len(participants) <= winners_count:
            winners = participants
        else:
            winners = random.sample(participants, winners_count)
        
        winner_mentions = [f"<@{w}>" for w in winners]
        await ctx.send(f"🎉 New winners: {', '.join(winner_mentions)}! You won **{prize}**!")
    
    @giveaway.command(name="list", description="List active giveaways.")
    async def giveaway_list(self, ctx):
        """List all active giveaways in the server."""
        giveaways = await self.bot.db.fetch_all(
            "SELECT * FROM giveaways WHERE guild_id = ? AND ended = 0",
            ctx.guild.id
        )
        
        if not giveaways:
            await ctx.send("📊 No active giveaways!")
            return
        
        embed = discord.Embed(
            title="🎉 Active Giveaways",
            color=discord.Color.from_rgb(88, 101, 242)
        )
        
        for giveaway in giveaways[:10]:
            giveaway_id, guild_id, channel_id, message_id, prize, winners_count, end_time, host_id, requirements, participants_json, ended = giveaway
            
            try:
                participants = json.loads(participants_json) if participants_json else []
            except:
                participants = []
            
            try:
                end_dt = datetime.datetime.fromisoformat(end_time)
                end_ts = int(end_dt.timestamp())
                time_str = f"<t:{end_ts}:R>"
            except:
                time_str = end_time
            
            embed.add_field(
                name=f"🎁 {prize}",
                value=(
                    f"**Channel:** <#{channel_id}>\n"
                    f"**Winners:** {winners_count}\n"
                    f"**Entries:** {len(participants)}\n"
                    f"**Ends:** {time_str}\n"
                    f"**ID:** `{message_id}`"
                ),
                inline=False
            )
        
        await ctx.send(embed=embed)

    @giveaway.command(name="info", description="View detailed info about a giveaway.")
    async def giveaway_info(self, ctx, message_id: str):
        """View detailed information about a specific giveaway."""
        try:
            msg_id = int(message_id)
        except:
            await ctx.send("❌ Invalid message ID!")
            return

        giveaway = await self.bot.db.fetch(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ?",
            msg_id, ctx.guild.id
        )

        if not giveaway:
            await ctx.send("❌ No giveaway found with that message ID!")
            return

        giveaway_id, guild_id, channel_id, message_id_val, prize, winners_count, end_time, host_id, requirements, participants_json, ended = giveaway

        try:
            participants = json.loads(participants_json) if participants_json else []
        except:
            participants = []

        try:
            reqs = json.loads(requirements) if requirements else {}
        except:
            reqs = {}

        # Status
        status = "🏁 Ended" if ended else "🟢 Active"
        
        # Time display
        try:
            end_dt = datetime.datetime.fromisoformat(end_time)
            end_ts = int(end_dt.timestamp())
            if ended:
                time_str = f"<t:{end_ts}:F>"
            else:
                time_str = f"<t:{end_ts}:R> (<t:{end_ts}:F>)"
        except:
            time_str = end_time

        # Requirements display
        req_parts = []
        if reqs.get('min_level'):
            req_parts.append(f"Level {reqs['min_level']}+")
        req_str = ", ".join(req_parts) if req_parts else "None"

        embed = discord.Embed(
            title=f"🎉 Giveaway Info: {prize}",
            color=discord.Color.gold() if not ended else discord.Color.greyple(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📡 Status", value=status, inline=True)
        embed.add_field(name="🎯 Hosted by", value=f"<@{host_id}>", inline=True)
        embed.add_field(name="🏆 Winners", value=str(winners_count), inline=True)
        embed.add_field(name="🎟️ Entries", value=f"**{len(participants)}**", inline=True)
        embed.add_field(name="⏰ Ends", value=time_str, inline=True)
        embed.add_field(name="📋 Requirements", value=req_str, inline=True)
        embed.add_field(name="📍 Channel", value=f"<#{channel_id}>", inline=True)
        embed.add_field(name="🆔 Message ID", value=f"`{message_id_val}`", inline=True)

        # Show recent participants (up to 10)
        if participants:
            recent = participants[-10:]
            participant_mentions = [f"<@{p}>" for p in recent]
            plist = ", ".join(participant_mentions)
            if len(participants) > 10:
                plist += f" ... (+{len(participants) - 10} more)"
            embed.add_field(name="👥 Recent Participants", value=plist, inline=False)

        embed.set_footer(text="Use /giveaway reroll to pick new winners")
        await ctx.send(embed=embed)


class GiveawayView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
    
    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.primary, emoji="🎉", custom_id="giveaway_enter")
    async def enter_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Get giveaway from database
        giveaway = await self.bot.db.fetch(
            "SELECT * FROM giveaways WHERE message_id = ? AND ended = 0",
            interaction.message.id
        )
        
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway has ended!", ephemeral=True)
            return
        
        giveaway_id, guild_id, channel_id, message_id, prize, winners_count, end_time, host_id, requirements, participants_json, ended = giveaway
        
        # Parse participants
        try:
            participants = json.loads(participants_json) if participants_json else []
        except:
            participants = []
        
        # Check requirements
        try:
            reqs = json.loads(requirements) if requirements else {}
        except:
            reqs = {}
            
        if 'min_level' in reqs:
            min_level = reqs['min_level']
            # Fetch user level
            level_data = await self.bot.db.fetch("SELECT level FROM guild_levels WHERE guild_id = ? AND user_id = ?", interaction.guild.id, interaction.user.id)
            user_level = level_data[0] if level_data else 0
            
            if user_level < min_level:
                await interaction.response.send_message(f"❌ You need to be level **{min_level}** to join (You are level {user_level}).", ephemeral=True)
                return

        # Check if already entered
        if interaction.user.id in participants:
            await interaction.response.send_message("❌ You're already entered! Use the **Leave** button to withdraw.", ephemeral=True)
            return
        
        # Add participant
        participants.append(interaction.user.id)
        
        # Update database
        await self.bot.db.execute(
            "UPDATE giveaways SET participants = ? WHERE id = ?",
            json.dumps(participants), giveaway_id
        )
        
        # Update embed with new entry count
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "🎟️ Entries":
                embed.set_field_at(i, name="🎟️ Entries", value=f"**{len(participants)}**", inline=True)
                break
        
        # Update button label with count
        button.label = f"Enter Giveaway ({len(participants)})"
        
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"✅ You've entered the giveaway for **{prize}**! Good luck! 🍀", ephemeral=True)

        # DM confirmation
        try:
            end_dt = datetime.datetime.fromisoformat(end_time)
            end_ts = int(end_dt.timestamp())
            dm_embed = discord.Embed(
                title="🎉 Giveaway Entry Confirmed!",
                description=(
                    f"You've entered a giveaway for **{prize}**!\n\n"
                    f"⏰ Ends: <t:{end_ts}:R>\n"
                    f"📍 Server: **{interaction.guild.name}**"
                ),
                color=discord.Color.from_rgb(88, 101, 242)
            )
            await interaction.user.send(embed=dm_embed)
        except:
            pass  # DMs might be disabled

    @discord.ui.button(label="Leave Giveaway", style=discord.ButtonStyle.danger, emoji="❌", custom_id="giveaway_leave")
    async def leave_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Allow users to leave a giveaway."""
        giveaway = await self.bot.db.fetch(
            "SELECT * FROM giveaways WHERE message_id = ? AND ended = 0",
            interaction.message.id
        )

        if not giveaway:
            await interaction.response.send_message("❌ This giveaway has ended!", ephemeral=True)
            return

        giveaway_id, guild_id, channel_id, message_id, prize, winners_count, end_time, host_id, requirements, participants_json, ended = giveaway

        try:
            participants = json.loads(participants_json) if participants_json else []
        except:
            participants = []

        if interaction.user.id not in participants:
            await interaction.response.send_message("❌ You're not entered in this giveaway!", ephemeral=True)
            return

        # Remove participant
        participants.remove(interaction.user.id)

        await self.bot.db.execute(
            "UPDATE giveaways SET participants = ? WHERE id = ?",
            json.dumps(participants), giveaway_id
        )

        # Update embed
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "🎟️ Entries":
                embed.set_field_at(i, name="🎟️ Entries", value=f"**{len(participants)}**", inline=True)
                break

        # Update enter button label
        for item in self.children:
            if hasattr(item, 'custom_id') and item.custom_id == "giveaway_enter":
                if len(participants) > 0:
                    item.label = f"Enter Giveaway ({len(participants)})"
                else:
                    item.label = "Enter Giveaway"
                break

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ You've left the giveaway.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Giveaways(bot))
