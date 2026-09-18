import logging
import discord
from discord.ext import commands, tasks
import random
import datetime
import yaml
import os
import math
from utils.helpers import tr

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cd = commands.CooldownMapping.from_cooldown(1, 60.0, commands.BucketType.user)
        self.logger = logging.getLogger('DaBot.Leveling')
        
        self.weekly_leaderboard_loop.start()
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.weekly_leaderboard_loop.cancel()
        self.voice_xp_loop.cancel()

    def get_config(self, guild_id):
        config = self.bot.config.get(guild_id)
        if config:
            return config.get('leveling', {})
        return {}

    def _load_guild_config(self, guild_id):
        return self.bot.config.get(guild_id) or {}

    def _save_guild_config(self, guild_id, config):
        self.bot.config.save_full_config(guild_id, config)

    async def _sync_guild_persona(self, guild):
        """Apply the Premium name as a per-guild nickname.

        Discord does not support a different real bot username/avatar per
        guild. The nickname is global for the member in that guild; custom
        avatars are handled by the Premium webhook persona.
        """
        me = guild.me
        if not me:
            return
        desired = None
        if await self.bot.db.is_guild_premium(guild, self.bot):
            row = await self.bot.db.fetch("SELECT custom_bot_name FROM premium_guilds WHERE guild_id = ?", guild.id)
            desired = (row[0] or "").strip()[:32] if row and row[0] else None
        if (me.nick or None) == desired:
            return
        try:
            await me.edit(nick=desired, reason="Dabot Premium persona synchronization")
        except (discord.Forbidden, discord.HTTPException):
            self.logger.info("Could not update Dabot nickname in guild %s", guild.id)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._sync_guild_persona(guild)

    def _t(self, ctx, key, fallback="", **kwargs):
        guild_id = getattr(getattr(ctx, "guild", None), "id", None)
        return tr(self.bot, guild_id, key, fallback, **kwargs)

    async def add_xp(self, guild_id, user_id, amount):
        user_data = await self.bot.db.fetch(
            "SELECT xp, weekly_xp, level FROM guild_levels WHERE user_id = ? AND guild_id = ?",
            user_id, guild_id
        )
        eco_cog = self.bot.get_cog("Economy")
        if eco_cog and guild_id:
            await eco_cog.update_balance(user_id, max(1, amount // 5), "wallet", guild_id)

        await self.add_global_xp(user_id, amount)

        if not user_data:
            await self.bot.db.execute(
                "INSERT INTO guild_levels (user_id, guild_id, xp, weekly_xp, level) VALUES (?, ?, ?, ?, ?)",
                user_id, guild_id, amount, amount, 1
            )
            return False, 1
        current_xp, current_weekly, current_level = user_data
        new_xp = current_xp + amount
        new_weekly = current_weekly + amount
        xp_needed = current_level * 100
        level_up = False
        if new_xp >= xp_needed:
            current_level += 1
            new_xp -= xp_needed
            level_up = True
        await self.bot.db.execute(
            "UPDATE guild_levels SET xp = ?, weekly_xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            new_xp, new_weekly, current_level, user_id, guild_id
        )
        return level_up, current_level

    async def add_global_xp(self, user_id, amount=None):
        if amount is None:
            amount = random.randint(1, 3)
        user_data = await self.bot.db.fetch("SELECT xp, weekly_xp, level FROM users WHERE user_id = ?", user_id)
        if not user_data:
            await self.bot.db.execute(
                "INSERT INTO users (user_id, xp, weekly_xp, level) VALUES (?, ?, ?, 1)",
                user_id, amount, amount
            )
            return False, 1
        current_xp = user_data[0] or 0
        current_weekly = user_data[1] if len(user_data) > 1 and user_data[1] is not None else 0
        current_level = user_data[2] if len(user_data) > 2 and user_data[2] else 1
        new_xp = current_xp + amount
        new_weekly = current_weekly + amount
        xp_needed = current_level * 200
        level_up = False
        new_level = current_level
        while new_xp >= xp_needed:
            new_xp -= xp_needed
            new_level += 1
            xp_needed = new_level * 200
            level_up = True
        await self.bot.db.execute(
            "UPDATE users SET xp = ?, weekly_xp = ?, level = ? WHERE user_id = ?",
            new_xp, new_weekly, new_level, user_id
        )
        return level_up, new_level

    async def announce_level_up(self, guild, member, new_level, config, current_channel=None):
        level_up_channel_id = config.get('level_up_channel')
        channel = None
        if level_up_channel_id:
            try:
                channel = guild.get_channel(int(level_up_channel_id))
            except Exception:
                pass
        if not channel:
            channel = current_channel
            
        if not channel:
            channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            
        if not channel:
            return
            
        embed = discord.Embed(
            title="🎉 ¡Subida de Nivel!",
            description=f"{member.mention} ha alcanzado el **Nivel {new_level}**!",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"¡Sigue así, {member.display_name}!")
        from utils.webhooks import send_webhook
        await send_webhook(self.bot, channel, embed=embed)
        
        # Check level roles
        role_data = await self.bot.db.fetch(
            "SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?",
            guild.id, new_level
        )
        if role_data:
            role = guild.get_role(role_data[0])
            if role:
                try:
                    await member.add_roles(role, reason=f"Reached level {new_level}")
                    await channel.send(f"🎁 {member.mention} has earned the {role.mention} role!")
                except Exception:
                    pass

    # ══════════════════════════════════════════════════════════════════════
    #  LISTENERS
    # ══════════════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        config = self.get_config(message.guild.id)
        if not config.get('enabled', False):
            return
        if message.channel.id in config.get('ignored_channels', []) or \
           any(role.id in config.get('ignored_roles', []) for role in message.author.roles):
            return
        bucket = self._cd.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            return
        min_xp = config.get('text_xp', {}).get('min', 15)
        max_xp = config.get('text_xp', {}).get('max', 25)
        xp_gain = random.randint(min_xp, max_xp)
        result = await self.add_xp(message.guild.id, message.author.id, xp_gain)
        if result:
            leveled_up, new_level = result
            if leveled_up:
                await self.announce_level_up(message.guild, message.author, new_level, config, message.channel)



    # ══════════════════════════════════════════════════════════════════════
    #  LOOPS
    # ══════════════════════════════════════════════════════════════════════
    @tasks.loop(minutes=5)
    async def voice_xp_loop(self):
        for guild in self.bot.guilds:
            config = self.get_config(guild.id)
            if not config.get('enabled', False):
                continue
            min_xp = config.get('voice_xp', {}).get('min', 10)
            max_xp = config.get('voice_xp', {}).get('max', 20)
            for channel in guild.voice_channels:
                if channel.id in config.get('ignored_channels', []):
                    continue
                members = [m for m in channel.members if not m.bot and not m.voice.self_mute and not m.voice.self_deaf]
                if len(members) < 2:
                    continue
                for member in members:
                    if any(role.id in config.get('ignored_roles', []) for role in member.roles):
                        continue
                    xp_gain = random.randint(min_xp, max_xp)
                    result = await self.add_xp(guild.id, member.id, xp_gain)
                    if result:
                        leveled_up, new_level = result
                        if leveled_up:
                            await self.announce_level_up(guild, member, new_level, config)

    @tasks.loop(minutes=15)
    async def weekly_leaderboard_loop(self):
        """Executes strictly once a week on Monday at 00:00 UTC, persisted via database."""
        now = datetime.datetime.now(datetime.timezone.utc)
        # Only run on Mondays (weekday == 0) between 00:00 and 01:00 UTC
        if now.weekday() != 0 or now.hour != 0:
            return

        current_week_key = f"weekly_xp_{now.strftime('%Y_%W')}"
        try:
            row = await self.bot.db.fetch("SELECT last_run FROM system_schedule WHERE key = ?", current_week_key)
            if row:
                # Already processed for this calendar week. Skip to prevent duplicate postings upon restarts.
                return

            # Mark this week as executed immediately to prevent race conditions
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO system_schedule (key, last_run) VALUES (?, ?)",
                current_week_key, now.isoformat()
            )
        except Exception as e:
            self.logger.error(f"Error checking system_schedule for weekly XP: {e}")
            return

        self.logger.info(f"Iniciando reseteo y publicación semanal de XP para la semana {current_week_key}...")
        for guild in self.bot.guilds:
            config = self.get_config(guild.id)
            channel_id = config.get('leaderboard_channel')
            if not channel_id:
                await self.bot.db.execute("UPDATE guild_levels SET weekly_xp = 0 WHERE guild_id = ?", guild.id)
                continue
                
            try:
                target_channel_id = int(channel_id)
                channel = guild.get_channel(target_channel_id)
            except (ValueError, TypeError):
                channel = None
                
            if not channel:
                await self.bot.db.execute("UPDATE guild_levels SET weekly_xp = 0 WHERE guild_id = ?", guild.id)
                continue
                
            top_users = await self.bot.db.fetch_all(
                "SELECT user_id, weekly_xp FROM guild_levels WHERE guild_id = ? AND weekly_xp > 0 ORDER BY weekly_xp DESC LIMIT 10",
                guild.id
            )
            
            if top_users:
                embed = discord.Embed(title="🏆 Clasificación Semanal de XP 🏆", color=discord.Color.gold())
                medals = ["🥇", "🥈", "🥉"]
                desc_lines = []
                for idx, row in enumerate(top_users, 1):
                    uid = row[0] if (isinstance(row, tuple) or not hasattr(row, 'keys')) else row['user_id']
                    xp = row[1] if (isinstance(row, tuple) or not hasattr(row, 'keys')) else row['weekly_xp']
                    medal = medals[idx - 1] if idx <= 3 else f"**#{idx}**"
                    user = guild.get_member(uid)
                    name = user.display_name if user else f"Usuario ({uid})"
                    desc_lines.append(f"{medal} **{name}** — `{xp:,} XP`")
                embed.description = "\n".join(desc_lines)
                embed.set_footer(text="¡El XP semanal ha sido reiniciado para la nueva semana!")
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    self.logger.warning(f"No se pudo enviar leaderboard semanal en {guild.name}: {e}")

            await self.bot.db.execute("UPDATE guild_levels SET weekly_xp = 0 WHERE guild_id = ?", guild.id)



    @voice_xp_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

    @weekly_leaderboard_loop.before_loop
    async def before_weekly_loop(self):
        await self.bot.wait_until_ready()

    # ══════════════════════════════════════════════════════════════════════
    #  /level GROUP — All leveling commands (1 slash slot)
    # ══════════════════════════════════════════════════════════════════════
    @commands.hybrid_group(name="level", description="⭐ Leveling system commands.")
    async def level(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="⭐ Level Commands", description=(
                "`/level rank [user]` — Rank de este servidor\n"
                "`/level leaderboard` — Ranking del servidor\n"
                "`/level global` — Ranking global del bot\n"
                "`/level set <user> <level>` — Set level (Admin)\n"
                "`/level setxp <user> <xp>` — Set XP (Admin)\n"
                "`/level channel [channel]` — Set level-up channel\n"
                "`/level addrole <level> <role>` — Add role reward\n"
                "`/level roles` — View role rewards\n"
                "`/level removerole <level>` — Remove role reward\n"
                "`/level background <image>` — Set background (Premium)\n"
                "`/level botname <name>` — Set bot name (Premium)\n"
                "`/level botavatar <image>` — Set bot avatar (Premium)\n"
                "`/level toggle <on/off>` — Enable/disable leveling\n"
                "`/level botrank [user]` — Global bot rank"
            ), color=discord.Color.gold())
            await ctx.send(embed=embed)

    @level.command(name="rank", description="Check your rank and level.")
    async def level_rank(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        await ctx.defer()
        user_data = await self.bot.db.fetch("SELECT xp, level FROM guild_levels WHERE user_id = ? AND guild_id = ?", member.id, ctx.guild.id)
        if not user_data:
            xp, lvl = 0, 1
        else:
            xp, lvl = user_data
        rank_data = await self.bot.db.fetch_all("SELECT user_id FROM guild_levels WHERE guild_id = ? ORDER BY level DESC, xp DESC", ctx.guild.id)
        rank = 1
        for r_user in rank_data:
            if r_user[0] == member.id:
                break
            rank += 1
        xp_needed = lvl * 100
        bg_url = None
        is_premium = await self.bot.db.is_guild_premium(ctx.guild, self.bot)
        premium = await self.bot.db.fetch("SELECT custom_background FROM premium_guilds WHERE guild_id = ?", ctx.guild.id)
        if is_premium and premium and premium[0]:
            bg_url = premium[0]
            footer_text = "Premium Server"
        else:
            bg_url = "assets/card_background.jpg"
            footer_text = ""
        leveling_config = self.get_config(ctx.guild.id)
        custom_text = leveling_config.get("card_custom_text", "") if is_premium else ""
        layout = leveling_config.get("card_layout", {}) if is_premium else {}
        try:
            custom_text = (custom_text or "").format(
                member=member.display_name,
                user=member.display_name,
                mention=member.mention,
                guild=ctx.guild.name,
                server=ctx.guild.name,
                level=lvl,
                xp=xp,
                rank=rank,
            )
        except (KeyError, ValueError):
            pass
        from utils.images import create_level_card
        try:
            file = await create_level_card(
                member, lvl, xp, xp_needed, rank,
                background_source=bg_url, session=self.bot.session,
                custom_text=custom_text, layout=layout,
            )
            await ctx.send(file=file)
        except Exception as e:
            self.logger.error(f"Error generating rank card: {e}")
            embed = discord.Embed(title=self._t(ctx, "leveling.rank_card_title", "Level card - {member}", member=member.display_name), color=discord.Color.purple())
            embed.add_field(name=self._t(ctx, "leveling.server_level", "Server level"), value=str(lvl), inline=True)
            embed.add_field(name=self._t(ctx, "leveling.server_xp", "Server XP"), value=f"{xp} / {xp_needed}", inline=True)
            gdat = await self.bot.db.fetch("SELECT xp, level FROM users WHERE user_id = ?", member.id)
            if gdat:
                embed.add_field(name=self._t(ctx, "leveling.global_level", "Global level"), value=f"{gdat[1]} · {gdat[0]} XP", inline=False)
            embed.set_footer(text=footer_text)
            await ctx.send(embed=embed)

    @level.command(name="leaderboard", description="View the server leaderboard.")
    async def level_leaderboard(self, ctx):
        top_users = await self.bot.db.fetch_all("SELECT user_id, xp, level FROM guild_levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 10", ctx.guild.id)
        embed = discord.Embed(title=self._t(ctx, "leveling.leaderboard_title", "🌍 Server leaderboard"), color=discord.Color.blue())
        description = ""
        for idx, (user_id, xp, lvl) in enumerate(top_users, 1):
            user = ctx.guild.get_member(user_id)
            name = user.display_name if user else f"User {user_id}"
            description += f"**{idx}.** {name} • Lvl {lvl} • `{xp} XP`\n"
        embed.description = description or self._t(ctx, "leveling.leaderboard_empty", "No one has gained XP yet!")
        await ctx.send(embed=embed)

    @level.command(name="set", description="Set a user's level (Admin).")
    @commands.has_permissions(administrator=True)
    async def level_set(self, ctx, member: discord.Member, lvl: int):
        if lvl < 1:
            await ctx.send(self._t(ctx, "leveling.level_min", "Level must be at least 1."))
            return
        user_data = await self.bot.db.fetch("SELECT 1 FROM guild_levels WHERE user_id = ? AND guild_id = ?", member.id, ctx.guild.id)
        if not user_data:
            await self.bot.db.execute("INSERT INTO guild_levels (user_id, guild_id, xp, weekly_xp, level) VALUES (?, ?, 0, 0, ?)", member.id, ctx.guild.id, lvl)
        else:
            await self.bot.db.execute("UPDATE guild_levels SET level = ?, xp = 0 WHERE user_id = ? AND guild_id = ?", lvl, member.id, ctx.guild.id)
        await ctx.send(self._t(ctx, "leveling.level_set", "Set {member}'s level to **{level}** (XP reset to 0).", member=member.mention, level=lvl))

    @level.command(name="setxp", description="Set a user's XP (Admin).")
    @commands.has_permissions(administrator=True)
    async def level_setxp(self, ctx, member: discord.Member, amount: int):
        user_data = await self.bot.db.fetch("SELECT level FROM guild_levels WHERE user_id = ? AND guild_id = ?", member.id, ctx.guild.id)
        if not user_data:
            current_level = 1
            await self.bot.db.execute("INSERT INTO guild_levels (user_id, guild_id, xp, weekly_xp, level) VALUES (?, ?, ?, 0, 1)", member.id, ctx.guild.id, amount)
        else:
            current_level = user_data[0]
            await self.bot.db.execute("UPDATE guild_levels SET xp = ? WHERE user_id = ? AND guild_id = ?", amount, member.id, ctx.guild.id)
        base_absolute_xp = 50 * current_level * (current_level - 1)
        total_xp = base_absolute_xp + amount
        calculated_level = (50 + math.sqrt(2500 + 200 * total_xp)) / 100
        new_level = int(calculated_level)
        xp_used_for_lvl = 50 * new_level * (new_level - 1)
        final_xp = int(total_xp - xp_used_for_lvl)
        await self.bot.db.execute("UPDATE guild_levels SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?", final_xp, new_level, member.id, ctx.guild.id)
        await ctx.send(self._t(ctx, "leveling.xp_set", "Set {member}'s XP to **{amount}**. Now level **{level}** with **{xp}** XP.", member=member.mention, amount=amount, level=new_level, xp=final_xp))

    @level.command(name="channel", description="Set the channel for level-up announcements.")
    @commands.has_permissions(administrator=True)
    async def level_channel(self, ctx, channel: discord.TextChannel = None):
        """Use without a channel to reset to default."""
        config = self._load_guild_config(ctx.guild.id)
        if 'leveling' not in config:
            config['leveling'] = {}
        if channel:
            config['leveling']['level_up_channel'] = str(channel.id)
            await ctx.send(self._t(ctx, "leveling.channel_set", "✅ Level-up announcements → {channel}", channel=channel.mention))
        else:
            config['leveling']['level_up_channel'] = ''
            await ctx.send(self._t(ctx, "leveling.channel_default", "✅ Level-up announcements → same channel as message."))
        self._save_guild_config(ctx.guild.id, config)

    @level.command(name="addrole", description="Set a role reward for reaching a level.")
    @commands.has_permissions(administrator=True)
    async def level_addrole(self, ctx, lvl: int, role: discord.Role):
        if lvl < 1:
            await ctx.send(self._t(ctx, "leveling.role_level_min", "❌ Level must be 1 or higher."))
            return
        existing = await self.bot.db.fetch("SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?", ctx.guild.id, lvl)
        if existing:
            await self.bot.db.execute("UPDATE level_roles SET role_id = ? WHERE guild_id = ? AND level = ?", role.id, ctx.guild.id, lvl)
            await ctx.send(self._t(ctx, "leveling.role_updated", "✅ Updated level **{level}** reward to {role}.", level=lvl, role=role.mention))
        else:
            await self.bot.db.execute("INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", ctx.guild.id, lvl, role.id)
            await ctx.send(self._t(ctx, "leveling.role_set", "✅ Set {role} as reward for level **{level}**.", role=role.mention, level=lvl))

    @level.command(name="roles", description="View all configured level role rewards.")
    async def level_roles(self, ctx):
        roles = await self.bot.db.fetch_all("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", ctx.guild.id)
        if not roles:
            await ctx.send(self._t(ctx, "leveling.roles_empty", "❌ No level roles configured. Use `/level addrole`."))
            return
        embed = discord.Embed(title="🎁 Level Role Rewards", color=discord.Color.gold())
        for lvl, role_id in roles:
            role = ctx.guild.get_role(role_id)
            embed.add_field(name=f"Level {lvl}", value=role.mention if role else f"~~Deleted ({role_id})~~", inline=True)
        await ctx.send(embed=embed)

    @level.command(name="removerole", description="Remove a level role reward.")
    @commands.has_permissions(administrator=True)
    async def level_removerole(self, ctx, lvl: int):
        result = await self.bot.db.fetch("SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?", ctx.guild.id, lvl)
        if not result:
            await ctx.send(self._t(ctx, "leveling.role_missing", "❌ No role reward for level **{level}**.", level=lvl))
            return
        await self.bot.db.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", ctx.guild.id, lvl)
        await ctx.send(self._t(ctx, "leveling.role_removed", "✅ Removed role reward for level **{level}**.", level=lvl))

    @level.command(name="background", description="Set the rank card background (Premium).")
    @commands.has_permissions(administrator=True)
    async def level_background(self, ctx, image: discord.Attachment):
        if not await self.bot.db.is_guild_premium(ctx.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await ctx.send(deny_text(guild_lang(self.bot, ctx.guild.id)))
            return
        if not str(image.content_type or "").startswith("image/"):
            await ctx.send("❌ Please upload a valid image file.")
            return
        from utils.images import persist_discord_image
        try:
            background_source = await persist_discord_image(image, ctx.guild.id)
        except (ValueError, OSError) as exc:
            await ctx.send(f"❌ Could not save the image: {exc}")
            return
        await self.bot.db.execute(
            """INSERT INTO premium_guilds
               (guild_id, activated_at, expires_at, plan, custom_background)
               VALUES (?, ?, '9999-12-31T23:59:59', 'lifetime', ?)
               ON CONFLICT(guild_id) DO UPDATE SET custom_background = excluded.custom_background""",
            ctx.guild.id, datetime.datetime.now(datetime.timezone.utc).isoformat(), background_source,
        )
        embed = discord.Embed(title=self._t(ctx, "leveling.background_updated", "✅ Background updated"), color=discord.Color.green())
        embed.set_image(url=image.url)
        await ctx.send(embed=embed)

    @level.command(name="botname", description="Set custom bot name (Premium).")
    @commands.has_permissions(administrator=True)
    async def level_botname(self, ctx, *, name: str):
        if not await self.bot.db.is_guild_premium(ctx.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await ctx.send(deny_text(guild_lang(self.bot, ctx.guild.id)))
            return
        name = " ".join(str(name).split()).strip()[:32]
        if not name:
            await ctx.send("❌ Name cannot be empty.")
            return
        await self.bot.db.execute(
            """INSERT INTO premium_guilds
               (guild_id, activated_at, expires_at, plan, custom_bot_name)
               VALUES (?, ?, '9999-12-31T23:59:59', 'lifetime', ?)
               ON CONFLICT(guild_id) DO UPDATE SET custom_bot_name = excluded.custom_bot_name""",
            ctx.guild.id, datetime.datetime.now(datetime.timezone.utc).isoformat(), name,
        )
        await self._sync_guild_persona(ctx.guild)
        await ctx.send(self._t(ctx, "leveling.bot_name_set", "✅ Bot name set to: **{name}**", name=name))

    @level.command(name="botavatar", description="Set custom bot avatar (Premium).")
    @commands.has_permissions(administrator=True)
    async def level_botavatar(self, ctx, image: discord.Attachment):
        if not await self.bot.db.is_guild_premium(ctx.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await ctx.send(deny_text(guild_lang(self.bot, ctx.guild.id)))
            return
        if not str(image.content_type or "").startswith("image/"):
            await ctx.send("❌ Invalid image.")
            return
        from utils.images import persist_discord_image
        try:
            avatar_source = await persist_discord_image(image, ctx.guild.id, purpose="bot_avatar")
        except (ValueError, OSError) as exc:
            await ctx.send(f"❌ Could not save the avatar: {exc}")
            return
        await self.bot.db.execute(
            """INSERT INTO premium_guilds
               (guild_id, activated_at, expires_at, plan, custom_bot_avatar)
               VALUES (?, ?, '9999-12-31T23:59:59', 'lifetime', ?)
               ON CONFLICT(guild_id) DO UPDATE SET custom_bot_avatar = excluded.custom_bot_avatar""",
            ctx.guild.id, datetime.datetime.now(datetime.timezone.utc).isoformat(), avatar_source,
        )
        embed = discord.Embed(title=self._t(ctx, "leveling.avatar_updated", "✅ Bot avatar updated"), color=discord.Color.green())
        embed.set_thumbnail(url=image.url)
        await ctx.send(embed=embed)

    @level.command(name="toggle", description="Enable or disable the leveling system.")
    @commands.has_permissions(administrator=True)
    async def level_toggle(self, ctx, enabled: bool):
        config = self._load_guild_config(ctx.guild.id)
        if 'leveling' not in config:
            config['leveling'] = {}
        config['leveling']['enabled'] = enabled
        self._save_guild_config(ctx.guild.id, config)
        status = self._t(
            ctx,
            "leveling.status_on" if enabled else "leveling.status_off",
            "enabled" if enabled else "disabled",
        )
        await ctx.send(self._t(ctx, "leveling.leveling_enabled", "✅ Leveling system **{status}**.", status=status))

    @level.command(name="global", description="Ranking global (todos los servidores de Dabot).")
    async def level_global(self, ctx):
        top_users = await self.bot.db.fetch_all(
            "SELECT user_id, xp, level FROM users ORDER BY level DESC, xp DESC LIMIT 10"
        )
        embed = discord.Embed(
            title="🌐 Ranking global Dabot",
            description="Suma la actividad de **todos** los servidores donde está el bot.",
            color=discord.Color.teal(),
        )
        lines = []
        for idx, (user_id, xp, lvl) in enumerate(top_users or [], 1):
            user = self.bot.get_user(user_id)
            name = user.display_name if user else f"ID {user_id}"
            lines.append(f"**{idx}.** {name} • Lvl {lvl} • `{xp} XP`")
        embed.description = (embed.description or "") + "\n\n" + ("\n".join(lines) or "Aún no hay XP global.")
        await ctx.send(embed=embed)

    @level.command(name="botrank", description="Tu nivel global (todos los servidores).")
    async def level_botrank(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user_data = await self.bot.db.fetch("SELECT xp, level FROM users WHERE user_id = ?", member.id)
        if not user_data:
            xp, lvl = 0, 1
        else:
            xp, lvl = user_data
        rank_data = await self.bot.db.fetch_all("SELECT user_id FROM users ORDER BY level DESC, xp DESC")
        rank = 1
        for r_user in rank_data:
            if r_user[0] == member.id:
                break
            rank += 1
        server_data = None
        if ctx.guild:
            server_data = await self.bot.db.fetch(
                "SELECT xp, level FROM guild_levels WHERE user_id = ? AND guild_id = ?",
                member.id, ctx.guild.id
            )
        xp_needed = lvl * 200
        embed = discord.Embed(title=f"Niveles de {member.display_name}", color=discord.Color.teal())
        embed.set_thumbnail(url=member.display_avatar.url)
        if server_data:
            embed.add_field(name=f"Servidor · {ctx.guild.name}", value=f"Nivel **{server_data[1]}** · {server_data[0]} XP", inline=False)
        embed.add_field(name="Global (todos los servers)", value=f"Nivel **{lvl}** · #{rank} · `{xp} / {xp_needed}` XP", inline=False)
        await ctx.send(embed=embed)

    # Hidden admin helper
    @commands.command(name="reset_weekly", hidden=True)
    @commands.has_permissions(administrator=True)
    async def reset_weekly(self, ctx):
        await self.bot.db.execute("UPDATE guild_levels SET weekly_xp = 0 WHERE guild_id = ?", ctx.guild.id)
        await ctx.send("Weekly XP has been manually reset.")


async def setup(bot):
    await bot.add_cog(Leveling(bot))
