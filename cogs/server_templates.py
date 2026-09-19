import asyncio
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import DASHBOARD_URL, DABOT_GREEN
from utils.server_templates import TEMPLATES, list_templates, resolve_template, save_template_config

SUPER_OWNER_ID = int(os.getenv("SUPER_OWNER_ID") or "0")
log = logging.getLogger("Dabot.Templates")


def _can_nuke(member: discord.Member) -> bool:
    if not member or not member.guild:
        return False
    if member.id == SUPER_OWNER_ID:
        return True
    return member.id == member.guild.owner_id


class ServerTemplates(commands.Cog):
    """Aplica una estructura de servidor (roles + categorías + canales) desde una plantilla."""

    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Dabot.Templates")

    template_group = app_commands.Group(
        name="template",
        description="Plantillas para montar un servidor desde cero.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @template_group.command(name="list", description="List available server templates.")
    @app_commands.describe(idioma="Language of names and channels")
    @app_commands.choices(idioma=[
        app_commands.Choice(name="Español", value="es"),
        app_commands.Choice(name="English", value="en"),
    ])
    async def template_list(self, interaction: discord.Interaction, idioma: str = "es"):
        lang = idioma if idioma in ("es", "en") else ("en" if str(interaction.locale).startswith("en") else "es")
        embed = discord.Embed(
            title="Dabot templates" if lang == "en" else "Plantillas de Dabot",
            description=(
                "Use `/template apply` on an empty (or almost empty) server. Logs, verification, welcome, rules and levels are wired automatically."
                if lang == "en" else
                "Usa `/template apply` en un servidor vacío (o casi). Logs, verificación, bienvenida, normas y niveles se enchufan solos."
            ),
            color=DABOT_GREEN,
        )
        for t in list_templates(lang):
            embed.add_field(
                name=f"{t['icon']} {t['name']}",
                value=f"{t['description']}\n`{t['roles']} roles · {t['channels']} canales`",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @template_group.command(name="apply", description="Create roles and channels from a community template.")
    @app_commands.describe(plantilla="Community type", idioma="Channel and role language")
    @app_commands.choices(
        plantilla=[
            app_commands.Choice(name="Videojuegos / Gaming", value="gaming"),
            app_commands.Choice(name="Comunidad social / Social", value="social"),
            app_commands.Choice(name="Streamer / creator", value="streamer"),
            app_commands.Choice(name="Tienda / Shop", value="shop"),
            app_commands.Choice(name="Estudio / Study", value="study"),
            app_commands.Choice(name="Clan / guild", value="clan"),
            app_commands.Choice(name="Música / Music", value="music"),
        ],
        idioma=[
            app_commands.Choice(name="Español", value="es"),
            app_commands.Choice(name="English", value="en"),
        ],
    )
    async def template_apply(self, interaction: discord.Interaction, plantilla: app_commands.Choice[str],
                             idioma: str = "es"):
        lang = idioma if idioma in ("es", "en") else "es"
        tpl = resolve_template(plantilla.value, lang)
        if not tpl:
            await interaction.response.send_message("Unknown template." if lang == "en" else "Plantilla desconocida.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        created = await apply_template(interaction.guild, tpl, self.logger, bot=self.bot)
        msg = (
            f"✅ Template **{tpl['name']}** applied: {created['roles']} roles, {created['channels']} channels. "
            f"Logs, verification, welcome, rules and levels are live."
            if lang == "en" else
            f"✅ Plantilla **{tpl['name']}** aplicada: {created['roles']} roles y {created['channels']} canales. "
            f"Logs, verificación, bienvenida, normas y niveles ya están activos."
        )
        await interaction.followup.send(msg, ephemeral=True)

    @template_group.command(name="nuke", description="Delete all channels and roles. Owner or superuser only.")
    @app_commands.default_permissions(administrator=True)
    async def nuke(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Only in a server.", ephemeral=True)
            return
        if not _can_nuke(interaction.user):
            await interaction.response.send_message(
                "Solo el **dueño del servidor** o el superusuario de Dabot pueden nukear.",
                ephemeral=True,
            )
            return
        view = NukeConfirmView(self.bot, interaction.user.id, interaction.guild.id)
        await interaction.response.send_message(
            f"⚠️ Esto **borra todos los canales y roles** de **{interaction.guild.name}**.\n"
            f"Escribe el nombre exacto del servidor para confirmar. No hay marcha atrás.",
            view=view,
            ephemeral=True,
        )


class NukeConfirmView(discord.ui.View):
    def __init__(self, bot, user_id: int, guild_id: int):
        super().__init__(timeout=90)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Continuar…", style=discord.ButtonStyle.danger)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("No es tu confirmación.", ephemeral=True)
            return
        await interaction.response.send_modal(NukeNameModal(self.bot, self.guild_id))


class NukeNameModal(discord.ui.Modal, title="Confirmar nuke"):
    nombre = discord.ui.TextInput(label="Nombre exacto del servidor", max_length=100)

    def __init__(self, bot, guild_id: int):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or guild.id != self.guild_id:
            await interaction.response.send_message("Servidor incorrecto.", ephemeral=True)
            return
        if not _can_nuke(interaction.user):
            await interaction.response.send_message("Sin permiso.", ephemeral=True)
            return
        if (self.nombre.value or "").strip() != guild.name:
            await interaction.response.send_message("El nombre no coincide. Nuke cancelado.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        stats = await nuke_guild(guild, interaction.user)
        await interaction.followup.send(
            f"💥 Nuke listo. Borrados **{stats['channels']}** canales y **{stats['roles']}** roles. "
            f"Queda {stats['landing']}.",
            ephemeral=True,
        )


async def nuke_guild(guild: discord.Guild, actor) -> dict:
    actor_id = getattr(actor, "id", 0)
    reason = f"Nuke by {actor} ({actor_id})"
    deleted_ch = 0
    deleted_roles = 0
    channels = list(guild.channels)
    for ch in channels:
        try:
            await ch.delete(reason=reason)
            deleted_ch += 1
            await asyncio.sleep(0.35)
        except Exception as e:
            log.warning("nuke channel %s: %s", getattr(ch, "name", ch.id), e)
    me = guild.me
    my_top = me.top_role if me else None
    for role in list(guild.roles):
        if role.is_default() or role.managed:
            continue
        if my_top and role >= my_top:
            continue
        try:
            await role.delete(reason=reason)
            deleted_roles += 1
            await asyncio.sleep(0.35)
        except Exception as e:
            log.warning("nuke role %s: %s", role.name, e)
    landing = "#general"
    try:
        ch = await guild.create_text_channel("general", reason=reason)
        landing = ch.mention
        mention = getattr(actor, "mention", None) or f"`{actor_id}`"
        await ch.send(
            f"Servidor reiniciado por {mention}. Usa `/template apply` para montar Dabot de cero."
        )
    except Exception:
        pass
    return {"channels": deleted_ch, "roles": deleted_roles, "landing": landing}


def _ow_staff():
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        manage_messages=True,
        embed_links=True,
        attach_files=True,
        create_public_threads=True,
        send_messages_in_threads=True,
        add_reactions=True,
        use_application_commands=True,
    )


def _ow_readonly(*, reactions=True):
    """Members can read info/announcements, not talk or open threads."""
    return discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=False,
        send_tts_messages=False,
        create_public_threads=False,
        create_private_threads=False,
        send_messages_in_threads=False,
        attach_files=False,
        embed_links=False,
        add_reactions=reactions,
        use_application_commands=False,
    )


def _ow_talk():
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        embed_links=True,
        attach_files=True,
        add_reactions=True,
        use_application_commands=True,
        create_public_threads=False,
        create_private_threads=False,
        send_messages_in_threads=False,
    )


READONLY_SLOTS = {"rules", "announcements", "welcome", "levels"}


def _overwrites(access: str, everyone, staff_roles, verified, unverified, me):
    ow = {}
    if me:
        ow[me] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, manage_messages=True,
            read_message_history=True, embed_links=True, attach_files=True, use_application_commands=True,
        )
    staff_ow = _ow_staff()
    if access == "staff":
        ow[everyone] = discord.PermissionOverwrite(view_channel=False)
        for r in staff_roles:
            ow[r] = staff_ow
    elif access == "verify":
        ow[everyone] = _ow_readonly(reactions=False)
        if unverified:
            ow[unverified] = _ow_talk()
        if verified:
            ow[verified] = _ow_talk()
        for r in staff_roles:
            ow[r] = staff_ow
    elif access == "info":
        # Rules, announcements, welcome, levels: members read, staff writes.
        ow[everyone] = _ow_readonly()
        if unverified:
            ow[unverified] = _ow_readonly()
        if verified:
            ow[verified] = _ow_readonly()
        for r in staff_roles:
            ow[r] = staff_ow
    elif access == "tickets":
        ow[everyone] = _ow_readonly(reactions=True)
        if unverified:
            ow[unverified] = _ow_readonly(reactions=True)
        if verified:
            ow[verified] = _ow_readonly(reactions=True)
        for r in staff_roles:
            ow[r] = staff_ow
    else:  # verified community
        ow[everyone] = discord.PermissionOverwrite(view_channel=False)
        if unverified:
            ow[unverified] = discord.PermissionOverwrite(view_channel=False)
        if verified:
            ow[verified] = _ow_talk()
        for r in staff_roles:
            ow[r] = staff_ow
    return ow


def _channel_overwrites(access, slot, everyone, staff_roles, verified, unverified, me):
    ow = _overwrites(access, everyone, staff_roles, verified, unverified, me)
    if slot == "commands":
        talk = _ow_talk()
        if verified:
            ow[verified] = talk
        if everyone:
            ow[everyone] = talk
    elif slot == "autorole":
        read = _ow_readonly(reactions=True)
        if everyone:
            ow[everyone] = read
        if verified:
            ow[verified] = read
        if unverified:
            ow[unverified] = read
    elif slot in READONLY_SLOTS or (access == "info" and slot not in ("commands", "autorole")):
        read = _ow_readonly()
        if everyone:
            ow[everyone] = read
        if verified:
            ow[verified] = read
        if unverified:
            ow[unverified] = read
    elif slot == "tickets":
        read = _ow_readonly(reactions=True)
        if everyone:
            ow[everyone] = read
        if unverified:
            ow[unverified] = read
        if verified:
            ow[verified] = read
    elif slot == "verify":
        if unverified:
            ow[unverified] = _ow_talk()
        if everyone:
            ow[everyone] = _ow_readonly(reactions=False)
    return ow


async def apply_template(guild: discord.Guild, tpl: dict, logger, bot=None) -> dict:
    created_roles = 0
    created_channels = 0
    # Leftover #general after a nuke (uncategorized) — drop it so the template owns general.
    for ch in list(guild.text_channels):
        if ch.name == "general" and ch.category is None:
            try:
                await ch.delete(reason="Dabot template: leftover general after nuke")
            except Exception:
                pass
    role_by_key = {}
    staff_roles = []
    slots = {}

    for spec in tpl["roles"]:
        existing = discord.utils.get(guild.roles, name=spec["name"])
        role = existing
        if not existing:
            try:
                perms = discord.Permissions(permissions=int(spec.get("permissions") or 0))
                role = await guild.create_role(
                    name=spec["name"],
                    colour=discord.Colour(spec.get("color") or 0),
                    hoist=bool(spec.get("hoist")),
                    permissions=perms,
                    reason=f"Dabot template {tpl['id']}",
                )
                created_roles += 1
                await asyncio.sleep(0.35)
            except Exception as e:
                logger.warning("role create failed %s: %s", spec["name"], e)
                continue
        role_by_key[spec["id"]] = role
        if "staff" in (spec.get("tags") or []):
            staff_roles.append(role)
        if "unverified" in (spec.get("tags") or []):
            slots["role.unverified"] = role.id
        if "verified" in (spec.get("tags") or []):
            slots["role.verified"] = role.id

    verified = role_by_key.get("verified")
    unverified = role_by_key.get("unverified")
    everyone = guild.default_role
    me = guild.me

    for cat in tpl["categories"]:
        access = cat.get("access") or ("staff" if cat.get("staff_only") else "verified")
        ow = _overwrites(access, everyone, staff_roles, verified, unverified, me)
        category = discord.utils.get(guild.categories, name=cat["name"])
        if not category:
            try:
                category = await guild.create_category(cat["name"], overwrites=ow, reason=f"Dabot template {tpl['id']}")
                created_channels += 1
                await asyncio.sleep(0.35)
            except Exception as e:
                logger.warning("category create failed %s: %s", cat["name"], e)
                continue
        else:
            try:
                await category.edit(overwrites=ow)
            except Exception:
                pass
        for ch in cat["channels"]:
            name = ch["name"]
            slug = name.lower().replace(" ", "-")
            exists = discord.utils.get(category.channels, name=slug) or discord.utils.get(guild.channels, name=slug)
            channel = exists
            ch_ow = _channel_overwrites(access, ch.get("slot"), everyone, staff_roles, verified, unverified, me)
            if not exists:
                try:
                    if ch.get("type") == 2:
                        channel = await guild.create_voice_channel(name, category=category, overwrites=ch_ow, reason=f"Dabot template {tpl['id']}")
                    else:
                        channel = await guild.create_text_channel(
                            name,
                            category=category,
                            topic=(ch.get("topic") or "")[:1024],
                            overwrites=ch_ow,
                            reason=f"Dabot template {tpl['id']}",
                        )
                    created_channels += 1
                    await asyncio.sleep(0.35)
                except Exception as e:
                    logger.warning("channel create failed %s: %s", name, e)
                    continue
            else:
                try:
                    await channel.edit(overwrites=ch_ow, reason=f"Dabot template {tpl['id']} overwrites")
                except Exception as e:
                    logger.warning("channel overwrite failed %s: %s", name, e)
            if channel and ch.get("slot"):
                slots[ch["slot"]] = channel.id

    staff_names = [r.name for r in staff_roles]
    try:
        save_template_config(guild.id, slots, tpl, staff_names)
    except Exception as e:
        logger.warning("template config save failed: %s", e)

    if bot:
        try:
            bot.config.set_config(guild.id, "lang", tpl.get("locale") or "es-ES")
            for key in ("logs.messages", "logs.moderation", "logs.voice", "logs.members", "logs.joins", "logs.alts", "logs.hijack", "logs.tickets", "logs.server", "logs.verification"):
                if slots.get(key):
                    bot.config.set_config(guild.id, key, str(slots[key]))
            if slots.get("welcome"):
                bot.config.set_config(guild.id, "welcome.enabled", True)
                bot.config.set_config(guild.id, "welcome.channel_id", str(slots["welcome"]))
                bot.config.set_config(guild.id, "welcome.message", tpl.get("welcome"))
                bot.config.set_config(guild.id, "goodbye.enabled", True)
                bot.config.set_config(guild.id, "goodbye.channel_id", str(slots["welcome"]))
            if slots.get("levels"):
                bot.config.set_config(guild.id, "leveling.enabled", False)
                bot.config.set_config(guild.id, "leveling.level_up_channel", str(slots["levels"]))
                bot.config.set_config(guild.id, "leveling.leaderboard_channel", str(slots["levels"]))
            bot.config.set_config(guild.id, "achievements.enabled", False)
            bot.config.set_config(guild.id, "chatbot.enabled", False)
            bot.config.set_config(guild.id, "automod.enabled", True)
            bot.config.set_config(guild.id, "automod.hijack", True)
            bot.config.set_config(guild.id, "automod.block_invites", True)
            alert_ch = slots.get("logs.moderation") or slots.get("logs.joins")
            if alert_ch and bot.db:
                await bot.db.execute(
                    """INSERT OR REPLACE INTO antiraid_config
                       (guild_id, enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes)
                       VALUES (?, 1, 10, 10, ?, 5)""",
                    guild.id, int(alert_ch),
                )
            bot.config.set_config(guild.id, "tickets.category_name", tpl.get("tickets_category") or "Tickets")
            bot.config.set_config(guild.id, "tickets.staff_roles", staff_names)
            if tpl.get("ticket_categories"):
                bot.config.set_config(guild.id, "tickets.categories", tpl["ticket_categories"])
            if tpl.get("ticket_panel"):
                bot.config.set_config(guild.id, "tickets.panel", tpl["ticket_panel"])
            if slots.get("logs.tickets"):
                bot.config.set_config(guild.id, "tickets.transcript_channel_id", str(slots["logs.tickets"]))
        except Exception as e:
            logger.warning("bot.config template wire failed: %s", e)

    await _post_starter_messages(guild, tpl, slots, bot, logger)
    return {"roles": created_roles, "channels": created_channels, "slots": {k: str(v) for k, v in slots.items()}}


async def _post_starter_messages(guild, tpl, slots, bot, logger):
    from utils.template_posts import (
        announcements_payload,
        catalog_payloads,
        commands_payload,
        embed_from_payload,
        economy_payload,
        howto_buy_payload,
        levels_payload,
        rules_payloads,
        verify_payload,
        welcome_payload,
    )
    info_slots = {"rules", "announcements", "welcome", "commands", "levels", "autorole"}

    async def send_starter(channel, slot, *, embed=None, embeds=None, view=None):
        kwargs = {"view": view} if view is not None else {}
        if embeds:
            kwargs["embeds"] = embeds[:10]
        elif embed is not None:
            kwargs["embed"] = embed
        message = await channel.send(**kwargs)
        if slot not in info_slots:
            try:
                await message.pin(reason="Dabot template starter message")
            except Exception as e:
                logger.warning("template pin failed %s: %s", slot, e)
        return message

    lang = tpl.get("lang") or "es"
    rules_id = slots.get("rules")
    if rules_id:
        ch = guild.get_channel(rules_id)
        if ch:
            try:
                for payload in rules_payloads(tpl, lang, slots):
                    await send_starter(ch, "rules", embed=embed_from_payload(payload))
                    await asyncio.sleep(0.35)
            except Exception as e:
                logger.warning("rules post: %s", e)
    verify_id = slots.get("verify")
    if verify_id and bot:
        ch = guild.get_channel(verify_id)
        if ch:
            try:
                from cogs.verification import VerificationPanelView
                url = f"{DASHBOARD_URL}/verify/{guild.id}"
                embed = embed_from_payload(verify_payload(tpl, lang, slots, guild.id))
                await send_starter(ch, "verify", embed=embed, view=VerificationPanelView(bot, guild.id))
            except Exception as e:
                logger.warning("verify panel: %s", e)
    tickets_id = slots.get("tickets")
    logs_tickets_id = slots.get("logs.tickets")
    if tickets_id and bot:
        ch = guild.get_channel(tickets_id)
        if ch:
            try:
                from cogs.tickets import make_ticket_panel
                extra = None
                log_ch = guild.get_channel(logs_tickets_id) if logs_tickets_id else None
                if log_ch:
                    extra = (
                        f"Cada ticket se registra en {log_ch.mention} con el **nombre** y el **enlace web**."
                        if lang != "en" else
                        f"Each ticket is logged in {log_ch.mention} with its **name** and **web link**."
                    )
                embeds, view = make_ticket_panel(bot, guild.id, extra=extra)
                await send_starter(ch, "tickets", embeds=embeds, view=view)
            except Exception as e:
                logger.warning("ticket panel: %s", e)
    if logs_tickets_id:
        ch = guild.get_channel(logs_tickets_id)
        if ch:
            try:
                url = f"{DASHBOARD_URL}/dashboard?guild={guild.id}"
                embed = discord.Embed(
                    title="🎫 Logs de tickets" if lang != "en" else "🎫 Ticket logs",
                    description=(
                        "Aquí se publica **cada ticket** al abrirse y al cerrarse:\n"
                        "• Nombre del canal (`ticket-pedidos-…`)\n"
                        "• Tipo (Pedidos, Soporte, etc.)\n"
                        "• Usuario y canal de Discord\n"
                        f"• Enlace directo a la web: {url}\n\n"
                        "El historial completo vive en dabot.davito.es → Tickets."
                        if lang != "en" else
                        "Every ticket is posted here when it opens and closes:\n"
                        "• Channel name (`ticket-orders-…`)\n"
                        "• Type (Orders, Support, etc.)\n"
                        "• User and Discord channel\n"
                        f"• Direct web link: {url}\n\n"
                        "The full transcript lives on dabot.davito.es → Tickets."
                    ),
                    color=DABOT_GREEN,
                )
                embed.set_footer(text="Dabot · dabot.davito.es")
                await send_starter(ch, "logs.tickets", embed=embed)
            except Exception as e:
                logger.warning("ticket logs intro: %s", e)
    logs_verify_id = slots.get("logs.verification")
    if logs_verify_id:
        ch = guild.get_channel(logs_verify_id)
        if ch:
            try:
                url = f"{DASHBOARD_URL}/dashboard?guild={guild.id}"
                embed = discord.Embed(
                    title="🛡️ Logs de verificación" if lang != "en" else "🛡️ Verification logs",
                    description=(
                        "Aquí se publica **cada verificación** de este servidor:\n"
                        "• Usuario (mención + ID)\n"
                        "• Método (navegador, emoji, mates, staff)\n"
                        "• Estado y riesgo de multicuenta\n"
                        "• Códigos de red `ip:` (misma IP) y `net:` (misma subred). Nunca la IP en claro.\n\n"
                        f"El listado de gente verificada: {url}"
                        if lang != "en" else
                        "Every verification on this server is posted here:\n"
                        "• User (mention + ID)\n"
                        "• Method (browser, emoji, math, staff)\n"
                        "• Status and alt-account risk\n"
                        "• Network codes `ip:` (same address) and `net:` (same subnet). Never the raw IP.\n\n"
                        f"Verified people list: {url}"
                    ),
                    color=DABOT_GREEN,
                )
                embed.set_footer(text="Dabot · dabot.davito.es")
                await send_starter(ch, "logs.verification", embed=embed)
            except Exception as e:
                logger.warning("verification logs intro: %s", e)
    autorole_id = slots.get("autorole")
    if autorole_id and bot:
        ch = guild.get_channel(autorole_id)
        if ch:
            try:
                from cogs.roles import build_autorole_view
                extra = [r for r in guild.roles if not r.is_default() and not r.managed and r.name not in ("Admin", "Moderador", "Moderator", "Helper", "No verificado", "Unverified", "Verificado", "Verified", "Silenciado", "Muted", "Bot")]
                extra = [r for r in extra if not r.permissions.administrator][:10]
                if extra:
                    embed, view = build_autorole_view(
                        title="Elige tus roles" if lang != "en" else "Pick your roles",
                        description=(
                            "Pulsa un botón para asignarte o quitarte el rol. El staff puede borrar este mensaje si no lo quiere."
                            if lang != "en" else
                            "Press a button to add or remove a role. Staff can delete this message."
                        ),
                        options=[(r.name, r, None) for r in extra],
                    )
                    await send_starter(ch, "autorole", embed=embed, view=view)
            except Exception as e:
                logger.warning("autorole panel: %s", e)
    cmd_id = slots.get("commands")
    if cmd_id:
        ch = guild.get_channel(cmd_id)
        if ch:
            try:
                await send_starter(ch, "commands", embed=embed_from_payload(commands_payload(tpl, lang, slots)))
            except Exception as e:
                logger.warning("commands post: %s", e)
    welcome_id = slots.get("welcome")
    if welcome_id:
        ch = guild.get_channel(welcome_id)
        if ch:
            try:
                await send_starter(ch, "welcome", embed=embed_from_payload(welcome_payload(tpl, lang, slots)))
            except Exception as e:
                logger.warning("welcome post: %s", e)
    levels_id = slots.get("levels")
    if levels_id:
        ch = guild.get_channel(levels_id)
        if ch:
            try:
                await send_starter(ch, "levels", embed=embed_from_payload(levels_payload(tpl, lang, slots)))
            except Exception as e:
                logger.warning("levels post: %s", e)
    ann_id = slots.get("announcements")
    if ann_id:
        ch = guild.get_channel(ann_id)
        if ch:
            try:
                await send_starter(ch, "announcements", embed=embed_from_payload(announcements_payload(tpl, lang, slots)))
            except Exception as e:
                logger.warning("announcements post: %s", e)
    for slot, kind in (("economy", "main"), ("economy.top", "top"), ("economy.shop", "shop")):
        channel_id = slots.get(slot)
        if channel_id:
            ch = guild.get_channel(channel_id)
            if ch:
                try:
                    await send_starter(ch, slot, embed=embed_from_payload(economy_payload(tpl, lang, slots, kind)))
                except Exception as e:
                    logger.warning("economy post %s: %s", slot, e)
    catalog_id = slots.get("catalog")
    if catalog_id:
        ch = guild.get_channel(catalog_id)
        if ch:
            try:
                payloads = catalog_payloads(tpl, lang, slots)
                for i in range(0, len(payloads), 10):
                    await ch.send(embeds=[embed_from_payload(p) for p in payloads[i:i + 10]])
                    await asyncio.sleep(0.35)
            except Exception as e:
                logger.warning("catalog post: %s", e)
    howto_id = slots.get("howto")
    if howto_id:
        ch = guild.get_channel(howto_id)
        if ch:
            try:
                await send_starter(ch, "howto", embed=embed_from_payload(howto_buy_payload(tpl, lang, slots)))
            except Exception as e:
                logger.warning("howto post: %s", e)


async def setup(bot):
    await bot.add_cog(ServerTemplates(bot))
