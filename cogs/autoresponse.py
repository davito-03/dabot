import discord
from discord.ext import commands
import datetime

class AutoResponse(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        
        # Get all auto-responses for this guild
        responses = await self.bot.db.fetch_all(
            "SELECT trigger, response FROM auto_responses WHERE guild_id = ?",
            message.guild.id
        )
        
        if not responses:
            return
        
        content_lower = message.content.lower()
        
        for trigger, response in responses:
            if trigger.lower() in content_lower:
                await message.channel.send(response)
                break  # Only respond to first match
    
    @commands.command(name="addresponse")
    @commands.has_permissions(manage_guild=True)
    async def addresponse(self, ctx, trigger: str, *, response: str):
        """
        Add an automatic response when a trigger word is detected.
        """
        await self.bot.db.execute(
            "INSERT INTO auto_responses (guild_id, trigger, response, created_by) VALUES (?, ?, ?, ?)",
            ctx.guild.id, trigger, response, ctx.author.id
        )
        await ctx.send(f"✅ Auto-response added!\n**Trigger:** `{trigger}`\n**Response:** {response}")
    
    @commands.command(name="removeresponse")
    @commands.has_permissions(manage_guild=True)
    async def removeresponse(self, ctx, trigger: str):
        """
        Remove an auto-response by its trigger.
        """
        result = await self.bot.db.fetch(
            "SELECT id FROM auto_responses WHERE guild_id = ? AND trigger = ?",
            ctx.guild.id, trigger
        )
        
        if not result:
            await ctx.send(f"❌ No auto-response found for trigger: `{trigger}`")
            return
        
        await self.bot.db.execute(
            "DELETE FROM auto_responses WHERE guild_id = ? AND trigger = ?",
            ctx.guild.id, trigger
        )
        await ctx.send(f"✅ Removed auto-response for trigger: `{trigger}`")
    
    @commands.command(name="responses")
    async def responses(self, ctx):
        """
        View all configured auto-responses for this server.
        """
        responses = await self.bot.db.fetch_all(
            "SELECT trigger, response FROM auto_responses WHERE guild_id = ?",
            ctx.guild.id
        )
        
        if not responses:
            await ctx.send("📝 No auto-responses configured.")
            return
        
        embed = discord.Embed(
            title="🤖 Auto-Responses",
            description=f"Configured responses for {ctx.guild.name}",
            color=discord.Color.blue()
        )
        
        for trigger, response in responses[:25]:  # Limit to 25 to avoid embed limits
            embed.add_field(
                name=f"Trigger: `{trigger}`",
                value=response[:100] + ("..." if len(response) > 100 else ""),
                inline=False
            )
        
        if len(responses) > 25:
            embed.set_footer(text=f"Showing 25 of {len(responses)} responses")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AutoResponse(bot))
