import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
import io
import datetime

log = logging.getLogger('Dabot.Privacy')

ALLOWED_EXPORT_TABLES = {
    "users": "user_id",
    "social_profiles": "user_id",
    "birthdays": "user_id",
    "reputation": "user_id",
    "user_achievements": "user_id",
    "guild_levels": "user_id",
    "guild_economy": "user_id",
    "infractions": "user_id",
    "ticket_messages": "author_id",
    "verification_events": "user_id",
    "game_stats": "user_id",
    "notes": "user_id",
    "user_notes": "user_id",
    "afk": "user_id",
    "reminders": "user_id"
}

class ConfirmView(discord.ui.View):
    def __init__(self, timeout=30):
        super().__init__(timeout=timeout)
        self.value = None

    @discord.ui.button(label="Confirmar Solicitud", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        try:
            await interaction.response.defer()
        except discord.NotFound:
            pass

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        try:
            await interaction.response.defer()
        except discord.NotFound:
            pass

class Privacy(commands.Cog):
    """Cog para gestionar los derechos RGPD de los usuarios."""

    def __init__(self, bot):
        self.bot = bot

    privacy_group = app_commands.Group(name="privacy", description="Comandos de privacidad y cumplimiento RGPD / UE")

    async def fetch_table_data(self, table: str, user_id: int) -> list:
        """Helper seguro para consultar datos de una tabla permitida."""
        user_col = ALLOWED_EXPORT_TABLES.get(table)
        if not user_col:
            return []
        try:
            return await self.bot.db.fetch_all(f"SELECT * FROM {table} WHERE {user_col} = ?", user_id)
        except Exception as e:
            log.warning(f"Could not fetch {table} for user {user_id}: {e}")
            return []

    @privacy_group.command(name="mis-datos", description="Exporta todos los datos personales que Dabot tiene sobre ti (Art. 15 RGPD)")
    async def mis_datos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        try:
            data = {"user_id": user_id, "export_date": now_iso}
            summary_counts = {}
            
            # Recopilar todos los datos
            for table in ALLOWED_EXPORT_TABLES:
                records = await self.fetch_table_data(table, user_id)
                data[table] = records
                summary_counts[table] = len(records) if records else 0

            json_data = json.dumps(data, indent=4, default=str)
            file = discord.File(fp=io.BytesIO(json_data.encode("utf-8")), filename="mis_datos_dabot.json")
            
            try:
                await interaction.user.send("📦 **Aquí tienes la copia completa de tus datos personales (Art. 15 RGPD):**", file=file)
                await interaction.followup.send("✅ Tus datos personales han sido recopilados y enviados a tus mensajes directos en formato JSON.", ephemeral=True)
                log.info(f"User {user_id} exported their data via /privacy mis-datos.")
                
                # Registrar solicitud en la base de datos para supervisión del superusuario
                snapshot = json.dumps(summary_counts)
                await self.bot.db.execute(
                    """INSERT INTO privacy_requests 
                       (user_id, user_name, request_type, status, data_snapshot, requested_at, processed_at, admin_notes)
                       VALUES (?, ?, 'export', 'completed', ?, ?, ?, 'Entrega automatizada por MD')""",
                    user_id, str(interaction.user), snapshot, now_iso, now_iso
                )
            except discord.Forbidden:
                await interaction.followup.send("❌ No he podido enviarte los datos. Por favor, asegúrate de tener los mensajes directos abiertos para recibir el archivo de exportación.", ephemeral=True)
                
        except Exception as e:
            log.error(f"Error fetching data for {user_id}: {e}")
            await interaction.followup.send("❌ Ha ocurrido un error al recopilar tus datos. Por favor, contacta con soporte.", ephemeral=True)

    @privacy_group.command(name="borrar-datos", description="Solicita la eliminación formal de tus datos personales (Art. 17 RGPD)")
    async def borrar_datos(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # Comprobar si ya tiene una solicitud pendiente
        pending = await self.bot.db.fetch(
            "SELECT id, requested_at FROM privacy_requests WHERE user_id = ? AND request_type = 'deletion' AND status = 'pending'",
            user_id
        )
        if pending:
            req_id = pending[0] if isinstance(pending, tuple) else pending["id"]
            await interaction.response.send_message(
                f"ℹ️ Ya tienes una solicitud de supresión de datos en curso (Solicitud **#{req_id}**).\n"
                "Está pendiente de revisión y procesamiento por el superadministrador en el panel de control.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🛡️ Solicitud de Supresión de Datos Personales (Art. 17 RGPD)",
            description=(
                "De conformidad con el **Reglamento General de Protección de Datos (RGPD / UE)**, tienes derecho a solicitar la eliminación de tus datos personales.\n\n"
                "**Datos que se eliminarán:**\n"
                "• Perfiles sociales, biografía y enlaces vinculados.\n"
                "• Fecha de cumpleaños.\n"
                "• Logros, estadísticas de juegos y estado AFK.\n"
                "• Recordatorios personales y notas de perfil.\n\n"
                "**Tratamiento de seguridad del sistema (Art. 6.1.f RGPD):**\n"
                "• La dirección IP/huella técnica de verificación quedará disociada y respaldada en un almacén encriptado seguro e irreversible (HMAC-SHA256 con sal) únicamente a efectos de prevención de abusos, multicuentas y seguridad global del bot.\n\n"
                "¿Deseas enviar formalmente la solicitud de eliminación al superadministrador?"
            ),
            color=discord.Color.red()
        )
        
        view = ConfirmView(timeout=45)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()
        
        if view.value is None:
            await interaction.edit_original_response(content="⏳ Se agotó el tiempo para confirmar la solicitud.", embed=None, view=None)
            return
        elif view.value is False:
            await interaction.edit_original_response(content="❌ Solicitud cancelada. No se ha registrado ninguna petición de borrado.", embed=None, view=None)
            return
            
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            req_id = await self.bot.db.execute(
                """INSERT INTO privacy_requests 
                   (user_id, user_name, request_type, status, requested_at, admin_notes)
                   VALUES (?, ?, 'deletion', 'pending', ?, 'Solicitado mediante comando /privacy borrar-datos')""",
                user_id, str(interaction.user), now_iso
            )
            
            await interaction.edit_original_response(
                content=(
                    f"✅ **Solicitud formal de eliminación registrada con éxito (Caso #{req_id})**\n\n"
                    "Tu solicitud ha sido transmitida a la cola de administración de privacidad del superusuario.\n"
                    "Se procesará desde el panel de control garantizando la supresión de tus datos y la preservación encriptada de seguridad según la normativa europea."
                ),
                embed=None,
                view=None
            )
            log.info(f"User {user_id} submitted GDPR deletion request #{req_id}.")
            
            # Avisar al superusuario si está configurado
            super_owner_id = getattr(self.bot, 'super_owner_id', None)
            if super_owner_id:
                try:
                    owner_user = await self.bot.fetch_user(super_owner_id)
                    if owner_user:
                        await owner_user.send(
                            f"🚨 **Nueva Solicitud RGPD de Supresión (Caso #{req_id})**\n"
                            f"👤 **Usuario:** {interaction.user} (`{user_id}`)\n"
                            f"📅 **Fecha:** `{now_iso[:19]}`\n"
                            f"Puedes revisarla y procesarla manualmente desde la pestaña de administración de la dashboard web."
                        )
                except Exception as e:
                    log.warning(f"Could not notify super_owner of GDPR request: {e}")
                    
        except Exception as e:
            log.error(f"Error registering deletion request for {user_id}: {e}")
            await interaction.edit_original_response(
                content="❌ Ha ocurrido un error al tramitar tu solicitud. Por favor contacta directamente con el soporte.",
                embed=None,
                view=None
            )

    @privacy_group.command(name="estado", description="Consulta el estado de tus solicitudes de datos y derechos RGPD")
    async def estado(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        requests = await self.bot.db.fetch_all(
            "SELECT id, request_type, status, requested_at, processed_at FROM privacy_requests WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            user_id
        )
        
        if not requests:
            await interaction.response.send_message("ℹ️ No tienes ninguna solicitud de datos o privacidad registrada.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Historial de Solicitudes RGPD", color=discord.Color.blue())
        for req in requests:
            rid = req[0] if isinstance(req, tuple) else req["id"]
            rtype = req[1] if isinstance(req, tuple) else req["request_type"]
            status = req[2] if isinstance(req, tuple) else req["status"]
            req_at = str(req[3] if isinstance(req, tuple) else req["requested_at"])[:16]
            
            status_map = {
                "pending": "⏳ Pendiente de revisión",
                "completed": "✅ Completada",
                "approved": "✅ Aprobada y Ejecutada",
                "rejected": "❌ Denegada"
            }
            type_map = {
                "export": "Exportación de datos (Art. 15)",
                "deletion": "Supresión / Derecho al Olvido (Art. 17)"
            }
            embed.add_field(
                name=f"Caso #{rid} · {type_map.get(rtype, rtype)}",
                value=f"• **Estado:** {status_map.get(status, status)}\n• **Fecha:** `{req_at}`",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @privacy_group.command(name="info", description="Muestra información sobre la política de privacidad y protección de datos")
    async def info(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔒 Privacidad y Protección de Datos (RGPD / UE)",
            description="En Dabot nos tomamos muy en serio tu privacidad. Cumplimos rigurosamente con el Reglamento General de Protección de Datos (RGPD).",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="¿Qué datos guardamos y por qué?",
            value="- **Datos operativos y seguridad:** Niveles, economía, infracciones, tickets y registros de moderación (necesarios para el servicio).\n"
                  "- **Datos opcionales:** Perfiles sociales, cumpleaños, estado AFK, estadísticas de juego (voluntarios).",
            inline=False
        )
        embed.add_field(
            name="Tus derechos (Art. 15-17 RGPD)",
            value="- Solicitar exportación completa de tus datos: `/privacy mis-datos`.\n"
                  "- Solicitar supresión formal de datos personales: `/privacy borrar-datos`.\n"
                  "- Consultar el estado de tus peticiones: `/privacy estado`.",
            inline=False
        )
        embed.add_field(
            name="Política de Privacidad Web",
            value="Puedes consultar la política íntegra en la web: [Política de Privacidad de Dabot](https://dabot.davito.es/privacy).",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Privacy(bot))
