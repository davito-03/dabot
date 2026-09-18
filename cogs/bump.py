import discord
from discord import app_commands
from discord.ext import commands
import datetime
from datetime import timezone
import asyncio
import logging
from typing import Optional
from utils.helpers import DASHBOARD_URL, DABOT_GREEN

logger = logging.getLogger("Dabot.Bump")
COOLDOWN_SECONDS = 7200  # 2 hours (Disboard standard)
REWARD_XP = 50
REWARD_COINS = 100


class Bump(commands.Cog):
    """Disboard-like server discovery, bump rewards, and automated 2h reminder system."""

    def __init__(self, bot):
        self.bot = bot
        self._active_reminders = {}

    async def _schedule_bump_reminder(self, guild_id: int, channel_id: int):
        """Wait 2 hours and notify the guild that /bump is ready again."""
        try:
            await asyncio.sleep(COOLDOWN_SECONDS)
            row = await self.bot.db.fetch(
                "SELECT last_bump_at, bump_reminder_role_id FROM server_discovery WHERE guild_id = ?",
                guild_id
            )
            if not row:
                return

            last_bump_str = row[0] if isinstance(row, (list, tuple)) else row.get("last_bump_at")
            reminder_role_id = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else row.get("bump_reminder_role_id")

            if last_bump_str:
                try:
                    lb = datetime.datetime.fromisoformat(last_bump_str)
                    if lb.tzinfo is None:
                        lb = lb.replace(tzinfo=timezone.utc)
                    now = datetime.datetime.now(timezone.utc)
                    # If already bumped again, exit
                    if (now - lb).total_seconds() < COOLDOWN_SECONDS - 10:
                        return
                except Exception:
                    pass

            guild = self.bot.get_guild(guild_id)
            if not guild:
                return

            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.TextChannel) or not channel.permissions_for(guild.me).send_messages:
                channel = guild.system_channel
                if not channel or not channel.permissions_for(guild.me).send_messages:
                    for ch in guild.text_channels:
                        if ch.permissions_for(guild.me).send_messages:
                            channel = ch
                            break

            if not channel:
                return

            role_ping = ""
            if reminder_role_id:
                role = guild.get_role(int(reminder_role_id))
                if role:
                    role_ping = f"{role.mention} "

            embed = discord.Embed(
                title="⏰ ¡El servidor ya se puede volver a promocionar!",
                description=(
                    f"{role_ping}Han pasado 2 horas desde el último bump.\n\n"
                    f"Escribe **/bump** para volver a posicionar a **{guild.name}** en lo más alto de la lista pública.\n\n"
                    f"🎁 *¡Recibirás `+{REWARD_XP} XP` y `+{REWARD_COINS} 🦞` al promocionar!*"
                ),
                color=DABOT_GREEN
            )
            embed.set_footer(text="Dabot Discovery • dabot.davito.es/servers", icon_url="https://davito.es/media/dabot.png")
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="🌐 Ver Servidores", url=f"{DASHBOARD_URL}/servers", style=discord.ButtonStyle.link))

            await channel.send(content=role_ping if role_ping else None, embed=embed, view=view)
        except Exception as e:
            logger.debug(f"Error in bump reminder for guild {guild_id}: {e}")

    async def _award_bump_rewards(self, guild_id: int, user_id: int) -> bool:
        """Award XP and coins for boosting the server."""
        try:
            # Economy: +100 coins
            await self.bot.db.execute(
                """INSERT INTO guild_economy (user_id, guild_id, balance, bank)
                   VALUES (?, ?, ?, 0)
                   ON CONFLICT(user_id, guild_id) DO UPDATE SET balance = balance + excluded.balance""",
                user_id, guild_id, REWARD_COINS
            )
            # Leveling: +50 XP
            await self.bot.db.execute(
                """INSERT INTO guild_levels (guild_id, user_id, xp, level, weekly_xp)
                   VALUES (?, ?, ?, 1, ?)
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET
                     xp = xp + excluded.xp,
                     weekly_xp = weekly_xp + excluded.weekly_xp""",
                guild_id, user_id, REWARD_XP, REWARD_XP
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to award bump rewards to {user_id}: {e}")
            return False

    async def _get_or_create_invite(self, guild: discord.Guild, channel: Optional[discord.TextChannel] = None) -> Optional[str]:
        """Fetch an existing invite or create a fresh permanent invite for the guild."""
        target_channel = channel or guild.system_channel
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            for ch in guild.text_channels:
                perms = ch.permissions_for(guild.me)
                if perms.create_instant_invite and perms.view_channel:
                    target_channel = ch
                    break

        if target_channel:
            try:
                perms = target_channel.permissions_for(guild.me)
                if perms.create_instant_invite:
                    invites = await target_channel.invites()
                    for inv in invites:
                        if inv.max_age == 0 or inv.max_age >= 86400:
                            return inv.url
                    new_inv = await target_channel.create_invite(
                        max_age=0,
                        max_uses=0,
                        temporary=False,
                        reason="Dabot Servidores / Disboard Bump Discovery"
                    )
                    return new_inv.url
            except Exception as e:
                logger.warning(f"Failed to create invite in {target_channel.name}: {e}")

        try:
            guild_invites = await guild.invites()
            if guild_invites:
                return guild_invites[0].url
        except Exception:
            pass

        return None

    bump_group = app_commands.Group(name="bump", description="Promociona este servidor en dabot.davito.es/servers")

    @bump_group.command(
        name="now",
        description="🚀 Promociona este servidor (cooldown de 2 horas)"
    )
    async def slash_bump(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Este comando solo se puede usar en un servidor.", ephemeral=True)
            return

        guild = interaction.guild
        now = datetime.datetime.now(timezone.utc)

        row = await self.bot.db.fetch(
            "SELECT bump_count, last_bump_at, invite_url, is_public, description, tags, category FROM server_discovery WHERE guild_id = ?",
            guild.id
        )

        last_bump_at = None
        bump_count = 0
        existing_invite = None
        is_public = 0

        if row:
            bump_count = row[0] if isinstance(row, (list, tuple)) else row.get("bump_count", 0)
            last_bump_str = row[1] if isinstance(row, (list, tuple)) else row.get("last_bump_at")
            existing_invite = row[2] if isinstance(row, (list, tuple)) else row.get("invite_url")
            is_public = int(row[3]) if isinstance(row, (list, tuple)) and row[3] is not None else int(row.get("is_public", 0) if isinstance(row, dict) else 0)

            if last_bump_str:
                try:
                    last_bump_at = datetime.datetime.fromisoformat(last_bump_str)
                    if last_bump_at.tzinfo is None:
                        last_bump_at = last_bump_at.replace(tzinfo=timezone.utc)
                except Exception:
                    last_bump_at = None

        if not is_public:
            embed = discord.Embed(
                title="🔒 Descubrimiento público desactivado",
                description=(
                    f"La visibilidad pública de **{guild.name}** en **dabot.davito.es/servers** está **desactivada por defecto** para proteger la privacidad de tu comunidad.\n\n"
                    "Un administrador del servidor puede activar la visibilidad y configurar la descripción y etiquetas con:\n"
                    "👉 **/bump_setup visible:True**"
                ),
                color=discord.Color.from_rgb(245, 158, 11)
            )
            embed.set_footer(text="Dabot Discovery • Privacidad por defecto", icon_url="https://davito.es/media/dabot.png")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if last_bump_at:
            diff = (now - last_bump_at).total_seconds()
            if diff < COOLDOWN_SECONDS:
                next_bump_ts = int(last_bump_at.timestamp() + COOLDOWN_SECONDS)
                embed = discord.Embed(
                    title="⏳ Espera para volver a hacer bump",
                    description=(
                        f"Este servidor ya fue promocionado recientemente.\n\n"
                        f"⏰ **Podrás volver a usar `/bump`:** <t:{next_bump_ts}:R> (<t:{next_bump_ts}:t>)\n"
                        f"🌐 **Lista pública:** [{DASHBOARD_URL}/servers]({DASHBOARD_URL}/servers)"
                    ),
                    color=discord.Color.from_rgb(245, 158, 11)
                )
                embed.set_footer(text="Dabot Discovery • Cooldown de 2 horas", icon_url="https://davito.es/media/dabot.png")
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Ver en la web", url=f"{DASHBOARD_URL}/servers", style=discord.ButtonStyle.link))
                await interaction.response.send_message(embed=embed, view=view)
                return

        await interaction.response.defer()

        invite_url = existing_invite
        target_channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        new_invite = await self._get_or_create_invite(guild, target_channel)
        if new_invite:
            invite_url = new_invite

        icon_hash = guild.icon.key if guild.icon else None
        new_bump_count = (bump_count or 0) + 1
        now_str = now.isoformat()

        await self.bot.db.execute(
            """INSERT INTO server_discovery
               (guild_id, name, description, icon, invite_url, invite_channel_id, member_count, bump_count, last_bump_at, last_bump_user_id, is_public, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 name = excluded.name,
                 icon = excluded.icon,
                 invite_url = COALESCE(excluded.invite_url, server_discovery.invite_url),
                 member_count = excluded.member_count,
                 bump_count = excluded.bump_count,
                 last_bump_at = excluded.last_bump_at,
                 last_bump_user_id = excluded.last_bump_user_id,
                 is_public = server_discovery.is_public,
                 updated_at = excluded.updated_at""",
            guild.id,
            guild.name,
            row[4] if row and len(row) > 4 and row[4] else f"Servidor {guild.name} en la comunidad de Dabot.",
            icon_hash,
            invite_url,
            interaction.channel_id,
            guild.member_count or 0,
            new_bump_count,
            now_str,
            interaction.user.id,
            is_public,
            now_str,
            now_str
        )

        # Rewards & 2h Reminder
        await self._award_bump_rewards(guild.id, interaction.user.id)
        asyncio.create_task(self._schedule_bump_reminder(guild.id, interaction.channel_id))

        next_ts = int(now.timestamp() + COOLDOWN_SECONDS)

        embed = discord.Embed(
            title="🚀 ¡Servidor promocionado con éxito!",
            description=(
                f"**{guild.name}** ha subido a la primera posición de la lista de servidores de Dabot.\n\n"
                f"🌐 **Descubrimiento:** [{DASHBOARD_URL.replace('https://', '')}/servers]({DASHBOARD_URL}/servers)\n"
                f"⏰ **Próximo bump disponible:** <t:{next_ts}:R> (<t:{next_ts}:t>)\n"
                f"👥 **Miembros actuales:** `{guild.member_count:,}`\n\n"
                f"🎁 **¡Recompensa ganada!** Recibes `+{REWARD_XP} XP` y `+{REWARD_COINS} 🦞` por apoyar al servidor."
            ),
            color=DABOT_GREEN
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(
            text=f"Promocionado por {interaction.user.display_name} • Bumps totales: {new_bump_count}",
            icon_url=interaction.user.display_avatar.url
        )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="🌐 Ver lista de servidores", url=f"{DASHBOARD_URL}/servers", style=discord.ButtonStyle.link))
        if invite_url:
            view.add_item(discord.ui.Button(label="🔗 Enlace del servidor", url=invite_url, style=discord.ButtonStyle.link))

        await interaction.followup.send(embed=embed, view=view)

    @commands.command(name="bump")
    @commands.guild_only()
    async def prefix_bump(self, ctx):
        """Prefix fallback for users typing !bump instead of /bump."""
        guild = ctx.guild
        now = datetime.datetime.now(timezone.utc)

        row = await self.bot.db.fetch(
            "SELECT bump_count, last_bump_at, invite_url, is_public, description FROM server_discovery WHERE guild_id = ?",
            guild.id
        )

        last_bump_at = None
        bump_count = 0
        existing_invite = None
        is_public = 0

        if row:
            bump_count = row[0] if isinstance(row, (list, tuple)) else row.get("bump_count", 0)
            last_bump_str = row[1] if isinstance(row, (list, tuple)) else row.get("last_bump_at")
            existing_invite = row[2] if isinstance(row, (list, tuple)) else row.get("invite_url")
            is_public = int(row[3]) if isinstance(row, (list, tuple)) and row[3] is not None else int(row.get("is_public", 0) if isinstance(row, dict) else 0)

            if last_bump_str:
                try:
                    last_bump_at = datetime.datetime.fromisoformat(last_bump_str)
                    if last_bump_at.tzinfo is None:
                        last_bump_at = last_bump_at.replace(tzinfo=timezone.utc)
                except Exception:
                    last_bump_at = None

        if not is_public:
            embed = discord.Embed(
                title="🔒 Descubrimiento público desactivado",
                description=(
                    f"La visibilidad pública de **{guild.name}** en **dabot.davito.es/servers** está **desactivada por defecto** para proteger la privacidad de tu comunidad.\n\n"
                    "Un administrador del servidor puede activarla con el comando:\n"
                    "👉 `/bump_setup visible:True`"
                ),
                color=discord.Color.from_rgb(245, 158, 11)
            )
            embed.set_footer(text="Dabot Discovery • Privacidad por defecto", icon_url="https://davito.es/media/dabot.png")
            await ctx.send(embed=embed)
            return

        if last_bump_at:
            diff = (now - last_bump_at).total_seconds()
            if diff < COOLDOWN_SECONDS:
                next_bump_ts = int(last_bump_at.timestamp() + COOLDOWN_SECONDS)
                embed = discord.Embed(
                    title="⏳ Espera para volver a hacer bump",
                    description=(
                        f"Este servidor ya fue promocionado recientemente.\n\n"
                        f"⏰ **Podrás volver a promocionar:** <t:{next_bump_ts}:R> (<t:{next_bump_ts}:t>)\n"
                        f"🌐 **Lista pública:** [{DASHBOARD_URL}/servers]({DASHBOARD_URL}/servers)"
                    ),
                    color=discord.Color.from_rgb(245, 158, 11)
                )
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Ver en la web", url=f"{DASHBOARD_URL}/servers", style=discord.ButtonStyle.link))
                await ctx.send(embed=embed, view=view)
                return

        invite_url = existing_invite or await self._get_or_create_invite(guild, ctx.channel)
        icon_hash = guild.icon.key if guild.icon else None
        new_bump_count = (bump_count or 0) + 1
        now_str = now.isoformat()

        await self.bot.db.execute(
            """INSERT INTO server_discovery
               (guild_id, name, description, icon, invite_url, invite_channel_id, member_count, bump_count, last_bump_at, last_bump_user_id, is_public, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 name = excluded.name,
                 icon = excluded.icon,
                 invite_url = COALESCE(excluded.invite_url, server_discovery.invite_url),
                 member_count = excluded.member_count,
                 bump_count = excluded.bump_count,
                 last_bump_at = excluded.last_bump_at,
                 last_bump_user_id = excluded.last_bump_user_id,
                 is_public = server_discovery.is_public,
                 updated_at = excluded.updated_at""",
            guild.id,
            guild.name,
            f"Servidor {guild.name} en la comunidad de Dabot.",
            icon_hash,
            invite_url,
            ctx.channel.id,
            guild.member_count or 0,
            new_bump_count,
            now_str,
            ctx.author.id,
            is_public,
            now_str,
            now_str
        )

        await self._award_bump_rewards(guild.id, ctx.author.id)
        asyncio.create_task(self._schedule_bump_reminder(guild.id, ctx.channel.id))

        next_ts = int(now.timestamp() + COOLDOWN_SECONDS)

        embed = discord.Embed(
            title="🚀 ¡Servidor promocionado con éxito!",
            description=(
                f"**{guild.name}** ha subido a la primera posición de la lista de servidores de Dabot.\n\n"
                f"🌐 **Descubrimiento:** [{DASHBOARD_URL.replace('https://', '')}/servers]({DASHBOARD_URL}/servers)\n"
                f"⏰ **Próximo bump disponible:** <t:{next_ts}:R> (<t:{next_ts}:t>)\n"
                f"👥 **Miembros actuales:** `{guild.member_count:,}`\n\n"
                f"🎁 **¡Recompensa ganada!** Recibes `+{REWARD_XP} XP` y `+{REWARD_COINS} 🦞` por apoyar al servidor."
            ),
            color=DABOT_GREEN
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(
            text=f"Promocionado por {ctx.author.display_name} • Bumps totales: {new_bump_count}",
            icon_url=ctx.author.display_avatar.url
        )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="🌐 Ver lista de servidores", url=f"{DASHBOARD_URL}/servers", style=discord.ButtonStyle.link))
        if invite_url:
            view.add_item(discord.ui.Button(label="🔗 Enlace del servidor", url=invite_url, style=discord.ButtonStyle.link))

        await ctx.send(embed=embed, view=view)

    @bump_group.command(
        name="setup",
        description="⚙️ Configura la descripción, etiquetas y visibilidad en /servers"
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        descripcion="Descripción personalizada que se verá en la lista pública",
        etiquetas="Etiquetas separadas por coma (ej: gaming, amigos, minecraft)",
        categoria="Categoría principal del servidor",
        visible="¿Mostrar en la lista pública de dabot.davito.es/servers? (Desactivado por defecto)",
        rol_recordatorio="Rol al que avisar cuando pasen las 2 horas de bump"
    )
    @app_commands.choices(categoria=[
        app_commands.Choice(name="🎮 Gaming / Videojuegos", value="Gaming"),
        app_commands.Choice(name="💬 Comunidad / Charla", value="Comunidad"),
        app_commands.Choice(name="🎌 Anime / Manga", value="Anime"),
        app_commands.Choice(name="🎵 Música", value="Música"),
        app_commands.Choice(name="💻 Tecnología / Programación", value="Tecnología"),
        app_commands.Choice(name="🎨 Arte / Diseño", value="Arte"),
        app_commands.Choice(name="🎲 Rol / RPG", value="Rol"),
        app_commands.Choice(name="🌐 Otros", value="Otros"),
    ])
    async def slash_bump_setup(
        self,
        interaction: discord.Interaction,
        descripcion: Optional[str] = None,
        etiquetas: Optional[str] = None,
        categoria: Optional[app_commands.Choice[str]] = None,
        visible: Optional[bool] = None,
        rol_recordatorio: Optional[discord.Role] = None
    ):
        if not interaction.guild:
            await interaction.response.send_message("❌ Este comando solo se puede usar en un servidor.", ephemeral=True)
            return

        guild = interaction.guild
        now_str = datetime.datetime.now(timezone.utc).isoformat()
        cat_val = categoria.value if categoria else "Comunidad"

        row = await self.bot.db.fetch(
            "SELECT description, tags, category, is_public, invite_url, bump_reminder_role_id FROM server_discovery WHERE guild_id = ?",
            guild.id
        )

        curr_desc = row[0] if row and len(row) > 0 and row[0] else f"Servidor {guild.name} en Dabot."
        curr_tags = row[1] if row and len(row) > 1 and row[1] else ""
        curr_cat = row[2] if row and len(row) > 2 and row[2] else "General"
        curr_public = row[3] if row and len(row) > 3 and row[3] is not None else 0
        curr_inv = row[4] if row and len(row) > 4 else None
        curr_role = row[5] if row and len(row) > 5 else None

        new_desc = descripcion.strip() if descripcion else curr_desc
        new_tags = etiquetas.strip() if etiquetas else curr_tags
        new_cat = cat_val if categoria else curr_cat
        new_public = 1 if visible is True else (0 if visible is False else curr_public)
        new_role_id = rol_recordatorio.id if rol_recordatorio else curr_role

        if not curr_inv:
            curr_inv = await self._get_or_create_invite(guild, interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None)

        await self.bot.db.execute(
            """INSERT INTO server_discovery
               (guild_id, name, description, icon, invite_url, tags, category, member_count, is_public, bump_reminder_role_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 name = excluded.name,
                 description = excluded.description,
                 tags = excluded.tags,
                 category = excluded.category,
                 is_public = excluded.is_public,
                 bump_reminder_role_id = excluded.bump_reminder_role_id,
                 member_count = excluded.member_count,
                 updated_at = excluded.updated_at""",
            guild.id,
            guild.name,
            new_desc,
            guild.icon.key if guild.icon else None,
            curr_inv,
            new_tags,
            new_cat,
            guild.member_count or 0,
            new_public,
            new_role_id,
            now_str,
            now_str
        )

        role_text = f"<@&{new_role_id}>" if new_role_id else "Ninguno"
        embed = discord.Embed(
            title="✅ Configuración de descubrimiento guardada",
            description=(
                f"**Descripción:** {new_desc}\n"
                f"**Categoría:** {new_cat}\n"
                f"**Etiquetas:** `{new_tags or 'Ninguna'}`\n"
                f"**Visibilidad:** {'Visible en /servers' if new_public else 'Oculto'}\n"
                f"**Rol de recordatorio:** {role_text}\n\n"
                f"Usa **/bump** para promocionar el servidor y ganar `+{REWARD_XP} XP` y `+{REWARD_COINS} 🦞`."
            ),
            color=DABOT_GREEN
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Bump(bot))
