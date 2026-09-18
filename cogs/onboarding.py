import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import DASHBOARD_URL, DABOT_GREEN


class Onboarding(commands.Cog):
    """First-run assistant so any admin can set Dabot up on any server."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="start",
        description="Asistente para configurar Dabot en este servidor."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        modulo="Módulo a activar ahora (opcional). El resto se configura en el panel web."
    )
    @app_commands.choices(modulo=[
        app_commands.Choice(name="Ver estado actual", value="status"),
        app_commands.Choice(name="Abrir panel web", value="web"),
        app_commands.Choice(name="Activar niveles", value="leveling"),
        app_commands.Choice(name="Activar economía", value="economy"),
        app_commands.Choice(name="Activar AutoMod", value="automod"),
    ])
    async def start(self, interaction: discord.Interaction, modulo: app_commands.Choice[str] = None):
        if not interaction.guild:
            await interaction.response.send_message("Este comando solo funciona en un servidor.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        self.bot.config.load_config(guild_id)
        choice = modulo.value if modulo else "status"

        if choice == "web":
            embed = discord.Embed(
                title="Panel web de Dabot",
                description=(
                    f"Toda la configuración visual está en **[{DASHBOARD_URL.replace('https://', '')}]({DASHBOARD_URL})**.\n\n"
                    "1. Inicia sesión con Discord.\n"
                    "2. Elige este servidor.\n"
                    "3. Activa bienvenidas, logs, tickets, anti-raid y más."
                ),
                color=DABOT_GREEN
            )
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Abrir panel", url=DASHBOARD_URL, style=discord.ButtonStyle.link))
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        if choice == "leveling":
            self.bot.config.set_config(guild_id, "leveling.enabled", False)
            msg = "Sistema de niveles **activado**. XP por texto y voz. Configura canales de anuncio en el panel."
        elif choice == "economy":
            self.bot.config.set_config(guild_id, "economy.enabled", True)
            msg = "Economía **activada**. Los miembros pueden usar `/eco balance` y `/eco work`."
        elif choice == "automod":
            self.bot.config.set_config(guild_id, "automod.enabled", True)
            self.bot.config.set_config(guild_id, "automod.block_invites", True)
            self.bot.config.set_config(guild_id, "automod.hijack", True)
            msg = "AutoMod **activado** (anti-spam, invitaciones y radar de cuentas hackeadas / MrBeast). Ajusta umbrales en el panel."
        else:
            msg = None

        cfg = self.bot.config.get(guild_id) or {}
        leveling = cfg.get("leveling", {})
        automod = cfg.get("automod", {})
        welcome = cfg.get("welcome", {})
        logs = cfg.get("logs", {})
        tickets = cfg.get("tickets", {})
        economy = cfg.get("economy", {})

        def flag(ok):
            return "✅" if ok else "—"

        embed = discord.Embed(
            title=f"Dabot en {interaction.guild.name}",
            description=msg or "Estado de los módulos. Lo que falta se activa en 30 segundos desde el panel web.",
            color=DABOT_GREEN
        )
        health_bits = []
        try:
            import sqlite3, os
            from utils.health import evaluate
            conn = sqlite3.connect(os.environ.get("DATABASE_PATH", "dabot.db"))
            conn.row_factory = sqlite3.Row
            h = evaluate(conn, guild_id, cfg)
            conn.close()
            health_bits.append(f"Salud **{h['score']}%** ({h['done']}/{h['total']})")
            for m in (h.get("missing") or [])[:6]:
                health_bits.append(f"{flag(False)} {m['label']}")
        except Exception:
            health_bits = []
        embed.add_field(
            name="Módulos",
            value=(
                f"{flag(leveling.get('enabled', True))} Niveles\n"
                f"{flag(economy.get('enabled', True))} Economía\n"
                f"{flag(automod.get('enabled'))} AutoMod\n"
                f"{flag(automod.get('hijack', True))} Radar secuestro\n"
                f"{flag(welcome.get('enabled') and welcome.get('channel_id'))} Bienvenida\n"
                f"{flag(bool(logs.get('moderation') or logs.get('messages')))} Logs\n"
                f"{flag(True)} Tickets → web"
            ),
            inline=True
        )
        if health_bits:
            embed.add_field(name="Checklist", value="\n".join(health_bits)[:1024], inline=True)
        embed.add_field(
            name="Siguiente paso",
            value=(
                f"• Panel: {DASHBOARD_URL}\n"
                f"• Prefijo: `{cfg.get('prefix', '!')}`\n"
                f"• Idioma: `{cfg.get('lang', 'es-ES')}`\n"
                f"• `/welcome setup` · `/antiraid setup` · `/verification setup`"
            ),
            inline=True
        )
        embed.set_footer(text="Dabot · davito.es")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Abrir dashboard", url=DASHBOARD_URL, style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="dashboard", description="Enlace al panel web de Dabot.")
    async def dashboard_cmd(self, interaction: discord.Interaction):
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="dabot.davito.es", url=DASHBOARD_URL, style=discord.ButtonStyle.link))
        await interaction.response.send_message(
            f"Panel de control: **{DASHBOARD_URL}**\nInicia sesión con Discord para gestionar este servidor.",
            view=view,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
