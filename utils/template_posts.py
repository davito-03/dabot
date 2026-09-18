"""Pretty starter embeds for Dabot server templates."""
from __future__ import annotations

from utils.helpers import DASHBOARD_URL

LOBSTER = 0xE23D28
GREEN = 0x00FF88
ORANGE = 0xF97316
GOLD = 0xF59E0B
PURPLE = 0xA855F7
BRAND_ICON = f"{DASHBOARD_URL}/static/img/dabot.png"


def _fill(text: str, slots: dict) -> str:
    if not text:
        return text
    mapping = {
        "{verify}": f"<#{slots['verify']}>" if slots.get("verify") else "#verificacion",
        "{tickets}": f"<#{slots['tickets']}>" if slots.get("tickets") else "#abre-ticket",
        "{rules}": f"<#{slots['rules']}>" if slots.get("rules") else "#reglas",
        "{commands}": f"<#{slots['commands']}>" if slots.get("commands") else "#comandos",
        "{welcome}": f"<#{slots['welcome']}>" if slots.get("welcome") else "#bienvenida",
        "{levels}": f"<#{slots['levels']}>" if slots.get("levels") else "#niveles",
        "{dashboard}": DASHBOARD_URL,
    }
    for key, val in mapping.items():
        text = text.replace(key, str(val))
    return text


def _fill_embed(embed: dict, slots: dict) -> dict:
    out = dict(embed)
    if out.get("description"):
        out["description"] = _fill(out["description"], slots)
    fields = []
    for f in out.get("fields") or []:
        fields.append({
            "name": _fill(f.get("name") or "", slots)[:256],
            "value": _fill(f.get("value") or "", slots)[:1024],
            "inline": bool(f.get("inline")),
        })
    if fields:
        out["fields"] = fields
    return out


def rules_payloads(tpl: dict, lang: str, slots: dict) -> list[dict]:
    is_en = lang == "en"
    items = tpl.get("rules") if isinstance(tpl.get("rules"), list) else []
    intro = (
        "Read this before you chat. Verify, use tickets for problems, and keep the tone of this community. "
        "Breaking a rule can mean a warn, mute, kick or ban."
        if is_en else
        "Lee esto antes de hablar. Verifícate, usa tickets si hay un problema y cuida el tono de esta comunidad. "
        "Incumplir una norma puede acabar en warn, mute, kick o ban."
    )
    fields = []
    for i, r in enumerate(items, 1):
        title = f"{i}. {r.get('title') or ''}".strip()[:256]
        text = (r.get("text") or "—")[:1024]
        fields.append({"name": title, "value": text, "inline": False})
    if not fields:
        fields.append({
            "name": "1. Staff" if is_en else "1. Staff",
            "value": "Staff has the final say." if is_en else "El staff tiene la última palabra.",
            "inline": False,
        })
    chunks = [fields[i:i + 6] for i in range(0, len(fields), 6)]
    total = len(chunks)
    embeds = []
    base_title = f"{tpl.get('icon') or '🦞'}  " + ("Server rules" if is_en else "Normas del servidor")
    for n, chunk in enumerate(chunks):
        title = base_title if total == 1 else f"{base_title}  ·  {n + 1}/{total}"
        embeds.append(_fill_embed({
            "title": title[:256],
            "description": intro if n == 0 else ("Continued." if is_en else "Siguen las normas."),
            "color": LOBSTER,
            "author": {"name": tpl.get("name") or "Dabot", "icon_url": BRAND_ICON},
            "thumbnail": {"url": BRAND_ICON},
            "fields": chunk,
            "footer": {
                "text": "Dabot · dabot.davito.es · Staff has the final say"
                if is_en else
                "Dabot · dabot.davito.es · El staff tiene la última palabra"
            },
        }, slots))
    return embeds


def commands_payload(tpl: dict, lang: str, slots: dict) -> dict:
    is_en = lang == "en"
    return _fill_embed({
        "title": "🦞  Dabot commands" if is_en else "🦞  Comandos de Dabot",
        "description": (
            "Use **this channel** for bot commands so the rest of the server stays clean. "
            f"Full panel: {DASHBOARD_URL}"
            if is_en else
            "Usa **este canal** para los comandos del bot y deja el resto del servidor limpio. "
            f"Panel completo: {DASHBOARD_URL}"
        ),
        "color": GREEN,
        "author": {"name": "Dabot", "icon_url": BRAND_ICON},
        "thumbnail": {"url": BRAND_ICON},
        "fields": [
            {
                "name": "👋  Start" if is_en else "👋  Empezar",
                "value": "`/start` — setup\n`/help` — command list\n`/dashboard` — web panel",
                "inline": True,
            },
            {
                "name": "📈  Levels" if is_en else "📈  Niveles",
                "value": "`/level rank` — card\n`/level leaderboard`\n`/level toggle` — staff",
                "inline": True,
            },
            {
                "name": "💰  Economy" if is_en else "💰  Economía",
                "value": "`/eco` — wallet\nCasino and shop when enabled.",
                "inline": True,
            },
            {
                "name": "🎮  Games" if is_en else "🎮  Juegos",
                "value": "`/game rps` — rock paper lizard Spock\n`/minigame battle` · wordle · hangman",
                "inline": True,
            },
            {
                "name": "🎫  Tickets",
                "value": (
                    "Open from {tickets}. Categories in the dropdown. Transcript on the web."
                    if is_en else
                    "Ábrelos en {tickets}. Categorías en el desplegable. El historial va a la web."
                ),
                "inline": True,
            },
            {
                "name": "🛡️  Verification" if is_en else "🛡️  Verificación",
                "value": (
                    "One click in {verify} → dabot.davito.es/verify"
                    if is_en else
                    "Un clic en {verify} → dabot.davito.es/verify"
                ),
                "inline": True,
            },
            {
                "name": "🔨  Staff",
                "value": "`/mod warn` · `/mod warnlist`\n`/log config` · `/welcome setup`\n`/ticket panel` · `/ticket logs`",
                "inline": False,
            },
        ],
        "footer": {"text": "Dabot · dabot.davito.es"},
    }, slots)


def welcome_payload(tpl: dict, lang: str, slots: dict) -> dict:
    is_en = lang == "en"
    return _fill_embed({
        "title": "🧡  Welcome channel" if is_en else "🧡  Canal de bienvenida",
        "description": (
            "Dabot posts a **welcome card** here when someone joins (lobster red art). "
            "Staff: `/welcome setup` to pick the channel, message and whether it's on."
            if is_en else
            "Dabot publica aquí una **tarjeta de bienvenida** cuando alguien entra (arte rojo langosta). "
            "Staff: `/welcome setup` para canal, mensaje y activarla."
        ),
        "color": ORANGE,
        "author": {"name": tpl.get("name") or "Dabot", "icon_url": BRAND_ICON},
        "thumbnail": {"url": BRAND_ICON},
        "fields": [
            {
                "name": "Placeholders" if is_en else "Variables",
                "value": "`{mention}` `{server}` `{count}` `{member}` `{guild}`",
                "inline": False,
            },
            {
                "name": "Custom art" if is_en else "Arte propio",
                "value": "`/welcome background` — image upload" if is_en else "`/welcome background` — sube una imagen",
                "inline": False,
            },
        ],
        "footer": {"text": "Dabot · dabot.davito.es"},
    }, slots)


def levels_payload(tpl: dict, lang: str, slots: dict) -> dict:
    is_en = lang == "en"
    return _fill_embed({
        "title": "📈  Levels" if is_en else "📈  Niveles",
        "description": (
            "Level-ups land here **when staff turns levels on** (`/level toggle`). "
            "Default is off. Cards use the lobster rank design: `/level rank`."
            if is_en else
            "Las subidas de nivel salen aquí **cuando el staff active niveles** (`/level toggle`). "
            "Vienen apagados por defecto. La tarjeta langosta: `/level rank`."
        ),
        "color": GOLD,
        "author": {"name": "Dabot", "icon_url": BRAND_ICON},
        "thumbnail": {"url": BRAND_ICON},
        "fields": [
            {
                "name": "Useful" if is_en else "Útil",
                "value": "`/level rank` · `/level leaderboard` · `/level background` (premium)",
                "inline": False,
            }
        ],
        "footer": {"text": "Dabot · dabot.davito.es"},
    }, slots)


def economy_payload(tpl: dict, lang: str, slots: dict, kind: str = "main") -> dict:
    is_en = lang == "en"
    if kind == "top":
        title = "🏆  Economy leaderboard" if is_en else "🏆  Ranking de economía"
        description = (
            "See the richest members with `/eco top`. Balances belong to this server only."
            if is_en else
            "Consulta a los miembros con más dinero usando `/eco top`. Los saldos son solo de este servidor."
        )
    elif kind == "shop":
        title = "🛒  Server shop" if is_en else "🛒  Tienda del servidor"
        description = (
            "Browse items with `/eco shop` and buy them with `/eco buy`."
            if is_en else
            "Consulta los objetos con `/eco shop` y cómpralos con `/eco buy`."
        )
    else:
        title = "💰  Server economy" if is_en else "💰  Economía del servidor"
        description = (
            "Use `/eco balance`, `/eco work`, `/eco daily`, `/eco shop` and `/eco top`."
            if is_en else
            "Usa `/eco balance`, `/eco work`, `/eco daily`, `/eco shop` y `/eco top`."
        )
    return _fill_embed({
        "title": title,
        "description": description,
        "color": GREEN,
        "author": {"name": tpl.get("name") or "Dabot", "icon_url": BRAND_ICON},
        "thumbnail": {"url": BRAND_ICON},
        "footer": {"text": "Dabot · dabot.davito.es"},
    }, slots)


def verify_payload(tpl: dict, lang: str, slots: dict, guild_id: int) -> dict:
    is_en = lang == "en"
    url = f"{DASHBOARD_URL}/verify/{guild_id}"
    return {
        "title": "🛡️  Verification" if is_en else "🛡️  Verificación",
        "description": (
            f"One step in the browser. Open **dabot.davito.es/verify** with Discord, tap the lobster 🦞 and you're in.\n\n**{url}**"
            if is_en else
            f"Un paso en el navegador. Abre **dabot.davito.es/verify** con Discord, pulsa la langosta 🦞 y listo.\n\n**{url}**"
        ),
        "color": GREEN,
        "author": {"name": "Dabot", "icon_url": BRAND_ICON},
        "thumbnail": {"url": BRAND_ICON},
        "footer": {"text": "Dabot · dabot.davito.es/verify"},
        "url": url,
    }


def announcements_payload(tpl: dict, lang: str, slots: dict) -> dict:
    is_en = lang == "en"
    return _fill_embed({
        "title": "📢  Announcements" if is_en else "📢  Anuncios",
        "description": (
            "Staff-only posting. Members can read, not chat. Keep raids, patch notes and events here so they don't drown in general."
            if is_en else
            "Solo escribe el staff. La gente lee, no habla. Raids, parches y eventos aquí para que no se pierdan en el general."
        ),
        "color": PURPLE,
        "author": {"name": tpl.get("name") or "Dabot", "icon_url": BRAND_ICON},
        "footer": {"text": "Dabot · dabot.davito.es"},
    }, slots)


def catalog_payloads(tpl: dict, lang: str, slots: dict) -> list[dict]:
    is_en = lang == "en"
    items = [c for c in (tpl.get("ticket_categories") or []) if c.get("price") or c.get("details") or c.get("image")]
    items = [c for c in items if c.get("id") not in ("support", "refund")]
    intro = {
        "title": "🛒  Digital catalogue" if is_en else "🛒  Catálogo digital",
        "description": (
            "Keys, accounts and subscriptions. **Orders only via the ticket dropdown** in {tickets} — never pay a DM.\n"
            "Verify in {verify} to chat with other customers. Unverified members can still open an order ticket."
            if is_en else
            "Keys, cuentas y suscripciones. **Los pedidos solo por el desplegable** de {tickets} — nunca pagues un MD.\n"
            "Verifícate en {verify} para hablar con otros clientes. Sin verificar también puedes abrir un ticket de compra."
        ),
        "color": GREEN,
        "author": {"name": tpl.get("name") or "Dabot", "icon_url": BRAND_ICON},
        "thumbnail": {"url": BRAND_ICON},
        "footer": {"text": "Dabot · dabot.davito.es"},
    }
    out = [_fill_embed(intro, slots)]
    for c in items[:8]:
        body = c.get("details") or c.get("description") or ""
        if c.get("price"):
            body = f"**{c['price']}**\n{body}"
        card = {
            "title": f"{c.get('emoji') or '📦'}  {c.get('label')}",
            "description": (body or "")[:4096],
            "color": int(c.get("color") or GREEN),
            "footer": {"text": "Pedido → desplegable de tickets"},
        }
        if str(c.get("image") or "").startswith("https://"):
            card["image"] = {"url": c["image"]}
        out.append(_fill_embed(card, slots))
    return out


def howto_buy_payload(tpl: dict, lang: str, slots: dict) -> dict:
    is_en = lang == "en"
    return _fill_embed({
        "title": "🛍️  How to buy" if is_en else "🛍️  Cómo comprar",
        "description": (
            "1. Read the catalogue.\n"
            "2. Open {tickets} and pick the **product** in the dropdown.\n"
            "3. Pay only the methods staff post **inside that ticket**.\n"
            "4. Delivery happens in the ticket (key, invite or account).\n"
            "5. Keep screenshots. Chargebacks without talking first = ban.\n\n"
            "Verify in {verify} to use customer chat."
            if is_en else
            "1. Mira el catálogo.\n"
            "2. Abre {tickets} y elige el **producto** en el desplegable.\n"
            "3. Paga solo los métodos que el staff indique **dentro de ese ticket**.\n"
            "4. La entrega es en el ticket (key, invitación o cuenta).\n"
            "5. Guarda capturas. Chargeback sin hablar = ban.\n\n"
            "Verifícate en {verify} para el chat de clientes."
        ),
        "color": ORANGE,
        "author": {"name": tpl.get("name") or "Dabot", "icon_url": BRAND_ICON},
        "footer": {"text": "Dabot · dabot.davito.es"},
    }, slots)


def embed_from_payload(payload: dict):
    import discord
    e = discord.Embed(
        title=payload.get("title"),
        description=payload.get("description"),
        color=payload.get("color") or GREEN,
        url=payload.get("url"),
    )
    author = payload.get("author") or {}
    if author.get("name"):
        e.set_author(name=author["name"], icon_url=author.get("icon_url"))
    thumb = payload.get("thumbnail") or {}
    if thumb.get("url"):
        e.set_thumbnail(url=thumb["url"])
    image = payload.get("image") or {}
    if isinstance(image, str) and image.startswith("https://"):
        e.set_image(url=image)
    elif isinstance(image, dict) and str(image.get("url") or "").startswith("https://"):
        e.set_image(url=image["url"])
    for f in payload.get("fields") or []:
        e.add_field(name=f.get("name") or "·", value=f.get("value") or "—", inline=bool(f.get("inline")))
    footer = payload.get("footer") or {}
    if footer.get("text"):
        e.set_footer(text=footer["text"], icon_url=footer.get("icon_url") or BRAND_ICON)
    return e
