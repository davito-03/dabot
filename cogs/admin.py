import logging
import re
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os

from utils.abuse import PROTECTED_GUILDS

class BlacklistButton(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Blacklist User", style=discord.ButtonStyle.danger)
    async def blacklist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Add to blacklist
        timestamp = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, reason, timestamp) VALUES (?, ?, ?)",
            self.user_id, "Attempted owner command", timestamp
        )
        
        await interaction.response.send_message(f"✅ User <@{self.user_id}> has been blacklisted from using the bot.", ephemeral=True)
        self.stop()


class RepairView(discord.ui.View):
    def __init__(self, bot, fixes, owner_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.fixes = fixes
        self.owner_id = owner_id
        from utils.ai_repair import RepairEngine
        self.engine = RepairEngine(bot)
        
        # Add a button for each fix? Or one "Apply All"?
        # For simplicity, "Apply All Repairs" if fixes exist
        if self.fixes:
            self.add_item(ApplyFixesButton(bot, self.fixes, self.engine))

    @discord.ui.button(label="🔄 Restart Bot", style=discord.ButtonStyle.danger, row=1)
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id: 
            await interaction.response.send_message("⛔ Only the owner can restart the bot.", ephemeral=True)
            return
            
        await interaction.response.send_message("🔄 Restarting system...", ephemeral=True)
        
        # 1. Try systemd (Linux/VPS)
        # The user specifically requested this for the server.
        import subprocess
        import sys
        
        try:
             # We use Popen to fire and forget, as the bot will die shortly.
             # Note: This requires passwordless sudo for the dabot service.
             subprocess.Popen(["sudo", "systemctl", "restart", "dabot"])
        except FileNotFoundError:
             pass # Not on Linux or systemctl not found

        # 2. Global Fallback (Windows / No Service)
        # If systemctl didn't kill us immediately, we restart the process manually.
        # This is useful for testing on Windows.
        await self.bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)

class ApplyFixesButton(discord.ui.Button):
    def __init__(self, bot, fixes, engine):
        super().__init__(style=discord.ButtonStyle.success, label=f"🛠️ Auto-Repair ({len(fixes)})", row=0)
        self.bot = bot
        self.fixes = fixes
        self.engine = engine

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        msg = await interaction.followup.send("🛠️ Applying fixes... This requires AI processing.", ephemeral=True)
        
        results = []
        backup_ids = []
        
        for fix in self.fixes:
            # Update signature: success, info, backup_id
            success, info, bid = await self.engine.apply_fix(fix)
            icon = "✅" if success else "❌"
            results.append(f"{icon} {fix['id']}: {info}")
            if bid:
                backup_ids.append(bid)
        
        # Save state for auto-restart
        self.engine.save_repair_state(interaction.channel_id, backup_ids)
        
        final_msg = "**Repair Results:**\n" + "\n".join(results) + "\n\n🔄 **Restarting bot to apply changes...**"
        
        await msg.edit(content=final_msg)
        self.disabled = True
        await interaction.message.edit(view=self.view)
        
        # Restart Logic
        import subprocess
        import sys
        
        # Linux/Systemd
        try:
             subprocess.Popen(["sudo", "systemctl", "restart", "dabot"])
        except:
             pass

        # Windows/Manual
        await self.bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)

class UndoButton(discord.ui.Button):
    def __init__(self, backup_ids, engine):
        super().__init__(style=discord.ButtonStyle.secondary, label="↩️ Undo Changes", row=0)
        self.backup_ids = backup_ids
        self.engine = engine

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        results = []
        for bid in reversed(self.backup_ids):
             success, msg = self.engine.restore_backup(bid)
             results.append(msg)
             
        await interaction.followup.send(f"↩️ **Restoration Complete**:\n" + "\n".join(results), ephemeral=True)
        self.disabled = True
        self.label = "Restored"
        await interaction.message.edit(view=self.view)


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.super_owner_id = int(os.getenv('SUPER_OWNER_ID', 0))
        self.logger = logging.getLogger('Dabot')
        # Add global check immediately
        bot.add_check(self.global_blacklist_check)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info('Admin Cog loaded.')
        self.logger.info(f'Super Owner ID: {self.super_owner_id}')

        # Check for repair state
        from utils.ai_repair import RepairEngine
        engine = RepairEngine(self.bot)
        state = engine.check_repair_state()
        
        if state:
            channel_id = state.get('channel_id')
            status = state.get('status')
            
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    if status == 'pending_restart':
                        await channel.send("✅ **System Repair Successful!** Bot has restarted and is stable.")
                    elif status == 'reverted':
                        await channel.send("⚠️ **Repair Failed:** The bot crashed during startup. Changes have been automatically reverted to the latest backup.")
            
            # Clear state so we don't spam on next reboot
            engine.clear_repair_state()

    async def cog_load(self):
        tree = self.bot.tree
        if getattr(tree, "_dabot_abuse_check", False):
            return
        previous = tree.interaction_check

        async def combined_interaction_check(interaction: discord.Interaction):
            if not await self._interaction_allowed(interaction):
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "No puedes usar Dabot (usuario o servidor bloqueado).",
                            ephemeral=True,
                        )
                except Exception:
                    pass
                return False
            if previous is not None:
                return await previous(interaction)
            return True

        tree.interaction_check = combined_interaction_check
        tree._dabot_abuse_check = True

    async def _interaction_allowed(self, interaction: discord.Interaction) -> bool:
        uid = getattr(interaction.user, "id", None)
        if uid and uid == self.super_owner_id:
            return True
        guard = getattr(self.bot, "abuse", None)
        if guard:
            if await guard.user_banned(uid):
                return False
            gid = interaction.guild_id
            if gid and await guard.guild_banned(gid):
                return False
            if guard.note_command(uid, gid):
                asyncio.create_task(guard.alert(
                    kind="command_flood",
                    details="Demasiados comandos en poco tiempo. Se ha pausado a este usuario 2 min.",
                    user_id=uid,
                    guild_id=gid,
                ))
                return False
        else:
            if uid:
                row = await self.bot.db.fetch("SELECT user_id FROM blacklist WHERE user_id = ?", uid)
                if row:
                    return False
            if interaction.guild_id:
                row = await self.bot.db.fetch(
                    "SELECT guild_id FROM guild_blacklist WHERE guild_id = ?", interaction.guild_id
                )
                if row:
                    return False
        return True

    async def global_blacklist_check(self, ctx):
        """Block blacklisted users/guilds and crude command floods."""
        if ctx.author.id == self.super_owner_id:
            return True
        guard = getattr(self.bot, "abuse", None)
        if guard:
            if await guard.user_banned(ctx.author.id):
                return False
            if ctx.guild and await guard.guild_banned(ctx.guild.id):
                return False
            if guard.note_command(ctx.author.id, ctx.guild.id if ctx.guild else 0):
                asyncio.create_task(guard.alert(
                    kind="command_flood",
                    details="Demasiados comandos en poco tiempo. Se ha pausado a este usuario 2 min.",
                    user_id=ctx.author.id,
                    guild_id=ctx.guild.id if ctx.guild else None,
                ))
                return False
            return True
        blacklisted = await self.bot.db.fetch("SELECT user_id FROM blacklist WHERE user_id = ?", ctx.author.id)
        if blacklisted:
            return False
        if ctx.guild:
            banned = await self.bot.db.fetch(
                "SELECT guild_id FROM guild_blacklist WHERE guild_id = ?", ctx.guild.id
            )
            if banned:
                return False
        return True

    def _is_super(self, user) -> bool:
        return getattr(user, "id", None) == self.super_owner_id

    @staticmethod
    def _parse_id(raw: str) -> int:
        digits = re.sub(r"\D", "", str(raw or ""))
        return int(digits) if digits else 0

    async def _owner_audit(self, ctx, action: str, target_id=None, guild_id=None, detail=""):
        now = datetime.datetime.now().isoformat()
        gid = guild_id or (ctx.guild.id if ctx.guild else None)
        try:
            await self.bot.db.execute(
                """INSERT INTO owner_audit (action, actor_id, target_id, guild_id, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                action, ctx.author.id, target_id, gid, detail, now,
            )
        except Exception:
            pass
        guard = getattr(self.bot, "abuse", None)
        if guard:
            await guard.alert(
                kind=f"owner_{action}",
                details=f"Comando de superusuario `{action}`.\n{detail}"[:2000],
                user_id=ctx.author.id,
                guild_id=gid,
                extra={"acción": action, "objetivo": target_id},
            )

    @staticmethod
    def _premium_view():
        from utils.premium import PAYMENT_LINKS
        view = discord.ui.View(timeout=900)
        view.add_item(discord.ui.Button(label="5 € / mes", style=discord.ButtonStyle.link, url=PAYMENT_LINKS["monthly"]))
        view.add_item(discord.ui.Button(label="50 € / año", style=discord.ButtonStyle.link, url=PAYMENT_LINKS["yearly"]))
        view.add_item(discord.ui.Button(label="200 € vitalicio", style=discord.ButtonStyle.link, url=PAYMENT_LINKS["lifetime"]))
        return view

    @staticmethod
    def _premium_purchase_embed(guild_id=None):
        from utils.premium import FREE_FEATURES, PREMIUM_FEATURES
        target = f"\n\n**Servidor:** `{guild_id}`" if guild_id else ""
        return discord.Embed(
            title="🦞 Dabot Premium",
            description=(
                "Elige un plan con los botones. En Stripe introduce el ID numérico del servidor "
                "que quieres activar.\n\n"
                "1. Pulsa un plan.\n"
                "2. Introduce `discord_guild_id`.\n"
                "3. Completa el pago.\n"
                "4. Premium se activa automáticamente tras la confirmación.\n\n"
                "Para copiar el ID: Discord → Ajustes → Avanzado → Modo desarrollador → clic derecho en el servidor → Copiar ID."
                + target
            ),
            color=discord.Color.gold(),
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Catch owner-only command attempts and notify the owner"""
        if isinstance(error, commands.NotOwner):
            if self.super_owner_id:
                try:
                    owner = self.bot.get_user(self.super_owner_id)
                    if not owner:
                        owner = await self.bot.fetch_user(self.super_owner_id)
                    
                    embed = discord.Embed(
                        title="⚠️ Unauthorized Command Attempt",
                        description=f"Someone tried to use an owner-only command!",
                        color=discord.Color.red(),
                        timestamp=datetime.datetime.now()
                    )
                    embed.add_field(name="User", value=f"{ctx.author} ({ctx.author.id})", inline=False)
                    embed.add_field(name="Command", value=f"`{ctx.command.name if ctx.command else 'Unknown'}`", inline=True)
                    embed.add_field(name="Server", value=f"{ctx.guild.name if ctx.guild else 'DM'}", inline=True)
                    
                    view = BlacklistButton(self.bot, ctx.author.id)
                    await owner.send(embed=embed, view=view)
                    await ctx.send("⛔ This command is restricted to the bot owner only.", ephemeral=True)
                except Exception as e:
                    self.logger.error(f"Failed to notify owner: {e}")

    @commands.command(name="blacklist")
    @commands.is_owner()
    async def blacklist(self, ctx, user: discord.User, *, reason: str = "No reason provided"):
        timestamp = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, reason, timestamp) VALUES (?, ?, ?)",
            user.id, reason, timestamp
        )
        await ctx.send(f"✅ {user.mention} has been blacklisted. Reason: {reason}")

    @commands.command(name="unblacklist")
    @commands.is_owner()
    async def unblacklist(self, ctx, user: discord.User):
        await self.bot.db.execute("DELETE FROM blacklist WHERE user_id = ?", user.id)
        await ctx.send(f"✅ {user.mention} has been removed from the blacklist.")

    @commands.command(name="blacklist_list")
    @commands.is_owner()
    async def blacklist_list(self, ctx):
        blacklisted = await self.bot.db.fetch_all("SELECT user_id, reason, timestamp FROM blacklist")
        
        if not blacklisted:
            await ctx.send("No users are currently blacklisted.")
            return
        
        embed = discord.Embed(title="Blacklisted Users", color=discord.Color.red())
        
        for user_id, reason, timestamp in blacklisted:
            user = self.bot.get_user(user_id)
            user_name = user.name if user else f"Unknown ({user_id})"
            embed.add_field(
                name=user_name,
                value=f"**Reason:** {reason}\n**Date:** {timestamp[:10]}",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(name="botban", aliases=["dabotban"], hidden=True)
    async def botban(self, ctx, target: str, *, reason: str = "Banned from Dabot"):
        """Superusuario: quita a un usuario el uso de Dabot. `!botban <id>`"""
        if not self._is_super(ctx.author):
            return
        uid = self._parse_id(target)
        if uid < 10**15:
            await ctx.send("❌ ID de usuario inválido.")
            return
        if uid == self.super_owner_id:
            await ctx.send("No.")
            return
        timestamp = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, reason, timestamp) VALUES (?, ?, ?)",
            uid, reason, timestamp,
        )
        await self._owner_audit(ctx, "botban", target_id=uid, detail=reason)
        await ctx.send(f"✅ Usuario `{uid}` baneado de Dabot. Motivo: {reason}")

    @commands.command(name="botunban", aliases=["dabotunban"], hidden=True)
    async def botunban(self, ctx, target: str):
        """Superusuario: `!botunban <id>`"""
        if not self._is_super(ctx.author):
            return
        uid = self._parse_id(target)
        await self.bot.db.execute("DELETE FROM blacklist WHERE user_id = ?", uid)
        await self._owner_audit(ctx, "botunban", target_id=uid)
        await ctx.send(f"✅ Usuario `{uid}` puede volver a usar Dabot.")

    @commands.command(name="serverban", aliases=["guildban"], hidden=True)
    async def serverban(self, ctx, target: str, *, reason: str = "Banned from Dabot"):
        """Superusuario: bloquea un servidor y sale de él. `!serverban <id>`"""
        if not self._is_super(ctx.author):
            return
        gid = self._parse_id(target)
        if gid < 10**15:
            await ctx.send("❌ ID de servidor inválido.")
            return
        if gid in PROTECTED_GUILDS or gid == getattr(ctx.guild, "id", None):
            await ctx.send("❌ Ese servidor está protegido (no me auto-baneo del tuyo).")
            return
        timestamp = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO guild_blacklist (guild_id, reason, timestamp, banned_by) VALUES (?, ?, ?, ?)",
            gid, reason, timestamp, ctx.author.id,
        )
        guild = self.bot.get_guild(gid)
        left = False
        if guild:
            try:
                await guild.leave()
                left = True
            except Exception as e:
                await ctx.send(f"Bloqueado, pero no pude salir: {e}")
                return
        extra = " y he salido." if left else ". Si me invitan otra vez, me salgo."
        await self._owner_audit(ctx, "serverban", target_id=gid, guild_id=gid, detail=reason)
        await ctx.send(f"✅ Servidor `{gid}` baneado de Dabot{extra} Motivo: {reason}")

    @commands.command(name="serverunban", aliases=["guildunban"], hidden=True)
    async def serverunban(self, ctx, target: str):
        """Superusuario: `!serverunban <id>`"""
        if not self._is_super(ctx.author):
            return
        gid = self._parse_id(target)
        await self.bot.db.execute("DELETE FROM guild_blacklist WHERE guild_id = ?", gid)
        await self._owner_audit(ctx, "serverunban", target_id=gid, guild_id=gid)
        await ctx.send(f"✅ Servidor `{gid}` puede volver a usar Dabot (hay que reinvitarlo).")

    @commands.command(name="serverbanlist", hidden=True)
    async def serverbanlist(self, ctx):
        if not self._is_super(ctx.author):
            return
        rows = await self.bot.db.fetch_all(
            "SELECT guild_id, reason, timestamp FROM guild_blacklist"
        )
        if not rows:
            await ctx.send("Ningún servidor baneado.")
            return
        embed = discord.Embed(title="Servidores baneados de Dabot", color=discord.Color.red())
        for gid, reason, ts in rows[:25]:
            embed.add_field(name=str(gid), value=f"{reason or '—'}\n{str(ts)[:10]}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="remotenuke", hidden=True)
    async def remotenuke(self, ctx, target: str):
        """Superusuario: nuke remoto. `!remotenuke <id del server>`"""
        if not self._is_super(ctx.author):
            return
        gid = self._parse_id(target)
        if gid < 10**15:
            await ctx.send("❌ ID de servidor inválido.")
            return
        if gid in PROTECTED_GUILDS:
            await ctx.send("❌ Ese servidor está protegido.")
            return
        guild = self.bot.get_guild(gid)
        if guild is None:
            await ctx.send(f"❌ No estoy en `{gid}`.")
            return
        view = RemoteNukeView(self.bot, ctx.author.id, gid)
        await ctx.send(
            f"⚠️ Nuke remoto de **{guild.name}** (`{gid}`)\n"
            f"Miembros: **{guild.member_count or '?'}** · Owner: `{guild.owner_id}`\n"
            f"Borra canales y roles. Confirma en 60s.",
            view=view,
        )

    # --- ANALYSIS & REPAIR ---

    @commands.hybrid_command(name="analyze", description="Deep System Health Check & Integrity Verify.")
    async def analyze(self, ctx):
        """Deep System Health Check & Integrity Verify."""
        if ctx.author.id != self.super_owner_id and not await self.bot.is_owner(ctx.author):
            await ctx.send("⛔ You are not the owner.", ephemeral=True)
            return

        try:
            await ctx.defer()
        except: pass

        msg = await ctx.send("🔍 **Running Deep System Health Check...** (This may take a moment)")
        
        from utils.ai_repair import RepairEngine
        repair_engine = RepairEngine(self.bot)
        
        report = []
        issues = []
        
        report.append(f"**🛠️ System Status Report**")
        report.append(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        try:
            await self.bot.db.fetch("SELECT 1")
            report.append("✅ **Database**: Connected")
        except Exception as e:
            report.append(f"❌ **Database**: Error ({e})")
            issues.append({'type': 'database_error', 'data': str(e)})
        
        latency = round(self.bot.latency * 1000)
        status = "✅" if latency < 200 else "⚠️" if latency < 500 else "❌"
        report.append(f"{status} **Latency**: {latency}ms")
        
        from discord.app_commands import ContextMenu, Group as AppGroup
        app_commands = self.bot.tree.get_commands()
        report.append(f"**⚡ Slash Commands Analysis ({len(app_commands)})**")
        
        missing_count = 0
        langs_to_check = ['en', 'es']
        
        for lang in langs_to_check:
            slash_trans = self.bot.i18n.translations.get(lang, {}).get('slash_commands', {})
            lang_missing = []
            
            for cmd in app_commands:
                if isinstance(cmd, ContextMenu):
                    continue
                desc = getattr(cmd, "description", None)
                if not desc:
                    continue
                if cmd.name not in slash_trans:
                    lang_missing.append({'key': cmd.name, 'base_value': cmd.name, 'lang': lang})
                if desc not in slash_trans:
                    lang_missing.append({'key': desc, 'base_value': desc, 'lang': lang})
                if isinstance(cmd, AppGroup):
                    for sub in getattr(cmd, "commands", []) or []:
                        sdesc = getattr(sub, "description", None)
                        if not sdesc:
                            continue
                        if sub.name not in slash_trans:
                            lang_missing.append({'key': sub.name, 'base_value': sub.name, 'lang': lang})
                        if sdesc not in slash_trans:
                            lang_missing.append({'key': sdesc, 'base_value': sdesc, 'lang': lang})
            
            if lang_missing:
                missing_count += len(lang_missing)
                report.append(f"❌ **{lang.upper()} Translations**: {len(lang_missing)} missing keys.")
                for miss in lang_missing:
                    issues.append({'type': 'translation_missing', 'data': miss})
            else:
                report.append(f"✅ **{lang.upper()} Translations**: 100% Coverage")
        
        if missing_count == 0:
            report.append("✅ **Total Translations**: All Good.")
            
        try:
            log_files = sorted([f for f in os.listdir("logs") if f.endswith(".txt")], reverse=True)
            if log_files:
                latest_log = os.path.join("logs", log_files[0])
                report.append(f"**📜 Log Analysis ({log_files[0]})**")
                ai_log_summary = await repair_engine.analyze_log_content(latest_log)
                report.append(f"{ai_log_summary}")
        except Exception as e:
            report.append(f"⚠️ **Logs**: Could not read logs ({e})")

        fixes = []
        if issues:
            report.append("\n**🔧 Proposed AI Repairs:**")
            fixes = await repair_engine.propose_fixes(issues)
            if fixes:
                for idx, fix in enumerate(fixes, 1):
                    report.append(f"{idx}. {fix['description']}")
            else:
                report.append("No automatic repairs available for these issues.")
        else:
            report.append("\n✨ **System Clean. No issues found.**")

        final_text = "\n".join(report)
        view = RepairView(self.bot, fixes, ctx.author.id)
        
        if len(final_text) > 2000:
             with open("health_check.txt", "w", encoding="utf-8") as f:
                 f.write(final_text.replace("*", ""))
             await msg.edit(content="Report is too long:", attachments=[discord.File("health_check.txt")], view=view)
             os.remove("health_check.txt")
        else:
            await msg.edit(content=final_text, view=view)

    @commands.command(name="dx")
    @commands.is_owner()
    async def dx(self, ctx, user_id: str):
        """Deep User Analysis (DX) tool."""
        try:
            uid = int(user_id)
        except ValueError:
            await ctx.send("❌ Invalid User ID.")
            return

        await ctx.send(f"🔍 **Running DX Analysis on {uid}...**")
        
        # 1. Fetch Discord Data
        try:
            user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            await ctx.send("❌ User not found via Discord API.")
            return

        embed = discord.Embed(title=f"🕵️ DX Intelligence Report: {user}", color=discord.Color.dark_teal(), timestamp=datetime.datetime.now())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_image(url=user.banner.url if user.banner else None)
        
        # Account Info
        created_at = user.created_at.strftime("%Y-%m-%d %H:%M:%S")
        account_age = (datetime.datetime.now(datetime.timezone.utc) - user.created_at).days
        flags = [flag[0] for flag in user.public_flags if flag[1]]
        
        embed.add_field(name="🆔 Identity", value=f"ID: `{user.id}`\nCreated: `{created_at}`\nAge: `{account_age} days`", inline=False)
        embed.add_field(name="🚩 Flags", value=", ".join(flags) if flags else "None", inline=False)
        
        # Nitro Detection (Inferred)
        nitro_hints = []
        if user.avatar and user.avatar.is_animated():
            nitro_hints.append("Animated Avatar")
        if user.banner:
            nitro_hints.append("Custom Banner")
            
        # Check for boost in mutual guilds
        is_booster = False
        for guild in self.bot.guilds:
            m = guild.get_member(uid)
            if m and m.premium_since:
                is_booster = True
                nitro_hints.append(f"Boosting {guild.name}")
                break # Found evidence, good enough
        
        nitro_status = "⚪ No Nitro Detected"
        if is_booster:
             nitro_status = "🚀 Server Booster (Full Nitro)"
        elif nitro_hints:
             nitro_status = f"💎 Nitro Detected ({', '.join(nitro_hints)})"
             
        embed.add_field(name="💎 Nitro Status", value=nitro_status, inline=False)
        
        # 2. Mutual Guilds
        mutual_guilds = []
        for guild in self.bot.guilds:
            if guild.get_member(uid):
                mutual_guilds.append(f"{guild.name} ({guild.id})")
        
        mutual_str = "\n".join(mutual_guilds[:5]) if mutual_guilds else "None"
        if len(mutual_guilds) > 5:
            mutual_str += f"\n...and {len(mutual_guilds)-5} more."
            
        embed.add_field(name=f"🤝 Mutual Servers ({len(mutual_guilds)})", value=mutual_str, inline=False)
        
        # 3. Database Data
        # Economy
        eco_data = await self.bot.db.fetch("SELECT balance, bank FROM users WHERE user_id = ?", uid)
        wallet = eco_data[0] if eco_data else 0
        bank = eco_data[1] if eco_data else 0
        
        # Leveling
        lvl_data = await self.bot.db.fetch("SELECT level, xp FROM users WHERE user_id = ?", uid)
        level = lvl_data[0] if lvl_data else 1
        xp = lvl_data[1] if lvl_data else 0
        
        # Infractions
        inf_count = await self.bot.db.fetch("SELECT COUNT(*) FROM infractions WHERE user_id = ?", uid)
        total_infractions = inf_count[0] if inf_count else 0
        
        embed.add_field(name="📊 Database Profile", value=f"**Economy:** ${wallet} (Wallet) / ${bank} (Bank)\n**Level:** {level} (XP: {xp})\n**Infractions:** {total_infractions} records", inline=False)

        # 4. Nicknames Scan
        nicknames = []
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if member and member.nick:
                nicknames.append(f"**{guild.name}:** {member.nick}")
        
        if nicknames:
            nick_str = "\n".join(nicknames[:10])
            if len(nicknames) > 10:
                nick_str += f"\n...and {len(nicknames)-10} more."
            embed.add_field(name="🎭 Nicknames (Server Specific)", value=nick_str, inline=False)
        else:
             embed.add_field(name="🎭 Nicknames", value="No custom nicknames found.", inline=False)
        
        # Check if tracked
        is_tracked = await self.bot.db.fetch("SELECT started_at FROM tracking WHERE user_id = ?", uid)
        track_status = "🟢 TRACKING ACTIVE" if is_tracked else "⚪ Not Tracked"
        embed.set_footer(text=f"DX System • {track_status}")
        
        await ctx.send(embed=embed)

    @commands.command(name="track")
    @commands.is_owner()
    async def track(self, ctx, user_id: str):
        """Toggle activity tracking for a user."""
        try:
            uid = int(user_id)
        except ValueError:
             await ctx.send("❌ Invalid User ID.")
             return
        
        # Check if already tracking
        existing = await self.bot.db.fetch("SELECT started_at FROM tracking WHERE user_id = ?", uid)
        
        if existing:
            await self.bot.db.execute("DELETE FROM tracking WHERE user_id = ?", uid)
            await ctx.send(f"🛑 Tracking STOPPED for user `{uid}`.")
        else:
            now = datetime.datetime.now().isoformat()
            await self.bot.db.execute("INSERT INTO tracking (user_id, started_at) VALUES (?, ?)", uid, now)
            await ctx.send(f"👀 Tracking STARTED for user `{uid}`.\nActivity logs will be saved to `logs/activity_{uid}.txt`.")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        # 1. Check if user is being tracked
        try:
            is_tracked = await self.bot.db.fetch("SELECT started_at FROM tracking WHERE user_id = ?", after.id)
            if not is_tracked:
                 return
            
            # Debug
            self.logger.debug(f"Tracking update for {after} ({after.id})")
                 
            # 2. Compare activities
            # We want to log significant changes: Status change, Game start/stop, Spotify change
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_line = ""
            
            # Status Change
            if before.status != after.status:
                 log_line += f"[{timestamp}] Status Change: {before.status} -> {after.status}\n"
                 
            # Activity Change
            # 2.1 Check for Spotify specific changes
            new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
            old_spotify = next((a for a in before.activities if isinstance(a, discord.Spotify)), None)
            
            if new_spotify and old_spotify:
                if new_spotify.track_id != old_spotify.track_id:
                     log_line += f"[{timestamp}] 🎵 Spotify Changed: {old_spotify.artist} - {old_spotify.title} -> {new_spotify.artist} - {new_spotify.title}\n"
            
            # 2.2 Check for new/ended activities (ignoring Spotify updates handled above)
            old_acts = [a.name for a in before.activities if not isinstance(a, discord.Spotify)]
            new_acts = [a.name for a in after.activities if not isinstance(a, discord.Spotify)]
            
            # Log Spotify Start/End separately via name list or handle here?
            # Actually, standard "Started" logic works for Spotify START, but not update.
            # So we exclude Spotify from the generic loop ONLY if we want to avoid duplicates, 
            # but "Spotify" name doesn't change, so "Started" only fires on fresh start.
            
            # Let's keep generic loop for Start/End of ANY activity including Spotify
            # But the 'update' logic above handles the song change.
            
            old_act_names = [a.name for a in before.activities]
            new_act_names = [a.name for a in after.activities]

            for act in after.activities:
                if act.name not in old_act_names:
                     details = ""
                     if isinstance(act, discord.Spotify):
                          details = f" (Song: {act.title} - {act.artist})"
                     elif isinstance(act, discord.Game):
                          details = f" (Started Playing)"
                     log_line += f"[{timestamp}] Activity Started: {act.name}{details}\n"
            
            for act in before.activities:
                 if act.name not in new_act_names:
                      log_line += f"[{timestamp}] Activity Ended: {act.name}\n"
            
            if log_line:
                 self.logger.info(f"Writing tracking log for {after.id}: {log_line.strip()}")
                 log_file = f"logs/activity_{after.id}.txt"
                 try:
                     with open(log_file, "a", encoding="utf-8") as f:
                          f.write(log_line)
                 except Exception as e:
                      self.logger.error(f"Failed to write activity log: {e}")
        except Exception as e:
            self.logger.error(f"Error in on_presence_update: {e}")

    premium_slash = app_commands.Group(
        name="premium",
        description="Dabot Premium: status and (owner) grant/revoke.",
    )

    @premium_slash.command(name="status", description="See this server's Premium plan.")
    async def premium_status(self, interaction: discord.Interaction):
        from utils.premium import plan_label, PLANS, FREE_FEATURES, PREMIUM_FEATURES
        from utils.helpers import DASHBOARD_URL
        active = False
        rec = None
        if interaction.guild:
            active = await self.bot.db.is_guild_premium(interaction.guild, self.bot)
            rec = await self.bot.db.fetch(
                "SELECT plan, expires_at FROM premium_guilds WHERE guild_id = ?",
                interaction.guild.id,
            )
        embed = discord.Embed(title="🦞 Dabot Premium", color=discord.Color.gold())
        if active:
            plan = rec[0] if rec else "monthly"
            exp = rec[1] if rec else "—"
            embed.description = f"Este servidor está **activo** · {plan_label(plan)}\nCaduca: `{str(exp)[:10]}`"
        else:
            embed.description = (
                "Este servidor está en el plan **gratis**.\n"
                "Elige un plan en los botones y completa el pago con el ID de este servidor."
            )
        embed.add_field(name="Gratis", value="• " + "\n• ".join(FREE_FEATURES), inline=False)
        embed.add_field(name="Premium", value="• " + "\n• ".join(PREMIUM_FEATURES), inline=False)
        await interaction.response.send_message(embed=embed, view=None if active else self._premium_view(), ephemeral=True)

    @premium_slash.command(name="plans", description="See Premium plans and payment instructions.")
    async def premium_plans_slash(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id if interaction.guild else None
        await interaction.response.send_message(
            embed=self._premium_purchase_embed(guild_id),
            view=self._premium_view(),
            ephemeral=True,
        )

    @premium_slash.command(name="grant", description="Owner: grant Premium to a server.")
    @app_commands.describe(guild_id="Server ID", plan="monthly, yearly or lifetime")
    @app_commands.choices(plan=[
        app_commands.Choice(name="Mensual (30 días)", value="monthly"),
        app_commands.Choice(name="Anual (365 días)", value="yearly"),
        app_commands.Choice(name="Vitalicio", value="lifetime"),
    ])
    async def premium_grant_slash(self, interaction: discord.Interaction, guild_id: str, plan: app_commands.Choice[str]):
        if interaction.user.id != self.super_owner_id:
            await interaction.response.send_message("Solo el superusuario puede otorgar Premium.", ephemeral=True)
            return
        from utils.premium import expires_iso, normalize_plan
        gid = int("".join(c for c in guild_id if c.isdigit()) or "0")
        if gid < 10**15:
            await interaction.response.send_message("ID de servidor inválido.", ephemeral=True)
            return
        p = normalize_plan(plan.value)
        now = datetime.datetime.now()
        exp = expires_iso(p, now)
        await self.bot.db.execute(
            """INSERT INTO premium_guilds (guild_id, activated_at, expires_at, plan)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET expires_at = excluded.expires_at, plan = excluded.plan""",
            gid, now.isoformat(), exp, p,
        )
        g = self.bot.get_guild(gid)
        await interaction.response.send_message(
            f"✅ Premium **{p}** en **{g.name if g else gid}** hasta `{exp[:10]}`.",
            ephemeral=True,
        )

    @premium_slash.command(name="revoke", description="Owner: remove Premium from a server.")
    async def premium_revoke_slash(self, interaction: discord.Interaction, guild_id: str):
        if interaction.user.id != self.super_owner_id:
            await interaction.response.send_message("Solo el superusuario.", ephemeral=True)
            return
        gid = int("".join(c for c in guild_id if c.isdigit()) or "0")
        await self.bot.db.execute("DELETE FROM premium_guilds WHERE guild_id = ?", gid)
        await interaction.response.send_message(f"✅ Premium quitado a `{gid}`.", ephemeral=True)

    @commands.group(name="premium", description="Learn about Premium features.", invoke_without_command=True)
    async def premium(self, ctx):
        from utils.premium import FREE_FEATURES, PREMIUM_FEATURES
        from utils.helpers import DASHBOARD_URL
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🦞 Dabot Premium",
                description=f"Gratis vs de pago. Detalle: {DASHBOARD_URL}/premium",
                color=discord.Color.gold()
            )
            embed.add_field(name="Gratis", value="• " + "\n• ".join(FREE_FEATURES), inline=False)
            embed.add_field(name="Premium", value="• " + "\n• ".join(PREMIUM_FEATURES), inline=False)
            embed.add_field(
                name="Planes",
                value="5 € mensual · 50 € anual · 200 € vitalicio\nPulsa un botón, introduce el ID del servidor y completa el pago.",
                inline=False,
            )
            await ctx.send(embed=embed, view=self._premium_view())

    @premium.command(name="plans")
    async def premium_plans(self, ctx):
        """Show plans, payment buttons and setup instructions."""
        guild_id = ctx.guild.id if ctx.guild else None
        await ctx.send(embed=self._premium_purchase_embed(guild_id), view=self._premium_view())

    @premium.command(name="add")
    @commands.is_owner()
    async def premium_add(self, ctx, guild_id: str, plan: str = "monthly"):
        """Add premium. Usage: !premium add <guild_id> monthly|yearly|lifetime"""
        from utils.premium import expires_iso, normalize_plan
        gid = int("".join(c for c in str(guild_id) if c.isdigit()) or "0")
        if gid < 10**15:
            await ctx.send("❌ ID de servidor inválido.")
            return
        p = normalize_plan(plan)
        now = datetime.datetime.now()
        exp = expires_iso(p, now)
        await self.bot.db.execute(
            """INSERT INTO premium_guilds (guild_id, activated_at, expires_at, plan)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET expires_at = excluded.expires_at, plan = excluded.plan""",
            gid, now.isoformat(), exp, p,
        )
        g = self.bot.get_guild(gid)
        await ctx.send(f"✅ Premium **{p}** en **{g.name if g else gid}** hasta `{exp[:10]}`.")

    @premium.command(name="remove")
    @commands.is_owner()
    async def premium_remove(self, ctx, guild_id: str):
        """Remove premium from a guild."""
        try:
            gid = int(guild_id)
        except Exception:
            await ctx.send("❌ Invalid Guild ID.")
            return
        now = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            """INSERT INTO premium_guilds (guild_id, activated_at, expires_at, plan)
               VALUES (?, ?, ?, 'disabled')
               ON CONFLICT(guild_id) DO UPDATE SET plan = 'disabled', expires_at = excluded.expires_at""",
            gid, now, now,
        )
        await ctx.send(f"✅ Premium desactivado en `{gid}` (aunque sea servidor del superusuario).")

    @premium.command(name="list")
    @commands.is_owner()
    async def premium_list(self, ctx):
        """List all premium guilds."""
        from utils.premium import is_active, plan_label
        guilds = await self.bot.db.fetch_all(
            "SELECT guild_id, expires_at, plan FROM premium_guilds"
        )
        if not guilds:
            await ctx.send("Ningún servidor Premium.")
            return
        embed = discord.Embed(title="✨ Servidores Premium", color=discord.Color.gold())
        for row in guilds:
            gid, expires = row[0], row[1]
            plan = row[2] if len(row) > 2 else "monthly"
            guild = self.bot.get_guild(gid)
            name = guild.name if guild else "Unknown"
            flag = "activo" if is_active(expires, plan) else "caducado"
            embed.add_field(
                name=f"{name} ({gid})",
                value=f"{plan_label(plan)} · {flag} · {str(expires)[:10]}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @premium.command(name="setbg")
    @commands.is_owner()
    async def premium_setbg(self, ctx, guild_id: str, url: str):
        """Force set a custom background for a guild."""
        try:
            gid = int(guild_id)
        except:
            await ctx.send("❌ Invalid Guild ID.")
            return

        # Check if guild is premium first? Or just allow override.
        # Ideally we check, but owner override is powerful.
        
        await self.bot.db.execute("UPDATE premium_guilds SET custom_background = ? WHERE guild_id = ?", url, gid)
        await ctx.send(f"✅ Custom background set for guild {gid}.")

class RemoteNukeView(discord.ui.View):
    def __init__(self, bot, owner_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.owner_id = owner_id
        self.guild_id = guild_id

    @discord.ui.button(label="Nuke ahora", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("No.", ephemeral=True)
            return
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message("Ya no estoy en ese servidor.", ephemeral=True)
            return
        await interaction.response.defer()
        from cogs.server_templates import nuke_guild
        stats = await nuke_guild(guild, interaction.user)
        try:
            await self.bot.db.execute(
                """INSERT INTO owner_audit (action, actor_id, target_id, guild_id, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                "remotenuke", interaction.user.id, guild.id, guild.id,
                f"channels={stats.get('channels')} roles={stats.get('roles')}",
                datetime.datetime.now().isoformat(),
            )
        except Exception:
            pass
        guard = getattr(self.bot, "abuse", None)
        if guard:
            await guard.alert(
                kind="owner_remotenuke",
                details=f"Nuke remoto de **{guild.name}**: {stats.get('channels')} canales, {stats.get('roles')} roles.",
                user_id=interaction.user.id,
                guild_id=guild.id,
            )
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"💥 Nuke remoto listo en **{guild.name}** (`{guild.id}`): "
            f"{stats['channels']} canales y {stats['roles']} roles. Queda {stats['landing']}."
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("No.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Nuke cancelado.", view=self)


async def setup(bot):
    await bot.add_cog(Admin(bot))
