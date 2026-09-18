import discord
from discord.ext import commands
from discord import app_commands
import logging
import datetime
import json
from utils.images import create_welcome_card, persist_discord_image

class WelcomeCards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.WelcomeCards')

    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_table()
        self.logger.info('WelcomeCards Cog loaded and initialized.')

    async def ensure_table(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS welcome_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                channel_id INTEGER,
                background_url TEXT,
                message_text TEXT DEFAULT '¡Bienvenido {member} a nuestro servidor!',
                card_heading TEXT DEFAULT 'BIENVENIDO',
                member_label TEXT DEFAULT 'Miembro',
                custom_text TEXT DEFAULT '',
                layout_json TEXT DEFAULT '{}'
            )
        """)

    # Slash Command Group for Welcome Cards
    welcome_group = app_commands.Group(
        name="welcome",
        description="Sistema de tarjetas de bienvenida dinámicas."
    )

    @welcome_group.command(name="setup", description="Configura canal, mensaje y estado de las bienvenidas.")
    @app_commands.describe(
        canal="Canal donde se publicará el mensaje de bienvenida.",
        habilitado="Habilita (True) o deshabilita (False) las bienvenidas.",
        mensaje="Texto. Variables: {member} {guild} {mention} {server} {count}",
        titulo="Título opcional de la tarjeta/embed.",
    )
    @app_commands.default_permissions(administrator=True)
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        habilitado: bool,
        mensaje: str = None,
        titulo: str = None,
    ):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()
        for sql in (
            "ALTER TABLE welcome_config ADD COLUMN title TEXT",
            "ALTER TABLE welcome_config ADD COLUMN card_heading TEXT DEFAULT 'BIENVENIDO'",
            "ALTER TABLE welcome_config ADD COLUMN member_label TEXT DEFAULT 'Miembro'",
            "ALTER TABLE welcome_config ADD COLUMN custom_text TEXT DEFAULT ''",
            "ALTER TABLE welcome_config ADD COLUMN layout_json TEXT DEFAULT '{}'",
        ):
            try:
                await self.bot.db.execute(sql)
            except Exception:
                pass

        config = await self.bot.db.fetch("SELECT 1 FROM welcome_config WHERE guild_id = ?", interaction.guild.id)
        if not config:
            await self.bot.db.execute(
                "INSERT INTO welcome_config (guild_id, enabled, channel_id, message_text, title) VALUES (?, ?, ?, ?, ?)",
                interaction.guild.id, 1 if habilitado else 0, canal.id,
                mensaje or "¡Bienvenido {member} a {guild}!", titulo,
            )
        else:
            await self.bot.db.execute(
                "UPDATE welcome_config SET enabled = ?, channel_id = ? WHERE guild_id = ?",
                1 if habilitado else 0, canal.id, interaction.guild.id
            )
            if mensaje:
                await self.bot.db.execute(
                    "UPDATE welcome_config SET message_text = ? WHERE guild_id = ?",
                    mensaje, interaction.guild.id,
                )
            if titulo is not None:
                await self.bot.db.execute(
                    "UPDATE welcome_config SET title = ? WHERE guild_id = ?",
                    titulo, interaction.guild.id,
                )

        self.bot.config.set_config(interaction.guild.id, "welcome.enabled", habilitado)
        self.bot.config.set_config(interaction.guild.id, "welcome.channel_id", str(canal.id))
        if mensaje:
            self.bot.config.set_config(interaction.guild.id, "welcome.message", mensaje)

        status = "habilitadas" if habilitado else "deshabilitadas"
        await interaction.followup.send(
            f"✅ Bienvenidas **{status}** en {canal.mention}.\n"
            f"Mensaje: `{mensaje or 'el que ya había'}`",
            ephemeral=True
        )

    @welcome_group.command(name="setmsg", description="Configura el mensaje de texto acompañante (Solo Admins).")
    @app_commands.describe(mensaje="Mensaje de bienvenida (usa {member} y {guild} como variables).")
    @app_commands.default_permissions(administrator=True)
    async def welcome_setmsg(self, interaction: discord.Interaction, mensaje: str):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        config = await self.bot.db.fetch("SELECT 1 FROM welcome_config WHERE guild_id = ?", interaction.guild.id)
        if not config:
            await self.bot.db.execute(
                "INSERT INTO welcome_config (guild_id, message_text) VALUES (?, ?)",
                interaction.guild.id, mensaje
            )
        else:
            await self.bot.db.execute(
                "UPDATE welcome_config SET message_text = ? WHERE guild_id = ?",
                mensaje, interaction.guild.id
            )

        await interaction.followup.send(
            f"✅ Mensaje de bienvenida actualizado:\n`{mensaje}`",
            ephemeral=True
        )

    @welcome_group.command(name="background", description="Cambia el fondo de la tarjeta de bienvenida (Solo Admins).")
    @app_commands.describe(imagen="Sube la imagen que se usará como fondo para las bienvenidas.")
    @app_commands.default_permissions(administrator=True)
    async def welcome_background(self, interaction: discord.Interaction, imagen: discord.Attachment):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        if not imagen.content_type.startswith("image/"):
            await interaction.followup.send("❌ Adjunto inválido. Por favor sube un archivo de imagen.", ephemeral=True)
            return

        try:
            background_source = await persist_discord_image(imagen, interaction.guild.id)
        except (ValueError, OSError) as exc:
            await interaction.followup.send(f"❌ No se pudo guardar la imagen: {exc}", ephemeral=True)
            return

        config = await self.bot.db.fetch("SELECT 1 FROM welcome_config WHERE guild_id = ?", interaction.guild.id)
        if not config:
            await self.bot.db.execute(
                "INSERT INTO welcome_config (guild_id, background_url) VALUES (?, ?)",
                interaction.guild.id, background_source
            )
        else:
            await self.bot.db.execute(
                "UPDATE welcome_config SET background_url = ? WHERE guild_id = ?",
                background_source, interaction.guild.id
            )

        # Premium backgrounds are shared by welcome and rank cards. Upsert is
        # important for super-owner servers, which are premium without a
        # pre-existing premium_guilds row.
        if await self.bot.db.is_guild_premium(interaction.guild, self.bot):
            await self.bot.db.execute(
                """INSERT INTO premium_guilds
                   (guild_id, activated_at, expires_at, plan, custom_background)
                   VALUES (?, ?, '9999-12-31T23:59:59', 'lifetime', ?)
                   ON CONFLICT(guild_id) DO UPDATE SET custom_background = excluded.custom_background""",
                interaction.guild.id, datetime.datetime.now(datetime.timezone.utc).isoformat(), background_source,
            )

        embed = discord.Embed(title="✅ Fondo de Bienvenida Actualizado", color=discord.Color.green())
        embed.set_image(url=imagen.url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _send_welcome_card(self, member: discord.Member):
        await self.ensure_table()
        config = await self.bot.db.fetch(
            "SELECT enabled, channel_id, background_url, message_text, card_heading, member_label, custom_text, layout_json FROM welcome_config WHERE guild_id = ?",
            member.guild.id
        )
        if not config or not config[0]:
            return

        enabled, channel_id, background_url, message_text, card_heading, member_label, custom_text, layout_json = config
        try:
            layout = json.loads(layout_json or "{}")
        except (TypeError, ValueError):
            layout = {}

        # Let the optional card line use the same placeholders as the
        # welcome message without allowing malformed braces to break joins.
        try:
            custom_text = (custom_text or "").format(
                member=member.display_name,
                user=member.display_name,
                mention=member.mention,
                guild=member.guild.name,
                server=member.guild.name,
                count=member.guild.member_count or 0,
            )
        except (KeyError, ValueError):
            pass
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return

        # Prepare background
        premium = await self.bot.db.fetch(
            "SELECT custom_background FROM premium_guilds WHERE guild_id = ?", member.guild.id
        )
        bg_source = (premium[0] if premium and premium[0] else None) or background_url or "assets/welcome_background.jpg"

        try:
            # Generate Pillow card
            file = await create_welcome_card(
                member, background_source=bg_source, session=self.bot.session,
                welcome_text=card_heading or "BIENVENIDO", member_label=member_label or "Miembro",
                custom_text=custom_text or "", layout=layout,
            )
            
            # Format message text
            formatted_text = (message_text or "¡Bienvenido {member} a {guild}!").format(
                member=member.mention,
                mention=member.mention,
                guild=member.guild.name,
                server=member.guild.name,
                count=member.guild.member_count,
                user=member.display_name,
            ) if "{" in (message_text or "") and "{member}" not in (message_text or "") else (
                (message_text or "¡Bienvenido {member} a {guild}!")
                .replace("{member}", member.mention)
                .replace("{mention}", member.mention)
                .replace("{guild}", member.guild.name)
                .replace("{server}", member.guild.name)
                .replace("{count}", str(member.guild.member_count))
                .replace("{user}", member.display_name)
            )

            # Send both
            await channel.send(content=formatted_text, file=file)
            self.logger.info(f"Enviada tarjeta de bienvenida para {member} en {member.guild.name}")
        except Exception as e:
            self.logger.error(f"Error al enviar tarjeta de bienvenida en {member.guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        # Discord Rule Screening / Member Verification check:
        # If the member has pending rules, wait until they accept them
        if getattr(member, 'pending', False):
            self.logger.info(f"Miembro {member} tiene verificación de reglas pendiente en {member.guild.name}. Esperando aceptación...")
            return

        await self._send_welcome_card(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return

        # Member just accepted rules/passed screening (pending transitioned from True to False)
        if getattr(before, 'pending', False) and not getattr(after, 'pending', False):
            self.logger.info(f"Miembro {after} completó la verificación de reglas en {after.guild.name}. Enviando bienvenida...")
            await self._send_welcome_card(after)


async def setup(bot):
    await bot.add_cog(WelcomeCards(bot))
