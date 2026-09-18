import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from datetime import datetime, timezone
import math

log = logging.getLogger("Dabot.VoiceStats")

def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0m"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 and days == 0 and hours == 0:
        parts.append(f"{secs}s")
        
    if not parts:
        return "0m"
    return " ".join(parts)

class VoiceStats(commands.Cog):
    """Voice time tracking and leaderboards."""

    def __init__(self, bot):
        self.bot = bot
        # Maps guild_id -> {user_id: connect_time}
        self._voice_sessions = {}
        self.flush_sessions.start()
        self.weekly_reset.start()

    def cog_unload(self):
        self.flush_sessions.cancel()
        self.weekly_reset.cancel()
        # Note: In a real shutdown we would ideally flush sessions synchronously, 
        # but discord.py cog_unload is sync. Let the background task handle most of it.

    def _ensure_guild(self, guild_id: int):
        if guild_id not in self._voice_sessions:
            self._voice_sessions[guild_id] = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        guild_id = member.guild.id
        self._ensure_guild(guild_id)
        user_id = member.id
        
        now = datetime.utcnow()

        # Check if they were already connected and tracked
        join_time = self._voice_sessions[guild_id].get(user_id)
        if join_time:
            # Calculate elapsed
            elapsed = int((now - join_time).total_seconds())
            
            # Check if previous channel was valid for tracking
            if before.channel:
                # Basic AFK prevention: discard if alone or deafened
                # Check how many non-bots were in the channel before they left (including them)
                # Since we are in the event, before.channel.members might already not include them if they left, 
                # but we'll approximate. A better check is if they were self_deaf or deaf.
                if not (before.self_deaf or before.deaf):
                    # Only count if elapsed > 0
                    if elapsed > 0:
                        try:
                            channel_name = before.channel.name
                            last_active = now.isoformat()
                            await self.bot.db.execute('''
                                INSERT INTO voice_time (user_id, guild_id, weekly_seconds, total_seconds, last_channel_name, last_active)
                                VALUES (?, ?, ?, ?, ?, ?)
                                ON CONFLICT(user_id, guild_id) DO UPDATE SET
                                weekly_seconds = weekly_seconds + ?,
                                total_seconds = total_seconds + ?,
                                last_channel_name = excluded.last_channel_name,
                                last_active = excluded.last_active
                            ''', (user_id, guild_id, elapsed, elapsed, channel_name, last_active, elapsed, elapsed))
                        except Exception as e:
                            log.error(f"Error saving voice time for {user_id}: {e}")

        # Update session state
        if after.channel is None:
            # Left voice completely
            self._voice_sessions[guild_id].pop(user_id, None)
        else:
            # Joined or moved channel
            # Reset the clock from now
            self._voice_sessions[guild_id][user_id] = now

    @tasks.loop(minutes=5)
    async def flush_sessions(self):
        """Periodically flushes ongoing sessions to DB to prevent data loss."""
        now = datetime.utcnow()
        for guild_id, users in self._voice_sessions.items():
            for user_id, join_time in list(users.items()):
                elapsed = int((now - join_time).total_seconds())
                if elapsed > 60: # Only save if at least a minute passed
                    # To get the channel name, we need the member
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        member = guild.get_member(user_id)
                        if member and member.voice and member.voice.channel:
                            # Verify they are not deafened
                            if not (member.voice.self_deaf or member.voice.deaf):
                                channel_name = member.voice.channel.name
                                last_active = now.isoformat()
                                try:
                                    await self.bot.db.execute('''
                                        INSERT INTO voice_time (user_id, guild_id, weekly_seconds, total_seconds, last_channel_name, last_active)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                        ON CONFLICT(user_id, guild_id) DO UPDATE SET
                                        weekly_seconds = weekly_seconds + ?,
                                        total_seconds = total_seconds + ?,
                                        last_channel_name = excluded.last_channel_name,
                                        last_active = excluded.last_active
                                    ''', (user_id, guild_id, elapsed, elapsed, channel_name, last_active, elapsed, elapsed))
                                except Exception as e:
                                    log.error(f"Error flushing voice time for {user_id}: {e}")
                    
                    # Reset join time
                    self._voice_sessions[guild_id][user_id] = now

    @flush_sessions.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def weekly_reset(self):
        """Resets weekly seconds on Monday at midnight UTC."""
        now = datetime.utcnow()
        if now.weekday() == 0 and now.hour == 0:
            try:
                await self.bot.db.execute('UPDATE voice_time SET weekly_seconds = 0')
                log.info("Weekly voice time reset completed.")
            except Exception as e:
                log.error(f"Failed to reset weekly voice time: {e}")

    @weekly_reset.before_loop
    async def before_weekly_reset(self):
        await self.bot.wait_until_ready()

    voicetime = app_commands.Group(name="voicetime", description="Tiempo en canales de voz")

    @voicetime.command(name="top", description="Muestra el top de tiempo en voz del servidor.")
    @app_commands.choices(periodo=[
        app_commands.Choice(name="semana", value="semana"),
        app_commands.Choice(name="total", value="total")
    ])
    async def voicetop(self, interaction: discord.Interaction, periodo: app_commands.Choice[str] = None):
        period_val = periodo.value if periodo else "total"
        order_col = "weekly_seconds" if period_val == "semana" else "total_seconds"
        
        # Flush current sessions first for accurate stats
        await self._flush_guild_sessions(interaction.guild.id)
        
        try:
            records = await self.bot.db.fetch_all(f'''
                SELECT user_id, {order_col} as seconds
                FROM voice_time
                WHERE guild_id = ? AND {order_col} > 0
                ORDER BY seconds DESC
                LIMIT 10
            ''', (interaction.guild.id,))
            
            if not records:
                await interaction.response.send_message("Nadie tiene tiempo registrado aún.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"🏆 Top Tiempo en Voz ({'Semanal' if period_val == 'semana' else 'Total'})",
                color=discord.Color.gold()
            )

            medals = ["🥇", "🥈", "🥉"]
            desc = []
            
            for i, row in enumerate(records):
                rank = medals[i] if i < 3 else f"#{i+1}"
                uid = row['user_id'] if (isinstance(row, dict) or hasattr(row, 'keys')) else row[0]
                sec = row['seconds'] if (isinstance(row, dict) or hasattr(row, 'keys')) else row[1]
                user = interaction.guild.get_member(uid)
                username = user.display_name if user else f"Usuario ({uid})"
                time_str = format_duration(sec)
                desc.append(f"{rank} **{username}** — {time_str}")

            embed.description = "\n".join(desc)
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            log.error(f"Error in voicetop: {e}")
            await interaction.response.send_message("Ocurrió un error al cargar el ranking.", ephemeral=True)

    @voicetime.command(name="me", description="Muestra las estadísticas de tiempo en voz de un usuario.")
    async def voicestats(self, interaction: discord.Interaction, usuario: discord.Member = None):
        target = usuario or interaction.user
        
        # Flush current sessions first for accurate stats
        await self._flush_guild_sessions(interaction.guild.id)

        try:
            record = await self.bot.db.fetch('''
                SELECT weekly_seconds, total_seconds, last_channel_name, last_active
                FROM voice_time
                WHERE user_id = ? AND guild_id = ?
            ''', (target.id, interaction.guild.id))

            if not record:
                await interaction.response.send_message(f"No hay registros de tiempo en voz para {target.display_name}.", ephemeral=True)
                return

            # Get rank
            all_records = await self.bot.db.fetch_all('''
                SELECT user_id
                FROM voice_time
                WHERE guild_id = ? AND total_seconds > 0
                ORDER BY total_seconds DESC
            ''', (interaction.guild.id,))
            
            rank = "N/A"
            for i, row in enumerate(all_records):
                r_uid = row['user_id'] if (isinstance(row, dict) or hasattr(row, 'keys')) else row[0]
                if r_uid == target.id:
                    rank = f"#{i+1}"
                    break

            w_sec = record['weekly_seconds'] if (isinstance(record, dict) or hasattr(record, 'keys')) else record[0]
            t_sec = record['total_seconds'] if (isinstance(record, dict) or hasattr(record, 'keys')) else record[1]
            l_ch = (record['last_channel_name'] if (isinstance(record, dict) or hasattr(record, 'keys')) else record[2]) or "Desconocido"

            embed = discord.Embed(
                title=f"🎙️ Estadísticas de Voz — {target.display_name}",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            
            embed.add_field(name="Tiempo esta semana", value=format_duration(w_sec), inline=True)
            embed.add_field(name="Tiempo total", value=format_duration(t_sec), inline=True)
            embed.add_field(name="Ranking en servidor", value=rank, inline=True)
            embed.add_field(name="Último canal frecuentado", value=l_ch, inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            log.error(f"Error in voicestats: {e}")
            await interaction.response.send_message("Ocurrió un error al cargar las estadísticas.", ephemeral=True)

    @voicetime.command(name="reset", description="Resetea el tiempo en voz (Admin).")
    @app_commands.default_permissions(administrator=True)
    async def voicereset(self, interaction: discord.Interaction, objetivo: str, tipo: str = "semana"):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("No tienes permisos.", ephemeral=True)
            return
            
        try:
            if objetivo.lower() == "todos":
                if tipo == "total":
                    await self.bot.db.execute('UPDATE voice_time SET total_seconds = 0, weekly_seconds = 0 WHERE guild_id = ?', (interaction.guild.id,))
                else:
                    await self.bot.db.execute('UPDATE voice_time SET weekly_seconds = 0 WHERE guild_id = ?', (interaction.guild.id,))
                await interaction.response.send_message(f"Se ha reseteado el tiempo {'total' if tipo == 'total' else 'semanal'} de todos en el servidor.")
            else:
                # Try to parse user mention
                user_id = "".join(c for c in objetivo if c.isdigit())
                if user_id:
                    if tipo == "total":
                        await self.bot.db.execute('UPDATE voice_time SET total_seconds = 0, weekly_seconds = 0 WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, int(user_id)))
                    else:
                        await self.bot.db.execute('UPDATE voice_time SET weekly_seconds = 0 WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, int(user_id)))
                    await interaction.response.send_message(f"Se ha reseteado el tiempo {'total' if tipo == 'total' else 'semanal'} del usuario.")
                else:
                    await interaction.response.send_message("Usuario no válido. Usa 'todos' o menciona a un usuario.", ephemeral=True)
        except Exception as e:
            log.error(f"Error in voicereset: {e}")
            await interaction.response.send_message("Ocurrió un error al resetear.", ephemeral=True)

    async def _flush_guild_sessions(self, guild_id: int):
        now = datetime.utcnow()
        if guild_id not in self._voice_sessions:
            return
            
        for user_id, join_time in list(self._voice_sessions[guild_id].items()):
            elapsed = int((now - join_time).total_seconds())
            if elapsed > 0:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(user_id)
                    if member and member.voice and member.voice.channel:
                        channel_name = member.voice.channel.name
                        last_active = now.isoformat()
                        try:
                            await self.bot.db.execute('''
                                INSERT INTO voice_time (user_id, guild_id, weekly_seconds, total_seconds, last_channel_name, last_active)
                                VALUES (?, ?, ?, ?, ?, ?)
                                ON CONFLICT(user_id, guild_id) DO UPDATE SET
                                weekly_seconds = weekly_seconds + ?,
                                total_seconds = total_seconds + ?,
                                last_channel_name = excluded.last_channel_name,
                                last_active = excluded.last_active
                            ''', (user_id, guild_id, elapsed, elapsed, channel_name, last_active, elapsed, elapsed))
                        except Exception as e:
                            log.error(f"Error flushing guild session for {user_id}: {e}")
                self._voice_sessions[guild_id][user_id] = now

async def setup(bot):
    await bot.add_cog(VoiceStats(bot))
