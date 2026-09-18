import discord
from discord.ext import commands
from discord import app_commands
import logging
import traceback
import datetime

log = logging.getLogger("Dabot.NativeMod")

class DiscordAutoMod(commands.Cog):
    """Gestión de las reglas de AutoMod nativas de Discord."""

    def __init__(self, bot):
        self.bot = bot

    async def get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        try:
            config = self.bot.config.get(guild.id, {})
            log_channel_id = config.get('log_channel')
            if log_channel_id:
                return guild.get_channel(log_channel_id)
        except Exception as e:
            log.warning(f"Failed to get log channel for guild {guild.id}: {e}")
        return None

    nativemod = app_commands.Group(name="nativemod", description="Gestiona el AutoMod nativo de Discord")

    async def rule_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            rules = await interaction.guild.fetch_auto_moderation_rules()
            choices = [
                app_commands.Choice(name=rule.name, value=rule.name)
                for rule in rules if current.lower() in rule.name.lower()
            ]
            return choices[:25]
        except Exception:
            return []

    @nativemod.command(name="list", description="Lista todas las reglas de AutoMod activas en el servidor")
    @app_commands.default_permissions(manage_guild=True)
    async def list_rules(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            rules = await interaction.guild.fetch_auto_moderation_rules()
            
            if not rules:
                await interaction.followup.send("No hay reglas de AutoMod configuradas en este servidor.")
                return

            embed = discord.Embed(
                title="Reglas de AutoMod de Discord",
                color=discord.Color.blue()
            )

            for rule in rules:
                status = "🟢 Habilitada" if rule.enabled else "🔴 Deshabilitada"
                trigger_type = str(rule.trigger_type).replace("AutoModTriggerType.", "")
                
                actions = []
                for action in rule.actions:
                    if action.type == discord.AutoModRuleActionType.block_message:
                        actions.append("Bloquear Mensaje")
                    elif action.type == discord.AutoModRuleActionType.send_alert_message:
                        actions.append(f"Enviar Alerta (<#{action.channel_id}>)")
                    elif action.type == discord.AutoModRuleActionType.timeout:
                        actions.append(f"Timeout ({action.duration.total_seconds()}s)")
                
                actions_str = ", ".join(actions) if actions else "Ninguna"
                
                embed.add_field(
                    name=f"{rule.name} ({status})",
                    value=f"**Tipo:** {trigger_type}\n**Acciones:** {actions_str}",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para gestionar el servidor (`Manage Server`).")
        except Exception as e:
            log.error(f"Error list_rules: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("Ocurrió un error al listar las reglas.")

    @nativemod.command(name="block-words", description="Crea una regla para bloquear palabras específicas")
    @app_commands.describe(
        words="Lista de palabras a bloquear (separadas por comas)",
        name="Nombre de la regla (opcional)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def block_words(self, interaction: discord.Interaction, words: str, name: str = "Filtro de palabras - Dabot"):
        await interaction.response.defer()
        
        try:
            log_channel = await self.get_log_channel(interaction.guild)
            
            actions = [discord.AutoModRuleAction(custom_message="Mensaje bloqueado por contener palabras no permitidas.")]
            
            if log_channel:
                actions.append(discord.AutoModRuleAction(channel=log_channel))

            word_list = [w.strip() for w in words.split(",") if w.strip()]
            
            if not word_list:
                await interaction.followup.send("Debes proporcionar al menos una palabra válida.")
                return
            
            rule = await interaction.guild.create_auto_moderation_rule(
                name=name,
                event_type=discord.AutoModRuleEventType.message_send,
                trigger_type=discord.AutoModTriggerType.keyword,
                trigger_metadata=discord.AutoModTriggerMetadata(keyword_filter=word_list),
                actions=actions,
                enabled=True,
                reason=f"Regla creada por {interaction.user} via Dabot"
            )
            
            await interaction.followup.send(f"✅ Regla `{rule.name}` creada exitosamente. Bloqueando {len(word_list)} palabra(s).")
            
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para gestionar el servidor (`Manage Server`).")
        except discord.HTTPException as e:
            if e.code == 30043:
                await interaction.followup.send("Has alcanzado el límite máximo de reglas de AutoMod de este tipo.")
            else:
                await interaction.followup.send(f"Error de Discord: {e.text}")
        except Exception as e:
            log.error(f"Error block_words: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("Ocurrió un error al crear la regla.")

    @nativemod.command(name="block-links", description="Crea una regla para bloquear enlaces")
    @app_commands.describe(
        whitelist="Dominios permitidos (separados por comas)",
        name="Nombre de la regla (opcional)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def block_links(self, interaction: discord.Interaction, whitelist: str = None, name: str = "Anti-enlaces - Dabot"):
        await interaction.response.defer()
        
        try:
            log_channel = await self.get_log_channel(interaction.guild)
            
            actions = [discord.AutoModRuleAction(custom_message="Los enlaces no están permitidos en este servidor.")]
            if log_channel:
                actions.append(discord.AutoModRuleAction(channel=log_channel))

            trigger_metadata = discord.AutoModTriggerMetadata(
                regex_patterns=[r"(?:https?://)?[a-z0-9_\-]+\.[a-z]{2,}(?:/\S*)?"]
            )
            
            if whitelist:
                allowed = [w.strip() for w in whitelist.split(",") if w.strip()]
                trigger_metadata.allow_list = allowed

            rule = await interaction.guild.create_auto_moderation_rule(
                name=name,
                event_type=discord.AutoModRuleEventType.message_send,
                trigger_type=discord.AutoModTriggerType.keyword,
                trigger_metadata=trigger_metadata,
                actions=actions,
                enabled=True,
                reason=f"Regla de enlaces creada por {interaction.user} via Dabot"
            )
            
            await interaction.followup.send(f"✅ Regla `{rule.name}` creada exitosamente para bloquear enlaces.")
            
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para gestionar el servidor (`Manage Server`).")
        except discord.HTTPException as e:
            if e.code == 30043:
                await interaction.followup.send("Has alcanzado el límite máximo de reglas de AutoMod de este tipo.")
            else:
                await interaction.followup.send(f"Error de Discord: {e.text}")
        except Exception as e:
            log.error(f"Error block_links: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("Ocurrió un error al crear la regla de bloqueo de enlaces.")

    @nativemod.command(name="anti-spam", description="Crea protección contra spam de menciones")
    @app_commands.describe(
        mention_total_limit="Límite máximo de menciones (por defecto: 5)",
        name="Nombre de la regla (opcional)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def anti_spam(self, interaction: discord.Interaction, mention_total_limit: int = 5, name: str = "Anti-mención spam - Dabot"):
        await interaction.response.defer()
        
        try:
            log_channel = await self.get_log_channel(interaction.guild)
            
            actions = [
                discord.AutoModRuleAction(custom_message="Has superado el límite de menciones."),
                discord.AutoModRuleAction(duration=datetime.timedelta(seconds=60))
            ]
            if log_channel:
                actions.append(discord.AutoModRuleAction(channel=log_channel))

            rule = await interaction.guild.create_auto_moderation_rule(
                name=name,
                event_type=discord.AutoModRuleEventType.message_send,
                trigger_type=discord.AutoModTriggerType.mention_spam,
                trigger_metadata=discord.AutoModTriggerMetadata(mention_total_limit=mention_total_limit),
                actions=actions,
                enabled=True,
                reason=f"Regla anti-spam creada por {interaction.user} via Dabot"
            )
            
            await interaction.followup.send(f"✅ Regla `{rule.name}` creada exitosamente (Límite: {mention_total_limit} menciones).")
            
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para gestionar el servidor o para aplicar Timeouts (`Manage Server`, `Moderate Members`).")
        except discord.HTTPException as e:
            if e.code == 30043:
                await interaction.followup.send("Has alcanzado el límite máximo de reglas de AutoMod de este tipo.")
            else:
                await interaction.followup.send(f"Error de Discord: {e.text}")
        except Exception as e:
            log.error(f"Error anti_spam: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("Ocurrió un error al crear la regla anti-spam.")

    @nativemod.command(name="delete", description="Elimina una regla de AutoMod por nombre")
    @app_commands.describe(name="Nombre de la regla a eliminar")
    @app_commands.autocomplete(name=rule_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def delete_rule(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        
        try:
            rules = await interaction.guild.fetch_auto_moderation_rules()
            target_rule = next((r for r in rules if r.name.lower() == name.lower()), None)
            
            if not target_rule:
                await interaction.followup.send(f"No se encontró ninguna regla con el nombre `{name}`.")
                return
                
            await target_rule.delete(reason=f"Regla eliminada por {interaction.user} via Dabot")
            await interaction.followup.send(f"✅ Regla `{target_rule.name}` eliminada exitosamente.")
            
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para gestionar el servidor (`Manage Server`).")
        except Exception as e:
            log.error(f"Error delete_rule: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("Ocurrió un error al eliminar la regla.")

    @nativemod.command(name="toggle", description="Habilita o deshabilita una regla de AutoMod")
    @app_commands.describe(name="Nombre de la regla a alternar")
    @app_commands.autocomplete(name=rule_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def toggle_rule(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        
        try:
            rules = await interaction.guild.fetch_auto_moderation_rules()
            target_rule = next((r for r in rules if r.name.lower() == name.lower()), None)
            
            if not target_rule:
                await interaction.followup.send(f"No se encontró ninguna regla con el nombre `{name}`.")
                return
                
            new_state = not target_rule.enabled
            await target_rule.edit(enabled=new_state, reason=f"Regla {'habilitada' if new_state else 'deshabilitada'} por {interaction.user} via Dabot")
            
            status_text = "habilitada" if new_state else "deshabilitada"
            await interaction.followup.send(f"✅ Regla `{target_rule.name}` {status_text} exitosamente.")
            
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para gestionar el servidor (`Manage Server`).")
        except Exception as e:
            log.error(f"Error toggle_rule: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("Ocurrió un error al modificar la regla.")

async def setup(bot):
    await bot.add_cog(DiscordAutoMod(bot))
