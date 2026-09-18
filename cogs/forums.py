import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
import datetime
import asyncio

log = logging.getLogger('Dabot.Forums')

class Forums(commands.Cog):
    """Utilidades para canales de Foros y Hilos."""

    def __init__(self, bot):
        self.bot = bot
        self.forum_auto_close_loop.start()

    def cog_unload(self):
        self.forum_auto_close_loop.cancel()

    forum_group = app_commands.Group(name="forum", description="Configuración y estadísticas de foros", guild_only=True)

    @forum_group.command(name="solved", description="Marca este hilo como resuelto.")
    async def solved(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("Este comando solo puede ser usado dentro de un hilo (Thread).", ephemeral=True)
            return

        thread = interaction.channel
        
        # Check permissions: Thread owner OR manage_threads
        has_perms = False
        if thread.owner_id == interaction.user.id:
            has_perms = True
        elif interaction.channel.permissions_for(interaction.user).manage_threads:
            has_perms = True

        if not has_perms:
            await interaction.response.send_message("No tienes permiso para marcar este hilo como resuelto.", ephemeral=True)
            return

        await interaction.response.defer()
        
        parent = thread.parent
        if isinstance(parent, discord.ForumChannel):
            resolved_tag = None
            for tag in parent.available_tags:
                if tag.name.lower() in ("resuelto", "solved", "✅") or tag.emoji and str(tag.emoji) == "✅":
                    resolved_tag = tag
                    break
            
            if resolved_tag and resolved_tag not in thread.applied_tags:
                # Add the tag
                new_tags = thread.applied_tags.copy()
                new_tags.append(resolved_tag)
                try:
                    await thread.edit(applied_tags=new_tags)
                except Exception as e:
                    log.warning(f"No se pudo aplicar la etiqueta de resuelto en el hilo {thread.id}: {e}")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        try:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO forum_resolutions (thread_id, guild_id, channel_id, resolved_by, resolved_at) VALUES (?, ?, ?, ?, ?)",
                thread.id, thread.guild.id, parent.id if parent else 0, interaction.user.id, now
            )
        except Exception as e:
            log.error(f"Error al guardar resolución de foro: {e}")

        await interaction.followup.send(f"✅ Marcado como resuelto por {interaction.user.mention}")
        
        # Archive after 5 seconds
        await asyncio.sleep(5)
        try:
            await thread.edit(archived=True, reason=f"Marcado como resuelto por {interaction.user.name}")
        except Exception as e:
            log.warning(f"No se pudo archivar el hilo {thread.id}: {e}")

    @forum_group.command(name="auto-close", description="Configura el cierre automático de hilos inactivos.")
    @app_commands.describe(
        channel="El canal de foro a configurar",
        days="Días de inactividad antes de archivar (1-30)"
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def forum_auto_close(self, interaction: discord.Interaction, channel: discord.ForumChannel, days: app_commands.Range[int, 1, 30]):
        try:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO forum_config (guild_id, channel_id, auto_close_days) VALUES (?, ?, ?)",
                interaction.guild_id, channel.id, days
            )
            await interaction.response.send_message(f"✅ Hilos inactivos en {channel.mention} se archivarán automáticamente después de {days} días.")
        except Exception as e:
            log.error(f"Error guardando forum_config: {e}")
            await interaction.response.send_message("Ocurrió un error al guardar la configuración.", ephemeral=True)


    @forum_group.command(name="stats", description="Muestra estadísticas del foro.")
    @app_commands.describe(channel="El canal de foro (opcional, muestra estadísticas globales si se omite)")
    async def forum_stats(self, interaction: discord.Interaction, channel: discord.ForumChannel = None):
        await interaction.response.defer()
        
        try:
            if channel:
                threads = channel.threads
                channel_id = channel.id
                title = f"Estadísticas del Foro: {channel.name}"
            else:
                threads = [t for t in interaction.guild.threads if isinstance(t.parent, discord.ForumChannel)]
                channel_id = None
                title = "Estadísticas Globales de Foros"

            open_threads = len(threads)
            
            if channel_id:
                resolutions = await self.bot.db.fetch_all("SELECT COUNT(*) FROM forum_resolutions WHERE guild_id = ? AND channel_id = ?", interaction.guild_id, channel_id)
            else:
                resolutions = await self.bot.db.fetch_all("SELECT COUNT(*) FROM forum_resolutions WHERE guild_id = ?", interaction.guild_id)
            
            total_resolved = resolutions[0][0] if resolutions else 0
            
            embed = discord.Embed(title=title, color=discord.Color.blue())
            embed.add_field(name="Hilos Abiertos", value=str(open_threads), inline=True)
            embed.add_field(name="Hilos Resueltos", value=str(total_resolved), inline=True)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            log.error(f"Error generando stats de foro: {e}")
            await interaction.followup.send("Ocurrió un error al generar las estadísticas.")

    @tasks.loop(minutes=30)
    async def forum_auto_close_loop(self):
        try:
            configs = await self.bot.db.fetch_all("SELECT guild_id, channel_id, auto_close_days FROM forum_config")
            if not configs:
                return

            now = datetime.datetime.now(datetime.timezone.utc)
            for guild_id, channel_id, auto_close_days in configs:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.ForumChannel):
                    continue
                
                for thread in channel.threads:
                    if thread.flags.pinned:
                        continue
                    if thread.archived:
                        continue
                    
                    last_message = thread.last_message
                    last_time = None
                    
                    if last_message:
                        last_time = last_message.created_at
                    elif thread.last_message_id:
                        try:
                            msg = await thread.fetch_message(thread.last_message_id)
                            last_time = msg.created_at
                        except discord.NotFound:
                            last_time = thread.created_at
                    else:
                        last_time = thread.created_at

                    if not last_time:
                        continue

                    delta = now - last_time
                    if delta.days >= auto_close_days:
                        try:
                            await thread.edit(archived=True, reason="Inactividad automática")
                            log.info(f"Archivado hilo inactivo {thread.id} en {channel.name}")
                        except Exception as e:
                            log.warning(f"Error archivando hilo {thread.id}: {e}")
                            
        except Exception as e:
            log.error(f"Error en forum_auto_close_loop: {e}")

    @forum_auto_close_loop.before_loop
    async def before_forum_auto_close_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Forums(bot))
