import discord
from discord.ext import commands
import datetime

class Suggestions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="suggest", description="Submit a suggestion.")
    async def suggest(self, ctx, *, suggestion: str):
        """
        Submit a suggestion to the configured suggestions channel.
        """
        config = self.bot.config.get(ctx.guild.id)
        if not config:
            await ctx.send("❌ Server configuration not found.")
            return
        
        suggestions_config = config.get('suggestions', {})
        channel_id = suggestions_config.get('channel')
        
        if not channel_id:
            await ctx.send("❌ Suggestions channel not configured. Ask an admin to set it up!")
            return
        
        channel = ctx.guild.get_channel(int(channel_id))
        if not channel:
            await ctx.send("❌ Suggestions channel not found.")
            return
        
        embed = discord.Embed(
            title="💡 New Suggestion",
            description=suggestion,
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        embed.set_footer(text=f"ID: {ctx.author.id}")
        
        msg = await channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        
        await ctx.send("✅ Your suggestion has been submitted!", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member.bot:
            return

        config = self.bot.config.get(payload.guild_id)
        if not config: return
        
        suggestions_config = config.get('suggestions', {})
        channel_id = suggestions_config.get('channel')
        threshold = suggestions_config.get('auto_approve_threshold', 10) # Default 10 votes
        
        if not channel_id or payload.channel_id != int(channel_id):
            return

        if str(payload.emoji) != "👍":
            return

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        
        # Check reactions
        upvotes = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == "👍":
                upvotes = reaction.count - 1 # exclude bot
        
        if upvotes >= threshold:
             embed = message.embeds[0]
             if "Accepted" in embed.title:
                 return # Already accepted
                 
             embed.title = "✅ Suggestion Accepted!"
             embed.color = discord.Color.green()
             embed.add_field(name="Status", value=f"Auto-approved with {upvotes} votes.")
             
             await message.edit(embed=embed)
             await channel.send(f"🎉 The suggestion by {embed.author.name} has been automatically approved!", reference=message)
    
async def setup(bot):
    await bot.add_cog(Suggestions(bot))
