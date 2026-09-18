import discord
from discord.ext import commands
import datetime

class Reputation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="reputation", aliases=["rep"], description="📈 Reputation system commands.")
    async def reputation(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="📈 Reputation Commands", description=(
                "`/reputation give <member>` — Give reputation to a user\n"
                "`/reputation top [limit]` — View reputation leaderboard\n"
                "`/reputation reset` — Reset all reputation (Admin only)"
            ), color=discord.Color.green())
            await ctx.send(embed=embed)
    
    @reputation.command(name="give", description="Give reputation to a user.")
    async def reputation_give(self, ctx, member: discord.Member):
        """
        Give reputation points to another user. Can only be used once per 24 hours per user.
        """
        if member.id == ctx.author.id:
            await ctx.send("❌ You cannot give reputation to yourself!")
            return
        
        if member.bot:
            await ctx.send("❌ You cannot give reputation to bots!")
            return
        
        # Check cooldown from database
        cooldown_data = await self.bot.db.fetch(
            "SELECT timestamp FROM reputation WHERE guild_id = ? AND given_by = ? AND user_id = ?",
            ctx.guild.id, ctx.author.id, member.id
        )
        now = datetime.datetime.now()
        
        if cooldown_data:
            try:
                last_time = datetime.datetime.fromisoformat(cooldown_data[0])
                time_diff = (now - last_time).total_seconds()
                
                if time_diff < 86400:  # 24 hours
                    hours_left = int((86400 - time_diff) / 3600)
                    minutes_left = int(((86400 - time_diff) % 3600) / 60)
                    await ctx.send(f"⏰ You can give reputation to {member.mention} again in **{hours_left}h {minutes_left}m**.")
                    return
            except Exception:
                pass
        
        # Give reputation
        timestamp = now.isoformat()
        
        try:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO reputation (user_id, guild_id, given_by, timestamp) VALUES (?, ?, ?, ?)",
                member.id, ctx.guild.id, ctx.author.id, timestamp
            )
            
            # Get total rep
            total_rep = await self.get_reputation(member.id, ctx.guild.id)
            
            embed = discord.Embed(
                title="✨ Reputation Given!",
                description=f"{ctx.author.mention} gave reputation to {member.mention}!",
                color=discord.Color.gold()
            )
            embed.add_field(name="Total Reputation", value=f"⭐ {total_rep} points", inline=False)
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error giving reputation: {e}")
    
    async def get_reputation(self, user_id, guild_id):
        """Get total reputation for a user in a guild."""
        result = await self.bot.db.fetch_all(
            "SELECT COUNT(*) FROM reputation WHERE user_id = ? AND guild_id = ?",
            user_id, guild_id
        )
        return result[0][0] if result else 0
    
    @reputation.command(name="top", description="View reputation leaderboard.")
    async def reputation_top(self, ctx, limit: int = 10):
        """
        Display the top users by reputation points.
        """
        if limit > 25:
            limit = 25
        
        # Get all users with reputation
        all_reps = await self.bot.db.fetch_all(
            "SELECT user_id, COUNT(*) as rep_count FROM reputation WHERE guild_id = ? GROUP BY user_id ORDER BY rep_count DESC LIMIT ?",
            ctx.guild.id, limit
        )
        
        if not all_reps:
            await ctx.send("📊 No reputation data yet! Use `/rep @user` to give reputation.")
            return
        
        embed = discord.Embed(
            title="🏆 Reputation Leaderboard",
            description=f"Top {limit} users by reputation",
            color=discord.Color.gold()
        )
        
        medals = ["🥇", "🥈", "🥉"]
        
        for idx, (user_id, rep_count) in enumerate(all_reps, 1):
            user = ctx.guild.get_member(user_id)
            if user:
                medal = medals[idx - 1] if idx <= 3 else f"**#{idx}**"
                embed.add_field(
                    name=f"{medal} {user.display_name}",
                    value=f"⭐ {rep_count} reputation",
                    inline=False
                )
        
        embed.set_footer(text=f"Server: {ctx.guild.name}")
        await ctx.send(embed=embed)
    
    @reputation.command(name="reset", description="Reset all reputation (Admin only).")
    @commands.has_permissions(administrator=True)
    async def reputation_reset(self, ctx):
        """
        Reset all reputation in the server. Requires confirmation.
        """
        view = ConfirmView(ctx.author)
        embed = discord.Embed(
            title="⚠️ Reset Reputation",
            description="Are you sure you want to reset ALL reputation in this server? This cannot be undone!",
            color=discord.Color.red()
        )
        
        msg = await ctx.send(embed=embed, view=view)
        await view.wait()
        
        if view.value:
            await self.bot.db.execute(
                "DELETE FROM reputation WHERE guild_id = ?",
                ctx.guild.id
            )
            await msg.edit(content="✅ All reputation has been reset.", embed=None, view=None)
        else:
            await msg.edit(content="❌ Reputation reset cancelled.", embed=None, view=None)

class ConfirmView(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=30)
        self.value = None
        self.author = author
    
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Only the command author can confirm.", ephemeral=True)
            return
        
        self.value = True
        self.stop()
        await interaction.response.defer()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Only the command author can cancel.", ephemeral=True)
            return
        
        self.value = False
        self.stop()
        await interaction.response.defer()

async def setup(bot):
    await bot.add_cog(Reputation(bot))
