import logging
import re
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import time
import datetime
from datetime import timedelta, timezone as dt_timezone

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

TZ_ALIASES = {
    "spain": "Europe/Madrid", "españa": "Europe/Madrid", "madrid": "Europe/Madrid",
    "barcelona": "Europe/Madrid", "valencia": "Europe/Madrid",
    "mexico": "America/Mexico_City", "cdmx": "America/Mexico_City", "mexico city": "America/Mexico_City",
    "argentina": "America/Argentina/Buenos_Aires", "buenos aires": "America/Argentina/Buenos_Aires",
    "colombia": "America/Bogota", "bogota": "America/Bogota",
    "chile": "America/Santiago", "santiago": "America/Santiago",
    "peru": "America/Lima", "lima": "America/Lima",
    "venezuela": "America/Caracas", "caracas": "America/Caracas",
    "usa": "America/New_York", "ny": "America/New_York", "new york": "America/New_York",
    "la": "America/Los_Angeles", "los angeles": "America/Los_Angeles",
    "uk": "Europe/London", "london": "Europe/London",
    "france": "Europe/Paris", "paris": "Europe/Paris",
    "germany": "Europe/Berlin", "berlin": "Europe/Berlin",
    "utc": "UTC",
}


def resolve_tz(raw: str | None) -> str:
    text = (raw or "Europe/Madrid").strip()
    if not text:
        return "Europe/Madrid"
    alias = TZ_ALIASES.get(text.lower())
    if alias:
        return alias
    if re.match(r"^UTC[+-]\d{1,2}(:\d{2})?$", text, re.I):
        return text.upper()
    if ZoneInfo:
        try:
            ZoneInfo(text)
            return text
        except Exception:
            pass
    return "Europe/Madrid"


def now_in_tz(tz_name: str) -> datetime.datetime:
    tz_name = resolve_tz(tz_name)
    m = re.match(r"^UTC([+-])(\d{1,2})(?::(\d{2}))?$", tz_name, re.I)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        hours = int(m.group(2))
        mins = int(m.group(3) or 0)
        tz = dt_timezone(sign * timedelta(hours=hours, minutes=mins))
        return datetime.datetime.now(tz)
    if ZoneInfo:
        try:
            return datetime.datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.datetime.utcnow().replace(tzinfo=dt_timezone.utc)

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')
        self.message_buffer = {}  # (guild_id, user_id, date) -> count
        self.emoji_buffer = {}    # (guild_id, emoji_str) -> count
        self.channel_last_edit = {} # channel_id -> float timestamp
        self.update_stats_loop.start()
        self.daily_newsletter_loop.start()
        self.flush_stats_buffer_loop.start()

    @commands.hybrid_group(name="stats", description="📊 Server and user statistics.")
    async def stats_group(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="📊 Statistics Commands", description=(
                "`/stats server` — Crecimiento del servidor\n"
                "`/stats emoji` — Emojis más usados\n"
                "`/stats activity [user]` — Actividad de un usuario\n"
                "`/stats invites` — Ranking de invitaciones\n"
                "`/stats setup` — Canal de estadísticas en vivo\n"
                "`/stats remove` — Quitar canal de stats"
            ), color=discord.Color.blue())
            await ctx.send(embed=embed)

    def cog_unload(self):
        self.update_stats_loop.cancel()
        self.daily_newsletter_loop.cancel()
        self.flush_stats_buffer_loop.cancel()

    @tasks.loop(minutes=10)
    async def update_stats_loop(self):
        """Update all stat channels."""
        channels = await self.bot.db.fetch_all("SELECT channel_id, guild_id, type, format FROM stats_channels")
        
        for channel_id, guild_id, stat_type, fmt in channels:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                # Cleanup if channel deleted
                await self.bot.db.execute("DELETE FROM stats_channels WHERE channel_id = ?", channel_id)
                continue

            tz = "UTC"
            try:
                row = await self.bot.db.fetch("SELECT timezone FROM stats_channels WHERE channel_id = ?", channel_id)
                if row and row[0]:
                    tz = row[0]
            except Exception:
                pass
            new_name = self.get_stat_value(guild, stat_type, fmt, tz)
            if new_name and channel.name != new_name:
                # Discord allows at most 2 channel name edits per 10 minutes (600s)
                last_edit = self.channel_last_edit.get(channel_id, 0)
                if time.time() - last_edit >= 320:
                    try:
                        await channel.edit(name=new_name)
                        self.channel_last_edit[channel_id] = time.time()
                    except discord.errors.RateLimited:
                        self.logger.warning(f"Stat channel {channel_id} hit rate limit, waiting.")
                    except Exception as e:
                        self.logger.error(f"Failed to update stat channel {channel_id}: {e}")
            
            # Sleep to avoid burst calls
            await asyncio.sleep(2)

    @update_stats_loop.before_loop
    async def before_update_stats(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)

    def get_stat_value(self, guild, stat_type, fmt, tz_name="UTC"):
        if stat_type == 'members':
            count = len(guild.members)
            return fmt.format(count=count)
        elif stat_type == 'bots':
            count = len([m for m in guild.members if m.bot])
            return fmt.format(count=count)
        elif stat_type == 'humans':
            count = len([m for m in guild.members if not m.bot])
            return fmt.format(count=count)
        elif stat_type in ('time', 'date'):
            now = now_in_tz(tz_name)
            try:
                return now.strftime(fmt)
            except Exception:
                return now.strftime("%H:%M" if stat_type == "time" else "%d %b %Y")
        return None

    @stats_group.command(name="setup", description="Create a live stats voice channel with presets and timezone.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        stat_type="Qué mostrar",
        timezone="Ciudad/país (Spain, Mexico, Madrid) o IANA/manual (Europe/Madrid, UTC+1)",
    )
    @app_commands.choices(stat_type=[
        app_commands.Choice(name="👥 Miembros", value="members"),
        app_commands.Choice(name="👤 Humanos", value="humans"),
        app_commands.Choice(name="🤖 Bots", value="bots"),
        app_commands.Choice(name="🕒 Hora", value="time"),
        app_commands.Choice(name="📅 Fecha", value="date"),
    ])
    async def setup(self, ctx, stat_type: str, timezone: str = "Europe/Madrid"):
        stat_type = (stat_type.value if hasattr(stat_type, "value") else stat_type).lower()
        tz_name = resolve_tz(timezone)
        valid_types = {
            'members': "👥 Members: {count}",
            'bots': "🤖 Bots: {count}",
            'humans': "👤 Humans: {count}",
            'time': "🕒 %H:%M",
            'date': "📅 %d %b %Y"
        }
        if stat_type not in valid_types:
            await ctx.send("❌ Tipo inválido. Elige members, bots, humans, time o date.")
            return
        try:
            await self.bot.db.execute("ALTER TABLE stats_channels ADD COLUMN timezone TEXT")
        except Exception:
            pass
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(connect=False)
        }
        try:
            channel = await ctx.guild.create_voice_channel(
                name="Stats Loading...",
                overwrites=overwrites,
                reason="Dabot stats channel"
            )
            fmt = valid_types[stat_type]
            await self.bot.db.execute(
                "INSERT INTO stats_channels (channel_id, guild_id, type, format, timezone) VALUES (?, ?, ?, ?, ?)",
                channel.id, ctx.guild.id, stat_type, fmt, tz_name
            )
            new_name = self.get_stat_value(ctx.guild, stat_type, fmt, tz_name)
            await channel.edit(name=new_name, reason="Dabot stats")
            await ctx.send(f"✅ Canal de stats: {channel.mention} · zona `{tz_name}`")
        except Exception as e:
            await ctx.send(f"❌ Error creating channel: {e}")

    @stats_group.command(name="remove", description="Remove a live stats voice channel.")
    @commands.has_permissions(administrator=True)
    async def remove(self, ctx, channel: discord.VoiceChannel):
        """Remove a stat channel."""
        # Check if it was a stat channel
        exists = await self.bot.db.fetch("SELECT channel_id FROM stats_channels WHERE channel_id = ?", channel.id)
        if not exists:
            await ctx.send("❌ That is not a tracked stat channel.")
            return

        await self.bot.db.execute("DELETE FROM stats_channels WHERE channel_id = ?", channel.id)
        try:
            await channel.delete()
            await ctx.send("✅ Deleted stat channel.")
        except Exception as e:
            await ctx.send(f"✅ Stopped tracking stat channel (error: {e}).")

    @stats_group.command(name="server", description="View server growth statistics.")
    async def stats_server(self, ctx):
        """Generates a graph of server member growth."""
        await ctx.defer()
        
        try:
            import matplotlib.pyplot as plt
            import io
            
            # Gather join dates
            dates = [m.joined_at for m in ctx.guild.members]
            dates.sort()
            
            # Create data points (cumulative count)
            x_values = []
            y_values = []
            count = 0
            
            for date in dates:
                count += 1
                x_values.append(date)
                y_values.append(count)
            
            # Plot
            plt.figure(figsize=(10, 6))
            plt.style.use('dark_background')
            plt.plot(x_values, y_values, color='#00ffcc', linewidth=2)
            plt.fill_between(x_values, y_values, color='#00ffcc', alpha=0.1)
            
            plt.title(f"Member Growth - {ctx.guild.name}")
            plt.xlabel("Date")
            plt.ylabel("Members")
            plt.grid(True, linestyle='--', alpha=0.3)
            
            # Save to buffer
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png')
            buffer.seek(0)
            plt.close()
            
            file = discord.File(buffer, filename="growth.png")
            embed = discord.Embed(title=f"📈 Server Statistics: {ctx.guild.name}", color=discord.Color.teal())
            embed.set_image(url="attachment://growth.png")
            embed.add_field(name="Total Members", value=str(len(ctx.guild.members)), inline=True)
            embed.add_field(name="Total Bots", value=str(len([m for m in ctx.guild.members if m.bot])), inline=True)
            embed.add_field(name="Created At", value=ctx.guild.created_at.strftime("%Y-%m-%d"), inline=True)
            
            await ctx.send(embed=embed, file=file)
            
        except ImportError:
            await ctx.send("❌ Advanced stats are not available (matplotlib not installed).")
        except Exception as e:
            await ctx.send(f"❌ Error generating stats: {e}")

    @stats_group.command(name="emoji", description="View the most used emojis in this server.")
    async def stats_emoji(self, ctx):
        """Show top 10 server emojis by reaction count."""
        await ctx.defer()
        try:
            rows = await self.bot.db.fetch_all(
                "SELECT emoji, SUM(count) as total FROM emoji_usage WHERE guild_id = ? GROUP BY emoji ORDER BY total DESC LIMIT 10",
                ctx.guild.id
            )
        except Exception:
            rows = []

        if not rows:
            await ctx.send("📊 No emoji data yet — reactions will be tracked from now on!")
            return

        embed = discord.Embed(title="📊 Top Emojis", color=discord.Color.blurple())
        lines = []
        for i, (emoji, count) in enumerate(rows, 1):
            lines.append(f"**{i}.** {emoji}  —  {count} uses")
        embed.description = "\n".join(lines)
        embed.set_footer(text=ctx.guild.name)
        await ctx.send(embed=embed)

    @stats_group.command(name="activity", description="View message activity for a user this week.")
    async def stats_activity(self, ctx, member: discord.Member = None):
        """Show how many messages a user has sent this week."""
        await ctx.defer()
        member = member or ctx.author
        try:
            # Get last 7 days
            since = (datetime.datetime.now() - datetime.timedelta(days=7)).date().isoformat()
            rows = await self.bot.db.fetch_all(
                "SELECT date, count FROM message_activity WHERE guild_id = ? AND user_id = ? AND date >= ? ORDER BY date",
                ctx.guild.id, member.id, since
            )
        except Exception:
            rows = []

        total = sum(r[1] for r in rows) if rows else 0

        # Generate chart if we have rows
        file_to_send = None
        if rows:
            try:
                from utils.images import create_activity_chart
                chart_data = [(r[0], r[1]) for r in rows]
                chart_buffer = await create_activity_chart(chart_data, f"Actividad Semanal: {member.display_name}")
                if chart_buffer:
                    file_to_send = discord.File(chart_buffer, filename="activity_chart.png")
            except Exception as e:
                self.logger.error(f"Failed to generate stats activity chart: {e}")

        embed = discord.Embed(
            title=f"📈 Activity — {member.display_name}",
            color=discord.Color.teal()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Messages this week", value=str(total), inline=True)

        if rows:
            daily = "\n".join(f"`{r[0]}` — **{r[1]}** msgs" for r in rows[-7:])
            embed.add_field(name="Daily breakdown", value=daily, inline=False)
            if file_to_send:
                embed.set_image(url="attachment://activity_chart.png")
        else:
            embed.add_field(name="Note", value="No data yet — activity is tracked from now on.", inline=False)

        if file_to_send:
            await ctx.send(embed=embed, file=file_to_send)
        else:
            await ctx.send(embed=embed)

    @stats_group.command(name="invites", description="View the invite leaderboard for this server.")
    async def stats_invites(self, ctx):
        """Show the server's top inviters."""
        await ctx.defer()
        try:
            top_inviters = await self.bot.db.fetch_all(
                """SELECT inviter_id, COUNT(*) as invite_count 
                   FROM invite_tracker 
                   WHERE guild_id = ? 
                   GROUP BY inviter_id 
                   ORDER BY invite_count DESC 
                   LIMIT 10""",
                ctx.guild.id
            )
        except Exception as e:
            self.logger.error(f"Error querying top inviters: {e}")
            await ctx.send("❌ Error al consultar el ranking de invitaciones.")
            return

        embed = discord.Embed(title=f"🏆 Ranking de Invitaciones — {ctx.guild.name}", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        
        if top_inviters:
            description_lines = []
            for rank, (inviter_id, count) in enumerate(top_inviters, start=1):
                member = ctx.guild.get_member(inviter_id)
                member_name = member.mention if member else f"Usuario fuera del servidor (`{inviter_id}`)"
                description_lines.append(f"**#{rank}** {member_name} — **{count}** invitaciones")
            embed.description = "\n".join(description_lines)
        else:
            embed.description = "No hay registros de invitaciones en este servidor todavía."
            
        await ctx.send(embed=embed)

    # ── Listeners for tracking ──────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        today = datetime.date.today().isoformat()
        key = (message.guild.id, message.author.id, today)
        self.message_buffer[key] = self.message_buffer.get(key, 0) + 1

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or not reaction.message.guild:
            return
        emoji_str = str(reaction.emoji)
        key = (reaction.message.guild.id, emoji_str)
        self.emoji_buffer[key] = self.emoji_buffer.get(key, 0) + 1

    # ── Buffered Stats Flush Loop ───────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def flush_stats_buffer_loop(self):
        """Flush the buffered stats to the SQLite database in bulk."""
        if self.message_buffer:
            temp_msg = self.message_buffer.copy()
            self.message_buffer.clear()
            
            for (guild_id, user_id, date), count in temp_msg.items():
                try:
                    await self.bot.db.execute("""
                        INSERT INTO message_activity (guild_id, user_id, date, count)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(guild_id, user_id, date) DO UPDATE SET count = count + excluded.count
                    """, guild_id, user_id, date, count)
                except Exception as e:
                    self.logger.error(f"Failed to flush message stats: {e}")

        if self.emoji_buffer:
            temp_emoji = self.emoji_buffer.copy()
            self.emoji_buffer.clear()
            
            for (guild_id, emoji_str), count in temp_emoji.items():
                try:
                    await self.bot.db.execute("""
                        INSERT INTO emoji_usage (guild_id, emoji, count)
                        VALUES (?, ?, ?)
                        ON CONFLICT(guild_id, emoji) DO UPDATE SET count = count + excluded.count
                    """, guild_id, emoji_str, count)
                except Exception as e:
                    self.logger.error(f"Failed to flush emoji stats: {e}")

    @flush_stats_buffer_loop.before_loop
    async def before_flush_stats(self):
        await self.bot.wait_until_ready()

    # ── AI Server Daily Newsletter ──────────────────────────────────────────

    async def generate_ai_newsletter(self, guild):
        """Fetch server stats and generate an AI newspaper edition."""
        today = datetime.date.today().isoformat()
        
        # 1. Fetch top chatters of today
        try:
            chatters = await self.bot.db.fetch_all(
                "SELECT user_id, count FROM message_activity WHERE guild_id = ? AND date = ? ORDER BY count DESC LIMIT 5",
                guild.id, today
            )
        except Exception:
            chatters = []
            
        chatters_list = []
        for uid, count in chatters:
            member = guild.get_member(uid)
            name = member.display_name if member else f"Usuario ({uid})"
            chatters_list.append(f"• **{name}**: {count} mensajes")
        chatters_str = "\n".join(chatters_list) if chatters_list else "Ninguna actividad registrada aún."

        # 2. Fetch top emojis of today
        try:
            emojis = await self.bot.db.fetch_all(
                "SELECT emoji, count FROM emoji_usage WHERE guild_id = ? ORDER BY count DESC LIMIT 5",
                guild.id
            )
        except Exception:
            emojis = []
            
        emojis_list = []
        for emo, count in emojis:
            emojis_list.append(f"{emo} ({count} usos)")
        emojis_str = ", ".join(emojis_list) if emojis_list else "Ningún emoji usado todavía."

        # 3. Call AI engine
        chatbot = self.bot.get_cog('Chatbot')
        if not chatbot or not hasattr(chatbot, 'ai'):
            return None, "Servicio de IA no disponible (Chatbot no cargado)."
            
        prompt = (
            f"You are the senior chief editor of the official daily newspaper/newsletter for the Discord server '{guild.name}'. "
            f"Create a highly engaging, creative, and humorous daily newsletter summary based on today's server activity stats:\n\n"
            f"- **Total server members**: {len(guild.members)}\n"
            f"- **Active chatters today (Top 5)**:\n{chatters_str}\n"
            f"- **Most used emojis**: {emojis_str}\n\n"
            f"Write the newsletter in Spanish. Make it sound like a premium, witty, and slightly satirical newspaper edition. "
            f"Include a catchy headline, a short 'editorial/weather report' of the chat temperature, a gossip section highlighting the top chatter, "
            f"and a funny horoscope or prediction. Format with beautiful headers, bullet points, and high-impact emojis. "
            f"Keep the formatting clean and stylish."
        )

        try:
            msgs = [{"role": "user", "content": prompt}]
            response, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False)
            return response, None
        except Exception as e:
            return None, str(e)

    @stats_group.command(name="newsletter", description="📰 Manual trigger to generate the AI Daily Server Newsletter (Admin only).")
    @commands.has_permissions(administrator=True)
    async def newsletter_generate(self, ctx):
        await ctx.defer()
        content, error = await self.generate_ai_newsletter(ctx.guild)
        
        if error:
            await ctx.send(f"❌ Error al generar el boletín: {error}")
            return
            
        embed = discord.Embed(
            title=f"📰 Boletín Diario — {ctx.guild.name}",
            description=content[:4000],
            color=discord.Color.from_rgb(253, 150, 68),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Redactado por Dabot AI Newspaper • Edición Especial")
        await ctx.send(embed=embed)

    @tasks.loop(hours=24)
    async def daily_newsletter_loop(self):
        """Background loop that automatically posts the newsletter in a '#newsletter' or '#boletin' channel."""
        for guild in self.bot.guilds:
            # Look for newsletter channel
            channel = None
            for c in guild.text_channels:
                if c.name.lower() in ("newsletter", "boletin", "boletín", "novedades"):
                    channel = c
                    break
            
            if not channel:
                continue
                
            try:
                content, error = await self.generate_ai_newsletter(guild)
                if not error and content:
                    embed = discord.Embed(
                        title=f"📰 Boletín Diario — {guild.name}",
                        description=content[:4000],
                        color=discord.Color.from_rgb(253, 150, 68),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Redactado por Dabot AI Newspaper • Edición Oficial")
                    await channel.send(embed=embed)
            except Exception as e:
                self.logger.error(f"Failed auto daily newsletter for {guild.name}: {e}")

    @daily_newsletter_loop.before_loop
    async def before_daily_newsletter(self):
        await self.bot.wait_until_ready()
        # Sleep for a bit to avoid executing immediately at startup
        await asyncio.sleep(60)

async def setup(bot):
    await bot.add_cog(Stats(bot))
