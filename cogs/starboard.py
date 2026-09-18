import discord
from discord.ext import commands
import yaml
import os
import datetime

class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_config(self, guild_id):
        config = self.bot.config.get(guild_id)
        if config:
            return config.get('starboard', {})
        return {}

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if str(payload.emoji) != "⭐":
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        config = self.get_config(guild.id)
        if not config.get('enabled', False):
            return

        channel_id = config.get('channel_id')
        if not channel_id:
            return
        
        starboard_channel = guild.get_channel(int(channel_id))
        if not starboard_channel:
            return

        limit = config.get('limit', 3)

        # Get the message
        channel = guild.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except:
            return
            
        if message.author.bot or message.channel.is_nsfw():
            return # Ignore bots and NSFW for now

        # Count stars
        reaction = discord.utils.get(message.reactions, emoji="⭐")
        if not reaction:
            return
            
        count = reaction.count

        # Check DB if already posted
        entry = await self.bot.db.fetch(
            "SELECT starboard_message_id FROM starboard_messages WHERE original_message_id = ?",
            message.id
        )

        if count >= limit:
            embed = discord.Embed(
                description=message.content,
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now()
            )
            embed.set_author(name=message.author.display_name, icon_url=message.author.avatar.url if message.author.avatar else message.author.default_avatar.url)
            embed.add_field(name="Source", value=f"[Jump to Message]({message.jump_url})")
            
            if message.attachments:
                embed.set_image(url=message.attachments[0].url)

            content = f"⭐ **{count}** | {message.channel.mention}"

            if entry:
                # Update
                starboard_msg_id = entry[0]
                try:
                    starboard_msg = await starboard_channel.fetch_message(starboard_msg_id)
                    await starboard_msg.edit(content=content, embed=embed)
                except:
                    # Message might be deleted, re-send?
                    pass 
            else:
                # Post new
                starboard_msg = await starboard_channel.send(content=content, embed=embed)
                await self.bot.db.execute(
                    "INSERT INTO starboard_messages (original_message_id, starboard_message_id, guild_id, channel_id, starboard_channel_id) VALUES (?, ?, ?, ?, ?)",
                    message.id, starboard_msg.id, guild.id, channel.id, starboard_channel.id
                )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if str(payload.emoji) != "⭐":
            return
            
        # We need to update the star count
        entry = await self.bot.db.fetch(
            "SELECT starboard_message_id, starboard_channel_id FROM starboard_messages WHERE original_message_id = ?",
            payload.message_id
        )
        if not entry:
            return
            
        starboard_msg_id, starboard_channel_id = entry
        
        guild = self.bot.get_guild(payload.guild_id)
        starboard_channel = guild.get_channel(starboard_channel_id)
        if not starboard_channel:
            return
            
        channel = guild.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
            reaction = discord.utils.get(message.reactions, emoji="⭐")
            count = reaction.count if reaction else 0
        except:
             count = 0 
        
        config = self.get_config(payload.guild_id)
        limit = config.get('limit', 3)
        
        try:
            starboard_msg = await starboard_channel.fetch_message(starboard_msg_id)
            
            if count < limit:
                # Delete if below limit
                await starboard_msg.delete()
                await self.bot.db.execute("DELETE FROM starboard_messages WHERE original_message_id = ?", payload.message_id)
            else:
                # Update count
                content = f"⭐ **{count}** | {channel.mention}"
                await starboard_msg.edit(content=content)
        except:
            pass

    @commands.command(name="starboard", description="Setup or disable the starboard.")
    @commands.has_permissions(administrator=True)
    async def starboard(self, ctx, channel: discord.TextChannel = None, limit: int = 3):
        """
        Setup or disable the starboard.
        Run without arguments to disable.
        """
        if channel:
            self.bot.config.set_config(ctx.guild.id, "starboard", {
                "enabled": True,
                "channel_id": channel.id,
                "limit": limit
            })
            await ctx.send(f"✅ Starboard set to {channel.mention} with limit **{limit}** stars.")
        else:
            self.bot.config.set_config(ctx.guild.id, "starboard.enabled", False)
            await ctx.send("✅ Starboard disabled.")

async def setup(bot):
    await bot.add_cog(Starboard(bot))
