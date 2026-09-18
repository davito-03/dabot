import logging
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands
from discord import app_commands

from utils.gemini_client import generate_text
from utils.premium import deny_text
from utils.helpers import guild_lang

log = logging.getLogger("Dabot.Recap")


class Recap(commands.Cog):
    """Cog para generar resúmenes inteligentes de conversaciones en canales usando IA."""

    def __init__(self, bot):
        self.bot = bot

    async def _generate_summary_ai(self, prompt: str, is_premium: bool = True) -> str | None:
        """Query AI using Chatbot cog swarm with fallback to gemini_client."""
        # 1. Try Chatbot AI engine
        chatbot = self.bot.get_cog("Chatbot")
        if chatbot and hasattr(chatbot, "ai"):
            try:
                msgs = [{"role": "user", "content": prompt}]
                res, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False, is_premium=is_premium)
                if res and res.strip():
                    return res.strip()
            except Exception as e:
                log.warning(f"Chatbot swarm generation error: {e}")

        # 2. Fallback to Gemini rotation client
        try:
            res = await generate_text(prompt, timeout=18)
            if res and res.strip():
                return res.strip()
        except Exception as e:
            log.error(f"Gemini rotation client error: {e}")

        return None

    async def _run_summary(
        self,
        interaction: discord.Interaction,
        horas: int | None = 2,
        mensajes: int = 60,
        privado: bool = False,
    ):
        guild = interaction.guild
        channel = interaction.channel

        if not guild or not channel:
            await interaction.response.send_message("❌ Este comando solo se puede usar en un servidor.", ephemeral=True)
            return

        # Check permissions
        if hasattr(channel, "permissions_for"):
            perms = channel.permissions_for(interaction.user)
            if not perms.read_message_history:
                await interaction.response.send_message("❌ Necesitas permiso para ver el historial de este canal.", ephemeral=True)
                return

        # Check premium status
        if not await self.bot.db.is_guild_premium(guild.id, self.bot):
            await interaction.response.send_message(deny_text(guild_lang(self.bot, guild.id)), ephemeral=True)
            return

        mensajes = max(10, min(200, mensajes))
        if horas is not None:
            horas = max(1, min(48, horas))

        await interaction.response.defer(ephemeral=privado)

        valid_messages = []
        prefixes = ("!", "/", "-", "?", "$", ".")

        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=horas)) if horas else None

            if cutoff:
                async for msg in channel.history(limit=mensajes, after=cutoff):
                    if not msg.content or msg.author.bot or msg.content.startswith(prefixes):
                        continue
                    valid_messages.append(f"[{msg.author.display_name}]: {msg.content.strip()[:200]}")
            else:
                async for msg in channel.history(limit=mensajes):
                    if not msg.content or msg.author.bot or msg.content.startswith(prefixes):
                        continue
                    valid_messages.append(f"[{msg.author.display_name}]: {msg.content.strip()[:200]}")
                valid_messages.reverse()

        except discord.Forbidden:
            await interaction.followup.send("⚠️ No tengo permisos para leer el historial de este canal.", ephemeral=privado)
            return
        except Exception as e:
            log.error(f"Error reading channel history in #{channel.name}: {e}")
            await interaction.followup.send("⚠️ Ocurrió un error al intentar leer los mensajes del canal.", ephemeral=privado)
            return

        if len(valid_messages) < 3:
            period_text = f"las últimas {horas}h" if horas else f"los últimos {mensajes} mensajes"
            await interaction.followup.send(
                f"⚠️ No se encontraron suficientes mensajes de conversación en {period_text} para generar un resumen.",
                ephemeral=privado
            )
            return

        # Limit token footprint
        conversation = "\n".join(valid_messages[:120])
        lang = guild_lang(self.bot, guild.id)
        is_es = not str(lang).lower().startswith("en")

        if is_es:
            prompt = (
                "Eres Dabot, el asistente inteligente de la comunidad. "
                "Analiza la siguiente conversación de Discord y proporciona un resumen conciso, dinámico y bien estructurado.\n\n"
                "Formato requerido:\n"
                "📌 **Temas Principales**: (2 a 4 puntos clave tratados)\n"
                "💡 **Decisiones o Puntos Clave**: (acuerdos, avisos o novedades)\n"
                "🔥 **Momentos Destacados**: (debates o anécdotas más activas)\n"
                "❓ **Preguntas o Pendientes**: (dudas que quedaron en el aire, si las hay)\n\n"
                "Reglas: Sé directo, profesional pero cercano, no inventes nada y usa formato Markdown de Discord.\n\n"
                f"CONVERSACIÓN:\n{conversation}"
            )
        else:
            prompt = (
                "You are Dabot, an intelligent community Discord assistant. "
                "Analyze the following Discord conversation and provide a concise, structured, and engaging summary.\n\n"
                "Required format:\n"
                "📌 **Main Topics**: (2 to 4 key discussion points)\n"
                "💡 **Key Decisions / Announcements**: (agreements, updates, or decisions made)\n"
                "🔥 **Highlights & Debates**: (notable moments, discussions or jokes)\n"
                "❓ **Pending Questions**: (unresolved questions or open topics, if any)\n\n"
                "Rules: Be concise, direct, do not hallucinate, use Discord Markdown.\n\n"
                f"CONVERSATION:\n{conversation}"
            )

        summary = await self._generate_summary_ai(prompt, is_premium=True)

        if not summary:
            await interaction.followup.send(
                "⚠️ El servicio de Inteligencia Artificial no está disponible en este momento. Inténtalo de nuevo en unos segundos.",
                ephemeral=privado
            )
            return

        embed = discord.Embed(
            title=f"📝 Resumen de #{channel.name}" if is_es else f"📝 Summary of #{channel.name}",
            description=summary[:4000],
            color=discord.Color.from_rgb(0, 255, 136),
            timestamp=discord.utils.utcnow(),
        )
        time_info = f"{horas}h" if horas else "reciente"
        embed.set_footer(
            text=f"Analizados {len(valid_messages)} mensajes ({time_info}) · {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.followup.send(embed=embed, ephemeral=privado)

    @app_commands.command(name="resumen", description="📝 Resume la conversación reciente de este canal con IA.")
    @app_commands.describe(
        horas="Horas hacia atrás a resumir (1 a 48, por defecto 2)",
        mensajes="Límite máximo de mensajes a analizar (10 a 200, por defecto 60)",
        privado="Si es True, el resumen solo lo verás tú"
    )
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.channel_id)
    async def resumen(
        self,
        interaction: discord.Interaction,
        horas: int = 2,
        mensajes: int = 60,
        privado: bool = False
    ):
        await self._run_summary(interaction, horas=horas, mensajes=mensajes, privado=privado)

    @app_commands.command(name="recap", description="📝 Smart AI summary of recent channel conversation.")
    @app_commands.describe(
        horas="Horas hacia atrás a resumir (1 a 48, por defecto 2)",
        mensajes="Número de mensajes a analizar (10 a 200, por defecto 60)",
        privado="Si es True, el resumen solo lo verás tú"
    )
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.channel_id)
    async def recap_slash(
        self,
        interaction: discord.Interaction,
        horas: int = 2,
        mensajes: int = 60,
        privado: bool = False
    ):
        await self._run_summary(interaction, horas=horas, mensajes=mensajes, privado=privado)

    @resumen.error
    @recap_slash.error
    async def summary_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            sec = int(error.retry_after)
            await interaction.response.send_message(
                f"⏳ Por favor espera **{sec}s** antes de volver a solicitar un resumen en este canal.",
                ephemeral=True
            )
        else:
            log.error(f"Error in summary command: {error}")
            try:
                await interaction.response.send_message("❌ Ha ocurrido un error al procesar el resumen.", ephemeral=True)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(Recap(bot))
