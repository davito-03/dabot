import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
import time
from collections import defaultdict
from datetime import datetime
import re

log = logging.getLogger("Dabot.AntiNuke")

class AntiNuke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Structure: events[guild_id][actor_id][action_type] = [timestamps]
        self.events = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    async def get_config(self, guild_id: int):
        row = await self.bot.db.fetch("SELECT * FROM antinuke_config WHERE guild_id = ?", guild_id)
        if not row:
            return None
        # Convert row to dict
        keys = ['guild_id', 'enabled', 'max_channel_deletes', 'max_role_deletes', 'max_bans', 'max_kicks', 'window_seconds', 'action', 'log_channel_id', 'whitelist']
        if hasattr(row, 'keys'):
            return dict(row)
        return dict(zip(keys, row))

    def _cleanup_events(self, guild_id: int, actor_id: int, action_type: str, window: int):
        now = time.time()
        self.events[guild_id][actor_id][action_type] = [
            t for t in self.events[guild_id][actor_id][action_type] if now - t <= window
        ]
        return len(self.events[guild_id][actor_id][action_type])

    async def _trigger_punishment(self, guild: discord.Guild, actor: discord.Member, reason: str, count: int, action_type: str, config: dict):
        action = config.get('action', 'strip_roles')
        action_taken = action
        try:
            if action == 'strip_roles' or action == 'quarantine':
                dangerous_permissions = ['administrator', 'manage_guild', 'manage_channels', 'manage_roles', 'ban_members', 'kick_members']
                roles_to_remove = []
                for role in actor.roles:
                    if role.name == "@everyone":
                        continue
                    # Check if role has any dangerous permission
                    has_dangerous = any(getattr(role.permissions, perm, False) for perm in dangerous_permissions)
                    if has_dangerous:
                        roles_to_remove.append(role)
                
                if roles_to_remove:
                    await actor.remove_roles(*roles_to_remove, reason=f"AntiNuke: {reason}")
            elif action == 'ban':
                await guild.ban(actor, reason=f"AntiNuke: {reason}")
        except discord.Forbidden:
            log.warning(f"Missing permissions to punish {actor} in {guild.id}")
            action_taken = "failed (no permissions)"
        except Exception as e:
            log.error(f"Error punishing {actor} in {guild.id}: {e}")
            action_taken = f"failed ({e})"
            
        # Log to db
        now_str = datetime.utcnow().isoformat()
        await self.bot.db.execute(
            "INSERT INTO antinuke_logs (guild_id, user_id, user_name, action_type, count, action_taken, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            guild.id, actor.id, str(actor), action_type, count, action_taken, now_str
        )
        
        # Log to channel
        log_channel_id = config.get('log_channel_id')
        if log_channel_id:
            channel = guild.get_channel(log_channel_id)
            if channel:
                embed = discord.Embed(
                    title="🚨 ALERTA MÁXIMA DE SEGURIDAD 🚨",
                    description=f"**Usuario:** {actor.mention} (`{actor.id}`)\n**Razón:** {reason}\n**Acción tomada:** {action_taken}",
                    color=discord.Color.red()
                )
                try:
                    await channel.send(embed=embed)
                except:
                    pass
                    
        # Send emergency DM to owner
        if guild.owner:
            try:
                embed = discord.Embed(
                    title="🚨 ¡ALERTA MÁXIMA DE SEGURIDAD EN TU SERVIDOR! 🚨",
                    description=f"Se detectó un ataque en tu servidor **{guild.name}**.\n\n**Usuario:** {actor.mention} (`{actor.id}`)\n**Acciones detectadas:** {reason} ({count} veces)\n**Contramedidas:** {action_taken}",
                    color=discord.Color.red()
                )
                await guild.owner.send(embed=embed)
            except:
                pass

    async def check_action(self, guild: discord.Guild, action_type: str, limit_key: str, audit_action: discord.AuditLogAction):
        config = await self.get_config(guild.id)
        if not config or not config.get('enabled'):
            return

        limit = config.get(limit_key, 5)
        window = config.get('window_seconds', 10)
        whitelist = json.loads(config.get('whitelist', '[]'))

        try:
            # Find the actor in audit logs
            entries = [entry async for entry in guild.audit_logs(limit=3, action=audit_action)]
            if not entries:
                return
            entry = entries[0] # most recent
            actor = entry.user

            if actor is None or actor.id == self.bot.user.id or actor.id == guild.owner_id or actor.id == getattr(self.bot, 'super_owner_id', 0):
                return

            if actor.id in whitelist:
                return

            # Check if actor has a whitelisted role
            if isinstance(actor, discord.Member):
                for role in actor.roles:
                    if role.id in whitelist:
                        return

            now = time.time()
            self.events[guild.id][actor.id][action_type].append(now)
            count = self._cleanup_events(guild.id, actor.id, action_type, window)

            if count >= limit:
                # Trigger action!
                # clear events to avoid multiple triggers
                self.events[guild.id][actor.id][action_type].clear()
                member = guild.get_member(actor.id)
                if member:
                    reason = f"Excedió el límite de {action_type} ({count} en {window}s)"
                    await self._trigger_punishment(guild, member, reason, count, action_type, config)

        except discord.Forbidden:
            pass
        except Exception as e:
            log.error(f"AntiNuke check error: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.check_action(channel.guild, 'channel_delete', 'max_channel_deletes', discord.AuditLogAction.channel_delete)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.check_action(role.guild, 'role_delete', 'max_role_deletes', discord.AuditLogAction.role_delete)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.check_action(guild, 'member_ban', 'max_bans', discord.AuditLogAction.ban)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # We need to distinguish between leave and kick. We'll check audit logs for kicks.
        config = await self.get_config(member.guild.id)
        if not config or not config.get('enabled'):
            return

        limit = config.get('max_kicks', 5)
        window = config.get('window_seconds', 10)
        whitelist = json.loads(config.get('whitelist', '[]'))

        try:
            # Check if there is a recent kick entry for this member
            is_kick = False
            actor = None
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id:
                    # Check if it was recent
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                        is_kick = True
                        actor = entry.user
                    break

            if not is_kick or not actor:
                return

            if actor.id == self.bot.user.id or actor.id == member.guild.owner_id:
                return
                
            if actor.id in whitelist:
                return

            # Note: actor could just be a User if they left, but we can't fetch their roles if so. 
            # If they are still in the guild, we can check roles.
            actor_member = member.guild.get_member(actor.id)
            if actor_member:
                for role in actor_member.roles:
                    if role.id in whitelist:
                        return
                        
            now = time.time()
            self.events[member.guild.id][actor.id]['member_kick'].append(now)
            count = self._cleanup_events(member.guild.id, actor.id, 'member_kick', window)

            if count >= limit:
                self.events[member.guild.id][actor.id]['member_kick'].clear()
                if actor_member:
                    reason = f"Excedió el límite de kicks ({count} en {window}s)"
                    await self._trigger_punishment(member.guild, actor_member, reason, count, 'member_kick', config)
                    
        except discord.Forbidden:
            pass
        except Exception as e:
            log.error(f"AntiNuke kick check error: {e}")

    # SLASH COMMANDS
    antinuke_group = app_commands.Group(name="antinuke", description="Configuración del sistema Anti-Nuke", default_permissions=discord.Permissions(administrator=True))

    @antinuke_group.command(name="setup", description="Configura los límites del sistema Anti-Nuke")
    async def setup_cmd(self, interaction: discord.Interaction, canal_logs: discord.TextChannel, max_canales: int = 3, max_roles: int = 3, max_baneos: int = 5, accion: str = 'strip_roles'):
        if accion not in ['strip_roles', 'quarantine', 'ban']:
            await interaction.response.send_message("❌ La acción debe ser `strip_roles`, `quarantine` o `ban`.", ephemeral=True)
            return

        config = await self.get_config(interaction.guild.id)
        if not config:
            await self.bot.db.execute(
                "INSERT INTO antinuke_config (guild_id, enabled, max_channel_deletes, max_role_deletes, max_bans, action, log_channel_id) VALUES (?, 1, ?, ?, ?, ?, ?)",
                interaction.guild.id, max_canales, max_roles, max_baneos, accion, canal_logs.id
            )
        else:
            await self.bot.db.execute(
                "UPDATE antinuke_config SET max_channel_deletes = ?, max_role_deletes = ?, max_bans = ?, action = ?, log_channel_id = ? WHERE guild_id = ?",
                max_canales, max_roles, max_baneos, accion, canal_logs.id, interaction.guild.id
            )
            
        await interaction.response.send_message(f"✅ Configuración Anti-Nuke guardada. Canal de logs: {canal_logs.mention}. Acción: `{accion}`.", ephemeral=True)

    @antinuke_group.command(name="toggle", description="Activa o desactiva el sistema Anti-Nuke")
    async def toggle_cmd(self, interaction: discord.Interaction, estado: bool):
        config = await self.get_config(interaction.guild.id)
        if not config:
            await self.bot.db.execute("INSERT INTO antinuke_config (guild_id, enabled) VALUES (?, ?)", interaction.guild.id, 1 if estado else 0)
        else:
            await self.bot.db.execute("UPDATE antinuke_config SET enabled = ? WHERE guild_id = ?", 1 if estado else 0, interaction.guild.id)
            
        await interaction.response.send_message(f"✅ Sistema Anti-Nuke {'activado' if estado else 'desactivado'}.", ephemeral=True)

    @antinuke_group.command(name="whitelist_add", description="Añade un usuario o rol a la lista blanca del Anti-Nuke")
    async def wl_add_cmd(self, interaction: discord.Interaction, id_o_mencion: str):
        config = await self.get_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message("❌ Primero debes configurar el Anti-Nuke con `/antinuke setup`.", ephemeral=True)
            return
            
        clean_id = re.sub(r'[<@&!>]', '', id_o_mencion.strip())
        if not clean_id.isdigit():
            await interaction.response.send_message("❌ Debes proporcionar una ID válida o mención de usuario/rol.", ephemeral=True)
            return
        target_id = int(clean_id)
        whitelist = json.loads(config.get('whitelist', '[]'))
        if target_id not in whitelist:
            whitelist.append(target_id)
            await self.bot.db.execute("UPDATE antinuke_config SET whitelist = ? WHERE guild_id = ?", json.dumps(whitelist), interaction.guild.id)
            await interaction.response.send_message(f"✅ ID `{target_id}` añadida a la whitelist.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Esta ID ya está en la whitelist.", ephemeral=True)

    @antinuke_group.command(name="whitelist_remove", description="Elimina un usuario o rol de la lista blanca del Anti-Nuke")
    async def wl_remove_cmd(self, interaction: discord.Interaction, id_o_mencion: str):
        config = await self.get_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message("❌ No hay configuración activa.", ephemeral=True)
            return
            
        clean_id = re.sub(r'[<@&!>]', '', id_o_mencion.strip())
        if not clean_id.isdigit():
            await interaction.response.send_message("❌ Debes proporcionar una ID válida o mención.", ephemeral=True)
            return
        target_id = int(clean_id)
        whitelist = json.loads(config.get('whitelist', '[]'))
        if target_id in whitelist:
            whitelist.remove(target_id)
            await self.bot.db.execute("UPDATE antinuke_config SET whitelist = ? WHERE guild_id = ?", json.dumps(whitelist), interaction.guild.id)
            await interaction.response.send_message(f"✅ ID `{target_id}` eliminada de la whitelist.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Esta ID no estaba en la whitelist.", ephemeral=True)

    @antinuke_group.command(name="status", description="Muestra el estado actual del Anti-Nuke")
    async def status_cmd(self, interaction: discord.Interaction):
        config = await self.get_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message("❌ El Anti-Nuke no está configurado en este servidor.", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="🛡️ Estado del Anti-Nuke",
            color=discord.Color.green() if config['enabled'] else discord.Color.red()
        )
        embed.add_field(name="Estado", value="Activado ✅" if config['enabled'] else "Desactivado ❌", inline=False)
        embed.add_field(name="Límites (ventana de 10s)", value=(
            f"🗑️ Canales eliminados: **{config.get('max_channel_deletes', 3)}**\n"
            f"❌ Roles eliminados: **{config.get('max_role_deletes', 3)}**\n"
            f"🔨 Baneos: **{config.get('max_bans', 5)}**\n"
            f"👢 Expulsiones: **{config.get('max_kicks', 5)}**\n"
        ), inline=False)
        embed.add_field(name="Acción a tomar", value=f"`{config.get('action', 'strip_roles')}`", inline=True)
        
        log_ch = interaction.guild.get_channel(config.get('log_channel_id', 0))
        embed.add_field(name="Canal de Logs", value=log_ch.mention if log_ch else "Ninguno", inline=True)
        
        whitelist = json.loads(config.get('whitelist', '[]'))
        wl_text = ", ".join(f"`{x}`" for x in whitelist) if whitelist else "Ninguno"
        embed.add_field(name="Whitelist (IDs)", value=wl_text, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @antinuke_group.command(name="logs", description="Muestra los registros recientes de acciones Anti-Nuke")
    async def logs_cmd(self, interaction: discord.Interaction, limite: int = 10):
        rows = await self.bot.db.fetch_all("SELECT * FROM antinuke_logs WHERE guild_id = ? ORDER BY id DESC LIMIT ?", interaction.guild.id, limite)
        if not rows:
            await interaction.response.send_message("No hay registros recientes.", ephemeral=True)
            return
            
        embed = discord.Embed(title="📜 Registros de Anti-Nuke", color=discord.Color.blue())
        for row in rows:
            # Handle row whether it's dict or tuple
            if hasattr(row, 'keys'):
                r = dict(row)
            else:
                keys = ['id', 'guild_id', 'user_id', 'user_name', 'action_type', 'count', 'action_taken', 'created_at']
                r = dict(zip(keys, row))
                
            embed.add_field(
                name=f"[{r['created_at'][:19]}] {r['action_type']} - x{r['count']}",
                value=f"**Usuario:** {r['user_name']} (`{r['user_id']}`)\n**Acción:** {r['action_taken']}",
                inline=False
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
