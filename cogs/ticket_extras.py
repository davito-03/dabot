import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from datetime import datetime
import asyncio

log = logging.getLogger('Dabot.TicketExtras')

class CSATModal(discord.ui.Modal, title="Opinión sobre la atención"):
    comment = discord.ui.TextInput(
        label="Comentarios o sugerencias",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    def __init__(self, bot, ticket_id: int, rating: int, staff_id: int, staff_name: str, original_message: discord.Message):
        super().__init__()
        self.bot = bot
        self.ticket_id = ticket_id
        self.rating = rating
        self.staff_id = staff_id
        self.staff_name = staff_name
        self.original_message = original_message
        self.comment.label = f"¿Qué te pareció la atención de {staff_name}?"[:45]

    async def on_submit(self, interaction: discord.Interaction):
        comment_text = self.comment.value
        # Resolve guild_id from tickets table since DM interactions have interaction.guild_id == None
        row_guild = await self.bot.db.fetch("SELECT guild_id FROM tickets WHERE id = ?", self.ticket_id)
        guild_id = row_guild[0] if row_guild else (interaction.guild_id or 0)

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO ticket_ratings (ticket_id, guild_id, user_id, staff_id, staff_name, rating, comment, rated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            self.ticket_id, guild_id, interaction.user.id, self.staff_id, self.staff_name, self.rating, comment_text, datetime.utcnow().isoformat()
        )
        await interaction.response.send_message(f"✅ ¡Muchas gracias! Tu reseña sobre la atención de **{self.staff_name}** ha sido registrada.", ephemeral=True)
        
        view = discord.ui.View()
        for comp in self.original_message.components:
            for child in comp.children:
                btn = discord.ui.Button(
                    style=discord.ButtonStyle(child.style),
                    label=child.label,
                    custom_id=child.custom_id,
                    disabled=True
                )
                view.add_item(btn)
        try:
            await self.original_message.edit(view=view)
        except Exception:
            pass

        try:
            if guild_id:
                config = self.bot.config.get(guild_id) or {}
                log_channel_id = config.get('tickets', {}).get('log_channel')
                if log_channel_id:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        log_channel = guild.get_channel(log_channel_id)
                        if log_channel:
                            embed = discord.Embed(
                                title="🌟 Nueva Reseña de Ticket",
                                color=discord.Color.gold()
                            )
                            embed.add_field(name="Ticket ID", value=str(self.ticket_id))
                            embed.add_field(name="Staff", value=self.staff_name)
                            embed.add_field(name="Valoración", value=f"{'⭐' * self.rating} ({self.rating}/5)")
                            if comment_text:
                                embed.add_field(name="Comentario", value=comment_text, inline=False)
                            await log_channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging review: {e}")

class CSATView(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        for i in range(1, 6):
            self.add_item(discord.ui.Button(
                label=f"⭐ {i}",
                custom_id=f"dabot:csat:{ticket_id}:{i}",
                style=discord.ButtonStyle.secondary
            ))

class TicketExtras(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._reminded_tickets = set()

    async def cog_load(self):
        self.sla_check_loop.start()
        for stmt in [
            "ALTER TABLE ticket_ratings ADD COLUMN staff_id INTEGER",
            "ALTER TABLE ticket_ratings ADD COLUMN staff_name TEXT",
            "ALTER TABLE ticket_ratings ADD COLUMN comment TEXT"
        ]:
            try:
                await self.bot.db.execute(stmt)
            except Exception:
                pass

    def cog_unload(self):
        self.sla_check_loop.cancel()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("dabot:csat:"):
            parts = custom_id.split(":")
            if len(parts) == 4:
                ticket_id = int(parts[2])
                rating = int(parts[3])
                
                row = await self.bot.db.fetch(
                    "SELECT claimed_by, claimed_name, closed_by, closed_name FROM tickets WHERE id = ?",
                    ticket_id
                )
                if row:
                    claimed_by, claimed_name, closed_by, closed_name = row
                    staff_id = claimed_by or closed_by
                    staff_name = claimed_name or closed_name or 'Equipo de Soporte'
                else:
                    staff_id = None
                    staff_name = 'Equipo de Soporte'
                
                modal = CSATModal(self.bot, ticket_id, rating, staff_id, staff_name, interaction.message)
                await interaction.response.send_modal(modal)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not isinstance(channel, discord.TextChannel):
            return
        if not channel.name.startswith("ticket-"):
            return
            
        await asyncio.sleep(2.0)
        
        row = await self.bot.db.fetch(
            "SELECT id, opener_id, claimed_by, claimed_name, closed_by, closed_name FROM tickets WHERE channel_id = ? AND status = 'closed' ORDER BY closed_at DESC LIMIT 1",
            channel.id
        )
        if row:
            ticket_id, user_id, claimed_by, claimed_name, closed_by, closed_name = row
            guild = channel.guild
            user = guild.get_member(user_id) or self.bot.get_user(user_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(user_id)
                except Exception:
                    pass
            
            if user:
                staff_name = claimed_name or closed_name or 'Equipo de Soporte'
                embed = discord.Embed(
                    title=f"🌟 Valoración de Soporte · {guild.name}",
                    description=f"Hola {user.display_name}, tu ticket ha sido finalizado.\n👤 **Atendido por:** {staff_name}\nPor favor califica la atención recibida:",
                    color=discord.Color.blue()
                )
                try:
                    view = CSATView(ticket_id)
                    await user.send(embed=embed, view=view)
                except discord.Forbidden:
                    pass

    @tasks.loop(minutes=15)
    async def sla_check_loop(self):
        try:
            now = datetime.utcnow()
            # Fetch from active_tickets as requested by context, joining with tickets for opener_id and created_at
            rows = await self.bot.db.fetch_all(
                "SELECT t.channel_id, t.guild_id, t.created_at, t.id, t.opener_id "
                "FROM tickets t JOIN active_tickets a ON t.id = a.ticket_id "
                "WHERE t.status = 'open'"
            )
            
            for row in rows:
                channel_id, guild_id, created_at_str, ticket_id, opener_id = row
                
                if ticket_id in self._reminded_tickets:
                    continue
                    
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                except Exception:
                    continue
                    
                if (now - created_at).total_seconds() > 7200:
                    messages = await self.bot.db.fetch_all(
                        "SELECT user_id FROM ticket_messages WHERE ticket_id = ?", ticket_id
                    )
                    has_staff_response = False
                    for (m_user_id,) in messages:
                        if m_user_id != opener_id and m_user_id != self.bot.user.id:
                            has_staff_response = True
                            break
                            
                    if not has_staff_response:
                        config = self.bot.config.get(guild_id) or {}
                        log_channel_id = config.get('tickets', {}).get('log_channel')
                        if log_channel_id:
                            guild = self.bot.get_guild(guild_id)
                            if guild:
                                log_channel = guild.get_channel(log_channel_id)
                                if log_channel:
                                    embed = discord.Embed(
                                        title="⚠️ Ticket sin respuesta",
                                        description=f"El ticket <#{channel_id}> lleva abierto más de 2 horas sin respuesta del staff.",
                                        color=discord.Color.yellow()
                                    )
                                    await log_channel.send(embed=embed)
                        
                        self._reminded_tickets.add(ticket_id)
                        
        except Exception as e:
            log.error(f"Error in sla_check_loop: {e}")

    @sla_check_loop.before_loop
    async def before_sla_check_loop(self):
        await self.bot.wait_until_ready()

    snippet_group = app_commands.Group(name="snippet", description="Gestión de respuestas rápidas para tickets")

    @snippet_group.command(name="add", description="Añade un snippet")
    @app_commands.default_permissions(manage_guild=True)
    async def snippet_add(self, interaction: discord.Interaction, name: str, content: str):
        try:
            await self.bot.db.execute(
                "INSERT INTO ticket_snippets (guild_id, name, content, created_by) VALUES (?, ?, ?, ?)",
                interaction.guild_id, name, content, interaction.user.id
            )
            await interaction.response.send_message(f"Snippet `{name}` añadido.", ephemeral=True)
        except Exception:
            await interaction.response.send_message(f"Error: Es posible que el snippet `{name}` ya exista.", ephemeral=True)

    @snippet_group.command(name="remove", description="Elimina un snippet")
    @app_commands.default_permissions(manage_guild=True)
    async def snippet_remove(self, interaction: discord.Interaction, name: str):
        await self.bot.db.execute(
            "DELETE FROM ticket_snippets WHERE guild_id = ? AND name = ?",
            interaction.guild_id, name
        )
        await interaction.response.send_message(f"Snippet `{name}` eliminado.", ephemeral=True)

    @snippet_group.command(name="list", description="Lista todos los snippets")
    async def snippet_list(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetch_all(
            "SELECT name FROM ticket_snippets WHERE guild_id = ?",
            interaction.guild_id
        )
        if not rows:
            await interaction.response.send_message("No hay snippets configurados.", ephemeral=True)
            return
        names = ", ".join([r[0] for r in rows])
        await interaction.response.send_message(f"Snippets: {names}", ephemeral=True)

    @snippet_group.command(name="use", description="Usa un snippet")
    async def snippet_use(self, interaction: discord.Interaction, name: str):
        row = await self.bot.db.fetch(
            "SELECT content FROM ticket_snippets WHERE guild_id = ? AND name = ?",
            interaction.guild_id, name
        )
        if not row:
            await interaction.response.send_message("Snippet no encontrado.", ephemeral=True)
            return
            
        await self.bot.db.execute(
            "UPDATE ticket_snippets SET usage_count = usage_count + 1 WHERE guild_id = ? AND name = ?",
            interaction.guild_id, name
        )
        
        await interaction.response.send_message(row[0])

    @snippet_use.autocomplete("name")
    async def snippet_use_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await self.bot.db.fetch_all(
            "SELECT name FROM ticket_snippets WHERE guild_id = ? AND name LIKE ? LIMIT 25",
            interaction.guild_id, f"%{current}%"
        )
        return [app_commands.Choice(name=r[0], value=r[0]) for r in rows]

    @commands.command(name="snippet")
    async def snippet_prefix(self, ctx, name: str):
        row = await self.bot.db.fetch(
            "SELECT content FROM ticket_snippets WHERE guild_id = ? AND name = ?",
            ctx.guild.id, name
        )
        if not row:
            return
            
        await self.bot.db.execute(
            "UPDATE ticket_snippets SET usage_count = usage_count + 1 WHERE guild_id = ? AND name = ?",
            ctx.guild.id, name
        )
        
        await ctx.send(row[0])

    async def ticket_stats(self, interaction: discord.Interaction):
        row = await self.bot.db.fetch(
            "SELECT AVG(rating), COUNT(rating) FROM ticket_ratings WHERE guild_id = ?",
            interaction.guild_id
        )
        avg_rating = row[0] or 0.0
        count = row[1] or 0
        
        embed = discord.Embed(
            title="Estadísticas de Tickets",
            description=f"Valoración media: {avg_rating:.2f} ⭐\nTotal de valoraciones: {count}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    async def staff_ratings(self, interaction: discord.Interaction, staff_member: discord.Member = None):
        if staff_member:
            rows = await self.bot.db.fetch_all(
                "SELECT rating, comment FROM ticket_ratings WHERE guild_id = ? AND staff_id = ? ORDER BY rated_at DESC",
                interaction.guild_id, staff_member.id
            )
            if not rows:
                await interaction.response.send_message(f"No hay reseñas para {staff_member.display_name}.", ephemeral=True)
                return
            
            total_ratings = len(rows)
            avg_rating = sum(r[0] for r in rows) / total_ratings
            
            embed = discord.Embed(
                title=f"Estadísticas de {staff_member.display_name}",
                description=f"**Valoración Media:** ⭐ {avg_rating:.1f} / 5.0\n**Total Reseñas:** {total_ratings}",
                color=discord.Color.gold()
            )
            
            comments = [r for r in rows if r[1]]
            if comments:
                comments_text = ""
                for r in comments[:3]:
                    rating, comment = r
                    comments_text += f"{'⭐' * rating} - {comment}\n\n"
                embed.add_field(name="Últimos Comentarios", value=comments_text, inline=False)
            
            await interaction.response.send_message(embed=embed)
        else:
            rows = await self.bot.db.fetch_all(
                "SELECT staff_id, staff_name, AVG(rating), COUNT(rating) FROM ticket_ratings WHERE guild_id = ? AND staff_id IS NOT NULL GROUP BY staff_id ORDER BY AVG(rating) DESC, COUNT(rating) DESC LIMIT 10",
                interaction.guild_id
            )
            if not rows:
                await interaction.response.send_message("No hay reseñas de staff registradas.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Staff CSAT Leaderboard",
                description="Ranking de miembros del staff por valoración media:",
                color=discord.Color.gold()
            )
            
            for rank, row in enumerate(rows, 1):
                staff_id, staff_name, avg_rating, count = row
                embed.add_field(
                    name=f"#{rank} {staff_name}",
                    value=f"⭐ {avg_rating:.1f} / 5.0 ({count} tickets)",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(TicketExtras(bot))
