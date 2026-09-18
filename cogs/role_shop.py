import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import datetime

class RoleShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.RoleShop')
        self.check_temp_roles.start()

    def cog_unload(self):
        self.check_temp_roles.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_tables()
        self.logger.info('RoleShop Cog loaded and initialized.')

    async def ensure_tables(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS role_shop (
                guild_id INTEGER,
                role_id INTEGER,
                price INTEGER,
                duration_days INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, role_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS active_temp_roles (
                guild_id INTEGER,
                user_id INTEGER,
                role_id INTEGER,
                expires_at TEXT,
                PRIMARY KEY (guild_id, user_id, role_id)
            )
        """)

    # App Command Group for Role Shop
    roleshop_group = app_commands.Group(
        name="roleshop",
        description="Tienda de roles y roles temporales.",
    )

    @roleshop_group.command(name="add", description="Añade o edita un rol en la tienda (Solo Admins).")
    @app_commands.describe(
        role="El rol que se pondrá a la venta.",
        price="El precio en monedas del rol.",
        duration_days="Duración en días del rol (0 para permanente, por defecto 0)."
    )
    @app_commands.default_permissions(administrator=True)
    async def roleshop_add(self, interaction: discord.Interaction, role: discord.Role, price: int, duration_days: int = 0):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        if price <= 0:
            await interaction.followup.send("❌ El precio debe ser mayor a 0 monedas.", ephemeral=True)
            return
        if duration_days < 0:
            await interaction.followup.send("❌ La duración no puede ser negativa.", ephemeral=True)
            return

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO role_shop (guild_id, role_id, price, duration_days) VALUES (?, ?, ?, ?)",
            interaction.guild.id, role.id, price, duration_days
        )

        dur_text = f"{duration_days} días" if duration_days > 0 else "Permanente"
        embed = discord.Embed(
            title="🛒 Rol Añadido a la Tienda",
            description=(
                f"**Rol:** {role.mention}\n"
                f"**Precio:** {price} monedas\n"
                f"**Duración:** {dur_text}"
            ),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @roleshop_group.command(name="remove", description="Elimina un rol de la tienda (Solo Admins).")
    @app_commands.describe(role="El rol que se quiere quitar de la tienda.")
    @app_commands.default_permissions(administrator=True)
    async def roleshop_remove(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        existing = await self.bot.db.fetch(
            "SELECT 1 FROM role_shop WHERE guild_id = ? AND role_id = ?",
            interaction.guild.id, role.id
        )
        if not existing:
            await interaction.followup.send("❌ Ese rol no está a la venta en la tienda.", ephemeral=True)
            return

        await self.bot.db.execute(
            "DELETE FROM role_shop WHERE guild_id = ? AND role_id = ?",
            interaction.guild.id, role.id
        )

        await interaction.followup.send(f"✅ El rol {role.mention} ha sido retirado de la tienda.", ephemeral=True)

    @roleshop_group.command(name="list", description="Muestra todos los roles en venta en el servidor.")
    async def roleshop_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.ensure_tables()

        roles_data = await self.bot.db.fetch_all(
            "SELECT role_id, price, duration_days FROM role_shop WHERE guild_id = ? ORDER BY price ASC",
            interaction.guild.id
        )

        if not roles_data:
            await interaction.followup.send("❌ La tienda de roles está vacía en este servidor.")
            return

        embed = discord.Embed(
            title=f"🛒 Tienda de Roles de {interaction.guild.name}",
            description="Usa `/roleshop buy <rol>` para comprar cualquiera de estos roles.",
            color=discord.Color.blue()
        )

        for role_id, price, duration in roles_data:
            role = interaction.guild.get_role(role_id)
            if role:
                dur_text = f"{duration} días" if duration > 0 else "Permanente"
                embed.add_field(
                    name=f"✨ {role.name}",
                    value=f"**Precio:** {price} monedas\n**Duración:** {dur_text}",
                    inline=True
                )

        await interaction.followup.send(embed=embed)

    @roleshop_group.command(name="buy", description="Compra un rol de la tienda usando tus monedas.")
    @app_commands.describe(role="El rol que deseas comprar.")
    async def roleshop_buy(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        guild = interaction.guild
        member = interaction.user

        # Fetch role shop data
        role_data = await self.bot.db.fetch(
            "SELECT price, duration_days FROM role_shop WHERE guild_id = ? AND role_id = ?",
            guild.id, role.id
        )

        if not role_data:
            await interaction.followup.send("❌ Ese rol no está a la venta en la tienda de este servidor.", ephemeral=True)
            return

        price, duration_days = role_data[0], role_data[1]

        # Check if they already have the role
        if role in member.roles:
            await interaction.followup.send("❌ Ya tienes este rol asignado.", ephemeral=True)
            return

        # Check economy balance
        eco_cog = self.bot.get_cog("Economy")
        if not eco_cog:
            await interaction.followup.send("❌ El sistema de economía no está disponible en este momento.", ephemeral=True)
            return

        wallet, bank = await eco_cog.get_balance(member.id, guild.id)
        if wallet < price:
            await interaction.followup.send(
                f"❌ No tienes suficientes monedas en tu cartera para comprar este rol.\n"
                f"**Precio:** {price} monedas | **Tu cartera:** {wallet} monedas",
                ephemeral=True
            )
            return

        # Perform transaction and assign role
        try:
            # Add role first
            await member.add_roles(role, reason="Compra en tienda de roles.")
            
            # Deduct wallet balance
            await eco_cog.update_balance(member.id, -price, "wallet", guild.id)

            # Handle temporary role registration
            dur_text = "permanentemente"
            if duration_days > 0:
                expires_at = datetime.datetime.now() + datetime.timedelta(days=duration_days)
                expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

                await self.bot.db.execute(
                    "INSERT OR REPLACE INTO active_temp_roles (guild_id, user_id, role_id, expires_at) VALUES (?, ?, ?, ?)",
                    guild.id, member.id, role.id, expires_str
                )
                dur_text = f"durante {duration_days} días (expira el {expires_str})"

            embed = discord.Embed(
                title="✅ Compra Exitosa",
                description=(
                    f"Has adquirido el rol {role.mention} {dur_text}.\n"
                    f"Se han descontado **{price}** monedas de tu cartera."
                ),
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Log to mod channel if configured
            config_data = self.bot.config.get(guild.id)
            if config_data:
                channel_id = config_data.get('logs', {}).get('joins') # Using joins log or generic log channel
                if channel_id:
                    channel = guild.get_channel(int(channel_id))
                    if channel:
                        log_embed = discord.Embed(
                            title="🛒 Compra de Rol en Tienda",
                            description=(
                                f"**Usuario:** {member.mention} ({member.id})\n"
                                f"**Rol:** {role.mention} ({role.id})\n"
                                f"**Costo:** {price} monedas\n"
                                f"**Duración:** {duration_days} días" if duration_days > 0 else "Permanente"
                            ),
                            color=discord.Color.blue(),
                            timestamp=datetime.datetime.now()
                        )
                        await channel.send(embed=log_embed)

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ No tengo permisos suficientes para asignarte este rol.\n"
                "Asegúrate de que mi rol jerárquico esté por encima del rol que intentas comprar.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error inesperado al procesar la compra: {e}", ephemeral=True)
            self.logger.error(f"Error al comprar rol {role.id} para {member.id} en {guild.id}: {e}")

    # Expiration checker running every minute
    @tasks.loop(minutes=1)
    async def check_temp_roles(self):
        await self.bot.wait_until_ready()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Query expired roles
            expired = await self.bot.db.fetch_all(
                "SELECT guild_id, user_id, role_id FROM active_temp_roles WHERE expires_at <= ?",
                now_str
            )

            for guild_id, user_id, role_id in expired:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    # Clean up if guild not accessible
                    await self.bot.db.execute(
                        "DELETE FROM active_temp_roles WHERE guild_id = ? AND user_id = ? AND role_id = ?",
                        guild_id, user_id, role_id
                    )
                    continue

                member = guild.get_member(user_id)
                role = guild.get_role(role_id)

                if member and role:
                    try:
                        await member.remove_roles(role, reason="Expiración de rol temporal comprado.")
                        self.logger.info(f"Retirado rol temporal expirado {role.name} a {member} en {guild.name}")
                        
                        # DM the user
                        try:
                            await member.send(
                                f"⏳ Tu rol temporal **{role.name}** en el servidor **{guild.name}** ha expirado."
                            )
                        except discord.Forbidden:
                            pass # DMs are closed
                    except discord.Forbidden:
                        self.logger.warning(
                            f"No se pudo retirar el rol temporal {role.name} a {member.name} en {guild.name}: Sin permisos."
                        )
                    except Exception as e:
                        self.logger.error(f"Error al remover rol temporal en {guild.name}: {e}")

                # Remove database record
                await self.bot.db.execute(
                    "DELETE FROM active_temp_roles WHERE guild_id = ? AND user_id = ? AND role_id = ?",
                    guild_id, user_id, role_id
                )

        except Exception as e:
            self.logger.error(f"Error en el bucle check_temp_roles: {e}")

    @check_temp_roles.before_loop
    async def before_check_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(RoleShop(bot))
