import discord
from discord.ext import commands
from discord import app_commands

class EmbedBuilderModal(discord.ui.Modal, title="Crear Mensaje Embed"):
    embed_title = discord.ui.TextInput(
        label="Título del Embed",
        placeholder="Escribe el título aquí...",
        max_length=256,
        required=True
    )
    embed_description = discord.ui.TextInput(
        label="Descripción / Contenido",
        style=discord.TextStyle.paragraph,
        placeholder="Escribe el texto detallado del embed...",
        max_length=4000,
        required=True
    )
    embed_color = discord.ui.TextInput(
        label="Color HEX (opcional)",
        placeholder="Ej: #FF5733 o #00FFCA",
        max_length=7,
        required=False
    )
    embed_thumbnail = discord.ui.TextInput(
        label="URL de la Miniatura (opcional)",
        placeholder="https://ejemplo.com/imagen.png",
        required=False
    )
    embed_image = discord.ui.TextInput(
        label="URL de Imagen Grande (opcional)",
        placeholder="https://ejemplo.com/banner.png",
        required=False
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        # Validate hex color
        color_val = self.embed_color.value.strip()
        if color_val:
            if not color_val.startswith('#'):
                color_val = '#' + color_val
            try:
                color = discord.Color.from_str(color_val)
            except ValueError:
                color = discord.Color.blue()
        else:
            color = discord.Color.blue()

        embed = discord.Embed(
            title=self.embed_title.value,
            description=self.embed_description.value,
            color=color
        )

        # Validate thumbnail URL
        thumb_val = self.embed_thumbnail.value.strip()
        if thumb_val:
            if thumb_val.startswith("http://") or thumb_val.startswith("https://"):
                embed.set_thumbnail(url=thumb_val)

        # Validate image URL
        image_val = self.embed_image.value.strip()
        if image_val:
            if image_val.startswith("http://") or image_val.startswith("https://"):
                embed.set_image(url=image_val)

        try:
            await self.channel.send(embed=embed)
            await interaction.response.send_message(f"✅ ¡Embed enviado con éxito a {self.channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ No tengo permisos para enviar mensajes en {self.channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error al enviar el embed: {e}", ephemeral=True)


class EmbedBuilder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="embed", description="Crea y envía un mensaje embed enriquecido a un canal.")
    @app_commands.describe(channel="El canal donde se enviará el embed (por defecto el actual).")
    @app_commands.default_permissions(administrator=True)
    async def embed_create(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        
        # Verify permissions
        permissions = target_channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages or not permissions.embed_links:
            await interaction.response.send_message(
                f"❌ No tengo permisos suficientes en {target_channel.mention} (requiero enviar mensajes e insertar enlaces).",
                ephemeral=True
            )
            return

        modal = EmbedBuilderModal(target_channel)
        await interaction.response.send_modal(modal)


async def setup(bot):
    await bot.add_cog(EmbedBuilder(bot))
