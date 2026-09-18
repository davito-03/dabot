import asyncio
import json
import logging
import os
from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands

from utils.helpers import guild_lang

log = logging.getLogger("Dabot.ServerBackup")
SUPER_OWNER_ID = int(os.getenv("SUPER_OWNER_ID", "600041740124160011"))


class BackupRestoreConfirmView(discord.ui.View):
    def __init__(self, cog, backup_data: dict, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.backup_data = backup_data
        self.user_id = user_id
        self.value = None

    @discord.ui.button(label="Confirmar Restauración", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ No puedes pulsar este botón.", ephemeral=True)
            return

        self.value = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog.apply_backup(interaction, self.backup_data)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ No puedes pulsar este botón.", ephemeral=True)
            return

        self.value = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Restauración cancelada por el usuario.", view=self)


class ServerBackup(commands.GroupCog, group_name="serverbackup", group_description="📦 Copias de seguridad y plantillas de la estructura del servidor"):
    """Cog for creating, listing, and restoring server structure backups."""

    def __init__(self, bot):
        self.bot = bot
        self.backup_dir = "data/backups/servers"
        os.makedirs(self.backup_dir, exist_ok=True)

    @app_commands.command(name="create", description="📦 Crea una copia de seguridad de canales, categorías, roles y permisos.")
    @app_commands.describe(nombre="Nombre o nota identificativa para el backup (opcional)")
    @app_commands.default_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction, nombre: str | None = None):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Solo se puede usar en un servidor.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator and interaction.user.id != SUPER_OWNER_ID:
            await interaction.response.send_message("❌ Necesitas permisos de Administrador para crear backups.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # 1. Snapshot Roles
        roles_data = []
        for r in sorted(guild.roles, key=lambda x: x.position):
            if r.is_default() or r.managed:
                continue
            roles_data.append({
                "id": str(r.id),
                "name": r.name,
                "color": r.color.value,
                "hoist": r.hoist,
                "mentionable": r.mentionable,
                "permissions": str(r.permissions.value),
                "position": r.position
            })

        # 2. Snapshot Categories
        categories_data = []
        for cat in guild.categories:
            overwrites = []
            for target, ow in cat.overwrites.items():
                target_type = 0 if isinstance(target, discord.Role) else 1
                overwrites.append({
                    "id": str(target.id),
                    "type": target_type,
                    "allow": str(ow.pair()[0].value),
                    "deny": str(ow.pair()[1].value)
                })
            categories_data.append({
                "id": str(cat.id),
                "name": cat.name,
                "position": cat.position,
                "permission_overwrites": overwrites
            })

        # 3. Snapshot Channels
        channels_data = []
        for ch in guild.channels:
            if isinstance(ch, discord.CategoryChannel):
                continue

            channel_type = 0  # text
            if isinstance(ch, discord.VoiceChannel):
                channel_type = 2
            elif isinstance(ch, discord.StageChannel):
                channel_type = 13
            elif isinstance(ch, discord.ForumChannel):
                channel_type = 15

            overwrites = []
            for target, ow in ch.overwrites.items():
                target_type = 0 if isinstance(target, discord.Role) else 1
                overwrites.append({
                    "id": str(target.id),
                    "type": target_type,
                    "allow": str(ow.pair()[0].value),
                    "deny": str(ow.pair()[1].value)
                })

            channels_data.append({
                "id": str(ch.id),
                "name": ch.name,
                "type": channel_type,
                "position": ch.position,
                "topic": getattr(ch, "topic", "") or "",
                "nsfw": getattr(ch, "nsfw", False),
                "slowmode_delay": getattr(ch, "slowmode_delay", 0),
                "bitrate": getattr(ch, "bitrate", None),
                "user_limit": getattr(ch, "user_limit", None),
                "parent_id": str(ch.category_id) if ch.category_id else None,
                "permission_overwrites": overwrites
            })

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        backup_dict = {
            "name": nombre or f"Backup {guild.name} ({now_str})",
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "created_at": now_str,
            "created_by": interaction.user.id,
            "stats": {
                "roles": len(roles_data),
                "categories": len(categories_data),
                "channels": len(channels_data)
            },
            "roles": roles_data,
            "categories": categories_data,
            "channels": channels_data
        }

        backup_json = json.dumps(backup_dict, ensure_ascii=False)

        # Save to SQLite
        try:
            cursor = await self.bot.db.execute(
                "INSERT INTO server_backups (guild_id, backup_data, created_by, created_at, status, kind) VALUES (?, ?, ?, ?, 'ready', 'structure')",
                guild.id, backup_json, interaction.user.id, now_str
            )
            backup_id = cursor.lastrowid
        except Exception as e:
            log.error(f"Error saving backup to database: {e}")
            await interaction.followup.send(f"❌ Error al guardar el backup en base de datos: {e}", ephemeral=True)
            return

        # Save JSON file on disk
        file_path = os.path.join(self.backup_dir, f"{guild.id}_{backup_id}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(backup_json)
        except Exception as e:
            log.warning(f"Could not write backup to disk file: {e}")

        embed = discord.Embed(
            title="📦 Copia de Seguridad Creada con Éxito",
            description=f"Se ha guardado un snapshot completo de la estructura de **{guild.name}**.",
            color=discord.Color.from_rgb(0, 255, 136),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="ID del Backup", value=f"`#{backup_id}`", inline=True)
        embed.add_field(name="Nombre/Nota", value=f"**{backup_dict['name'][:40]}**", inline=True)
        embed.add_field(name="Fecha", value=now_str, inline=True)
        embed.add_field(name="🎭 Roles guardados", value=str(len(roles_data)), inline=True)
        embed.add_field(name="📁 Categorías", value=str(len(categories_data)), inline=True)
        embed.add_field(name="💬 Canales", value=str(len(channels_data)), inline=True)
        embed.set_footer(text="Usa /serverbackup list para ver backups o el panel web para restaurar.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="list", description="📋 Lista las copias de seguridad disponibles para este servidor.")
    @app_commands.default_permissions(administrator=True)
    async def list_backups(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Solo en un servidor.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        rows = await self.bot.db.fetch_all(
            "SELECT id, created_at, status, kind, backup_data FROM server_backups WHERE guild_id = ? ORDER BY id DESC LIMIT 10",
            guild.id
        )

        if not rows:
            await interaction.followup.send("ℹ️ No hay copias de seguridad guardadas para este servidor. Usa `/serverbackup create` para generar una.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 Backups de {guild.name}",
            description="Lista de las últimas copias de seguridad registradas en Dabot:",
            color=discord.Color.blue()
        )

        for r in rows:
            bid = r["id"] if isinstance(r, dict) else r[0]
            bdate = r["created_at"] if isinstance(r, dict) else r[1]
            bkind = r["kind"] if isinstance(r, dict) else r[3]
            raw_data = r["backup_data"] if isinstance(r, dict) else r[4]

            roles_cnt, ch_cnt = "?", "?"
            bname = f"Copia #{bid}"
            try:
                parsed = json.loads(raw_data)
                stats = parsed.get("stats", {})
                roles_cnt = stats.get("roles", len(parsed.get("roles", [])))
                ch_cnt = stats.get("channels", len(parsed.get("channels", [])))
                if parsed.get("name"):
                    bname = parsed["name"][:35]
            except Exception:
                pass

            embed.add_field(
                name=f"📦 #{bid} · {bname}",
                value=f"📅 {bdate}\n🎭 `{roles_cnt}` roles · 💬 `{ch_cnt}` canales · `{bkind or 'structure'}`",
                inline=False
            )

        embed.set_footer(text="Para restaurar: /serverbackup restore <id> o desde dabot.davito.es")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="🔍 Muestra la información detallada de una copia de seguridad.")
    @app_commands.describe(backup_id="ID numérico del backup")
    @app_commands.default_permissions(administrator=True)
    async def info(self, interaction: discord.Interaction, backup_id: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Solo en un servidor.", ephemeral=True)
            return

        row = await self.bot.db.fetch_one(
            "SELECT id, created_at, status, kind, backup_data FROM server_backups WHERE id = ? AND guild_id = ?",
            backup_id, guild.id
        )

        if not row:
            await interaction.response.send_message(f"❌ No se encontró ninguna copia con ID `#{backup_id}` en este servidor.", ephemeral=True)
            return

        raw_data = row["backup_data"] if isinstance(row, dict) else row[4]
        try:
            data = json.loads(raw_data)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error al procesar los datos de la copia: {e}", ephemeral=True)
            return

        roles = data.get("roles", [])
        categories = data.get("categories", [])
        channels = data.get("channels", [])

        created_str = row["created_at"] if isinstance(row, dict) else row[1]
        embed = discord.Embed(
            title=f"🔍 Detalle de Copia #{backup_id}",
            description=f"**Nombre:** {data.get('name', 'Sin nombre')}\n**Servidor original:** {data.get('guild_name', guild.name)}\n**Fecha:** {created_str}",
            color=discord.Color.teal()
        )
        embed.add_field(name="🎭 Roles", value=f"{len(roles)} roles", inline=True)
        embed.add_field(name="📁 Categorías", value=f"{len(categories)} categorías", inline=True)
        embed.add_field(name="💬 Canales", value=f"{len(channels)} canales", inline=True)

        if roles:
            sample_roles = ", ".join(r.get("name", "") for r in roles[:8])
            if len(roles) > 8:
                sample_roles += f" ... (+{len(roles)-8} más)"
            embed.add_field(name="Muestra de Roles", value=sample_roles, inline=False)

        if channels:
            sample_ch = ", ".join(f"#{c.get('name', '')}" for c in channels[:8])
            if len(channels) > 8:
                sample_ch += f" ... (+{len(channels)-8} más)"
            embed.add_field(name="Muestra de Canales", value=sample_ch, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="restore", description="⚠️ Restaura la estructura de canales y roles desde una copia de seguridad.")
    @app_commands.describe(backup_id="ID numérico del backup a restaurar")
    @app_commands.default_permissions(administrator=True)
    async def restore(self, interaction: discord.Interaction, backup_id: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Solo en un servidor.", ephemeral=True)
            return

        # Restrict to Guild Owner or Super Owner
        if interaction.user.id != guild.owner_id and interaction.user.id != SUPER_OWNER_ID:
            await interaction.response.send_message(
                "❌ Por seguridad crítica, solo el **Dueño del Servidor** o el Superadministrador de Dabot pueden restaurar copias de seguridad.",
                ephemeral=True
            )
            return

        row = await self.bot.db.fetch_one(
            "SELECT backup_data FROM server_backups WHERE id = ? AND guild_id = ?",
            backup_id, guild.id
        )

        if not row:
            await interaction.response.send_message(f"❌ No se encontró la copia `#{backup_id}` en este servidor.", ephemeral=True)
            return

        raw_data = row["backup_data"] if isinstance(row, dict) else row[0]
        try:
            backup_data = json.loads(raw_data)
        except Exception as e:
            await interaction.response.send_message(f"❌ Datos de la copia corruptos: {e}", ephemeral=True)
            return

        view = BackupRestoreConfirmView(self, backup_data, interaction.user.id)
        desc = (
            f"Estás a punto de restaurar la copia `#{backup_id}` (**{backup_data.get('name', '')}**).\n\n"
            f"• **Roles a restaurar:** {len(backup_data.get('roles', []))}\n"
            f"• **Categorías:** {len(backup_data.get('categories', []))}\n"
            f"• **Canales:** {len(backup_data.get('channels', []))}\n\n"
            "Dabot recreará los roles y canales faltantes con sus permisos originales.\n"
            "¿Deseas continuar?"
        )
        embed = discord.Embed(
            title="⚠️ Confirmación de Restauración de Servidor",
            description=desc,
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def apply_backup(self, interaction: discord.Interaction, data: dict):
        guild = interaction.guild
        await interaction.followup.send("⏳ Iniciando proceso de restauración... Por favor espera.", ephemeral=True)

        created_roles = 0
        created_categories = 0
        created_channels = 0
        role_map = {}

        # 1. Restore Roles
        existing_roles = {r.name.lower(): r for r in guild.roles}
        for r_info in data.get("roles", []):
            name = r_info.get("name")
            if not name:
                continue
            if name.lower() in existing_roles:
                role_map[r_info.get("id")] = existing_roles[name.lower()]
                continue
            try:
                perms_val = int(r_info.get("permissions", 0))
                perms = discord.Permissions(perms_val)
                new_role = await guild.create_role(
                    name=name,
                    color=discord.Color(int(r_info.get("color", 0))),
                    hoist=bool(r_info.get("hoist", False)),
                    mentionable=bool(r_info.get("mentionable", False)),
                    permissions=perms,
                    reason="Restauración de copia de seguridad Dabot"
                )
                role_map[r_info.get("id")] = new_role
                created_roles += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                log.warning(f"Error creating role {name}: {e}")

        # 2. Restore Categories
        cat_map = {}
        existing_cats = {c.name.lower(): c for c in guild.categories}
        for cat_info in data.get("categories", []):
            name = cat_info.get("name")
            if not name:
                continue
            if name.lower() in existing_cats:
                cat_map[cat_info.get("id")] = existing_cats[name.lower()]
                continue
            try:
                new_cat = await guild.create_category(
                    name=name,
                    position=cat_info.get("position", 0),
                    reason="Restauración de copia de seguridad Dabot"
                )
                cat_map[cat_info.get("id")] = new_cat
                created_categories += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                log.warning(f"Error creating category {name}: {e}")

        # 3. Restore Channels
        existing_chs = {c.name.lower(): c for c in guild.channels}
        for ch_info in data.get("channels", []):
            name = ch_info.get("name")
            if not name:
                continue
            if name.lower() in existing_chs:
                continue

            ch_type = ch_info.get("type", 0)
            parent = cat_map.get(ch_info.get("parent_id"))
            topic = ch_info.get("topic", "")
            nsfw = bool(ch_info.get("nsfw", False))
            slowmode = int(ch_info.get("slowmode_delay", 0))

            try:
                if ch_type == 2:  # Voice
                    await guild.create_voice_channel(
                        name=name,
                        category=parent,
                        position=ch_info.get("position", 0),
                        reason="Restauración de copia de seguridad Dabot"
                    )
                elif ch_type == 15:  # Forum
                    await guild.create_forum(
                        name=name,
                        topic=topic,
                        category=parent,
                        position=ch_info.get("position", 0),
                        reason="Restauración de copia de seguridad Dabot"
                    )
                else:  # Text
                    await guild.create_text_channel(
                        name=name,
                        topic=topic,
                        category=parent,
                        nsfw=nsfw,
                        slowmode_delay=slowmode,
                        position=ch_info.get("position", 0),
                        reason="Restauración de copia de seguridad Dabot"
                    )
                created_channels += 1
                await asyncio.sleep(0.35)
            except Exception as e:
                log.warning(f"Error creating channel {name}: {e}")

        result_embed = discord.Embed(
            title="✅ Restauración Completada",
            description=f"Se ha restaurado la estructura en **{guild.name}** satisfactoriamente.",
            color=discord.Color.green()
        )
        result_embed.add_field(name="🎭 Roles creados", value=str(created_roles), inline=True)
        result_embed.add_field(name="📁 Categorías creadas", value=str(created_categories), inline=True)
        result_embed.add_field(name="💬 Canales creados", value=str(created_channels), inline=True)
        await interaction.followup.send(embed=result_embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerBackup(bot))
