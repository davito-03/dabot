import asyncio
import discord
from discord.ext import commands
from datetime import datetime
import logging
from discord import app_commands
import io

class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.Commands')
        self.invites_cache = {}

    async def cog_load(self):
        asyncio.create_task(self.initialize_invites_cache())

    async def initialize_invites_cache(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                if guild.me and getattr(guild.me, "guild_permissions", None) and guild.me.guild_permissions.manage_guild:
                    invs = await guild.invites()
                    self.invites_cache[guild.id] = {invite.code: invite.uses for invite in invs}
            except Exception as e:
                self.logger.error(f"Failed to cache invites for {guild.name}: {e}")

    log_group = app_commands.Group(name="log", description="Logging configuration")

    @log_group.command(name="config", description="Configure log channels")
    @app_commands.describe(log_type="The type of log to configure", channel="The channel to send logs to")
    @app_commands.choices(log_type=[
        app_commands.Choice(name="Messages (Deleted/Edited)", value="messages"),
        app_commands.Choice(name="Voice (Join/Leave/Move)", value="voice"),
        app_commands.Choice(name="Members (Profile Updates)", value="members"),
        app_commands.Choice(name="Joins (Join/Leave)", value="joins"),
        app_commands.Choice(name="Moderation (Warn/Kick/Ban)", value="moderation"),
        app_commands.Choice(name="Hijack radar (hacked accounts)", value="hijack"),
        app_commands.Choice(name="Server (name/icon/settings)", value="server"),
        app_commands.Choice(name="Tickets (name + web link)", value="tickets"),
        app_commands.Choice(name="Alts (multi-account cases)", value="alts"),
        app_commands.Choice(name="Verification (who verified)", value="verification"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_config(self, interaction: discord.Interaction, log_type: app_commands.Choice[str], channel: discord.TextChannel):
        """Sets the log channel for a specific log type."""
        success = self.bot.config.set_config(interaction.guild.id, f"logs.{log_type.value}", str(channel.id))
        if log_type.value == "tickets":
            self.bot.config.set_config(interaction.guild.id, "tickets.transcript_channel_id", str(channel.id))
        
        if success:
            embed = discord.Embed(
                title="Log Configuration Updated",
                description=f"✅ **{log_type.name}** logs will now be sent to {channel.mention}.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Failed to save configuration.", ephemeral=True)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Log successful prefix command execution."""
        user = f"{ctx.author} ({ctx.author.id})"
        guild = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "DM"
        command = ctx.command.qualified_name
        self.logger.info(f"Prefix Command | User: {user} | Server: {guild} | Command: {command}")

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction, command):
        """Log successful slash command execution."""
        user = f"{interaction.user} ({interaction.user.id})"
        guild = f"{interaction.guild.name} ({interaction.guild.id})" if interaction.guild else "DM"
        cmd_name = command.qualified_name
        self.logger.info(f"Slash Command  | User: {user} | Server: {guild} | Command: {cmd_name}")

    async def log_event(self, guild, log_type, embed, file=None, files=None, *, actor_id=None, target_id=None, channel_id=None):
        """Send log embeds and persist a copy for the web dashboard."""
        if not guild:
            return
        try:
            await self.bot.db.execute(
                """INSERT INTO audit_events (guild_id, event_type, actor_id, target_id, channel_id, summary, extra, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                guild.id, log_type, actor_id, target_id, channel_id,
                (embed.title or log_type)[:180],
                None,
                datetime.now().isoformat(),
            )
        except Exception:
            pass

        config = self.bot.config.get(guild.id)
        if not config:
            return

        raw_id = (config.get("logs") or {}).get(log_type)
        if not raw_id:
            return

        try:
            channel = guild.get_channel(int(raw_id))
            if channel:
                await channel.send(embed=embed, file=file, files=files)
        except (ValueError, TypeError, discord.Forbidden, discord.HTTPException):
            pass

    def _uid(self, user) -> str:
        if not user:
            return "—"
        return f"{user} (`{getattr(user, 'id', '?')}`)"

    def _ch(self, channel) -> str:
        if not channel:
            return "—"
        mention = getattr(channel, "mention", None) or f"#{channel.name}"
        return f"{mention} · `{channel.name}` (`{channel.id}`)"

    async def _skip_stats_channel(self, channel) -> bool:
        if not channel:
            return False
        try:
            row = await self.bot.db.fetch("SELECT 1 FROM stats_channels WHERE channel_id = ?", channel.id)
            return bool(row)
        except Exception:
            return False

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild:
            return

        # 1. Lookup who deleted the message in the audit logs
        deleted_by = None
        if message.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in message.guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=5):
                    if entry.target.id == message.author.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        deleted_by = entry.user
                        break
            except Exception:
                pass

        embed = discord.Embed(title="Message Deleted", color=discord.Color.red(), timestamp=datetime.now())
        embed.set_author(name=self._uid(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Content", value=message.content or "[No Content]", inline=False)
        embed.add_field(name="Channel", value=self._ch(message.channel), inline=False)
        embed.add_field(name="Message ID", value=f"`{message.id}`", inline=True)
        
        if deleted_by:
            embed.add_field(name="Deleted By", value=self._uid(deleted_by), inline=True)
        else:
            embed.add_field(name="Deleted By", value="Member (Self-delete / Unknown)", inline=True)

        embed.set_footer(text=f"User `{message.author.id}` · Channel `{message.channel.id}` · Message `{message.id}`")

        # 2. Process attachments
        files_to_send = []
        first_image_filename = None
        
        if message.attachments:
            for idx, a in enumerate(message.attachments):
                try:
                    async with self.bot.session.get(a.url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            filename = a.filename or f"deleted_file_{idx}"
                            f = discord.File(io.BytesIO(data), filename=filename)
                            files_to_send.append(f)
                            
                            # Check if image to embed
                            if not first_image_filename and (a.content_type and a.content_type.startswith("image/") or filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))):
                                first_image_filename = filename
                except Exception as e:
                    self.logger.error(f"Failed to download deleted attachment: {e}")

        if first_image_filename:
            embed.set_image(url=f"attachment://{first_image_filename}")

        if files_to_send:
            await self.log_event(message.guild, 'messages', embed, files=files_to_send)
        else:
            await self.log_event(message.guild, 'messages', embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild or before.content == after.content:
            return

        import difflib
        before_lines = (before.content or "").splitlines()
        after_lines = (after.content or "").splitlines()
        
        # Generate unified diff
        diff = list(difflib.unified_diff(before_lines, after_lines, lineterm=""))
        diff_text = ""
        if len(diff) > 2:
            # Skip headers (first 2 lines of unified diff)
            diff_text = "\n".join(diff[2:])
        else:
            diff_text = f"- {before.content or '[No Content]'}\n+ {after.content or '[No Content]'}"

        if len(diff_text) > 1000:
            diff_text = diff_text[:990] + "\n... (cortado por límite de caracteres)"

        diff_block = f"```diff\n{diff_text}\n```"

        embed = discord.Embed(title="Message Edited", color=discord.Color.orange(), timestamp=datetime.now())
        embed.set_author(name=self._uid(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Changes (Diff)", value=diff_block, inline=False)
        embed.add_field(name="Channel", value=self._ch(before.channel), inline=False)
        embed.add_field(name="Message ID", value=f"`{before.id}`", inline=True)
        embed.set_footer(text=f"User `{before.author.id}` · Channel `{before.channel.id}` · Message `{before.id}`")
        
        await self.log_event(before.guild, 'messages', embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        embed = None
        if before.channel is None and after.channel is not None:
             embed = discord.Embed(title="Voice Join", color=discord.Color.green(), timestamp=datetime.now())
             embed.add_field(name="Channel", value=f"**{after.channel.name}** (`{after.channel.id}`)", inline=False)
        elif before.channel is not None and after.channel is None:
             embed = discord.Embed(title="Voice Leave", color=discord.Color.red(), timestamp=datetime.now())
             embed.add_field(name="Channel", value=f"**{before.channel.name}** (`{before.channel.id}`)", inline=False)
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
             embed = discord.Embed(title="Voice Move", color=discord.Color.blue(), timestamp=datetime.now())
             embed.add_field(name="From", value=f"**{before.channel.name}** (`{before.channel.id}`)", inline=True)
             embed.add_field(name="To", value=f"**{after.channel.name}** (`{after.channel.id}`)", inline=True)

             # Check who moved the member
             moved_by = None
             if member.guild.me.guild_permissions.view_audit_log:
                 try:
                     async for entry in member.guild.audit_logs(action=discord.AuditLogAction.member_move, limit=5):
                         if entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                             moved_by = entry.user
                             break
                 except Exception:
                     pass

             if moved_by:
                 embed.add_field(name="Moved By", value=f"{moved_by.mention} ({moved_by.id})", inline=False)
             else:
                 embed.add_field(name="Moved By", value="Self / Autonomous", inline=False)

        if embed:
            embed.set_author(name=self._uid(member), icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User `{member.id}`")
            await self.log_event(member.guild, 'voice', embed, actor_id=member.id,
                                 channel_id=(after.channel.id if after.channel else (before.channel.id if before.channel else None)))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        embed = None
        
        # Nickname Change
        if before.nick != after.nick:
             embed = discord.Embed(title="Nickname Changed", color=discord.Color.blue(), timestamp=datetime.now())
             embed.add_field(name="Before", value=before.nick or before.name or "None", inline=True)
             embed.add_field(name="After", value=after.nick or after.name or "None", inline=True)
             embed.add_field(name="User ID", value=f"`{after.id}`", inline=True)
             embed.set_thumbnail(url=after.display_avatar.url)
        
        # Role Change
        elif before.roles != after.roles:
             embed = discord.Embed(title="Roles Updated", color=discord.Color.blue(), timestamp=datetime.now())
             added = [r.mention for r in after.roles if r not in before.roles]
             removed = [r.mention for r in before.roles if r not in after.roles]
             if added:
                 embed.add_field(name="Added", value=", ".join(added), inline=False)
             if removed:
                 embed.add_field(name="Removed", value=", ".join(removed), inline=False)

        # Avatar Change (Server-specific or Global)
        elif before.display_avatar != after.display_avatar:
             try:
                 before_bytes = await before.display_avatar.read()
                 after_bytes = await after.display_avatar.read()
                 
                 from utils.images import create_avatar_comparison
                 img_buffer = await create_avatar_comparison(before_bytes, after_bytes)
                 
                 if img_buffer:
                     embed = discord.Embed(title="Avatar Changed", color=discord.Color.magenta(), timestamp=datetime.now())
                     embed.set_author(name=f"{after} ({after.id})", icon_url=after.display_avatar.url)
                     
                     file = discord.File(img_buffer, filename="avatar_change.png")
                     embed.set_image(url="attachment://avatar_change.png")
                     
                     await self.log_event(after.guild, 'members', embed, file=file)
                     return
             except Exception as e:
                 self.logger.error(f"Error processing avatar change log: {e}")

        # Timeout Change (Muted/Unmuted)
        elif before.timed_out_until != after.timed_out_until:
             try:
                 is_muted = after.timed_out_until is not None and after.timed_out_until > discord.utils.utcnow()
                 
                 moderator = None
                 reason = "No especificado"
                 
                 if after.guild.me.guild_permissions.view_audit_log:
                     try:
                         async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                             if entry.target.id == after.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                                 if hasattr(entry.changes, 'communication_disabled_until'):
                                     moderator = entry.user
                                     reason = entry.reason or "No especificado"
                                     break
                     except Exception:
                         pass
                 
                 if is_muted:
                     embed = discord.Embed(title="Usuario Silenciado 🔇", color=discord.Color.orange(), timestamp=datetime.now())
                     duration = (after.timed_out_until - discord.utils.utcnow()).total_seconds()
                     duration_str = ""
                     if duration >= 86400:
                         duration_str = f"{int(duration // 86400)}d"
                     elif duration >= 3600:
                         duration_str = f"{int(duration // 3600)}h"
                     else:
                         duration_str = f"{int(duration // 60)}m"
                         
                     embed.add_field(name="Duración", value=duration_str, inline=True)
                     embed.add_field(name="Hasta", value=after.timed_out_until.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
                     embed.add_field(name="Razón", value=reason, inline=False)
                     
                     if moderator:
                         embed.add_field(name="Moderador", value=f"{moderator.mention} ({moderator.id})", inline=True)
                     else:
                         embed.add_field(name="Moderador", value="Desconocido / Panel de Discord", inline=True)
                         
                     embed.set_author(name=f"{after} ({after.id})", icon_url=after.display_avatar.url)
                     await self.log_event(after.guild, 'moderation', embed)
                     return
                 else:
                     embed = discord.Embed(title="Silencio Removido 🔊", color=discord.Color.green(), timestamp=datetime.now())
                     embed.add_field(name="Razón", value=reason, inline=False)
                     if moderator:
                         embed.add_field(name="Moderador", value=f"{moderator.mention} ({moderator.id})", inline=True)
                     else:
                         embed.add_field(name="Moderador", value="Desconocido / Panel de Discord", inline=True)
                         
                     embed.set_author(name=f"{after} ({after.id})", icon_url=after.display_avatar.url)
                     await self.log_event(after.guild, 'moderation', embed)
                     return
             except Exception as e:
                 self.logger.error(f"Error processing timeout log: {e}")

        if embed:
            embed.set_author(name=f"{after} ({after.id})", icon_url=after.display_avatar.url)
            await self.log_event(after.guild, 'members', embed)

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        name_changed = before.name != after.name or before.discriminator != after.discriminator or getattr(before, "global_name", None) != getattr(after, "global_name", None)
        avatar_changed = before.avatar != after.avatar
        if not name_changed and not avatar_changed:
            return
        pair = None
        if avatar_changed:
            try:
                pair = (await before.display_avatar.read(), await after.display_avatar.read())
            except Exception as e:
                self.logger.error(f"Error reading global avatar: {e}")
        from utils.images import create_avatar_comparison
        for guild in self.bot.guilds:
            if not guild.get_member(after.id):
                continue
            embed = discord.Embed(
                title="Username Changed" if name_changed else "Avatar Changed",
                color=discord.Color.magenta(),
                timestamp=datetime.now(),
            )
            embed.set_author(name=self._uid(after), icon_url=after.display_avatar.url)
            if name_changed:
                embed.add_field(name="Before", value=f"{before} · global `{getattr(before, 'global_name', None) or '—'}`", inline=False)
                embed.add_field(name="After", value=f"{after} · global `{getattr(after, 'global_name', None) or '—'}`", inline=False)
            embed.add_field(name="User ID", value=f"`{after.id}`", inline=True)
            file = None
            if pair:
                try:
                    img_buffer = await create_avatar_comparison(pair[0], pair[1])
                    if img_buffer:
                        file = discord.File(img_buffer, filename="avatar_change.png")
                        embed.set_image(url="attachment://avatar_change.png")
                except Exception:
                    file = None
            await self.log_event(guild, 'members', embed, file=file)

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if invite.guild.id not in self.invites_cache:
            self.invites_cache[invite.guild.id] = {}
        self.invites_cache[invite.guild.id][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if invite.guild.id in self.invites_cache:
            self.invites_cache[invite.guild.id].pop(invite.code, None)

        embed = discord.Embed(title="Invite Deleted", color=discord.Color.red(), timestamp=datetime.now())
        embed.add_field(name="Code", value=invite.code, inline=True)
        if invite.inviter:
             embed.add_field(name="Created By", value=f"{invite.inviter.mention} ({invite.inviter.id})", inline=True)
        await self.log_event(invite.guild, 'joins', embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        inviter = None
        used_invite_code = None
        guild = member.guild
        total_invites = 0
        
        if guild.me.guild_permissions.manage_guild:
            try:
                new_invs = await guild.invites()
                old_invs = self.invites_cache.get(guild.id, {})
                
                for invite in new_invs:
                    old_uses = old_invs.get(invite.code)
                    if old_uses is not None and invite.uses > old_uses:
                        inviter = invite.inviter
                        used_invite_code = invite.code
                        break
                
                self.invites_cache[guild.id] = {invite.code: invite.uses for invite in new_invs}
            except Exception as e:
                self.logger.error(f"Invite tracking failed for {guild.name}: {e}")

        if inviter:
            try:
                timestamp = datetime.now().isoformat()
                await self.bot.db.execute(
                    """INSERT OR IGNORE INTO invite_tracker (guild_id, inviter_id, invited_id, invite_code, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                    guild.id, inviter.id, member.id, used_invite_code, timestamp
                )
                count_row = await self.bot.db.fetch(
                    "SELECT COUNT(*) FROM invite_tracker WHERE guild_id = ? AND inviter_id = ?",
                    guild.id, inviter.id
                )
                total_invites = count_row[0] if count_row else 1
            except Exception as e:
                self.logger.error(f"DB insert failed in invite tracker: {e}")
                total_invites = 1

        embed = discord.Embed(title="Member Joined", color=discord.Color.green(), timestamp=datetime.now())
        embed.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
        
        if inviter:
            embed.add_field(
                name="Invitación Utilizada", 
                value=f"Invitado por: {inviter.mention} (`{inviter.id}`)\nCódigo: `{used_invite_code}`\nTotal invitaciones: **{total_invites}**", 
                inline=False
            )
        else:
            embed.add_field(name="Invitación Utilizada", value="Desconocido / Vanity URL / Enlace temporal", inline=False)

        await self.log_event(guild, 'joins', embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        moderator = None
        reason = "No especificado"
        was_kicked = False
        
        if member.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=5):
                    if entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        reason = entry.reason or "No especificado"
                        was_kicked = True
                        break
            except Exception:
                pass

        if was_kicked:
            embed = discord.Embed(title="Usuario Expulsado 👢", color=discord.Color.red(), timestamp=datetime.now())
            embed.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
            embed.add_field(name="Razón", value=reason, inline=False)
            if moderator:
                embed.add_field(name="Moderador", value=f"{moderator.mention} ({moderator.id})", inline=True)
            else:
                embed.add_field(name="Moderador", value="Desconocido / Panel de Discord", inline=True)
            await self.log_event(member.guild, 'moderation', embed)
        else:
            embed = discord.Embed(title="Member Left", color=discord.Color.red(), timestamp=datetime.now())
            embed.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
            await self.log_event(member.guild, 'joins', embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        moderator = None
        reason = "No especificado"
        
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=5):
                    if entry.target.id == user.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        reason = entry.reason or "No especificado"
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Usuario Baneado 🔨", color=discord.Color.red(), timestamp=datetime.now())
        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
        embed.add_field(name="Razón", value=reason, inline=False)
        if moderator:
             embed.add_field(name="Moderador", value=f"{moderator.mention} ({moderator.id})", inline=True)
        else:
             embed.add_field(name="Moderador", value="Desconocido / Panel de Discord", inline=True)
             
        await self.log_event(guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        moderator = None
        reason = "No especificado"
        
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=5):
                    if entry.target.id == user.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        reason = entry.reason or "No especificado"
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Usuario Desbaneado 🔓", color=discord.Color.green(), timestamp=datetime.now())
        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
        embed.add_field(name="Razón", value=reason, inline=False)
        if moderator:
             embed.add_field(name="Moderador", value=f"{moderator.mention} ({moderator.id})", inline=True)
        else:
             embed.add_field(name="Moderador", value="Desconocido / Panel de Discord", inline=True)
             
        await self.log_event(guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        moderator = None
        if channel.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_create, limit=5):
                    if entry.target.id == channel.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Channel Created 📁", color=discord.Color.green(), timestamp=datetime.now())
        embed.add_field(name="Name", value=f"**{channel.name}** (`{channel.id}`)", inline=True)
        embed.add_field(name="Type", value=str(channel.type), inline=True)
        if moderator:
             embed.add_field(name="Created By", value=f"{moderator.mention} ({moderator.id})", inline=False)
             
        await self.log_event(channel.guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        moderator = None
        if channel.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=5):
                    if entry.target.id == channel.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Channel Deleted 📁", color=discord.Color.red(), timestamp=datetime.now())
        embed.add_field(name="Name", value=f"**{channel.name}** (`{channel.id}`)", inline=True)
        embed.add_field(name="Type", value=str(channel.type), inline=True)
        if moderator:
             embed.add_field(name="Deleted By", value=f"{moderator.mention} ({moderator.id})", inline=False)
             
        await self.log_event(channel.guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if await self._skip_stats_channel(after):
            return
        changes = []
        if before.name != after.name:
            changes.append(f"Nombre: `{before.name}` -> `{after.name}`")
        if getattr(before, 'topic', None) != getattr(after, 'topic', None):
            changes.append(f"Tema: `{before.topic}` -> `{after.topic}`")
        if getattr(before, 'nsfw', None) != getattr(after, 'nsfw', None):
            changes.append(f"NSFW: `{before.nsfw}` -> `{after.nsfw}`")
        if getattr(before, 'slowmode_delay', None) != getattr(after, 'slowmode_delay', None):
            changes.append(f"Slowmode: `{before.slowmode_delay}s` -> `{after.slowmode_delay}s`")
            
        if not changes:
            return
            
        moderator = None
        if after.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=5):
                    if entry.target.id == after.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Channel Updated 📝", color=discord.Color.blue(), timestamp=datetime.now())
        embed.add_field(name="Canal", value=self._ch(after), inline=False)
        embed.add_field(name="Cambios", value="\n".join(changes), inline=False)
        if moderator:
             embed.add_field(name="Modificado Por", value=f"{moderator.mention} ({moderator.id})", inline=False)
             
        await self.log_event(after.guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        moderator = None
        if role.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_create, limit=5):
                    if entry.target.id == role.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Role Created 🛡️", color=discord.Color.green(), timestamp=datetime.now())
        embed.add_field(name="Nombre", value=role.name, inline=True)
        if moderator:
             embed.add_field(name="Creado Por", value=f"{moderator.mention} ({moderator.id})", inline=False)
             
        await self.log_event(role.guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        moderator = None
        if role.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=5):
                    if entry.target.id == role.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Role Deleted 🗑️", color=discord.Color.red(), timestamp=datetime.now())
        embed.add_field(name="Nombre", value=role.name, inline=True)
        if moderator:
             embed.add_field(name="Eliminado Por", value=f"{moderator.mention} ({moderator.id})", inline=False)
             
        await self.log_event(role.guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"Nombre: `{before.name}` -> `{after.name}`")
        if before.color != after.color:
            changes.append(f"Color: `{before.color}` -> `{after.color}`")
        if before.hoist != after.hoist:
            changes.append(f"Separado: `{before.hoist}` -> `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"Mencionable: `{before.mentionable}` -> `{after.mentionable}`")
            
        if before.permissions != after.permissions:
            added_perms = [p[0] for p in after.permissions if p[1] and not getattr(before.permissions, p[0])]
            removed_perms = [p[0] for p in before.permissions if p[1] and not getattr(after.permissions, p[0])]
            if added_perms:
                changes.append(f"Permisos Añadidos: " + ", ".join(f"`{p}`" for p in added_perms))
            if removed_perms:
                changes.append(f"Permisos Removidos: " + ", ".join(f"`{p}`" for p in removed_perms))
                
        if not changes:
            return
            
        moderator = None
        if after.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.role_update, limit=5):
                    if entry.target.id == after.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Role Updated 🛡️", color=discord.Color.blue(), timestamp=datetime.now())
        embed.add_field(name="Rol", value=after.mention, inline=True)
        embed.add_field(name="Cambios", value="\n".join(changes), inline=False)
        if moderator:
             embed.add_field(name="Modificado Por", value=f"{moderator.mention} ({moderator.id})", inline=False)
             
        await self.log_event(after.guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes = []
        embed = None
        file_to_send = None
        
        if before.name != after.name:
            changes.append(f"Nombre: `{before.name}` -> `{after.name}`")
        if before.verification_level != after.verification_level:
            changes.append(f"Nivel de Verificación: `{before.verification_level}` -> `{after.verification_level}`")
        if getattr(before, "description", None) != getattr(after, "description", None):
            changes.append(f"Descripción actualizada")
        if getattr(before, "afk_channel", None) != getattr(after, "afk_channel", None):
            changes.append(f"AFK: `{getattr(before.afk_channel, 'name', None)}` → `{getattr(after.afk_channel, 'name', None)}`")
        if getattr(before, "owner_id", None) != getattr(after, "owner_id", None):
            changes.append(f"Owner: `{before.owner_id}` → `{after.owner_id}`")
        if getattr(before, "vanity_url_code", None) != getattr(after, "vanity_url_code", None):
            changes.append(f"Vanity: `{before.vanity_url_code}` → `{after.vanity_url_code}`")
        if getattr(before, "premium_tier", None) != getattr(after, "premium_tier", None):
            changes.append(f"Boost tier: `{before.premium_tier}` → `{after.premium_tier}`")
            
        if before.icon != after.icon and after.icon is not None and before.icon is not None:
            try:
                before_bytes = await before.icon.read()
                after_bytes = await after.icon.read()
                
                from utils.images import create_side_by_side_comparison
                img_buffer = await create_side_by_side_comparison(before_bytes, after_bytes, "ICONO ANTERIOR", "ICONO NUEVO")
                if img_buffer:
                    file_to_send = discord.File(img_buffer, filename="icon_change.png")
                    changes.append("Icono del servidor actualizado (ver imagen)")
            except Exception as e:
                self.logger.error(f"Failed to process guild icon update: {e}")
                
        elif before.banner != after.banner and after.banner is not None and before.banner is not None:
            try:
                before_bytes = await before.banner.read()
                after_bytes = await after.banner.read()
                
                from utils.images import create_side_by_side_comparison
                img_buffer = await create_side_by_side_comparison(before_bytes, after_bytes, "BANNER ANTERIOR", "BANNER NUEVO")
                if img_buffer:
                    file_to_send = discord.File(img_buffer, filename="banner_change.png")
                    changes.append("Banner del servidor actualizado (ver imagen)")
            except Exception as e:
                self.logger.error(f"Failed to process guild banner update: {e}")

        if not changes:
            return
            
        moderator = None
        if after.me.guild_permissions.view_audit_log:
            try:
                async for entry in after.audit_logs(action=discord.AuditLogAction.guild_update, limit=5):
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        moderator = entry.user
                        break
            except Exception:
                pass
                
        embed = discord.Embed(title="Servidor Actualizado ⚙️", color=discord.Color.blue(), timestamp=datetime.now())
        embed.add_field(name="Servidor", value=f"**{after.name}** (`{after.id}`)", inline=False)
        embed.add_field(name="Cambios realizados", value="\n".join(changes), inline=False)
        if moderator:
             embed.add_field(name="Modificado Por", value=self._uid(moderator), inline=False)
             
        if file_to_send:
            embed.set_image(url=f"attachment://{file_to_send.filename}")
            await self.log_event(after, 'server', embed, file=file_to_send)
            await self.log_event(after, 'moderation', embed)
        else:
            await self.log_event(after, 'server', embed)
            await self.log_event(after, 'moderation', embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        guild = messages[0].guild
        if not guild:
            return
        channel = messages[0].channel
        embed = discord.Embed(
            title=f"Purga · {len(messages)} mensajes",
            description=f"Se han borrado **{len(messages)}** mensajes en {channel.mention}.",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(),
        )
        lines = []
        for m in messages[:10]:
            snippet = (m.content or "[adjunto / embed]")[:90]
            lines.append(f"• `{m.author}`: {snippet}")
        if lines:
            embed.add_field(name="Muestra", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text=f"Canal ID {channel.id}")
        await self.log_event(guild, "messages", embed, channel_id=channel.id)

    @log_group.command(name="here", description="Usa este canal para TODOS los registros (mensajes, voz, joins, mods).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_here(self, interaction: discord.Interaction):
        for key in ("messages", "voice", "members", "joins", "moderation", "alts", "hijack", "tickets", "server", "verification"):
            self.bot.config.set_config(interaction.guild.id, f"logs.{key}", str(interaction.channel.id))
        try:
            import sqlite3, os
            from utils import alt_intel
            path = os.environ.get("DATABASE_PATH", "dabot.db")
            conn = sqlite3.connect(path, timeout=5)
            try:
                alt_intel.set_alts_channel(conn, interaction.guild.id, interaction.channel.id)
            finally:
                conn.close()
        except Exception:
            pass
        await interaction.response.send_message(
            f"✅ Todos los registros de Dabot (multicuentas, **verificaciones**, tickets…) irán a {interaction.channel.mention}.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Logging(bot))
