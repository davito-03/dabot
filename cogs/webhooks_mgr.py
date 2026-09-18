import discord
from discord.ext import commands
from discord import app_commands
import logging
import aiohttp

class WebhooksManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.WebhooksManager')

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info('WebhooksManager Cog loaded.')

    # Webhook Slash Command Group
    webhook_group = app_commands.Group(
        name="webhook",
        description="Gestión y envío de mensajes mediante Webhooks.",
    )

    @webhook_group.command(name="crear", description="Crea un webhook en el canal especificado (Solo Admins).")
    @app_commands.describe(
        canal="Canal donde se creará el webhook.",
        nombre="Nombre del webhook.",
        avatar="Imagen de avatar para el webhook (opcional)."
    )
    @app_commands.default_permissions(administrator=True)
    async def webhook_create(self, interaction: discord.Interaction, canal: discord.TextChannel, nombre: str, avatar: discord.Attachment = None):
        await interaction.response.defer(ephemeral=True)
        
        avatar_bytes = None
        if avatar:
            if not avatar.content_type.startswith("image/"):
                await interaction.followup.send("❌ El avatar debe ser una imagen.", ephemeral=True)
                return
            avatar_bytes = await avatar.read()
            
        try:
            webhook = await canal.create_webhook(name=nombre, avatar=avatar_bytes, reason=f"Creado por {interaction.user.name}")
            await interaction.followup.send(
                f"✅ Webhook **{webhook.name}** creado en {canal.mention} con éxito.\n"
                f"**URL:** `{webhook.url}`\n"
                f"**ID:** `{webhook.id}`",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo permisos para gestionar webhooks en ese canal.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error al crear el webhook: {e}", ephemeral=True)

    @webhook_group.command(name="listar", description="Muestra los webhooks del servidor (Solo Admins).")
    @app_commands.default_permissions(administrator=True)
    async def webhook_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            webhooks = await interaction.guild.webhooks()
            if not webhooks:
                await interaction.followup.send("No hay webhooks creados en este servidor.", ephemeral=True)
                return
                
            embed = discord.Embed(title="🔗 Webhooks del Servidor", color=discord.Color.blue())
            desc = ""
            for wh in webhooks[:25]:  # limit to 25 for embed limits
                desc += f"• **{wh.name}** | Canal: <#{wh.channel_id}> | ID: `{wh.id}`\n"
            embed.description = desc
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo permisos para ver los webhooks del servidor.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error al listar webhooks: {e}", ephemeral=True)

    @webhook_group.command(name="eliminar", description="Elimina un webhook por su ID (Solo Admins).")
    @app_commands.describe(webhook_id="El ID del webhook que quieres eliminar.")
    @app_commands.default_permissions(administrator=True)
    async def webhook_delete(self, interaction: discord.Interaction, webhook_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            webhooks = await interaction.guild.webhooks()
            target = discord.utils.get(webhooks, id=int(webhook_id))
            if not target:
                await interaction.followup.send("❌ Webhook no encontrado en este servidor.", ephemeral=True)
                return
            await target.delete(reason=f"Eliminado por {interaction.user.name}")
            await interaction.followup.send(f"✅ Webhook con ID `{webhook_id}` eliminado con éxito.", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ ID inválido. Debe ser un número entero.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo permisos para gestionar este webhook.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error al eliminar el webhook: {e}", ephemeral=True)

    @webhook_group.command(name="enviar", description="Envía un mensaje a través de un webhook personalizado.")
    @app_commands.describe(
        webhook_name_or_id="El Webhook a usar (escribe parte de su nombre para autocompletar, o usa una URL directa).",
        contenido="El mensaje de texto normal a enviar (opcional si se usa un embed).",
        titulo_embed="Título del embed (opcional).",
        desc_embed="Descripción/Contenido del embed (opcional).",
        color_hex="Color del embed en formato HEX (opcional).",
        username="Nombre personalizado de la identidad que envía (opcional).",
        avatar_url="Avatar personalizado de la identidad que envía (opcional)."
    )
    async def webhook_send(self, interaction: discord.Interaction, 
                             webhook_name_or_id: str, 
                             contenido: str = None, 
                             titulo_embed: str = None, 
                             desc_embed: str = None, 
                             color_hex: str = None,
                             username: str = None,
                             avatar_url: str = None):
        await interaction.response.defer(ephemeral=True)
        
        if not contenido and not titulo_embed and not desc_embed:
            await interaction.followup.send("❌ Debes proveer al menos el contenido de texto o los datos para crear un Embed.", ephemeral=True)
            return

        guild = interaction.guild
        webhook = None
        
        # Try to find webhook locally first
        try:
            webhooks = await guild.webhooks()
            if webhook_name_or_id.isdigit():
                webhook = discord.utils.get(webhooks, id=int(webhook_name_or_id))
            else:
                webhook = discord.utils.get(webhooks, name=webhook_name_or_id)
        except discord.Forbidden:
            pass # No permissions to list guild webhooks, will try direct URL next

        # Fallback to direct URL parsing if no local webhook match
        if not webhook:
            if webhook_name_or_id.startswith("https://discord.com/api/webhooks/"):
                webhook_url = webhook_name_or_id
            else:
                await interaction.followup.send("❌ Webhook no encontrado. Usa la lista autocompletada o una URL de webhook de Discord válida.", ephemeral=True)
                return
        else:
            webhook_url = webhook.url

        # Build embed if requested
        embed = None
        if titulo_embed or desc_embed:
            color = discord.Color.blue()
            if color_hex:
                if not color_hex.startswith("#"):
                    color_hex = "#" + color_hex
                try:
                    color = discord.Color.from_str(color_hex)
                except ValueError:
                    pass
            embed = discord.Embed(
                title=titulo_embed,
                description=desc_embed,
                color=color
            )

        # Send webhook message using an independent session for maximum reliability
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                temp_webhook = discord.Webhook.from_url(webhook_url, session=session)
                await temp_webhook.send(
                    content=contenido,
                    embed=embed,
                    username=username,
                    avatar_url=avatar_url
                )
            await interaction.followup.send("✅ Mensaje enviado a través del webhook con éxito.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error al enviar mensaje mediante webhook: {e}", ephemeral=True)
            self.logger.error(f"Error sending webhook message to {webhook_url}: {e}")

    # Autocomplete handler for webhook names and IDs
    @webhook_send.autocomplete('webhook_name_or_id')
    async def webhook_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            webhooks = await interaction.guild.webhooks()
            choices = []
            for wh in webhooks:
                name_display = f"{wh.name} (Canal: #{wh.channel.name if wh.channel else 'Desconocido'})"
                if current.lower() in wh.name.lower() or current in str(wh.id):
                    choices.append(app_commands.Choice(name=name_display[:100], value=str(wh.id)))
            return choices[:25]
        except Exception:
            return []


async def setup(bot):
    await bot.add_cog(WebhooksManager(bot))
