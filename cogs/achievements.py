import logging
import discord
from discord.ext import commands
import datetime
import yaml
import os

class Achievements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')

    @commands.hybrid_group(name="achievements", aliases=["achieve"], description="🏆 Achievements system commands.")
    async def achievements_group(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="🏆 Achievements Commands", description=(
                "`/achievements view [user]` — View your achievements\n"
                "`/achievements progress <name>` — View progress towards an achievement\n"
                "`/achievements toggle <on/off>` — Enable or disable the achievements system\n"
                "`/achievements channel [channel]` — Set the channel for achievement announcements"
            ), color=discord.Color.gold())
            await ctx.send(embed=embed)
        self.bot.loop.create_task(self.setup_achievements())
    
    async def setup_achievements(self):
        """Initialize all 30 achievements in the database."""
        await self.bot.wait_until_ready()
        
        achievements = [
            # Messaging (6)
            ("first_message", "First Steps", "Send your first message", "💬", "messages", 1),
            ("chatty", "Chatty", "Send 100 messages", "💭", "messages", 100),
            ("conversationalist", "Conversationalist", "Send 1,000 messages", "🗣️", "messages", 1000),
            ("broadcaster", "Broadcaster", "Send 10,000 messages", "📢", "messages", 10000),
            ("orator", "Orator", "Send 50,000 messages", "🎤", "messages", 50000),
            ("storyteller", "Storyteller", "Send 100,000 messages", "📚", "messages", 100000),
            
            # Leveling (6)
            ("level_5", "Rising Star", "Reach level 5", "⭐", "level", 5),
            ("level_10", "Veteran", "Reach level 10", "🌟", "level", 10),
            ("level_25", "Elite", "Reach level 25", "✨", "level", 25),
            ("level_50", "Legend", "Reach level 50", "💫", "level", 50),
            ("level_75", "Champion", "Reach level 75", "🏆", "level", 75),
            ("level_100", "Grandmaster", "Reach level 100", "👑", "level", 100),
            
            # Economy (6)
            ("first_coin", "First Coin", "Earn 100 coins", "💰", "balance", 100),
            ("wealthy", "Wealthy", "Have 10,000 coins", "💵", "balance", 10000),
            ("millionaire", "Millionaire", "Have 1,000,000 coins", "💎", "balance", 1000000),
            ("banker", "Banker", "Deposit 50,000 in bank", "🏦", "bank", 50000),
            ("gambler", "Gambler", "Play 100 casino games", "🎰", "games_played", 100),
            ("tycoon", "Tycoon", "Earn 10,000,000 total coins", "🤑", "total_earned", 10000000),
            
            # Social (6)
            ("generous", "Generous Soul", "Give 10 reputation", "❤️", "rep_given", 10),
            ("popular", "Popular", "Receive 25 reputation", "🌺", "rep_received", 25),
            ("friendly", "Friendly", "Give 50 reputation", "🤝", "rep_given", 50),
            ("celebrity", "Celebrity", "Receive 100 reputation", "⭐", "rep_received", 100),
            ("social_butterfly", "Social Butterfly", "Interact with 50 users", "👥", "interactions", 50),
            ("party_starter", "Party Starter", "Join voice 100 times", "🎉", "voice_joins", 100),
            
            # Gaming (6)
            ("trivia_master", "Trivia Master", "Win 50 trivia games", "🎯", "trivia_wins", 50),
            ("rps_champion", "RPS Champion", "Win 100 RPS games", "✊", "rps_wins", 100),
            ("lucky", "Lucky", "Win 10 games in a row", "🎲", "win_streak", 10),
            ("math_genius", "Math Genius", "Win 25 math challenges", "🧮", "math_wins", 25),
            ("competitive", "Competitive", "Play 500 total games", "🏅", "total_games", 500),
            ("undefeated", "Undefeated", "Win 50 games without losing", "🥇", "perfect_streak", 50),
        ]
        
        for ach_id, name, description, emoji, req_type, req_value in achievements:
            try:
                await self.bot.db.execute(
                    "INSERT OR IGNORE INTO achievements (name, description, emoji, requirement_type, requirement_value) VALUES (?, ?, ?, ?, ?)",
                    name, description, emoji, req_type, req_value
                )
            except Exception as e:
                self.logger.error(f"Error creating achievement {name}: {e}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Track messages for achievements."""
        if message.author.bot or not message.guild:
            return
        
        # Update message count
        current_count = await self.bot.db.fetch(
            "SELECT count FROM message_count WHERE user_id = ? AND guild_id = ?",
            message.author.id, message.guild.id
        )
        
        if current_count:
            new_count = current_count[0] + 1
            await self.bot.db.execute(
                "UPDATE message_count SET count = ? WHERE user_id = ? AND guild_id = ?",
                new_count, message.author.id, message.guild.id
            )
        else:
            new_count = 1
            await self.bot.db.execute(
                "INSERT INTO message_count (user_id, guild_id, count) VALUES (?, ?, ?)",
                message.author.id, message.guild.id, 1
            )
        
        # Check message achievements
        await self.check_achievement(message.author, message.guild, "messages", new_count)
    
    async def check_achievement(self, user, guild, requirement_type, current_value):
        """Check if user unlocked any achievements."""
        # Check global toggle
        config = self.bot.config.get(guild.id)
        if not config or not config.get('achievements', {}).get('enabled', False):
            return
        disabled = set(str(x) for x in (config.get('achievements', {}).get('disabled_ids') or []))

        # Get achievements of this type that user qualifies for
        achievements = await self.bot.db.fetch_all(
            "SELECT id, name, description, emoji, requirement_value FROM achievements WHERE requirement_type = ? AND requirement_value <= ?",
            requirement_type, current_value
        )
        
        for ach_id, name, description, emoji, req_value in achievements:
            if str(ach_id) in disabled or (name or "") in disabled:
                continue
            # Check if user already has it
            has_it = await self.bot.db.fetch(
                "SELECT 1 FROM user_achievements WHERE user_id = ? AND guild_id = ? AND achievement_id = ?",
                user.id, guild.id, ach_id
            )
            
            if not has_it:
                # Award achievement
                timestamp = datetime.datetime.now().isoformat()
                await self.bot.db.execute(
                    "INSERT INTO user_achievements (user_id, guild_id, achievement_id, earned_at) VALUES (?, ?, ?, ?)",
                    user.id, guild.id, ach_id, timestamp
                )
                
                # Notify user - Channel Logic
                target_channel = None
                
                # 1. Check configured channel
                ach_config = config.get('achievements', {}) if config else {}
                channel_id = ach_config.get('channel_id')
                
                if channel_id:
                     target_channel = guild.get_channel(int(channel_id))
                
                # 2. Fallback to General/System channel or current context (hard to get context here without passing it)
                if not target_channel:
                     if guild.system_channel:
                         target_channel = guild.system_channel
                     else:
                         # Try finding a channel named "general" or "chat"
                         for ch in guild.text_channels:
                             if ch.name in ["general", "chat", "general-chat"]:
                                 target_channel = ch
                                 break
                
                # If still no channel, we might just fail silently or log it. 
                # Preventing DM spam is priority.
                
                if target_channel:
                    embed = discord.Embed(
                        title=f"{emoji} Achievement Unlocked!",
                        description=f"{user.mention} has unlocked **{name}**!\n\n_{description}_",
                        color=discord.Color.gold()
                    )
                    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
                    embed.set_footer(text=f"Congrats {user.display_name}!")
                    
                    try:
                        await target_channel.send(embed=embed)
                    except:
                        pass

    async def check_level_achievement(self, user, guild, level):
        """Check level achievements."""
        await self.check_achievement(user, guild, "level", level)
    
    async def check_balance_achievement(self, user, guild, balance):
        """Check balance achievements."""
        await self.check_achievement(user, guild, "balance", balance)
    
    async def check_game_achievement(self, user, guild, game_type, wins):
        """Check game achievements."""
        achievement_map = {
            "trivia": "trivia_wins",
            "rps": "rps_wins",
            "math": "math_wins"
        }
        
        if game_type in achievement_map:
            await self.check_achievement(user, guild, achievement_map[game_type], wins)
    
    @achievements_group.command(name="view", description="View your achievements!")
    async def achievements_view(self, ctx, member: discord.Member = None):
        """
        Display achievements for yourself or another user.
        """
        member = member or ctx.author
        
        # Get user's achievements
        user_achievements = await self.bot.db.fetch_all(
            """SELECT a.name, a.description, a.emoji, ua.earned_at 
               FROM user_achievements ua 
               JOIN achievements a ON ua.achievement_id = a.id 
               WHERE ua.user_id = ? AND ua.guild_id = ?
               ORDER BY ua.earned_at DESC""",
            member.id, ctx.guild.id
        )
        
        # Get total achievements
        total_achievements = await self.bot.db.fetch_all(
            "SELECT COUNT(*) FROM achievements"
        )
        total = total_achievements[0][0] if total_achievements else 30
        unlocked = len(user_achievements)
        
        embed = discord.Embed(
            title=f"🏆 {member.display_name}'s Achievements",
            description=f"Unlocked: **{unlocked}/{total}** ({int(unlocked/total*100) if total > 0 else 0}%)",
            color=discord.Color.gold()
        )
        
        if user_achievements:
            for name, description, emoji, earned_at in user_achievements[:15]:
                try:
                    dt = datetime.datetime.fromisoformat(earned_at)
                    date_str = dt.strftime("%Y-%m-%d")
                except:
                    date_str = "Unknown"
                
                embed.add_field(
                    name=f"{emoji} {name}",
                    value=f"{description}\n*Earned: {date_str}*",
                    inline=True
                )
        else:
            embed.add_field(
                name="No achievements yet",
                value="Start chatting, leveling up, and playing games to unlock achievements!",
                inline=False
            )
        
        if unlocked > 15:
            embed.set_footer(text=f"Showing 15 of {unlocked} achievements")
        
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        await ctx.send(embed=embed)
    
    @achievements_group.command(name="progress", description="View progress towards an achievement!")
    async def achievements_progress(self, ctx, *, achievement_name: str):
        """View progress towards a specific achievement."""
        # Find achievement
        achievement = await self.bot.db.fetch(
            "SELECT id, name, description, emoji, requirement_type, requirement_value FROM achievements WHERE LOWER(name) LIKE ?",
            f"%{achievement_name.lower()}%"
        )
        
        if not achievement:
            await ctx.send(f"❌ Achievement '{achievement_name}' not found!")
            return
        
        ach_id, name, description, emoji, req_type, req_value = achievement
        
        # Check if already unlocked
        has_it = await self.bot.db.fetch(
            "SELECT earned_at FROM user_achievements WHERE user_id = ? AND guild_id = ? AND achievement_id = ?",
            ctx.author.id, ctx.guild.id, ach_id
        )
        
        if has_it:
            earned_at = has_it[0]
            try:
                dt = datetime.datetime.fromisoformat(earned_at)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except:
                date_str = "Unknown"
            
            embed = discord.Embed(
                title=f"{emoji} {name}",
                description=f"{description}\n\n✅ **Unlocked!**\nEarned: {date_str}",
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)
            return
        
        # Get current progress
        current = 0
        
        if req_type == "messages":
            result = await self.bot.db.fetch(
                "SELECT count FROM message_count WHERE user_id = ? AND guild_id = ?",
                ctx.author.id, ctx.guild.id
            )
            current = result[0] if result else 0
        
        elif req_type == "level":
            result = await self.bot.db.fetch(
                "SELECT level FROM levels WHERE user_id = ? AND guild_id = ?",
                ctx.author.id, ctx.guild.id
            )
            current = result[0] if result else 0
        
        elif req_type == "balance":
            result = await self.bot.db.fetch(
                "SELECT balance FROM guild_economy WHERE user_id = ? AND guild_id = ?",
                ctx.author.id, ctx.guild.id
            )
            current = result[0] if result else 0
        
        elif req_type in ["trivia_wins", "rps_wins", "math_wins"]:
            game_type = req_type.replace("_wins", "")
            result = await self.bot.db.fetch(
                "SELECT wins FROM game_stats WHERE user_id = ? AND guild_id = ? AND game_type = ?",
                ctx.author.id, ctx.guild.id, game_type
            )
            current = result[0] if result else 0
        
        # Calculate progress
        progress_percent = min(int((current / req_value) * 100), 100)
        progress_bar = "█" * (progress_percent // 10) + "░" * (10 - (progress_percent // 10))
        
        embed = discord.Embed(
            title=f"{emoji} {name}",
            description=description,
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Progress",
            value=f"{progress_bar} {progress_percent}%\n**{current:,}** / **{req_value:,}**",
            inline=False
        )
        embed.add_field(
            name="Remaining",
            value=f"**{max(req_value - current, 0):,}** more needed",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @achievements_group.command(name="list", description="List preset achievements (can be removed per server).")
    @commands.has_permissions(administrator=True)
    async def achievements_list(self, ctx):
        rows = await self.bot.db.fetch_all(
            "SELECT id, name, emoji, requirement_type, requirement_value FROM achievements ORDER BY id"
        )
        cfg = (self.bot.config.get(ctx.guild.id) or {}).get("achievements") or {}
        disabled = set(str(x) for x in (cfg.get("disabled_ids") or []))
        lines = []
        for ach_id, name, emoji, req_type, req_value in (rows or [])[:25]:
            mark = "🚫" if str(ach_id) in disabled or name in disabled else "✅"
            lines.append(f"{mark} `{ach_id}` {emoji} **{name}** — {req_type} ≥ {req_value}")
        embed = discord.Embed(
            title="Logros predefinidos",
            description="\n".join(lines) or "Ninguno",
            color=discord.Color.gold(),
        )
        embed.set_footer(text="/achievements remove <id> para quitar uno de este servidor")
        await ctx.send(embed=embed)

    @achievements_group.command(name="remove", description="Disable a preset achievement in this server.")
    @commands.has_permissions(administrator=True)
    async def achievements_remove(self, ctx, achievement_id: int):
        row = await self.bot.db.fetch("SELECT id, name FROM achievements WHERE id = ?", achievement_id)
        if not row:
            await ctx.send("❌ No existe ese logro.")
            return
        cfg = (self.bot.config.get(ctx.guild.id) or {}).get("achievements") or {}
        disabled = [str(x) for x in (cfg.get("disabled_ids") or [])]
        if str(achievement_id) not in disabled:
            disabled.append(str(achievement_id))
        self.bot.config.set_config(ctx.guild.id, "achievements.disabled_ids", disabled)
        await ctx.send(f"✅ El logro **{row[1]}** (`{achievement_id}`) ya no se otorga en este servidor.")

    @achievements_group.command(name="restore", description="Re-enable a previously removed achievement.")
    @commands.has_permissions(administrator=True)
    async def achievements_restore(self, ctx, achievement_id: int):
        cfg = (self.bot.config.get(ctx.guild.id) or {}).get("achievements") or {}
        disabled = [str(x) for x in (cfg.get("disabled_ids") or []) if str(x) != str(achievement_id)]
        self.bot.config.set_config(ctx.guild.id, "achievements.disabled_ids", disabled)
        await ctx.send(f"✅ Logro `{achievement_id}` restaurado en este servidor.")

    @achievements_group.command(name="toggle", description="Enable or disable the achievements system.")
    @commands.has_permissions(administrator=True)
    async def achievements_toggle(self, ctx, enabled: bool):
        """Enable or disable achievements."""
        self.bot.config.set_config(ctx.guild.id, "achievements.enabled", enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(f"✅ Achievements system has been **{status}**.")

    @achievements_group.command(name="channel", description="Set the channel for achievement announcements.")
    @commands.has_permissions(administrator=True)
    async def achievements_channel(self, ctx, channel: discord.TextChannel = None):
        """Set where achievement unlocks are posted."""
        if channel:
            self.bot.config.set_config(ctx.guild.id, "achievements.channel_id", channel.id)
            await ctx.send(f"✅ Achievement announcements will be sent to {channel.mention}.")
        else:
            self.bot.config.set_config(ctx.guild.id, "achievements.channel_id", None)
            await ctx.send(f"✅ Achievement announcements reset (will try System/General channel).")

async def setup(bot):
    await bot.add_cog(Achievements(bot))
