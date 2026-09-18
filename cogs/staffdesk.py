"""Context menus, appeals from DMs, backups, verified guilds, raid panic."""
from __future__ import annotations

import datetime
import logging
import os
import shutil

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.helpers import DASHBOARD_URL

log = logging.getLogger("Dabot.Staffdesk")

class SanctionModal(discord.ui.Modal):
    motivo = discord.ui.TextInput(label="Motivo (público, va al MD)", max_length=400, required=True)
    nota = discord.ui.TextInput(label="Nota interna (solo staff)", max_length=400, required=False)

    def __init__(self, cog: "Staffdesk", action: str, member: discord.Member, minutes: int = 10):
        titles = {"warn": "Advertir", "timeout": "Timeout", "ban": "Banear"}
        super().__init__(title=titles.get(action, "Sanción"))
        self.cog = cog
        self.action = action
        self.member = member
        self.minutes = minutes

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason = str(self.motivo.value or "").strip() or "Sin motivo"
        note = str(self.nota.value or "").strip() or None
        await self.cog.apply_from_menu(interaction, self.member, self.action, reason, note, self.minutes)


class AppealModal(discord.ui.Modal, title="Apelar sanción"):
    texto = discord.ui.TextInput(
        label="Por qué debería retirarse",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    def __init__(self, bot, guild_id: int, case_id: int):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.case_id = case_id

    async def on_submit(self, interaction: discord.Interaction):
        row = await self.bot.db.fetch(
            "SELECT user_id, status, type, reason FROM infractions WHERE id = ? AND guild_id = ?",
            self.case_id, self.guild_id,
        )
        if not row or int(row[0]) != interaction.user.id:
            await interaction.response.send_message("Este caso no es tuyo.", ephemeral=True)
            return
        existing = await self.bot.db.fetch(
            "SELECT status FROM infraction_appeals WHERE infraction_id = ?", self.case_id
        )
        if existing:
            await interaction.response.send_message("Ya hay una apelación para este caso.", ephemeral=True)
            return
        now = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            """INSERT INTO infraction_appeals (infraction_id, guild_id, user_id, appeal_reason, status, timestamp)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            self.case_id, self.guild_id, interaction.user.id, str(self.texto.value), now,
        )
        await interaction.response.send_message(
            f"Apelación enviada para el caso #{self.case_id}. El staff la ve en {DASHBOARD_URL}/dashboard?guild={self.guild_id}",
            ephemeral=True,
        )
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return
        cfg = self.bot.config.get(self.guild_id) or {}
        chan_id = (cfg.get("moderation") or {}).get("appeals_channel") or (cfg.get("logs") or {}).get("moderation")
        channel = guild.get_channel(int(chan_id)) if chan_id else None
        if channel:
            embed = discord.Embed(
                title=f"Apelación · caso #{self.case_id}",
                description=str(self.texto.value)[:2000],
                color=0xFBBF24,
            )
            embed.add_field(name="Usuario", value=f"<@{interaction.user.id}> `{interaction.user.id}`")
            embed.add_field(name="Sanción", value=f"{row[2]} · {row[3] or '—'}"[:500])
            try:
                await channel.send(embed=embed)
            except Exception:
                pass


class Staffdesk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ctx_warn = app_commands.ContextMenu(name="Warn", callback=self.menu_warn)
        self.ctx_timeout = app_commands.ContextMenu(name="Timeout 10m", callback=self.menu_timeout)
        self.ctx_ban = app_commands.ContextMenu(name="Ban", callback=self.menu_ban)

    async def cog_load(self):
        for cmd in (self.ctx_warn, self.ctx_timeout, self.ctx_ban):
            try:
                self.bot.tree.add_command(cmd)
            except Exception:
                pass
        if not self.db_backup.is_running():
            self.db_backup.start()

    async def cog_unload(self):
        for cmd in (self.ctx_warn, self.ctx_timeout, self.ctx_ban):
            try:
                self.bot.tree.remove_command(cmd.name, type=cmd.type)
            except Exception:
                pass
        self.db_backup.cancel()

    def _mod(self):
        return self.bot.get_cog("Moderation")

    async def menu_warn(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("Sin permiso.", ephemeral=True)
            return
        await interaction.response.send_modal(SanctionModal(self, "warn", member))

    async def menu_timeout(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("Sin permiso.", ephemeral=True)
            return
        await interaction.response.send_modal(SanctionModal(self, "timeout", member, 10))

    async def menu_ban(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Sin permiso.", ephemeral=True)
            return
        await interaction.response.send_modal(SanctionModal(self, "ban", member))

    async def apply_from_menu(self, interaction, member, action, reason, staff_note, minutes=10):
        mod = self._mod()
        if not mod:
            await interaction.followup.send("Módulo de moderación no cargado.", ephemeral=True)
            return
        guild = interaction.guild
        if member.top_role >= interaction.user.top_role and interaction.user.id != self.bot.super_owner_id:
            await interaction.followup.send("❌ No puedes sancionar a este usuario debido a la jerarquía de roles de Discord.", ephemeral=True)
            return

        if mod.is_immune(member):
            await interaction.followup.send("❌ Este usuario es inmune a sanciones de moderación.", ephemeral=True)
            return

        case_id = await mod.create_infraction(
            member.id, guild.id, interaction.user.id, action, reason, staff_note=staff_note
        )
        dm_status = await mod.send_dm_notification(
            member, action, reason, case_id, guild.id, guild=guild, moderator_id=interaction.user.id,
            duration=f"{minutes}m" if action == "timeout" else "",
        )
        try:
            if action == "timeout":
                await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
            elif action == "ban":
                await guild.ban(member, reason=reason)
        except Exception as e:
            await interaction.followup.send(f"Caso #{case_id} creado, pero Discord rechazó la acción: {e}", ephemeral=True)
            return
        await mod.log_action(guild, interaction.user, member, action, reason, case_id)
        await interaction.followup.send(
            f"{action} a **{member.display_name}** · caso #{case_id}\n{mod._dm_staff_note(guild.id, dm_status)}",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id") or ""
        if not cid.startswith("dabot:appeal:"):
            return
        parts = cid.split(":")
        if len(parts) < 4:
            return
        try:
            guild_id = int(parts[2])
            case_id = int(parts[3])
        except ValueError:
            return
        await interaction.response.send_modal(AppealModal(self.bot, guild_id, case_id))

    @commands.command(name="panic", hidden=True)
    @commands.has_permissions(administrator=True)
    async def panic_prefix(self, ctx):
        raid = self.bot.get_cog("AntiRaid")
        if not raid:
            await ctx.send("Anti-raid no está cargado.")
            return
        await raid._activate_lockdown(ctx.guild, manual=True)
        await ctx.send("🔒 Pánico activado. `/antiraid unlock` para quitarlo.")

    @commands.command(name="verifyguild", hidden=True)
    async def verifyguild(self, ctx, guild_id: str, *, note: str = ""):
        if ctx.author.id != getattr(self.bot, "super_owner_id", 0):
            return
        gid = int("".join(c for c in guild_id if c.isdigit()) or "0")
        now = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO verified_guilds (guild_id, note, added_by, added_at) VALUES (?, ?, ?, ?)",
            gid, note, ctx.author.id, now,
        )
        g = self.bot.get_guild(gid)
        await ctx.send(f"✅ **{g.name if g else gid}** marcado como verificado por Dabot.")

    @commands.command(name="unverifyguild", hidden=True)
    async def unverifyguild(self, ctx, guild_id: str):
        if ctx.author.id != getattr(self.bot, "super_owner_id", 0):
            return
        gid = int("".join(c for c in guild_id if c.isdigit()) or "0")
        await self.bot.db.execute("DELETE FROM verified_guilds WHERE guild_id = ?", gid)
        await ctx.send(f"✅ `{gid}` ya no está verificado.")

    @tasks.loop(hours=24)
    async def db_backup(self):
        src = os.environ.get("DATABASE_PATH", "dabot.db")
        if not os.path.exists(src):
            return
        dest_dir = os.path.join(os.path.dirname(src) or ".", "backups", "auto")
        os.makedirs(dest_dir, exist_ok=True)
        stamp = datetime.datetime.utcnow().strftime("%Y%m%d")
        dest = os.path.join(dest_dir, f"dabot_{stamp}.db")
        try:
            shutil.copy2(src, dest)
            wal = src + "-wal"
            if os.path.exists(wal):
                shutil.copy2(wal, dest + "-wal")
            files = sorted(
                (os.path.join(dest_dir, f) for f in os.listdir(dest_dir) if f.endswith(".db")),
                key=os.path.getmtime,
            )
            for old in files[:-7]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            log.info("SQLite backup → %s", dest)
        except Exception as e:
            log.warning("backup failed: %s", e)

    @db_backup.before_loop
    async def _before_backup(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Staffdesk(bot))
