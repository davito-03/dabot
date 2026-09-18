"""
Tickets Cog — registro principal en dabot.davito.es

Cada mensaje del ticket se guarda en SQLite y se consulta desde el panel web.
Si el servidor configura un canal de transcripciones, se replica también a Discord.
"""

import logging
import discord
from discord.ext import commands
import datetime
import os
import yaml
import asyncio
import aiohttp
import io
import re
from typing import Optional
import json
from utils.helpers import DASHBOARD_URL

log = logging.getLogger("Dabot.Tickets")

TICKET_CATEGORIES = [
    {"id": "support", "label": "Soporte", "emoji": "📩", "description": "Ayuda general", "category": "Tickets · Soporte"},
    {"id": "report", "label": "Reporte", "emoji": "🚨", "description": "Reportar a un usuario", "category": "Tickets · Reportes"},
    {"id": "idea", "label": "Sugerencia", "emoji": "💡", "description": "Proponer una idea", "category": "Tickets · Sugerencias"},
    {"id": "other", "label": "Otro", "emoji": "💬", "description": "Cualquier otra consulta", "category": "Tickets · General"},
]


def slug_ticket_id(name: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
    return raw or "cat"


def _parse_select_emoji(raw: str | None):
    text = (raw or "").strip()
    if not text:
        return "📩"
    m = re.match(r"<a?:([\w~]+):(\d+)>", text)
    if m:
        return discord.PartialEmoji(name=m.group(1), id=int(m.group(2)), animated=text.startswith("<a:"))
    return text[:32]


def normalize_ticket_category(item: dict, fallback_id: str | None = None) -> dict | None:
    if not isinstance(item, dict):
        return None
    label = str(item.get("label") or item.get("name") or "").strip()
    if not label:
        return None
    cat_id = str(item.get("id") or slug_ticket_id(label) or fallback_id or "cat")[:90]
    emoji = str(item.get("emoji") or "📩").strip() or "📩"
    desc = str(item.get("description") or item.get("desc") or label).strip()
    folder = str(item.get("category") or item.get("folder") or f"Tickets · {label}").strip()
    image = str(item.get("image") or item.get("image_url") or "").strip()
    if image and not image.startswith("https://"):
        image = ""
    price = str(item.get("price") or "").strip()[:80]
    details = str(item.get("details") or item.get("body") or "").strip()[:1000]
    color_raw = item.get("color")
    try:
        if isinstance(color_raw, str) and color_raw.startswith("#"):
            color = int(color_raw[1:], 16)
        else:
            color = int(color_raw) if color_raw not in (None, "") else None
    except Exception:
        color = None
    out = {
        "id": cat_id,
        "label": label[:100],
        "emoji": emoji[:64],
        "description": desc[:100],
        "category": folder[:100],
    }
    if image:
        out["image"] = image[:400]
    if price:
        out["price"] = price
    if details:
        out["details"] = details
    if color is not None:
        out["color"] = color
    return out


def categories_from_cfg(tickets_cfg: dict | None) -> list[dict]:
    cfg = tickets_cfg or {}
    raw = cfg.get("categories")
    out = []
    seen = set()
    if isinstance(raw, list):
        for item in raw:
            cat = normalize_ticket_category(item)
            if not cat or cat["id"] in seen:
                continue
            seen.add(cat["id"])
            out.append(cat)
            if len(out) >= 125:
                break
    return out or [dict(c) for c in TICKET_CATEGORIES]


def guild_ticket_categories(bot, guild_id) -> list[dict]:
    try:
        cfg = bot.config.get(int(guild_id), "tickets") or {}
    except Exception:
        cfg = {}
    return categories_from_cfg(cfg)


def ticket_category(cat_id: str, bot=None, guild_id=None) -> dict:
    cats = guild_ticket_categories(bot, guild_id) if bot and guild_id else TICKET_CATEGORIES
    for item in cats:
        if item["id"] == cat_id:
            return item
    for item in TICKET_CATEGORIES:
        if item["id"] == cat_id:
            return item
    label = cat_id.replace("-", " ").strip() or "Ticket"
    return {"id": cat_id[:90], "label": label[:100], "emoji": "📩", "description": label[:100], "category": f"Tickets · {label}"[:100]}


def _chunks(items, size=25):
    for i in range(0, len(items), size):
        yield i // size, items[i:i + size]


def _select_option(item: dict) -> discord.SelectOption:
    kwargs = {
        "label": item["label"][:100],
        "value": item["id"][:100],
        "description": (item.get("description") or item["label"])[:100],
    }
    try:
        kwargs["emoji"] = _parse_select_emoji(item.get("emoji"))
        return discord.SelectOption(**kwargs)
    except Exception:
        kwargs.pop("emoji", None)
        return discord.SelectOption(**kwargs)


def format_ticket_content(message: discord.Message) -> str:
    """Make mentions, roles and channels readable in the web transcript."""
    content = message.content or ""
    for member in message.mentions:
        for token in (f"<@{member.id}>", f"<@!{member.id}>"):
            content = content.replace(token, f"@{member.display_name} (`{member.id}`)")
    for role in message.role_mentions:
        content = content.replace(f"<@&{role.id}>", f"@{role.name} (`{role.id}`)")
    for channel in message.channel_mentions:
        content = content.replace(f"<#{channel.id}>", f"#{channel.name} (`{channel.id}`)")
    return content


# ---------------------------------------------------------------------------
# Helper – obtener o crear el webhook del canal de log
# ---------------------------------------------------------------------------

async def _get_or_create_webhook(channel: discord.TextChannel, name: str = "Dabot Ticket Log") -> discord.Webhook:
    """Devuelve el webhook de logs existente o crea uno nuevo."""
    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == name:
            return wh
    return await channel.create_webhook(name=name, reason="Dabot – sistema de logs de tickets")


# ---------------------------------------------------------------------------
# Cog principal
# ---------------------------------------------------------------------------

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Mapeo: channel_id (ticket) -> thread_id (hilo opcional en Discord)
        self._ticket_threads: dict = {}
        self._ticket_ids: dict = {}  # channel_id -> web ticket id
        # Cache de webhooks: log_channel_id -> Webhook
        self._webhooks: dict = {}

    async def cog_load(self):
        await self.bot.db.execute('''
            CREATE TABLE IF NOT EXISTS active_tickets (
                channel_id INTEGER PRIMARY KEY,
                thread_id INTEGER,
                ticket_id INTEGER
            )
        ''')
        try:
            await self.bot.db.execute("ALTER TABLE active_tickets ADD COLUMN ticket_id INTEGER")
        except Exception:
            pass
        for sql in (
            "ALTER TABLE tickets ADD COLUMN category TEXT",
            "ALTER TABLE tickets ADD COLUMN web_url TEXT",
            "ALTER TABLE ticket_messages ADD COLUMN edited INTEGER DEFAULT 0",
            "ALTER TABLE ticket_messages ADD COLUMN previous_content TEXT",
        ):
            try:
                await self.bot.db.execute(sql)
            except Exception:
                pass
        await self.bot.db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER,
                opener_id INTEGER NOT NULL,
                opener_name TEXT,
                opener_avatar TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by INTEGER,
                claimed_name TEXT,
                reason TEXT,
                created_at TEXT NOT NULL,
                closed_at TEXT,
                closed_by INTEGER,
                closed_name TEXT
            )
        ''')
        await self.bot.db.execute('''
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                discord_message_id INTEGER,
                user_id INTEGER,
                username TEXT,
                avatar TEXT,
                content TEXT,
                attachments TEXT,
                deleted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        ''')
        try:
            rows = await self.bot.db.fetch_all(
                "SELECT channel_id, thread_id, ticket_id FROM active_tickets"
            )
            for row in rows:
                channel_id = row[0]
                thread_id = row[1]
                ticket_id = row[2] if len(row) > 2 else None
                if thread_id:
                    self._ticket_threads[channel_id] = thread_id
                if ticket_id:
                    self._ticket_ids[channel_id] = ticket_id
            log.info(f"Cargados {len(self._ticket_ids)} tickets activos desde la base de datos.")
        except Exception as e:
            log.error(f"Error al cargar tickets activos: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        register_ticket_views(self.bot)
        self.bot.add_view(TicketControls(self.bot, self))
        log.info("Tickets Cog cargado.")

    # ------------------------------------------------------------------
    # Comandos de configuración
    # ------------------------------------------------------------------

    ticket_group = discord.app_commands.Group(
        name="ticket",
        description="Sistema de tickets de Dabot.",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @ticket_group.command(name="panel", description="Publica el panel para abrir tickets en este canal.")
    async def ticket_panel_slash(self, interaction: discord.Interaction):
        log_ch = await self._get_log_channel(interaction.guild)
        extra = None
        if log_ch:
            extra = f"Los logs (nombre + enlace web) van a {log_ch.mention}."
        embeds, view = make_ticket_panel(self.bot, interaction.guild.id, extra=extra)
        await interaction.response.send_message(embeds=embeds[:10], view=view)

    @ticket_group.command(name="addcategory", description="Añade un tipo de ticket al selector (tiendas, pedidos, etc.).")
    @discord.app_commands.describe(
        nombre="Nombre que verá el usuario (ej. Pedidos)",
        emoji="Emoji del desplegable",
        descripcion="Texto corto bajo el nombre",
        carpeta="Categoría de Discord donde se crean (opcional)",
    )
    async def ticket_addcategory(
        self,
        interaction: discord.Interaction,
        nombre: str,
        emoji: str = "📩",
        descripcion: str | None = None,
        carpeta: str | None = None,
    ):
        cats = guild_ticket_categories(self.bot, interaction.guild.id)
        new = normalize_ticket_category({
            "label": nombre,
            "emoji": emoji,
            "description": descripcion or nombre,
            "category": carpeta or f"Tickets · {nombre.strip()}",
        })
        if not new:
            await interaction.response.send_message("❌ Nombre inválido.", ephemeral=True)
            return
        existing_ids = {c["id"] for c in cats}
        if new["id"] in existing_ids:
            base = new["id"]
            n = 2
            while f"{base}-{n}" in existing_ids:
                n += 1
            new["id"] = f"{base}-{n}"
        if len(cats) >= 125:
            await interaction.response.send_message("❌ Máximo 125 tipos de ticket (5 menús de 25).", ephemeral=True)
            return
        cats.append(new)
        self.bot.config.set_config(interaction.guild.id, "tickets.categories", cats)
        extra = ""
        if len(cats) > 25:
            extra = f" Hay {len(cats)} tipos: el panel usará varios desplegables."
        await interaction.response.send_message(
            f"✅ Categoría **{new['emoji']} {new['label']}** añadida (`{new['id']}`).\n"
            f"Vuelve a publicar `/ticket panel` para actualizar el selector.{extra}",
            ephemeral=True,
        )

    @ticket_group.command(name="removecategory", description="Quita un tipo de ticket del selector.")
    @discord.app_commands.describe(nombre="Nombre o id de la categoría")
    async def ticket_removecategory(self, interaction: discord.Interaction, nombre: str):
        cats = guild_ticket_categories(self.bot, interaction.guild.id)
        key = (nombre or "").strip().lower()
        kept = [c for c in cats if c["id"].lower() != key and c["label"].lower() != key]
        if len(kept) == len(cats):
            await interaction.response.send_message("❌ No encontré esa categoría. Usa `/ticket categories`.", ephemeral=True)
            return
        if not kept:
            kept = [dict(c) for c in TICKET_CATEGORIES]
            self.bot.config.set_config(interaction.guild.id, "tickets.categories", kept)
            await interaction.response.send_message(
                "⚠️ Era la última. He restaurado las categorías predefinidas (Soporte, Reporte, Sugerencia, Otro).",
                ephemeral=True,
            )
            return
        self.bot.config.set_config(interaction.guild.id, "tickets.categories", kept)
        await interaction.response.send_message(
            f"✅ Categoría **{nombre}** eliminada. Publica de nuevo `/ticket panel`.",
            ephemeral=True,
        )

    @ticket_removecategory.autocomplete("nombre")
    async def _remove_cat_ac(self, interaction: discord.Interaction, current: str):
        cats = guild_ticket_categories(self.bot, interaction.guild_id)
        q = (current or "").lower()
        out = []
        for c in cats:
            if q and q not in c["label"].lower() and q not in c["id"].lower():
                continue
            out.append(discord.app_commands.Choice(name=f"{c.get('emoji') or ''} {c['label']}".strip()[:100], value=c["id"]))
            if len(out) >= 25:
                break
        return out

    @ticket_group.command(name="categories", description="Lista los tipos de ticket de este servidor.")
    async def ticket_categories_cmd(self, interaction: discord.Interaction):
        cats = guild_ticket_categories(self.bot, interaction.guild.id)
        lines = [f"{c.get('emoji') or '📩'} **{c['label']}** (`{c['id']}`) — {c.get('description') or ''} · carpeta `{c['category']}`" for c in cats]
        embed = discord.Embed(
            title=f"Tipos de ticket ({len(cats)})",
            description="\n".join(lines)[:4000] or "Ninguno",
            color=0x00FF88,
        )
        embed.set_footer(text="Añade con /ticket addcategory · quita con /ticket removecategory · panel con /ticket panel")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="resetcategories", description="Restaura Soporte, Reporte, Sugerencia y Otro.")
    async def ticket_resetcategories(self, interaction: discord.Interaction):
        self.bot.config.set_config(interaction.guild.id, "tickets.categories", [dict(c) for c in TICKET_CATEGORIES])
        await interaction.response.send_message(
            "✅ Categorías restauradas. Publica de nuevo `/ticket panel`.",
            ephemeral=True,
        )

    @ticket_group.command(name="logs", description="Canal donde se publica cada ticket (nombre + enlace web).")
    @discord.app_commands.describe(canal="Aquí se manda el nombre del ticket y el link a dabot.davito.es")
    async def ticket_logs_slash(self, interaction: discord.Interaction, canal: discord.TextChannel):
        self._bind_ticket_log_channel(interaction.guild.id, canal.id)
        sample = f"{DASHBOARD_URL}/dashboard?guild={interaction.guild.id}&ticket=1"
        embed = discord.Embed(
            title="🎫 Logs de tickets activados",
            description=(
                f"Cada ticket nuevo (y su cierre) se publicará en {canal.mention} con:\n"
                "• **Nombre** del canal (`ticket-pedidos-…`)\n"
                "• **Tipo** (Pedidos, Soporte, etc.)\n"
                "• Usuario y canal\n"
                f"• **Enlace directo** a la web, por ejemplo {sample}"
            ),
            color=0x00FF88,
        )
        await canal.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Logs de tickets en {canal.mention}. Nombre + enlace web en cada apertura.",
            ephemeral=True,
        )

    @ticket_group.command(name="stats", description="Estadísticas de tickets y CSAT")
    async def ticket_stats_slash(self, interaction: discord.Interaction):
        extras = self.bot.get_cog("TicketExtras")
        if not extras:
            await interaction.response.send_message("❌ Módulo de tickets extra no cargado.", ephemeral=True)
            return
        await extras.ticket_stats(interaction)

    @ticket_group.command(name="ratings", description="Valoraciones del staff en tickets")
    async def ticket_ratings_slash(self, interaction: discord.Interaction, staff_member: discord.Member = None):
        extras = self.bot.get_cog("TicketExtras")
        if not extras:
            await interaction.response.send_message("❌ Módulo de tickets extra no cargado.", ephemeral=True)
            return
        await extras.staff_ratings(interaction, staff_member)

    @commands.command(name="setup_tickets")
    @commands.has_permissions(administrator=True)
    async def setup_tickets(self, ctx):
        """Crea el panel de apertura de tickets en el canal actual."""
        embeds, view = make_ticket_panel(self.bot, ctx.guild.id)
        await ctx.send(embeds=embeds[:10], view=view)
        await ctx.message.delete(delay=3)

    @commands.command(name="settranscripts")
    @commands.has_permissions(administrator=True)
    async def settranscripts(self, ctx, channel: discord.TextChannel):
        """Establece el canal privado donde se registrarán los logs de los tickets."""
        self._bind_ticket_log_channel(ctx.guild.id, channel.id)
        await ctx.send(
            f"✅ Logs de tickets en {channel.mention}: nombre del ticket + enlace a {DASHBOARD_URL}."
        )

    # ------------------------------------------------------------------
    # Escucha de mensajes – replicar al hilo de log
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if not message.channel.name.startswith("ticket-"):
            return
        await self._mirror_message(message, deleted=False)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot:
            return
        if not isinstance(after.channel, discord.TextChannel):
            return
        if not after.channel.name.startswith("ticket-"):
            return
        if (before.content or "") == (after.content or "") and before.attachments == after.attachments:
            return
        try:
            await self._store_web_edit(before, after)
        except Exception as exc:
            log.warning("ticket web edit store failed: %s", exc)

        thread_id = self._ticket_threads.get(after.channel.id)
        if not thread_id:
            return

        log_channel = await self._get_log_channel(after.guild)
        if not log_channel:
            return

        thread = await self._resolve_thread(log_channel, thread_id)
        if not thread:
            return

        try:
            wh = await self._get_webhook(log_channel)
            embed = discord.Embed(
                description=(
                    f"**Antes:** {format_ticket_content(before) or '*sin texto*'}\n"
                    f"**Después:** {format_ticket_content(after) or '*sin texto*'}"
                ),
                color=0xf59e0b,
                timestamp=datetime.datetime.utcnow(),
            )
            embed.set_footer(text=f"Mensaje editado · Usuario `{after.author.id}` · Msg `{after.id}` · Canal `{after.channel.id}`")
            await wh.send(
                username=f"✏️ {after.author.display_name} (editó)",
                avatar_url=str(after.author.display_avatar.url),
                embed=embed,
                thread=thread,
            )
        except Exception as exc:
            log.warning("ticket discord edit mirror failed: %s", exc)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if not message.channel.name.startswith("ticket-"):
            return
        await self._mirror_message(message, deleted=True)

    # ------------------------------------------------------------------
    # Lógica interna
    # ------------------------------------------------------------------

    def _bind_ticket_log_channel(self, guild_id: int, channel_id: int):
        self.bot.config.set_config(guild_id, "tickets.transcript_channel_id", str(channel_id))
        self.bot.config.set_config(guild_id, "logs.tickets", str(channel_id))

    async def _get_log_channel(self, guild: discord.Guild):
        """Canal de logs de tickets: transcript, logs.tickets o #logs-tickets de la plantilla."""
        config = self.bot.config.get(guild.id) or {}
        tickets = config.get("tickets") or {}
        logs = config.get("logs") or {}
        raw = tickets.get("transcript_channel_id") or tickets.get("transcript_channel") or logs.get("tickets")
        ch = None
        if raw:
            try:
                found = guild.get_channel(int(raw))
                if isinstance(found, discord.TextChannel):
                    ch = found
            except (TypeError, ValueError):
                ch = None
        if not ch:
            for name in ("logs-tickets", "logs-ticket"):
                found = discord.utils.get(guild.text_channels, name=name)
                if isinstance(found, discord.TextChannel):
                    ch = found
                    break
        if ch:
            if str(tickets.get("transcript_channel_id") or "") != str(ch.id) or str(logs.get("tickets") or "") != str(ch.id):
                self._bind_ticket_log_channel(guild.id, ch.id)
        return ch

    async def _get_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """Devuelve (cacheado) el webhook para el canal de log."""
        if channel.id not in self._webhooks:
            wh = await _get_or_create_webhook(channel)
            self._webhooks[channel.id] = wh
        return self._webhooks[channel.id]

    async def _resolve_thread(self, log_channel: discord.TextChannel, thread_id: int):
        """Resuelve un Thread que puede o no estar en caché."""
        thread = log_channel.get_thread(thread_id)
        if thread:
            return thread
        try:
            return await self.bot.fetch_channel(thread_id)
        except Exception:
            return None

    async def _web_ticket_id(self, channel_id: int) -> int | None:
        tid = self._ticket_ids.get(channel_id)
        if tid:
            return tid
        row = await self.bot.db.fetch(
            "SELECT ticket_id FROM active_tickets WHERE channel_id = ?", channel_id
        )
        if row and row[0]:
            self._ticket_ids[channel_id] = int(row[0])
            return int(row[0])
        row = await self.bot.db.fetch(
            "SELECT id FROM tickets WHERE channel_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            channel_id,
        )
        if row:
            self._ticket_ids[channel_id] = int(row[0])
            return int(row[0])
        return None

    async def _store_web_message(self, message: discord.Message, deleted: bool = False):
        tid = await self._web_ticket_id(message.channel.id)
        if not tid:
            return
        atts = []
        for att in message.attachments or []:
            atts.append({
                "filename": att.filename,
                "url": att.url,
                "size": att.size,
                "content_type": getattr(att, "content_type", "") or "",
            })
        await self.bot.db.execute(
            """INSERT INTO ticket_messages
               (ticket_id, discord_message_id, user_id, username, avatar, content, attachments, deleted, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tid, message.id, message.author.id, str(message.author),
            str(message.author.display_avatar.url) if message.author.display_avatar else "",
            format_ticket_content(message), json.dumps(atts, ensure_ascii=False),
            1 if deleted else 0,
            (message.created_at.replace(tzinfo=None).isoformat() if message.created_at else datetime.datetime.utcnow().isoformat()),
        )

    async def _store_web_edit(self, before: discord.Message, after: discord.Message):
        tid = await self._web_ticket_id(after.channel.id)
        if not tid:
            return
        atts = []
        for att in after.attachments or []:
            atts.append({
                "filename": att.filename,
                "url": att.url,
                "size": att.size,
                "content_type": getattr(att, "content_type", "") or "",
            })
        new_content = format_ticket_content(after)
        old_content = format_ticket_content(before)
        existing = await self.bot.db.fetch(
            "SELECT id FROM ticket_messages WHERE ticket_id = ? AND discord_message_id = ?",
            tid, after.id,
        )
        if existing:
            await self.bot.db.execute(
                """UPDATE ticket_messages
                   SET content = ?, previous_content = ?, attachments = ?, edited = 1
                   WHERE ticket_id = ? AND discord_message_id = ?""",
                new_content, old_content, json.dumps(atts, ensure_ascii=False), tid, after.id,
            )
            return
        await self.bot.db.execute(
                """INSERT INTO ticket_messages
                   (ticket_id, discord_message_id, user_id, username, avatar, content, attachments, deleted, edited, previous_content, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)""",
                tid, after.id, after.author.id, str(after.author),
                str(after.author.display_avatar.url) if after.author.display_avatar else "",
                new_content, json.dumps(atts, ensure_ascii=False), old_content,
                datetime.datetime.utcnow().isoformat(),
            )

    def _ticket_web_url(self, guild_id: int, ticket_id: int) -> str:
        return f"{DASHBOARD_URL}/dashboard?guild={guild_id}&ticket={ticket_id}"

    def _ticket_log_embed(
        self,
        *,
        ticket_id: int,
        ticket_channel: discord.TextChannel,
        opener: discord.Member,
        cat: dict,
        reason: str,
        web_url: str,
        closed: bool = False,
        closer: discord.Member | None = None,
    ) -> discord.Embed:
        emoji = cat.get("emoji") or "🎫"
        label = cat.get("label") or cat.get("id") or "Ticket"
        color = 0xff4444 if closed else 0x00ff88
        title = f"{'🔒 Cerrado' if closed else '🎫 Abierto'} · {emoji} {label}"
        embed = discord.Embed(title=title[:256], color=color, timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Nombre", value=f"`#{ticket_channel.name}`", inline=True)
        embed.add_field(name="Tipo", value=f"{emoji} **{label}** (`{cat.get('id')}`)", inline=True)
        embed.add_field(name="Ticket web", value=f"**#{ticket_id}**", inline=True)
        embed.add_field(name="Usuario", value=f"{opener.mention}\n`{opener}` (`{opener.id}`)", inline=True)
        embed.add_field(
            name="Canal",
            value=f"{ticket_channel.mention}\n`{ticket_channel.id}`",
            inline=True,
        )
        if closer:
            embed.add_field(name="Cerrado por", value=f"{closer.mention} (`{closer.id}`)", inline=True)
        embed.add_field(name="Motivo", value=(reason or "—")[:1024], inline=False)
        embed.add_field(name="Enlace web", value=web_url, inline=False)
        embed.set_thumbnail(url=str(opener.display_avatar.url))
        embed.set_footer(text=f"Ticket #{ticket_id} · {ticket_channel.name} · dabot.davito.es")
        return embed

    def _ticket_log_view(self, web_url: str, jump_url: str | None = None) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Abrir en la web", style=discord.ButtonStyle.link, url=web_url))
        if jump_url:
            view.add_item(discord.ui.Button(label="Ir al ticket", style=discord.ButtonStyle.link, url=jump_url))
        return view

    async def open_ticket_log(
        self,
        ticket_channel: discord.TextChannel,
        opener: discord.Member,
        reason: str = "Sin motivo especificado",
        category: str = "other",
    ):
        """Crea el registro web y manda el log en Discord con nombre + enlace."""
        now = datetime.datetime.utcnow().isoformat()
        cat = ticket_category(category, self.bot, ticket_channel.guild.id)
        ticket_id = await self.bot.db.execute(
            """INSERT INTO tickets
               (guild_id, channel_id, opener_id, opener_name, opener_avatar, status, reason, created_at, category)
               VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
            ticket_channel.guild.id, ticket_channel.id, opener.id, str(opener),
            str(opener.display_avatar.url) if opener.display_avatar else "",
            reason, now, cat["id"],
        )
        ticket_id = int(ticket_id or 0)
        web_url = self._ticket_web_url(ticket_channel.guild.id, ticket_id)
        try:
            await self.bot.db.execute("UPDATE tickets SET web_url = ? WHERE id = ?", web_url, ticket_id)
        except Exception:
            pass
        self._ticket_ids[ticket_channel.id] = ticket_id
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO active_tickets (channel_id, thread_id, ticket_id) VALUES (?, ?, ?)",
            ticket_channel.id, 0, ticket_id,
        )

        log_channel = await self._get_log_channel(ticket_channel.guild)
        if not log_channel:
            return ticket_id

        log_embed = self._ticket_log_embed(
            ticket_id=ticket_id,
            ticket_channel=ticket_channel,
            opener=opener,
            cat=cat,
            reason=reason,
            web_url=web_url,
        )
        view = self._ticket_log_view(web_url, getattr(ticket_channel, "jump_url", None))
        try:
            root_msg = await log_channel.send(
                content=f"🎫 **{ticket_channel.name}** · {web_url}",
                embed=log_embed,
                view=view,
            )
        except Exception as exc:
            log.warning("ticket log send failed: %s", exc)
            return ticket_id

        thread_name = f"{cat.get('emoji') or '🎫'} {cat.get('label') or 'Ticket'} · {opener.display_name}"
        try:
            thread = await root_msg.create_thread(
                name=thread_name[:100],
                auto_archive_duration=10080,
                reason=f"Log de ticket {ticket_channel.name}",
            )
            self._ticket_threads[ticket_channel.id] = thread.id
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO active_tickets (channel_id, thread_id, ticket_id) VALUES (?, ?, ?)",
                ticket_channel.id, thread.id, ticket_id,
            )
        except Exception as exc:
            log.warning("ticket log thread failed: %s", exc)
        log.info(f"Ticket web #{ticket_id} logueado en {log_channel.id}")
        return ticket_id

    async def _mirror_message(self, message: discord.Message, deleted: bool):
        """Guarda el mensaje en la web y, si hay hilo, lo replica a Discord."""
        try:
            await self._store_web_message(message, deleted=deleted)
        except Exception as exc:
            log.warning("ticket web store failed: %s", exc)

        thread_id = self._ticket_threads.get(message.channel.id)
        if not thread_id:
            return

        log_channel = await self._get_log_channel(message.guild)
        if not log_channel:
            return

        thread = await self._resolve_thread(log_channel, thread_id)
        if not thread:
            return

        wh = await self._get_webhook(log_channel)

        # Construir archivos adjuntos (re-subir para preservarlos)
        files = []
        if message.attachments:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                for att in message.attachments:
                    try:
                        async with session.get(att.url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                files.append(discord.File(
                                    fp=io.BytesIO(data),
                                    filename=att.filename,
                                ))
                    except Exception as exc:
                        log.warning(f"No se pudo re-subir adjunto {att.filename}: {exc}")

        content_text = format_ticket_content(message)
        if deleted:
            content_text = f"~~{content_text}~~" if content_text else "*[sin texto — eliminado]*"

        embed = discord.Embed(
            description=content_text if content_text else None,
            color=0xff4444 if deleted else 0x2b2d31,
            timestamp=message.created_at,
        )
        if message.mentions:
            embed.add_field(
                name="Menciones",
                value=", ".join(f"{m.mention} (`{m.id}`)" for m in message.mentions[:8]),
                inline=False,
            )
        embed.set_footer(text=f"Usuario `{message.author.id}` · Msg `{message.id}` · Canal `{message.channel.id}`")

        if message.stickers:
            sticker_names = ", ".join(s.name for s in message.stickers)
            embed.add_field(name="Stickers", value=sticker_names, inline=False)

        username_prefix = "🗑️ [ELIMINADO] " if deleted else ""

        try:
            await wh.send(
                username=f"{username_prefix}{message.author.display_name}",
                avatar_url=str(message.author.display_avatar.url),
                embeds=[embed],
                files=files if files else [],
                thread=thread,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            log.error(f"Error enviando mensaje al webhook de ticket: {exc}")

    async def close_ticket_log(
        self,
        ticket_channel: discord.TextChannel,
        closer: discord.Member,
        opener: Optional[discord.Member] = None,
    ):
        """Cierra el registro web siempre; el hilo de Discord es opcional."""
        thread_id = self._ticket_threads.get(ticket_channel.id)
        tid = self._ticket_ids.get(ticket_channel.id) or await self._web_ticket_id(ticket_channel.id)
        if tid:
            await self.bot.db.execute(
                """UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ?, closed_name = ?
                   WHERE id = ?""",
                datetime.datetime.utcnow().isoformat(), closer.id, str(closer), tid,
            )
        self._ticket_ids.pop(ticket_channel.id, None)
        self._ticket_threads.pop(ticket_channel.id, None)
        await self.bot.db.execute("DELETE FROM active_tickets WHERE channel_id = ?", ticket_channel.id)

        log_channel = await self._get_log_channel(ticket_channel.guild)
        web_url = self._ticket_web_url(ticket_channel.guild.id, tid) if tid else DASHBOARD_URL
        row = None
        if tid:
            try:
                row = await self.bot.db.fetch("SELECT category, reason FROM tickets WHERE id = ?", tid)
            except Exception:
                row = None
        cat_id = row[0] if row else "other"
        reason = row[1] if row else "—"
        cat = ticket_category(cat_id, self.bot, ticket_channel.guild.id)
        who = opener or closer
        if log_channel:
            embed = self._ticket_log_embed(
                ticket_id=int(tid or 0),
                ticket_channel=ticket_channel,
                opener=who,
                cat=cat,
                reason=reason or "—",
                web_url=web_url,
                closed=True,
                closer=closer,
            )
            view = self._ticket_log_view(web_url)
            try:
                await log_channel.send(
                    content=f"🔒 **{ticket_channel.name}** · {web_url}",
                    embed=embed,
                    view=view,
                )
            except Exception:
                pass

        if not thread_id or not log_channel:
            return
        thread = await self._resolve_thread(log_channel, thread_id)
        if not thread:
            return
        try:
            await thread.send(embed=embed)
            await asyncio.sleep(1)
            await thread.edit(archived=True, locked=True, reason="Ticket cerrado")
        except discord.Forbidden:
            pass
        except discord.HTTPException as exc:
            log.error(f"Error cerrando hilo de ticket: {exc}")


# ---------------------------------------------------------------------------
# Vista: Lanzador de tickets (panel de apertura)
# ---------------------------------------------------------------------------

def parse_embed_color(val, default=0x00FF88) -> int:
    try:
        if isinstance(val, str) and val.startswith("#"):
            return int(val[1:], 16)
        if val in (None, ""):
            return default
        return int(val)
    except Exception:
        return default


def ticket_panel_payloads(tickets_cfg: dict | None, *, extra: str | None = None) -> list[dict]:
    cfg = tickets_cfg or {}
    panel = cfg.get("panel") if isinstance(cfg.get("panel"), dict) else {}
    cats = categories_from_cfg(cfg)
    listed = cats[:20]
    lines = [f"{c.get('emoji') or '📩'} **{c['label']}** — {c.get('description') or c.get('price') or c['label']}" for c in listed]
    if len(cats) > len(listed):
        lines.append(f"… y {len(cats) - len(listed)} más en el menú")
    desc = (panel.get("description") or "").strip()
    if not desc:
        desc = "Elige una opción en el **desplegable**. También puedes abrir ticket sin verificar."
    if extra:
        desc = extra.strip() + "\n\n" + desc
    desc = desc + "\n\n" + "\n".join(lines) + f"\n\nRegistro: {DASHBOARD_URL} → Tickets"
    color = parse_embed_color(panel.get("color"))
    main = {
        "title": (panel.get("title") or "🎫 Tickets")[:256],
        "description": desc[:4096],
        "color": color,
        "footer": {"text": (panel.get("footer") or "Dabot · dabot.davito.es")[:2048]},
    }
    img = str(panel.get("image") or "").strip()
    if img.startswith("https://"):
        main["image"] = {"url": img[:400]}
    thumb = str(panel.get("thumbnail") or "").strip()
    if thumb.startswith("https://"):
        main["thumbnail"] = {"url": thumb[:400]}
    embeds = [main]
    for c in cats:
        if not (c.get("image") or c.get("price") or c.get("details")):
            continue
        body = c.get("details") or c.get("description") or c["label"]
        if c.get("price"):
            body = f"**{c['price']}**\n{body}"
        card = {
            "title": f"{c.get('emoji') or '📩'}  {c['label']}"[:256],
            "description": str(body)[:4096],
            "color": parse_embed_color(c.get("color"), color),
            "footer": {"text": (c.get("category") or "Tickets")[:2048]},
        }
        pimg = str(c.get("image") or "").strip()
        if pimg.startswith("https://"):
            card["image"] = {"url": pimg[:400]}
        embeds.append(card)
        if len(embeds) >= 10:
            break
    return embeds


def make_ticket_panel(bot, guild_id, *, title: str | None = None, extra: str | None = None):
    try:
        cfg = bot.config.get(int(guild_id), "tickets") or {}
    except Exception:
        cfg = {}
    payloads = ticket_panel_payloads(cfg, extra=extra)
    if title:
        payloads[0]["title"] = title[:256]
    from utils.template_posts import embed_from_payload
    embeds = [embed_from_payload(p) for p in payloads]
    cats = guild_ticket_categories(bot, guild_id)
    return embeds, TicketLauncher(bot, cats)


def register_ticket_views(bot):
    dummy = [TICKET_CATEGORIES[0]]
    bot.add_view(TicketLauncher(bot, dummy, persist_pages=5))
    bot.add_view(LegacyOpenTicketButton(bot))


class TicketCategorySelect(discord.ui.Select):
    def __init__(self, bot, options: list[dict], page: int = 0, total_pages: int = 1):
        self.bot = bot
        placeholder = "Elige el tipo de ticket…"
        if total_pages > 1:
            placeholder = f"Elige el tipo de ticket… ({page + 1}/{total_pages})"
        custom_id = "dabot:ticket_category" if page == 0 else f"dabot:ticket_category:{page}"
        super().__init__(
            placeholder=placeholder[:150],
            min_values=1,
            max_values=1,
            options=[_select_option(item) for item in options],
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        parent: TicketLauncher = self.view  # type: ignore
        await parent.open_ticket(interaction, self.values[0])


class TicketLauncher(discord.ui.View):
    """Selector persistente. Nunca un botón 'Abrir ticket': si hay muchas opciones se parten en varios menús."""

    def __init__(self, bot, categories: list[dict] | None = None, persist_pages: int = 0):
        super().__init__(timeout=None)
        self.bot = bot
        cats = categories or TICKET_CATEGORIES
        pages = list(_chunks(cats, 25))
        total = max(len(pages), 1)
        if persist_pages:
            # Register empty extra pages so custom panels with 26–125 types keep working after restart.
            dummy = cats[:1] or TICKET_CATEGORIES[:1]
            for page in range(persist_pages):
                chunk = pages[page][1] if page < len(pages) else dummy
                self.add_item(TicketCategorySelect(bot, chunk, page, persist_pages))
            return
        for page, chunk in pages:
            self.add_item(TicketCategorySelect(bot, chunk, page, total))

    async def open_ticket(self, interaction: discord.Interaction, category_id: str = "other"):
        guild = interaction.guild
        user = interaction.user
        cat = ticket_category(category_id, self.bot, guild.id if guild else None)

        config = self.bot.config.get(guild.id, "tickets") or {}
        category_name = cat["category"] or config.get("category_name", "Tickets")

        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            try:
                category = await guild.create_category(
                    category_name,
                    reason="Dabot — Categoría de tickets creada automáticamente",
                )
            except discord.Forbidden:
                return await interaction.response.send_message(
                    "❌ No tengo permisos para crear categorías.", ephemeral=True
                )

        existing = None
        for parent in guild.categories:
            if not parent.name.lower().startswith("ticket"):
                continue
            for ch in parent.channels:
                if not isinstance(ch, discord.TextChannel):
                    continue
                if ch.topic and str(user.id) in ch.topic:
                    existing = ch
                    break
            if existing:
                break
        if not existing:
            for ch in guild.text_channels:
                if ch.name.startswith("ticket-") and ch.topic and str(user.id) in ch.topic:
                    existing = ch
                    break
        if existing:
            return await interaction.response.send_message(
                f"⚠️ Ya tienes un ticket abierto: {existing.mention}", ephemeral=True
            )

        # Construir permisos del canal
        staff_roles = config.get("staff_roles", ["Staff", "Moderator", "Support"])
        staff_role_ids = config.get("staff_role_ids") or []
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                embed_links=True,
            ),
        }
        staff_overwrite = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True,
        )
        for role_name in staff_roles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = staff_overwrite
        for rid in staff_role_ids:
            try:
                role = guild.get_role(int(rid))
            except (TypeError, ValueError):
                role = None
            if role:
                overwrites[role] = staff_overwrite

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        safe = re.sub(r"[^a-z0-9-]", "", (user.name or "user").lower())[:16] or "user"
        channel_name = f"ticket-{cat['id']}-{safe}-{str(user.id)[-4:]}"
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket de {user} ({user.id}) — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
                reason=f"Ticket abierto por {user}",
            )
        except discord.Forbidden:
            msg = "❌ No tengo permisos suficientes para crear el canal de ticket."
            if interaction.response.is_done():
                return await interaction.followup.send(msg, ephemeral=True)
            return await interaction.response.send_message(msg, ephemeral=True)

        tickets_cog = self.bot.get_cog("Tickets")
        ticket_id = None
        if tickets_cog:
            ticket_id = await tickets_cog.open_ticket_log(
                channel, user, reason=f"{cat['label']}", category=cat["id"]
            )
        web_url = f"{DASHBOARD_URL}/dashboard?guild={guild.id}&ticket={ticket_id or ''}"
        product_bits = []
        if cat.get("price"):
            product_bits.append(f"**Precio:** {cat['price']}")
        if cat.get("details"):
            product_bits.append(cat["details"])
        product_txt = ("\n".join(product_bits) + "\n\n") if product_bits else ""
        embed = discord.Embed(
            title=f"{cat.get('emoji') or '📩'} Ticket · {cat['label']}",
            description=(
                f"Hola {user.mention}, el staff te atenderá lo antes posible.\n\n"
                f"{product_txt}"
                "Describe tu consulta con el mayor detalle posible. Puedes mencionar usuarios, adjuntar fotos y editar mensajes: todo queda en el registro.\n"
                f"**Registro web:** [abrir ticket]({web_url})\n"
                "Pulsa 🔒 **Cerrar Ticket** cuando tu problema esté resuelto."
            )[:4096],
            color=parse_embed_color(cat.get("color")),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_author(name=user.display_name, icon_url=str(user.display_avatar.url))
        embed.set_footer(text=f"Usuario `{user.id}` · categoría {cat['id']}")
        if str(cat.get("image") or "").startswith("https://"):
            try:
                embed.set_image(url=cat["image"])
            except Exception:
                pass

        await channel.send(
            content=f"{user.mention}",
            embed=embed,
            view=TicketControls(self.bot, tickets_cog),
        )

        done = f"✅ Ticket **{cat['label']}** creado: {channel.mention}\n🔗 {web_url}"
        if interaction.response.is_done():
            await interaction.followup.send(done, ephemeral=True)
        else:
            await interaction.response.send_message(done, ephemeral=True)


class LegacyOpenTicketButton(discord.ui.View):
    """Paneles antiguos con botón. Los nuevos solo usan el desplegable."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Abrir Ticket",
        style=discord.ButtonStyle.green,
        emoji="📩",
        custom_id="dabot:create_ticket",
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cats = guild_ticket_categories(self.bot, interaction.guild.id) if interaction.guild else TICKET_CATEGORIES
        launcher = TicketLauncher(self.bot, cats)
        await launcher.open_ticket(interaction, cats[0]["id"] if cats else "other")


# ---------------------------------------------------------------------------
# Vista: Controles dentro del ticket
# ---------------------------------------------------------------------------

class TicketControls(discord.ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

    @discord.ui.button(
        label="Cerrar Ticket",
        style=discord.ButtonStyle.red,
        emoji="🔒",
        custom_id="dabot:close_ticket",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel

        embed = discord.Embed(
            description=f"🔒 Ticket cerrado por **{interaction.user.display_name}**. Se eliminará en 10 segundos.",
            color=0xff4444,
        )
        await interaction.response.send_message(embed=embed)

        # Buscar al opener desde el topic del canal
        opener = None
        if channel.topic:
            match = re.search(r"\((\d+)\)", channel.topic)
            if match:
                try:
                    opener = channel.guild.get_member(int(match.group(1)))
                except Exception:
                    pass

        if self.cog:
            await self.cog.close_ticket_log(channel, interaction.user, opener)

        await asyncio.sleep(10)
        try:
            await channel.delete(reason=f"Ticket cerrado por {interaction.user}")
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="Reclamar",
        style=discord.ButtonStyle.blurple,
        emoji="🙋",
        custom_id="dabot:claim_ticket",
    )
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel

        await channel.set_permissions(
            interaction.user,
            read_messages=True,
            send_messages=True,
            manage_messages=True,
        )

        embed = discord.Embed(
            description=f"✋ {interaction.user.mention} ha reclamado este ticket.",
            color=0x6366f1,
        )
        await interaction.response.send_message(embed=embed)

        if self.cog:
            tid = await self.cog._web_ticket_id(channel.id)
            if tid:
                try:
                    await self.bot.db.execute(
                        "UPDATE tickets SET claimed_by = ?, claimed_name = ? WHERE id = ?",
                        interaction.user.id, str(interaction.user), tid,
                    )
                except Exception:
                    pass

        # Mirror del evento al hilo de log
        if self.cog:
            thread_id = self.cog._ticket_threads.get(channel.id)
            if thread_id:
                log_channel = await self.cog._get_log_channel(interaction.guild)
                if log_channel:
                    thread = await self.cog._resolve_thread(log_channel, thread_id)
                    if thread:
                        claim_embed = discord.Embed(
                            description=f"✋ **{interaction.user.display_name}** (`{interaction.user.id}`) ha reclamado el ticket.",
                            color=0x6366f1,
                            timestamp=datetime.datetime.utcnow(),
                        )
                        try:
                            wh = await self.cog._get_webhook(log_channel)
                            await wh.send(
                                username=f"[CLAIM] {interaction.user.display_name}",
                                avatar_url=str(interaction.user.display_avatar.url),
                                embed=claim_embed,
                                thread=thread,
                            )
                        except Exception:
                            pass

    @discord.ui.button(
        label="Añadir Usuario",
        style=discord.ButtonStyle.grey,
        emoji="➕",
        custom_id="dabot:add_user_ticket",
    )
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddUserModal(self.bot, self.cog))


class AddUserModal(discord.ui.Modal, title="Añadir usuario al ticket"):
    user_id_input = discord.ui.TextInput(
        label="ID del usuario de Discord",
        placeholder="123456789012345678",
        min_length=15,
        max_length=21,
    )

    def __init__(self, bot, cog):
        super().__init__()
        self.bot = bot
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = int(self.user_id_input.value.strip())
            member = interaction.guild.get_member(user_id)
            if not member:
                member = await interaction.guild.fetch_member(user_id)
        except (ValueError, discord.NotFound):
            return await interaction.response.send_message(
                "❌ No se encontró ningún usuario con ese ID.", ephemeral=True
            )

        await interaction.channel.set_permissions(
            member,
            read_messages=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True,
        )

        embed = discord.Embed(
            description=f"➕ {member.mention} añadido al ticket por {interaction.user.mention}.",
            color=0x10b981,
        )
        await interaction.response.send_message(embed=embed)

        if self.cog:
            thread_id = self.cog._ticket_threads.get(interaction.channel.id)
            if thread_id:
                log_channel = await self.cog._get_log_channel(interaction.guild)
                if log_channel:
                    thread = await self.cog._resolve_thread(log_channel, thread_id)
                    if thread:
                        add_embed = discord.Embed(
                            description=(
                                f"➕ **{member.display_name}** (`{member.id}`) "
                                f"añadido por **{interaction.user.display_name}** (`{interaction.user.id}`)."
                            ),
                            color=0x10b981,
                            timestamp=datetime.datetime.utcnow(),
                        )
                        try:
                            wh = await self.cog._get_webhook(log_channel)
                            await wh.send(
                                username="[SISTEMA]",
                                avatar_url=str(self.bot.user.display_avatar.url),
                                embed=add_embed,
                                thread=thread,
                            )
                        except Exception:
                            pass


async def setup(bot):
    await bot.add_cog(Tickets(bot))
