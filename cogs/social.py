import discord
from discord.ext import commands
import sqlite3

class Social(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="social", description="Manage your social profile.")
    async def social(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `/social set` or `/social remove`")

    @social.command(name="set")
    async def set_social(self, ctx, platform: str, value: str):
        """
        Set a social link or bio.
        Platforms: bio, twitter, instagram, github, youtube, twitch, website
        """
        platform = platform.lower()
        valid_platforms = ["bio", "twitter", "instagram", "github", "youtube", "twitch", "website"]
        
        if platform not in valid_platforms:
            await ctx.send(f"❌ Invalid platform. Valid options: {', '.join(valid_platforms)}")
            return
            
        # Check if row exists
        exists = await self.bot.db.fetch("SELECT user_id FROM social_profiles WHERE user_id = ?", ctx.author.id)
        if not exists:
            await self.bot.db.execute("INSERT INTO social_profiles (user_id) VALUES (?)", ctx.author.id)
        
        # Update
        # SQL injection unsafe if we interpolated column name directly, but we validate strictly against valid_platforms list above.
        query = f"UPDATE social_profiles SET {platform} = ? WHERE user_id = ?"
        await self.bot.db.execute(query, value, ctx.author.id)
        
        await ctx.send(f"✅ Updated your **{platform}**.")

    @commands.hybrid_command(name="profile", description="View a user's profile.")
    async def profile(self, ctx, member: discord.Member = None):
        """
        Show a comprehensive profile card.
        """
        member = member or ctx.author
        
        # Fetch Data
        socials = await self.bot.db.fetch("SELECT * FROM social_profiles WHERE user_id = ?", member.id)
        eco = None
        glevel = None
        if ctx.guild:
            eco = await self.bot.db.fetch(
                "SELECT balance, bank FROM guild_economy WHERE user_id = ? AND guild_id = ?",
                member.id, ctx.guild.id
            )
            glevel = await self.bot.db.fetch(
                "SELECT xp, level FROM guild_levels WHERE user_id = ? AND guild_id = ?",
                member.id, ctx.guild.id
            )
        global_lvl = await self.bot.db.fetch("SELECT xp, level FROM users WHERE user_id = ?", member.id)
        rep = await self.bot.db.fetch("SELECT COUNT(*) FROM reputation WHERE user_id = ?", member.id)
        
        # Prepare Data
        bio = "No bio set."
        links = []
        
        if socials:
            # socials is tuple: (user_id, bio, twitter, ...) matching schema order
            # schema: user_id, bio, twitter, instagram, github, youtube, twitch, website
            if socials[1]: bio = socials[1]
            
            platforms = ["Twitter", "Instagram", "GitHub", "YouTube", "Twitch", "Website"]
            indices = [2, 3, 4, 5, 6, 7]
            
            for name, idx in zip(platforms, indices):
                if socials[idx]:
                    val = socials[idx]
                    if "http" not in val:
                        val = f"https://{name.lower()}.com/{val}"
                    links.append(f"**{name}:** [Link]({val})")
        
        balance = eco[0] if eco else 0
        bank = eco[1] if eco else 0
        level = glevel[1] if glevel else 1
        xp = glevel[0] if glevel else 0
        g_xp = global_lvl[0] if global_lvl else 0
        g_level = global_lvl[1] if global_lvl else 1
        rep_count = rep[0] if rep else 0
        
        # Build Embed
        embed = discord.Embed(
            description=bio,
            color=member.color
        )
        embed.set_author(name=f"{member.display_name}'s Profile", icon_url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        
        embed.add_field(name="💰 Economía (este server)", value=f"Cartera: {balance}\nBanco: {bank}", inline=True)
        embed.add_field(name="📊 Nivel servidor", value=f"Nivel {level}\n{xp} XP", inline=True)
        embed.add_field(name="🌐 Nivel global", value=f"Nivel {g_level}\n{g_xp} XP", inline=True)
        embed.add_field(name="⭐ Reputation", value=f"{rep_count} Rep", inline=True)
        
        if links:
            embed.add_field(name="🔗 Socials", value="\n".join(links), inline=False)
            
        embed.set_footer(text=f"Joined: {member.joined_at.strftime('%Y-%m-%d')}")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Social(bot))
