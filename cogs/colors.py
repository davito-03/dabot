import discord
from discord.ext import commands
from discord import app_commands
import logging
import datetime

class Colors(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.Colors')

    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_table()
        self.logger.info('Colors Cog loaded and initialized.')

    async def ensure_table(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS color_config (
                guild_id INTEGER PRIMARY KEY,
                price INTEGER DEFAULT 500,
                duration_days INTEGER DEFAULT 30
            )
        """)

    async def get_config(self, guild_id):
        await self.ensure_table()
        res = await self.bot.db.fetch("SELECT price, duration_days FROM color_config WHERE guild_id = ?", guild_id)
        if not res:
            return 500, 30
        return res[0], res[1]

    # Command Group for Custom Color Name
    color_group = app_commands.Group(
        name="namecolor",
        description="Colores de nombre personalizados."
    )

    @color_group.command(name="comprar", description="Compra un color personalizado para tu nombre.")
    @app_commands.describe(hex_code="El color en formato HEX (ej: #FF5733 o FF5733).")
    async def color_buy(self, interaction: discord.Interaction, hex_code: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        # Validate hex code
        hex_code = hex_code.strip()
        if not hex_code.startswith('#'):
            hex_code = '#' + hex_code

        try:
            color = discord.Color.from_str(hex_code)
        except ValueError:
            await interaction.followup.send("❌ Código de color HEX inválido. Por favor usa un formato como `#FF5733` o `FF5733`.", ephemeral=True)
            return

        price, duration_days = await self.get_config(guild.id)

        # Check balance
        eco_cog = self.bot.get_cog("Economy")
        if not eco_cog:
            await interaction.followup.send("❌ El sistema de economía no está disponible.", ephemeral=True)
            return

        wallet, _ = await eco_cog.get_balance(member.id, guild.id)
        if wallet < price:
            await interaction.followup.send(
                f"❌ No tienes suficientes monedas.\n"
                f"**Precio:** {price} monedas | **Tu cartera:** {wallet} monedas",
                ephemeral=True
            )
            return

        try:
            # Deduct wallet balance
            await eco_cog.update_balance(member.id, -price, "wallet", guild.id)

            # Clean up existing color roles for this user
            for role in list(member.roles):
                if role.name == f"color-{member.id}":
                    try:
                        await role.delete(reason="Reemplazo de color comprado")
                    except Exception:
                        pass

            # Create new color role
            new_role = await guild.create_role(
                name=f"color-{member.id}",
                color=color,
                reason=f"Color personalizado comprado por {member.name}"
            )

            # Position it below the bot's highest role
            try:
                bot_role = guild.me.top_role
                await new_role.edit(position=max(1, bot_role.position - 1))
            except Exception:
                pass

            # Assign to member
            await member.add_roles(new_role, reason="Color comprado.")

            # Register temporary role if duration is set
            dur_text = "permanentemente"
            if duration_days > 0:
                expires_at = datetime.datetime.now() + datetime.timedelta(days=duration_days)
                expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

                await self.bot.db.execute(
                    "INSERT OR REPLACE INTO active_temp_roles (guild_id, user_id, role_id, expires_at) VALUES (?, ?, ?, ?)",
                    guild.id, member.id, new_role.id, expires_str
                )
                dur_text = f"durante {duration_days} días (expira el {expires_str})"

            embed = discord.Embed(
                title="🎨 Color Comprado con Éxito",
                description=(
                    f"Tu nombre ahora brilla con el color **{hex_code}**.\n"
                    f"Se han descontado **{price}** monedas de tu cartera.\n"
                    f"El color se mantendrá {dur_text}."
                ),
                color=color
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        except discord.Forbidden:
            # Refund
            await eco_cog.update_balance(member.id, price, "wallet", guild.id)
            await interaction.followup.send(
                "❌ No tengo permisos suficientes para crear o posicionar el rol de color.\n"
                "Asegúrate de que mi rol jerárquico esté lo suficientemente alto en la configuración del servidor.",
                ephemeral=True
            )
        except Exception as e:
            # Refund
            await eco_cog.update_balance(member.id, price, "wallet", guild.id)
            await interaction.followup.send(f"❌ Ocurrió un error al procesar tu compra: {e}", ephemeral=True)
            self.logger.error(f"Error al comprar color para {member.id}: {e}")

    @color_group.command(name="remover", description="Elimina tu color personalizado actual de forma gratuita.")
    async def color_remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        found = False
        for role in list(member.roles):
            if role.name == f"color-{member.id}":
                try:
                    await role.delete(reason="Remoción de color a petición del usuario")
                    found = True
                except discord.Forbidden:
                    await interaction.followup.send("❌ No tengo permisos para eliminar tu rol de color actual.", ephemeral=True)
                    return
                except Exception as e:
                    await interaction.followup.send(f"❌ Error al eliminar el rol: {e}", ephemeral=True)
                    return

        # Clear temp role database record
        await self.bot.db.execute(
            "DELETE FROM active_temp_roles WHERE guild_id = ? AND user_id = ?",
            guild.id, member.id
        )

        if found:
            await interaction.followup.send("✅ Tu color personalizado ha sido removido y tu nombre ha vuelto a la normalidad.", ephemeral=True)
        else:
            await interaction.followup.send("❌ No tienes ningún color personalizado activo en este momento.", ephemeral=True)

    @color_group.command(name="configurar", description="Ajusta el precio y la duración del color (Solo Admins).")
    @app_commands.describe(
        precio="El costo en monedas del color (mínimo 1).",
        duracion_dias="Duración en días del color (0 para permanente)."
    )
    @app_commands.default_permissions(administrator=True)
    async def color_config(self, interaction: discord.Interaction, precio: int, duracion_dias: int):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        if precio <= 0:
            await interaction.followup.send("❌ El precio debe ser mayor a 0.", ephemeral=True)
            return
        if duracion_dias < 0:
            await interaction.followup.send("❌ La duración no puede ser negativa.", ephemeral=True)
            return

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO color_config (guild_id, price, duration_days) VALUES (?, ?, ?)",
            interaction.guild.id, precio, duracion_dias
        )

        dur_text = f"{duracion_dias} días" if duracion_dias > 0 else "Permanente"
        await interaction.followup.send(
            f"✅ Configuración de color actualizada:\n"
            f"**Precio:** {precio} monedas | **Duración:** {dur_text}",
            ephemeral=True
        )

    # Listen to member remove events to prevent orphaned color roles
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        for role in list(guild.roles):
            if role.name == f"color-{member.id}":
                try:
                    await role.delete(reason="El miembro salió del servidor")
                except Exception:
                    pass
        # Clean up database record
        await self.bot.db.execute(
            "DELETE FROM active_temp_roles WHERE guild_id = ? AND user_id = ?",
            guild.id, member.id
        )


async def setup(bot):
    await bot.add_cog(Colors(bot))
