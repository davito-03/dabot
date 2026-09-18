"""Bilingual Discord server templates with auto-wired Dabot modules."""
from __future__ import annotations

import json
import os
import sqlite3

PERM_ADMIN = "8"
# Kick, ban, timeout, manage messages/nick, view audit, moderate members
PERM_MOD = "1099914379383"
PERM_HELPER = "2147560512"  # manage messages + timeout-ish subset; 0 if Discord rejects

def t(es: str, en: str) -> dict:
    return {"es": es, "en": en}


def pick(value, lang: str = "es"):
    lang = "en" if str(lang).lower().startswith("en") else "es"
    if isinstance(value, dict) and "es" in value:
        return value.get(lang) or value["es"]
    return value


def _role(rid, name, color, *, hoist=False, permissions="0", tags=None):
    return {
        "id": rid,
        "name": name,
        "color": color,
        "hoist": hoist,
        "permissions": str(permissions),
        "tags": tags or [],
    }


def _ch(name, *, type=0, topic=None, slot=None):
    return {"name": name, "type": type, "topic": topic or t("", ""), "slot": slot}


def _cat(name, channels, *, access="verified", staff_only=False, cid=None):
    return {"name": name, "channels": channels, "access": access, "staff_only": staff_only, "cid": cid}


def rule(title_es: str, title_en: str, body_es: str, body_en: str) -> dict:
    return {"title": t(title_es, title_en), "text": t(body_es, body_en)}


# Shared staff / verification / member roles on every template
CORE_ROLES = [
    _role("admin", t("Admin", "Admin"), 0xEF4444, hoist=True, permissions=PERM_ADMIN, tags=["staff", "admin"]),
    _role("mod", t("Moderador", "Moderator"), 0x3B82F6, hoist=True, permissions=PERM_MOD, tags=["staff", "mod"]),
    _role("helper", t("Helper", "Helper"), 0x22C55E, hoist=True, permissions="0", tags=["staff"]),
    _role("unverified", t("No verificado", "Unverified"), 0x64748B, tags=["unverified"]),
    _role("verified", t("Verificado", "Verified"), 0x00FF88, tags=["verified"]),
    _role("muted", t("Silenciado", "Muted"), 0x1F2937, tags=["muted"]),
    _role("bot", t("Bot", "Bot"), 0x99AAB5, tags=["bot"]),
]


def _infra_categories():
    return [
        _cat(
            t("📌 INFORMACIÓN", "📌 INFORMATION"),
            [
                _ch(t("reglas", "rules"), topic=t("Normas del servidor.", "Server rules."), slot="rules"),
                _ch(t("anuncios", "announcements"), topic=t("Avisos del staff.", "Staff announcements."), slot="announcements"),
                _ch(t("bienvenida", "welcome"), topic=t("Entra y salidas.", "Joins and leaves."), slot="welcome"),
                _ch(t("comandos", "commands"), topic=t("Usa los comandos de Dabot aquí.", "Use Dabot commands here."), slot="commands"),
                _ch(t("niveles", "levels"), topic=t("Subidas de nivel y ranking.", "Level-ups and ranking."), slot="levels"),
                _ch(t("autoroles", "autoroles"), topic=t("Elige tus roles. Puedes borrar este panel si no lo quieres.", "Pick your roles. You can delete this panel."), slot="autorole"),
            ],
            access="info",
            cid="info",
        ),
        _cat(
            t("🛡️ VERIFICACIÓN", "🛡️ VERIFICATION"),
            [
                _ch(t("verificacion", "verify"), topic=t("Pasa la verificación web de Dabot.", "Complete Dabot web verification."), slot="verify"),
            ],
            access="verify",
            cid="verify",
        ),
        _cat(
            t("🎫 TICKETS", "🎫 TICKETS"),
            [
                _ch(t("abre-ticket", "open-ticket"), topic=t("Pulsa el panel para abrir un ticket. También si no estás verificado.", "Open a ticket from the panel. Unverified members can too."), slot="tickets"),
            ],
            access="tickets",
            cid="tickets",
        ),
        _cat(
            t("💰 ECONOMÍA", "💰 ECONOMY"),
            [
                _ch(t("economía", "economy"), topic=t("Cartera, banco, trabajo y tienda del servidor.", "Server wallet, bank, work and shop."), slot="economy"),
                _ch(t("ranking-economía", "economy-ranking"), topic=t("Top de riqueza del servidor.", "Server wealth leaderboard."), slot="economy.top"),
                _ch(t("tienda", "shop"), topic=t("Objetos comprables con la moneda del servidor.", "Items purchasable with server currency."), slot="economy.shop"),
            ],
            access="verified",
            cid="economy",
        ),
        _cat(
            t("📋 LOGS", "📋 LOGS"),
            [
                _ch(t("logs-mensajes", "logs-messages"), slot="logs.messages"),
                _ch(t("logs-moderacion", "logs-moderation"), slot="logs.moderation"),
                _ch(t("logs-voz", "logs-voice"), slot="logs.voice"),
                _ch(t("logs-miembros", "logs-members"), slot="logs.members"),
                _ch(t("logs-entradas", "logs-joins"), slot="logs.joins"),
                _ch(t("logs-multicuentas", "logs-alts"), slot="logs.alts"),
                _ch(t("logs-hacked", "logs-hijack"), slot="logs.hijack"),
                _ch(t("logs-tickets", "logs-tickets"), slot="logs.tickets"),
                _ch(t("logs-servidor", "logs-server"), slot="logs.server"),
                _ch(t("logs-verificaciones", "logs-verification"), slot="logs.verification"),
            ],
            access="staff",
            staff_only=True,
            cid="logs",
        ),
        _cat(
            t("🛡️ STAFF", "🛡️ STAFF"),
            [
                _ch(t("staff-chat", "staff-chat")),
                _ch(t("sanciones", "cases"), topic=t("Casos de moderación.", "Moderation cases.")),
            ],
            access="staff",
            staff_only=True,
            cid="staff",
        ),
    ]


TEMPLATES = {
    "gaming": {
        "id": "gaming",
        "icon": "🎮",
        "name": t("Videojuegos", "Gaming"),
        "description": t(
            "LFG, clips, rangos, plataformas y staff. Logs y verificación incluidos.",
            "LFG, clips, ranks, platforms and staff. Logs and verification included.",
        ),
        "extra_roles": [
            _role("vip", t("VIP", "VIP"), 0xF59E0B, hoist=True),
            _role("streamer", t("Streamer", "Streamer"), 0xA855F7, hoist=True),
            _role("pro", t("Pro", "Pro"), 0xF97316, hoist=True),
            _role("pc", t("PC", "PC"), 0x38BDF8),
            _role("playstation", t("PlayStation", "PlayStation"), 0x2563EB),
            _role("xbox", t("Xbox", "Xbox"), 0x16A34A),
            _role("switch", t("Nintendo", "Nintendo"), 0xEF4444),
            _role("member", t("Gamer", "Gamer"), 0x00FF88, hoist=True),
        ],
        "extra_categories": [
            _cat(t("💬 CHAT", "💬 CHAT"), [
                _ch(t("general", "general"), topic=t("Charla general.", "General chat.")),
                _ch(t("memes", "memes")),
                _ch(t("clips", "clips"), topic=t("Highlights y plays.", "Highlights and clips.")),
                _ch(t("looking-for-game", "looking-for-game"), topic=t("Busca squad.", "Find a squad.")),
            ]),
            _cat(t("🔊 VOZ", "🔊 VOICE"), [
                _ch(t("Lobby", "Lobby"), type=2),
                _ch(t("Ranked 1", "Ranked 1"), type=2),
                _ch(t("Ranked 2", "Ranked 2"), type=2),
                _ch(t("AFK", "AFK"), type=2),
            ]),
        ],
        "rules": [
            rule("Respeto", "Respect",
                 "Trata a todo el mundo con educación. Insultos, acoso, racismo, homofobia, transfobia o ataques personales = sanción inmediata. El banter en partida no es una excusa para humillar.",
                 "Treat everyone decently. Insults, harassment, racism, homophobia, transphobia or personal attacks mean an instant sanction. In-game banter is not an excuse to humiliate people."),
            rule("Sin trampas ni hacks", "No cheats or hacks",
                 "Cualquier cheat, exploit, account sharing de ranked o venta de cuentas se denuncia y se banea. No enseñes métodos de trampa ni en clips.",
                 "Cheats, exploits, ranked account sharing or account selling get reported and banned. Don't showcase cheat methods in clips either."),
            rule("Toxicidad en voz y chat", "Toxicity in voice and chat",
                 "Nada de earrape, soundboards abusivos, gritos constantes ni flood de mayúsculas. Si te calientas, mutea el mic y respira.",
                 "No earrape, abusive soundboards, constant yelling or caps flood. If you tilt, mute your mic and breathe."),
            rule("Canales con sentido", "Use channels properly",
                 "Clips en clips, LFG en looking-for-game, memes en memes. El general no es un tablón de anuncios. Si no sabes dónde va, pregunta al staff.",
                 "Clips in clips, LFG in looking-for-game, memes in memes. General is not a billboard. If you don't know where a post belongs, ask staff."),
            rule("LFG claro", "Clear LFG",
                 "Cuando busques squad indica juego, rango, plataforma e idioma. No reclutes a ciegas por MD. Cancela el LFG si ya llenaste el grupo.",
                 "When looking for a squad, state game, rank, platform and language. Don't cold-recruit in DMs. Delete the LFG when the group is full."),
            rule("Spoilers y clips", "Spoilers and clips",
                 "Marca spoilers de campañas, lore o torneos en curso. No subas clips de otras personas sin consentimiento si se les reconoce la cara o el nick.",
                 "Tag spoilers for campaigns, lore or ongoing tournaments. Don't post clips of other people without consent if their face or name is recognizable."),
            rule("Spam y publicidad", "Spam and ads",
                 "Nada de invitar a otros servidores, vender coaching pirata, crypto o nitro falso. Auto-promo solo con permiso de un admin y nunca por MD masivo.",
                 "No poaching to other servers, pirate coaching, crypto or fake Nitro. Self-promo only with admin permission, never mass DMs."),
            rule("Multicuentas", "Alts",
                 "Las alts para evadir sanciones se banean las dos. Si necesitas una segunda cuenta, dilo en un ticket. La verificación web rastrea dispositivo.",
                 "Alts used to dodge sanctions get both accounts banned. If you need a second account, say so in a ticket. Web verification tracks the device."),
            rule("NSFW y edad", "NSFW and age",
                 "Este servidor de gaming es SFW. Nada de gore, nudes ni contenido sexual. Si un juego es +18, avisa antes de streamearlo en voz.",
                 "This gaming server is SFW. No gore, nudes or sexual content. If a game is 18+, warn before streaming it in voice."),
            rule("Verificación", "Verification",
                 "Pasa por {verify} al entrar. Sin verificar no hay chat general. Los tickets de soporte sí están abiertos si te atascas.",
                 "Go through {verify} when you join. No general chat until you're verified. Support tickets stay open if you get stuck."),
            rule("Quejas por ticket", "Complaints via ticket",
                 "Denuncias, apelaciones y problemas con el staff van por {tickets}, no por MD a un mod concreto ni por el general. Adjunta pruebas (capturas, IDs, hora).",
                 "Reports, appeals and staff issues go through {tickets}, not a random mod's DMs or general. Attach proof (screenshots, IDs, timestamps)."),
            rule("El staff manda", "Staff has the final say",
                 "Si un mod te pide que pares, paras. Discutir una sanción en público agrava el caso. Puedes apelar en ticket con educación. Saltar un mute o un ban = ban permanente.",
                 "If a mod tells you to stop, you stop. Arguing a sanction in public makes it worse. You may appeal in a ticket, politely. Evading a mute or ban is a permanent ban."),
        ],
    },
    "social": {
        "id": "social",
        "icon": "🦞",
        "name": t("Comunidad social", "Social community"),
        "description": t(
            "Amigos, presentaciones, arte, eventos. Verificación y logs listos.",
            "Friends, intros, art, events. Verification and logs ready.",
        ),
        "extra_roles": [
            _role("events", t("Eventos", "Events"), 0xEC4899, hoist=True, tags=["staff"]),
            _role("vip", t("VIP", "VIP"), 0xF59E0B, hoist=True),
            _role("artist", t("Artista", "Artist"), 0xA855F7, hoist=True),
            _role("music", t("Músico", "Musician"), 0x38BDF8),
            _role("lobster", t("Langosta", "Lobster"), 0x00FF88, hoist=True),
            _role("member", t("Miembro", "Member"), 0x94A3B8, hoist=True),
        ],
        "extra_categories": [
            _cat(t("💬 SALA", "💬 LOUNGE"), [
                _ch(t("general", "general")),
                _ch(t("presentaciones", "introductions"), topic=t("Cuéntanos quién eres.", "Tell us who you are.")),
                _ch(t("fotos", "photos")),
                _ch(t("off-topic", "off-topic")),
            ]),
            _cat(t("🎉 EVENTOS", "🎉 EVENTS"), [
                _ch(t("quedadas", "meetups")),
                _ch(t("Voz sala", "Lounge"), type=2),
                _ch(t("Voz karaoke", "Karaoke"), type=2),
            ]),
        ],
        "rules": [
            rule("Sé amable", "Be kind",
                 "Esta es una comunidad para convivir. Saluda, no interrumpas y asume buena fe. El sarcasmo agresivo y las burlas por acento, aspecto o gustos no tienen cabida.",
                 "This is a community to hang out. Say hi, don't talk over people and assume good faith. Aggressive sarcasm and mocking accent, looks or taste have no place here."),
            rule("Cero acoso", "Zero harassment",
                 "No persigas a nadie por MD, no insistas si te han dicho que no y no publiques datos personales (doxxing). Un no es un no, también en broma.",
                 "Don't chase people in DMs, don't push after a no, and don't post personal data (doxxing). No means no, even as a joke."),
            rule("NSFW solo donde toca", "NSFW only where allowed",
                 "Nada de contenido sexual, gore o fetichista en canales generales, fotos o voz. Si hay un canal marcado NSFW, úsalo y avisa. Minors: cero excepciones.",
                 "No sexual, gore or fetish content in general, photos or voice. If an NSFW channel exists, use it and warn. Minors: zero exceptions."),
            rule("Privacidad", "Privacy",
                 "No subas capturas de chats privados, direcciones, teléfonos ni fotos de terceros sin permiso. Lo que se cuenta en presentaciones se queda aquí.",
                 "Don't post private chat screenshots, addresses, phone numbers or photos of others without permission. What people share in intros stays here."),
            rule("Fotos y arte", "Photos and art",
                 "Pide consentimiento antes de etiquetar a alguien. El arte de terceros lleva crédito. No re-subas memes con datos de personas reales.",
                 "Ask before tagging someone. Third-party art needs credit. Don't reshare memes that expose real people's data."),
            rule("Presentaciones", "Introductions",
                 "Cuéntanos quién eres en el canal de presentaciones cuando puedas: nombre, aficiones, de dónde vienes. No es obligatorio, pero ayuda a que te conozcan.",
                 "Tell us who you are in introductions when you can: name, hobbies, where you're from. Not mandatory, but it helps people know you."),
            rule("Eventos y quedadas", "Events and meetups",
                 "Las quedadas oficiales se anuncian en el canal de eventos. Quedadas privadas: el servidor no se hace responsable. Nada de quedadas con menores a solas.",
                 "Official meetups are posted in events. Private meetups: the server isn't responsible. No one-on-one meetups involving minors."),
            rule("Spam y captación", "Spam and poaching",
                 "Prohibido invitar a otros Discords, vender merch no autorizada o inundar de links. Una auto-promo puntual, con permiso, en off-topic.",
                 "No inviting to other Discords, selling unauthorised merch or flooding links. Occasional self-promo, with permission, in off-topic."),
            rule("Multicuentas", "Alts",
                 "Si entras con otra cuenta para saltarte un timeout, se van las dos. Avísanos en ticket si es una cuenta de backup legítima.",
                 "If you join on another account to dodge a timeout, both go. Tell us in a ticket if it's a legitimate backup."),
            rule("Verificación", "Verification",
                 "Entra por {verify}. Hasta entonces solo ves información y puedes abrir ticket. Es un paso de un minuto en el navegador.",
                 "Go through {verify}. Until then you only see info channels and can open a ticket. It's a one-minute browser step."),
            rule("Conflictos", "Conflicts",
                 "Si hay drama, no lo aires en general. Abre un ticket en {tickets} con contexto. El staff media; no montes bandos.",
                 "If there's drama, don't air it in general. Open a ticket in {tickets} with context. Staff mediates; don't form factions."),
            rule("Autoridad del staff", "Staff authority",
                 "Las decisiones de moderación se respetan en el momento. Puedes pedir revisión en ticket, no en público. Reincidir en lo mismo sube la sanción.",
                 "Moderation calls are respected on the spot. You can ask for a review in a ticket, not in public. Repeating the same thing raises the sanction."),
        ],
    },
    "streamer": {
        "id": "streamer",
        "icon": "📺",
        "name": t("Streamer / creador", "Streamer / creator"),
        "description": t(
            "Directos, clips, subs y backstage. Logs y verificación incluidos.",
            "Livestreams, clips, subs and backstage. Logs and verification included.",
        ),
        "extra_roles": [
            _role("creator", t("Creador", "Creator"), 0xEF4444, hoist=True, tags=["staff", "admin"]),
            _role("editor", t("Editor", "Editor"), 0x8B5CF6, hoist=True, tags=["staff"]),
            _role("vip", t("VIP", "VIP"), 0xF59E0B, hoist=True),
            _role("sub", t("Sub", "Sub"), 0xF97316, hoist=True),
            _role("regular", t("Regular", "Regular"), 0x38BDF8),
            _role("member", t("Viewer", "Viewer"), 0x94A3B8, hoist=True),
        ],
        "extra_categories": [
            _cat(t("📢 DIRECTO", "📢 LIVE"), [
                _ch(t("en-directo", "now-live"), topic=t("Avisos de stream.", "Stream alerts."), slot="streams"),
                _ch(t("horarios", "schedule")),
                _ch(t("clips", "clips")),
            ]),
            _cat(t("💬 VIEWERS", "💬 VIEWERS"), [
                _ch(t("general", "general"), slot="general"),
                _ch(t("chat", "chat")),
                _ch(t("sugerencias", "suggestions"), slot="suggestions"),
                _ch(t("fan-art", "fan-art")),
                _ch(t("Hangout", "Hangout"), type=2),
            ]),
            _cat(t("🎬 BACKSTAGE", "🎬 BACKSTAGE"), [
                _ch(t("ideas-contenido", "content-ideas")),
            ], access="staff", staff_only=True),
        ],
        "rules": [
            rule("Respeta al creador y al chat", "Respect the creator and chat",
                 "Este es el espacio del creador y de la comunidad. Nada de ataques al streamer, al equipo ni a otros viewers. Critica el contenido, no a la persona.",
                 "This is the creator's space and the community's. No attacks on the streamer, the team or other viewers. Critique the content, not the person."),
            rule("Spoilers", "Spoilers",
                 "Si el creador aún no ha visto un capítulo, final o parche, no lo sueltes en chat ni en clips. Usa aviso de spoiler y espera a que el vod salga.",
                 "If the creator hasn't seen an episode, ending or patch yet, don't drop it in chat or clips. Use a spoiler warning and wait for the VOD."),
            rule("Sin backseating tóxico", "No toxic backseating",
                 "Sugerir una build está bien si lo piden. Repetir «haz esto» cada 10 segundos, reírte de las muertes o putear la skill = mute en el directo.",
                 "Suggesting a build is fine if they ask. Repeating «do this» every 10 seconds, laughing at deaths or insulting skill = muted on stream."),
            rule("No mendigues roles", "Don't beg for roles",
                 "No pidas mod, sub, VIP ni shoutout en vano. Los roles se dan por criterio del creador. Insistir por MD es motivo de timeout.",
                 "Don't beg for mod, sub, VIP or shoutouts. Roles are the creator's call. Pushing in DMs is a timeout."),
            rule("Links y seguridad", "Links and safety",
                 "Nada de acortadores raros, «sorteos» de nitro, supuestas donaciones ni archivos .exe. Cualquier link sospechoso se borra y se avisa al radar de hijack.",
                 "No sketchy shorteners, «Nitro giveaways», fake donations or .exe files. Suspicious links get deleted and flagged on the hijack radar."),
            rule("Clips y retransmisión", "Clips and restreaming",
                 "Puedes clipear el directo para el canal de clips. No retransmidas el stream en otro lado sin permiso. Crédito al creador si lo subes fuera.",
                 "You may clip the stream for the clips channel. Don't restream it elsewhere without permission. Credit the creator if you post it outside."),
            rule("Fan-art y encargos", "Fan-art and commissions",
                 "El fan-art se agradece en su canal, SFW. Encargos de dibujo: pactad precio fuera, sin spam. No uses la cara del creador para deepfakes ni nsfw.",
                 "Fan-art is welcome in its channel, SFW. Art commissions: agree price elsewhere, no spam. Don't use the creator's face for deepfakes or NSFW."),
            rule("Raids y raids hostiles", "Raids",
                 "Las raids amistosas se anuncian. Raid hostil, copypasta coordinada o raid de bots = ban. Si os raidean, no respondáis: avisad al staff.",
                 "Friendly raids get announced. Hostile raids, coordinated copypasta or bot raids = ban. If you get raided, don't engage: ping staff."),
            rule("Subs y donaciones", "Subs and donations",
                 "Nadie del staff te va a pedir dinero por MD. Donaciones solo por los enlaces oficiales del creador. Quien finja ser el streamer se banea.",
                 "Staff will never ask for money in DMs. Donations only via the creator's official links. Impersonating the streamer is a ban."),
            rule("Verificación", "Verification",
                 "Verifícate en {verify} para hablar en el chat de viewers. El panel es un clic a dabot.davito.es/verify.",
                 "Verify in {verify} to talk in viewer chat. The panel is one click to dabot.davito.es/verify."),
            rule("Sugerencias", "Suggestions",
                 "Ideas de contenido y quejas constructivas en el canal de sugerencias o en {tickets}. No descarriles el directo para exigir un juego.",
                 "Content ideas and constructive complaints go in suggestions or {tickets}. Don't derail the stream to demand a game."),
            rule("Staff y mods del chat", "Staff and chat mods",
                 "Los mods del Discord y del chat del directo van a una. Si te silencian en uno, no vengas al otro a llorar. Apelación solo por ticket.",
                 "Discord mods and live-chat mods work together. If you're muted in one, don't come to the other to complain. Appeals only via ticket."),
        ],
    },
    "shop": {
        "id": "shop",
        "icon": "🛒",
        "name": t("Tienda digital", "Digital store"),
        "description": t(
            "Vitrina de productos digitales, verificación, pedidos por desplegable y entregas. Pensada para vender cuentas, keys y suscripciones.",
            "Digital product showcase, verification, order dropdown and delivery. Built to sell accounts, keys and subscriptions.",
        ),
        "omit_infra": ["economy"],
        "extra_roles": [
            _role("owner", t("Dueño", "Owner"), 0xFDE68A, hoist=True, tags=["staff", "admin"]),
            _role("manager", t("Manager", "Manager"), 0xF59E0B, hoist=True, tags=["staff"]),
            _role("support", t("Soporte", "Support"), 0x22C55E, hoist=True, tags=["staff", "mod"]),
            _role("delivery", t("Entregas", "Fulfillment"), 0x38BDF8, hoist=True, tags=["staff"]),
            _role("vip", t("Cliente VIP", "VIP client"), 0xA855F7, hoist=True),
            _role("member", t("Cliente", "Customer"), 0x00FF88, hoist=True),
        ],
        "extra_categories": [
            _cat(t("🛒 VITRINA", "🛒 SHOWCASE"), [
                _ch(t("catalogo", "catalog"), topic=t("Productos digitales a la venta. Lee y abre pedido en tickets.", "Digital goods for sale. Read, then open an order ticket."), slot="catalog"),
                _ch(t("como-comprar", "how-to-buy"), topic=t("Pasos de compra, métodos de pago y plazos de entrega.", "Purchase steps, payment methods and delivery times."), slot="howto"),
                _ch(t("entregas", "delivery"), topic=t("Cómo se entrega el producto (MD, ticket, key).", "How the product is delivered (DM, ticket, key)."), slot="delivery_info"),
                _ch(t("reseñas", "reviews"), topic=t("Opiniones reales de pedidos entregados.", "Real reviews of fulfilled orders.")),
                _ch(t("faq", "faq"), topic=t("Garantía, reembolsos y stock.", "Warranty, refunds and stock.")),
            ], access="info", cid="showcase"),
            _cat(t("💬 CLIENTES", "💬 CUSTOMERS"), [
                _ch(t("general-clientes", "customer-chat"), topic=t("Chat de clientes verificados. Pedidos solo por ticket.", "Verified customer chat. Orders only via ticket."), slot="general"),
                _ch(t("dudas", "questions"), topic=t("Preguntas rápidas. Si es un pedido, usa el panel de tickets.", "Quick questions. If it's an order, use the ticket panel.")),
            ], cid="customers"),
            _cat(t("📦 OPERACIONES", "📦 OPERATIONS"), [
                _ch(t("cola-pedidos", "order-queue"), topic=t("Cola interna de pedidos abiertos.", "Internal queue of open orders.")),
                _ch(t("pagos", "payments"), topic=t("Comprobantes y pasarelas. Solo staff.", "Proofs and payment rails. Staff only.")),
                _ch(t("entregas-staff", "fulfillment"), topic=t("Keys, cuentas y capturas de entrega.", "Keys, accounts and delivery screenshots.")),
            ], access="staff", staff_only=True, cid="ops"),
        ],
        "ticket_panel": {
            "title": t("🛒  Pedido de producto digital", "🛒  Digital product order"),
            "description": t(
                "Elige el **producto** en el desplegable. Se abre un ticket privado con el staff para pagarlo y recibirlo.\n\nTambién sin verificar. No pagues por MD. Stock y precio son los de este panel.",
                "Pick the **product** in the dropdown. A private staff ticket opens to pay and receive it.\n\nWorks unverified too. Never pay via DM. Stock and price are what's on this panel.",
            ),
            "color": 0x00FF88,
            "footer": t("Dabot · pedidos digitales · dabot.davito.es", "Dabot · digital orders · dabot.davito.es"),
        },
        "ticket_categories": [
            {"id": "netflix", "label": t("Netflix 4K", "Netflix 4K"), "emoji": "🎬", "description": t("1 mes · 7,99€", "1 month · €7.99"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "price": t("7,99€", "€7.99"), "details": t("Perfil 4K. Entrega en el ticket en menos de 15 min (horario de tienda).", "4K profile. Delivered in the ticket under 15 min (store hours).")},
            {"id": "spotify", "label": t("Spotify Family", "Spotify Family"), "emoji": "🎧", "description": t("1 mes · 4,50€", "1 month · €4.50"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "price": t("4,50€", "€4.50"), "details": t("Invitación al plan familiar. Indica el correo de Spotify en el ticket.", "Family-plan invite. Put your Spotify email in the ticket.")},
            {"id": "youtube", "label": t("YouTube Premium", "YouTube Premium"), "emoji": "▶️", "description": t("1 mes · 5,99€", "1 month · €5.99"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "price": t("5,99€", "€5.99"), "details": t("Sin anuncios. Se entrega por correo / cuenta en el ticket.", "Ad-free. Delivered by email / account in the ticket.")},
            {"id": "chatgpt", "label": t("ChatGPT Plus", "ChatGPT Plus"), "emoji": "🤖", "description": t("1 mes · 12,00€", "1 month · €12.00"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "price": t("12,00€", "€12.00"), "details": t("Acceso Plus. No compartas la cuenta fuera del uso acordado.", "Plus access. Don't share the account beyond the agreed use.")},
            {"id": "nitro", "label": t("Discord Nitro", "Discord Nitro"), "emoji": "💎", "description": t("1 mes · 6,99€", "1 month · €6.99"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "price": t("6,99€", "€6.99"), "details": t("Nitro clásico. Se canjea con el enlace que te pasa soporte.", "Classic Nitro. Redeemed with the link support sends.")},
            {"id": "canva", "label": t("Canva Pro", "Canva Pro"), "emoji": "🎨", "description": t("1 mes · 4,99€", "1 month · €4.99"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "price": t("4,99€", "€4.99"), "details": t("Invitación Pro. Correo de Canva en el ticket.", "Pro invite. Put your Canva email in the ticket.")},
            {"id": "custom", "label": t("Otro producto / pack", "Other product / pack"), "emoji": "📦", "description": t("Lo que no está en la vitrina", "Anything not in the showcase"), "category": t("Tickets · Pedidos", "Tickets · Orders"), "details": t("Describe el producto, duración y presupuesto.", "Describe the product, duration and budget.")},
            {"id": "support", "label": t("Incidencia con un pedido", "Issue with an order"), "emoji": "🛠️", "description": t("No llegó, no funciona, stock", "Didn't arrive, broken, stock"), "category": t("Tickets · Soporte", "Tickets · Support"), "details": t("Adjunta ID del ticket original y capturas.", "Attach the original ticket ID and screenshots.")},
            {"id": "refund", "label": t("Reembolso / garantía", "Refund / warranty"), "emoji": "↩️", "description": t("Política de FAQ", "FAQ policy"), "category": t("Tickets · Soporte", "Tickets · Support"), "details": t("Solo si el producto no se entregó o no coincide. Digital entregado no se reembolsa por cambio de opinión.", "Only if it wasn't delivered or doesn't match. Delivered digital goods are not refunded for a change of mind.")},
        ],
        "rules": [
            rule("Pedidos por ticket", "Orders via ticket",
                 "Todo pedido, incidencia o cambio se abre en {tickets}. El MD al dueño o al soporte no es un canal oficial y puede ignorarse. Indica producto, cantidad y método de pago.",
                 "Every order, issue or change is opened in {tickets}. DMing the owner or support is not official and may be ignored. State product, quantity and payment method."),
            rule("Precios y stock", "Prices and stock",
                 "Lo que vale es lo publicado en el catálogo. Si un precio cambió, se respeta el que había cuando abriste el ticket, salvo error evidente. Sin stock = se te avisa y se cancela o se espera.",
                 "The catalogue price is the one that counts. If a price changed, the one when you opened the ticket stands, unless it's an obvious error. Out of stock = you're told, then cancel or wait."),
            rule("Pagos", "Payments",
                 "Solo los métodos anunciados por la tienda. Nunca pagues a una cuenta que te escriba por MD haciéndose pasar por staff. El servidor no pide seed phrases ni códigos 2FA.",
                 "Only the shop's announced methods. Never pay an account that DMs you pretending to be staff. The server will never ask for seed phrases or 2FA codes."),
            rule("Sin estafas ni chargebacks de mala fe", "No scams or bad-faith chargebacks",
                 "Quien reciba el producto y abra chargeback sin hablarlo se banea y se comparte en la red de tiendas si aplica. Si hay un fallo real, ticket y se resuelve.",
                 "Anyone who receives the product and chargebacks without talking first is banned and may be listed on shop networks. If something is actually wrong, open a ticket and it gets fixed."),
            rule("Reembolsos y cambios", "Refunds and exchanges",
                 "La política de devolución se publica en FAQ. No hay reembolso por «ya no lo quiero» si el producto es digital y se entregó. Digitales: captura de la entrega.",
                 "The refund policy is in FAQ. No refund for «I changed my mind» if the product is digital and was delivered. Digital goods: keep a screenshot of delivery."),
            rule("Respeto al soporte", "Respect support",
                 "El equipo puede tardar; no spamées el ticket ni menciones a todos los mods. Insultar al soporte cierra el ticket y suma warn. Un ticket = un tema.",
                 "The team may take time; don't spam the ticket or ping every mod. Insulting support closes the ticket and adds a warn. One ticket = one topic."),
            rule("Reseñas honestas", "Honest reviews",
                 "Las reseñas van en su canal, sin inventar pedidos. Crítica el producto, no doxees al vendedor. Fake reviews se borran y se sanciona.",
                 "Reviews go in their channel, without inventing orders. Critique the product, don't dox the seller. Fake reviews are deleted and sanctioned."),
            rule("Impersonación", "Impersonation",
                 "Hacerse pasar por la tienda, por un cliente VIP o por pasarela de pago es ban inmediato. Comprueba siempre el tag del bot y el canal.",
                 "Pretending to be the shop, a VIP client or a payment gateway is an instant ban. Always check the bot tag and the channel."),
            rule("Contenido de productos", "Product content",
                 "Si vendéis algo +18, se queda fuera de anuncios públicos y solo tras verificar edad. Nada de bienes ilegales. El catálogo manda.",
                 "If you sell 18+ goods, they stay off public announcements and only after age verification. No illegal goods. The catalogue rules."),
            rule("Verificación", "Verification",
                 "Verifícate en {verify} para hablar y abrir pedidos con normalidad. Los no verificados sí pueden abrir ticket de compra.",
                 "Verify in {verify} to chat and place orders normally. Unverified members can still open a purchase ticket."),
            rule("Tiempos de entrega", "Delivery times",
                 "Los plazos se indican en el ticket. Si se retrasan, el soporte actualiza. No asumas estafa a las dos horas: mira FAQ y el último mensaje del staff.",
                 "Deadlines are stated in the ticket. If they slip, support updates you. Don't assume a scam after two hours: check FAQ and the last staff message."),
            rule("Staff y evidencia", "Staff and evidence",
                 "Guarda IDs de ticket, capturas de pago y fechas. En un conflicto, gana quien trae pruebas. El dueño tiene la última palabra sobre stock y baneos.",
                 "Keep ticket IDs, payment screenshots and dates. In a conflict, proof wins. The owner has the final say on stock and bans."),
        ],
    },
    "study": {
        "id": "study",
        "icon": "📚",
        "name": t("Estudio / clase", "Study / class"),
        "description": t(
            "Aulas, deberes, voz de estudio y claustro. Verificación incluida.",
            "Classrooms, homework, study voice and staff. Verification included.",
        ),
        "extra_roles": [
            _role("teacher", t("Profesor", "Teacher"), 0xF59E0B, hoist=True, tags=["staff", "admin"]),
            _role("coord", t("Coordinador", "Coordinator"), 0xA855F7, hoist=True, tags=["staff"]),
            _role("ta", t("Ayudante", "TA"), 0x3B82F6, hoist=True, tags=["staff"]),
            _role("delegate", t("Delegado", "Delegate"), 0x38BDF8, hoist=True),
            _role("member", t("Alumno", "Student"), 0x00FF88, hoist=True),
            _role("guest", t("Invitado", "Guest"), 0x94A3B8),
        ],
        "extra_categories": [
            _cat(t("💬 CHAT", "💬 CHAT"), [
                _ch(t("general", "general"), slot="general"),
            ]),
            _cat(t("📚 AULA", "📚 CLASS"), [
                _ch(t("avisos", "notices")),
                _ch(t("temario", "syllabus")),
                _ch(t("dudas", "questions")),
                _ch(t("deberes", "homework")),
            ]),
            _cat(t("🎧 ESTUDIO", "🎧 STUDY"), [
                _ch(t("Sala estudio 1", "Study room 1"), type=2),
                _ch(t("Sala estudio 2", "Study room 2"), type=2),
            ]),
            _cat(t("🛡️ CLAUSTRO", "🛡️ STAFF ROOM"), [
                _ch(t("claustro", "faculty")),
            ], access="staff", staff_only=True),
        ],
        "rules": [
            rule("Respeto en el aula", "Respect in class",
                 "Profesorado, ayudantes y compañeros se tratan de usted o con el tuteo que pida el grupo, pero siempre con respeto. Nada de motes hirientes ni risitas en las explicaciones.",
                 "Teachers, TAs and classmates are treated with respect. No hurtful nicknames or giggling over explanations."),
            rule("Sin copiar ni filtrar", "No cheating or leaks",
                 "Prohibido copiar exámenes, compartir respuestas en directo o subir PDFs privados del curso. Quien filtre material se expulsa del aula y se avisa a coordinación.",
                 "No copying exams, sharing live answers or uploading private course PDFs. Leaking material means removal from class and a report to coordinators."),
            rule("Dudas en su canal", "Questions in the right channel",
                 "Las preguntas de temario van en dudas, no por MD al profesor a las 3 de la mañana. Busca si ya se preguntó. Los deberes urgentes: canal de deberes, con enunciado.",
                 "Syllabus questions go in questions, not a 3am DM to the teacher. Search if it was already asked. Urgent homework: homework channel, with the prompt."),
            rule("Voz de estudio", "Study voice",
                 "En las salas de estudio se habla bajo o se usa push-to-talk. Nada de música a todo volumen ni calls ajenas a la asignatura. Si vas a charlar, cambia de sala.",
                 "Study rooms are quiet or push-to-talk. No loud music or off-topic calls. If you want to chat, switch rooms."),
            rule("Grabaciones", "Recordings",
                 "No grabes clases ni voz sin permiso explícito del profesor. Difundir un clip fuera del servidor es falta grave.",
                 "Don't record classes or voice without the teacher's explicit permission. Spreading a clip outside the server is a serious offence."),
            rule("Bullying académico", "Academic bullying",
                 "Reírse de notas, de preguntas «tontas» o de acentos no se tolera. El aula es para aprender. Un aviso y, si sigue, fuera.",
                 "Laughing at grades, «stupid» questions or accents is not tolerated. Class is for learning. One warning, then you're out."),
            rule("Entregas y plazos", "Deadlines",
                 "Las fechas de deberes se anuncian en avisos. Pedir prórroga: ticket o mensaje al ayudante con tiempo, no el mismo día a última hora.",
                 "Homework dates are posted in notices. Ask for extra time via ticket or a TA, in advance — not the same day at the last minute."),
            rule("Invitados", "Guests",
                 "Los invitados no entran a exámenes ni a material interno. Si traes a alguien, avisa a coordinación. El rol de alumno no se presta.",
                 "Guests don't join exams or internal material. If you bring someone, tell coordinators. The student role is not shared."),
            rule("Multicuentas", "Alts",
                 "Una persona, una cuenta de alumno. Las alts para entregar dos veces o evadir un mute se sancionan como copia.",
                 "One person, one student account. Alts used to submit twice or dodge a mute are treated as cheating."),
            rule("Verificación", "Verification",
                 "Verifícate en {verify} para acceder al aula. Es la forma de saber que no eres un bot coleccionando apuntes.",
                 "Verify in {verify} to access class. It's how we know you're not a bot farming notes."),
            rule("Tickets de incidencias", "Issue tickets",
                 "Notas mal puestas, ausencias, conflictos con un compañero: {tickets}. No lo discutas en general delante de toda la clase.",
                 "Wrong grades, absences, conflict with a classmate: {tickets}. Don't debate it in general in front of the whole class."),
            rule("Coordinación manda", "Coordinators decide",
                 "Profesor y coordinación tienen la última palabra sobre normas de evaluación. Reclamar está bien; saltarse un mute de clase no.",
                 "Teachers and coordinators have the final say on assessment rules. Appealing is fine; skipping a class mute is not."),
        ],
    },
    "clan": {
        "id": "clan",
        "icon": "⚔️",
        "name": t("Clan / guild", "Clan / guild"),
        "description": t(
            "Líder, officers, trials y alianzas. Logs y verify listos.",
            "Leader, officers, trials and allies. Logs and verify ready.",
        ),
        "extra_roles": [
            _role("leader", t("Líder", "Leader"), 0xFDE68A, hoist=True, tags=["staff", "admin"]),
            _role("officer", t("Officer", "Officer"), 0xF59E0B, hoist=True, tags=["staff", "mod"]),
            _role("veteran", t("Veterano", "Veteran"), 0xA855F7, hoist=True),
            _role("member", t("Miembro", "Member"), 0x00FF88, hoist=True),
            _role("trial", t("Trial", "Trial"), 0x38BDF8, hoist=True),
            _role("ally", t("Aliado", "Ally"), 0x94A3B8),
        ],
        "extra_categories": [
            _cat(t("🏰 CLAN", "🏰 CLAN"), [
                _ch(t("general", "general")),
                _ch(t("estrategia", "strategy")),
                _ch(t("reclutamiento", "recruiting")),
                _ch(t("botin", "loot")),
            ]),
            _cat(t("🔊 WAR", "🔊 WAR"), [
                _ch(t("War 1", "War 1"), type=2),
                _ch(t("War 2", "War 2"), type=2),
            ]),
        ],
        "rules": [
            rule("Lo de war se queda en war", "What happens in war stays in war",
                 "Composiciones, horarios de hit, logs y rage no se publican fuera ni en reclutamiento. Filtrar strats a otro clan es traición y ban + kick del roster.",
                 "Comps, hit times, logs and rage don't leave war or get posted in recruiting. Leaking strats to another clan is betrayal: ban + roster kick."),
            rule("Drama en ticket", "Drama in a ticket",
                 "Enfados de loot, parses o benches se hablan con officers por {tickets} o staff-chat, no en general. Airear un kick en público suma sanción.",
                 "Loot, parse or bench drama goes to officers via {tickets} or staff-chat, not general. Airing a kick in public adds a sanction."),
            rule("Trials y reclutamiento", "Trials and recruiting",
                 "Los trials se presentan en reclutamiento: clase, logs, disponibilidad. No prometas rango de member. Un officer confirma el trial y el periodo.",
                 "Trials intro in recruiting: class, logs, availability. Don't promise a member rank. An officer confirms the trial and the period."),
            rule("Horarios de raid", "Raid times",
                 "Si confirmaste asistencia, llega o avisa con margen. Tres no-shows sin aviso = review de roster. Invites se cierran a la hora anunciada.",
                 "If you confirmed, show up or give notice. Three no-shows without warning = roster review. Invites close at the announced time."),
            rule("Loot", "Loot",
                 "El sistema de loot (LC, EPGP, big dick, etc.) lo decide liderazgo y se respeta. Ninja loot = kick inmediato. Los rolls se hacen donde diga el officer.",
                 "The loot system (LC, EPGP, etc.) is leadership's call and is respected. Ninja loot = instant kick. Rolls happen where the officer says."),
            rule("Comms en voz", "Voice comms",
                 "En war, push-to-talk o mic limpio. Nada de música, discusiones de loot a mitad de boss ni insultos a aliados. El raid lead corta el habla.",
                 "In war, push-to-talk or a clean mic. No music, loot arguments mid-boss or insulting allies. The raid lead cuts talk."),
            rule("Aliados", "Allies",
                 "Los aliados son invitados: se les trata bien y no se les spamea reclutamiento. Sus normas en su raid se respetan cuando vamos de visita.",
                 "Allies are guests: treat them well and don't spam-recruit them. Their raid rules apply when we visit."),
            rule("Alts y rerolls", "Alts and rerolls",
                 "Avisa qué personaje es main. Traer un alt a war sin decirlo para llevarse loot de main es falta. Las alts de Discord para evadir kicks se banean.",
                 "Say which character is your main. Bringing an alt to war undeclared to take main loot is an offence. Discord alts to dodge kicks get banned."),
            rule("Reclutamiento externo", "External recruiting",
                 "No fichamos gente de clanes aliados sin hablarlo. Poaching = mal visto y posible expulsión. Las ofertas se consultan con el líder.",
                 "We don't poach allied rosters without a conversation. Poaching is frowned on and can mean removal. Offers go through the leader."),
            rule("Verificación", "Verification",
                 "Todo el mundo, también trials y aliados puntuales, pasa por {verify}. Así sabemos quién entra al Discord de war.",
                 "Everyone, including trials and one-night allies, goes through {verify}. That's how we know who is in the war Discord."),
            rule("Conducta fuera", "Conduct outside",
                 "Lo que hagas en otros servidores o en el juego puede pesar si mancha el nombre del clan. Representas el tag.",
                 "What you do on other servers or in-game can matter if it stains the clan name. You represent the tag."),
            rule("Liderazgo", "Leadership",
                 "Líder y officers tienen la última palabra en roster, strats y sanciones. Se puede discutir en privado; no se vota un kick en general a gritos.",
                 "Leader and officers have the final say on roster, strats and sanctions. You can discuss in private; we don't vote-kick in general by shouting."),
        ],
    },
    "music": {
        "id": "music",
        "icon": "🎵",
        "name": t("Música", "Music"),
        "description": t(
            "DJ, artistas, lanzamientos y salas de escucha.",
            "DJs, artists, releases and listening rooms.",
        ),
        "extra_roles": [
            _role("dj", t("DJ", "DJ"), 0xA855F7, hoist=True, tags=["staff"]),
            _role("artist", t("Artista", "Artist"), 0xEC4899, hoist=True),
            _role("producer", t("Productor", "Producer"), 0xF59E0B, hoist=True),
            _role("vip", t("VIP", "VIP"), 0xFDE68A, hoist=True),
            _role("member", t("Fan", "Fan"), 0x38BDF8, hoist=True),
        ],
        "extra_categories": [
            _cat(t("🎶 SALA", "🎶 LOUNGE"), [
                _ch(t("general", "general")),
                _ch(t("lanzamientos", "releases")),
                _ch(t("colaboraciones", "collabs")),
                _ch(t("feedback", "feedback")),
            ]),
            _cat(t("🎧 ESCUCHA", "🎧 LISTEN"), [
                _ch(t("DJ booth", "DJ booth"), type=2),
                _ch(t("Listening 1", "Listening 1"), type=2),
            ]),
        ],
        "rules": [
            rule("Nada de piratería ni leaks", "No piracy or leaks",
                 "Prohibido pasar mega, rips, leaks de álbumes no salidos o stems robados. Quien pida o suelte un leak se va. Apoya a los artistas: links oficiales, Bandcamp, Beatport.",
                 "No mega dumps, rips, unreleased album leaks or stolen stems. Anyone asking for or dropping a leak is out. Support artists: official links, Bandcamp, Beatport."),
            rule("Créditos", "Credit",
                 "Si compartes un tema, pon artista, título y enlace. No pases un track como tuyo. Los remixes no oficiales se marcan como bootleg.",
                 "When you share a track, add artist, title and a link. Don't pass a track off as yours. Unofficial remixes get marked as bootlegs."),
            rule("DJ booth", "DJ booth",
                 "La sala DJ booth es para quien tiene el rol DJ, en su slot. No te cueles a poner cola. Si quieres pinchar, pide turno en colaboraciones o a un DJ.",
                 "DJ booth is for the DJ role, in their slot. Don't jump in and queue tracks. If you want to play, ask for a slot in collabs or to a DJ."),
            rule("Feedback constructivo", "Constructive feedback",
                 "En feedback se critica la mezcla, el arrangement, el mastering: concreto y respetuoso. «Esto es basura» sin más se borra. Pide feedback, no validación eterna.",
                 "In feedback you talk mix, arrangement, mastering: specific and respectful. Bare «this is trash» gets deleted. Ask for feedback, not endless validation."),
            rule("Auto-promo", "Self-promo",
                 "Un drop por lanzamiento en el canal de lanzamientos. No pegues tu SoundCloud cada hora en general. Collabs: canal de colaboraciones, con referencias y deadline.",
                 "One drop per release in releases. Don't paste your SoundCloud every hour in general. Collabs: collabs channel, with references and a deadline."),
            rule("Volumen y oídos", "Volume and ears",
                 "En salas de escucha no pongas el bot a destrozar. Avisa si el track pega un drop muy fuerte. Quien haga earrape pierde el rol DJ un tiempo.",
                 "In listening rooms don't crank the bot to pain. Warn if a track has a huge drop. Earrape means you lose the DJ role for a while."),
            rule("Letras y NSFW", "Lyrics and NSFW",
                 "Temas con letras explícitas o samples +18 se avisan. Nada de portadas pornográficas en general. El arte erótico, si se permite, va etiquetado.",
                 "Tracks with explicit lyrics or 18+ samples get a warning. No porn covers in general. Erotic art, if allowed, is tagged."),
            rule("Sampling y derechos", "Sampling and rights",
                 "No subas un bootleg de un tema con copyright para que el bot lo ponga en bucle 24/7 si la sala es pública y el autor lo ha pedido bajar. Respeta Content ID y a los labels.",
                 "Don't upload a copyrighted bootleg for the bot to loop 24/7 in a public room if the artist asked it down. Respect Content ID and labels."),
            rule("Colaboraciones", "Collaborations",
                 "Si entras en un collab, cumple plazos o avisa. Quedarte stems de otro y sacarlos como tuyos es falta grave. Acordad splits antes de publicar.",
                 "If you join a collab, hit deadlines or say so. Keeping someone else's stems and releasing them as yours is serious. Agree splits before you publish."),
            rule("Verificación", "Verification",
                 "Verifícate en {verify} para pedir temas, dejar feedback y entrar a voz. Los DJs verificados primero.",
                 "Verify in {verify} to request tracks, leave feedback and join voice. DJs verify first."),
            rule("Tickets", "Tickets",
                 "Problemas con un collab, un DJ que no cede la sala o un leak: {tickets}. No lo conviertas en beef en general.",
                 "Issues with a collab, a DJ who won't leave the booth or a leak: {tickets}. Don't turn it into public beef."),
            rule("Staff y DJs", "Staff and DJs",
                 "Los DJs con rol de staff cortan la cola si hace falta. Discutir un corte de tema en voz a gritos = te sales. Se habla luego en ticket.",
                 "DJs with staff can cut the queue if needed. Yelling about a track cut in voice = you leave. Talk later in a ticket."),
        ],
    },
}


def resolve_template(template_id: str, lang: str = "es") -> dict | None:
    raw = TEMPLATES.get(template_id)
    if not raw:
        return None
    lang = "en" if str(lang).lower().startswith("en") else "es"
    roles = list(CORE_ROLES) + list(raw.get("extra_roles") or [])
    # de-dupe by id, extra can override core (e.g. creator as admin)
    by_id = {}
    for r in roles:
        by_id[r["id"]] = r
    roles = list(by_id.values())
    omit = set(raw.get("omit_infra") or [])
    cats = [c for c in _infra_categories() if (c.get("cid") or "") not in omit]
    cats = cats + list(raw.get("extra_categories") or [])

    def loc_role(r):
        return {
            "id": r["id"],
            "name": pick(r["name"], lang),
            "color": r["color"],
            "hoist": r.get("hoist") or False,
            "permissions": r.get("permissions") or "0",
            "tags": list(r.get("tags") or []),
        }

    def loc_ch(ch):
        return {
            "name": pick(ch["name"], lang),
            "type": ch.get("type") or 0,
            "topic": pick(ch.get("topic") or "", lang),
            "slot": ch.get("slot"),
        }

    def loc_cat(c):
        return {
            "name": pick(c["name"], lang),
            "access": c.get("access") or "verified",
            "staff_only": bool(c.get("staff_only")),
            "cid": c.get("cid"),
            "channels": [loc_ch(ch) for ch in c["channels"]],
        }

    def loc_ticket(c):
        out = dict(c)
        for key in ("label", "description", "category", "price", "details"):
            if key in out:
                out[key] = pick(out[key], lang)
        return out

    panel_raw = raw.get("ticket_panel") or {}
    ticket_panel = {
        "title": pick(panel_raw.get("title") or t("🎫 Tickets", "🎫 Tickets"), lang),
        "description": pick(panel_raw.get("description") or t(
            "Elige una opción en el desplegable. También sin verificar.",
            "Pick an option in the dropdown. Works unverified too.",
        ), lang),
        "color": int(panel_raw.get("color") or 0x00FF88),
        "image": panel_raw.get("image") or "",
        "thumbnail": panel_raw.get("thumbnail") or "",
        "footer": pick(panel_raw.get("footer") or t("Dabot · dabot.davito.es", "Dabot · dabot.davito.es"), lang),
    }

    return {
        "id": raw["id"],
        "icon": raw["icon"],
        "lang": lang,
        "name": pick(raw["name"], lang),
        "description": pick(raw["description"], lang),
        "rules": [
            {"title": pick(r.get("title") or "", lang), "text": pick(r.get("text") or "", lang)}
            for r in (raw.get("rules") or [])
            if isinstance(r, dict)
        ] if isinstance(raw.get("rules"), list) else pick(raw.get("rules") or t("", ""), lang),
        "roles": [loc_role(r) for r in roles],
        "categories": [loc_cat(c) for c in cats],
        "welcome": pick(
            t("¡Bienvenido {mention} a **{server}**! Verifícate y pasa por reglas. Eres el #{count} 🦞",
              "Welcome {mention} to **{server}**! Verify and read the rules. You are member #{count} 🦞"),
            lang,
        ),
        "goodbye": pick(
            t("{user} ha salido de **{server}**. Quedan {count}.",
              "{user} left **{server}**. {count} members remain."),
            lang,
        ),
        "tickets_category": pick(t("Tickets · Pedidos", "Tickets · Orders") if raw.get("id") == "shop" else t("Tickets", "Tickets"), lang),
        "ticket_panel": ticket_panel,
        "ticket_categories": [loc_ticket(c) for c in (raw.get("ticket_categories") or [])],
        "locale": "en-US" if lang == "en" else "es-ES",
    }


def list_templates(lang: str = "es") -> list[dict]:
    out = []
    for tid in TEMPLATES:
        tpl = resolve_template(tid, lang)
        if not tpl:
            continue
        out.append({
            "id": tpl["id"],
            "name": tpl["name"],
            "description": tpl["description"],
            "icon": tpl["icon"],
            "roles": len(tpl["roles"]),
            "channels": sum(len(c["channels"]) for c in tpl["categories"]),
            "lang": lang,
        })
    return out


def save_template_config(guild_id: int, slots: dict, tpl: dict, staff_role_names: list[str]) -> None:
    """Persist logs, welcome, leveling, tickets, automod, lang into guild_configs + verification."""
    from utils.config import DEFAULT_CONFIG
    path = os.environ.get("DATABASE_PATH", "dabot.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE verification_config ADD COLUMN alts_channel_id INTEGER")
        except Exception:
            pass
        cur.execute(
            """CREATE TABLE IF NOT EXISTS verification_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                verification_channel_id INTEGER NOT NULL,
                unverified_role_id INTEGER NOT NULL,
                verified_role_id INTEGER NOT NULL,
                verification_type TEXT DEFAULT 'web',
                alts_channel_id INTEGER
            )"""
        )
        cur.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (int(guild_id),))
        row = cur.fetchone()
        data = json.loads(row[0]) if row and row[0] else {}
        if not isinstance(data, dict):
            data = {}

        def merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    merge(dst[k], v)
                else:
                    dst[k] = v

        lang = tpl.get("locale") or "es-ES"
        patch = {
            "lang": lang,
            "prefix": "!",
            "welcome": {
                "enabled": True,
                "channel_id": str(slots.get("welcome") or ""),
                "message": tpl.get("welcome") or DEFAULT_CONFIG["welcome"]["message"],
            },
            "goodbye": {
                "enabled": True,
                "channel_id": str(slots.get("welcome") or ""),
                "message": tpl.get("goodbye") or DEFAULT_CONFIG["goodbye"]["message"],
            },
            "leveling": {
                "enabled": False,
                "level_up_channel": str(slots.get("levels") or ""),
                "leaderboard_channel": str(slots.get("levels") or ""),
            },
            "economy": {
                "enabled": True,
                "currency_symbol": "🦞",
                "channel_id": str(slots.get("economy") or ""),
                "leaderboard_channel": str(slots.get("economy.top") or ""),
                "shop_channel": str(slots.get("economy.shop") or ""),
            },
            "achievements": {"enabled": False},
            "chatbot": {"enabled": False, "channel_ids": []},
            "tickets": {
                "category_name": tpl.get("tickets_category") or "Tickets",
                "transcript_channel_id": str(slots.get("logs.tickets") or ""),
                "staff_roles": staff_role_names or ["Admin", "Moderador", "Moderator", "Soporte", "Support"],
                "panel": tpl.get("ticket_panel") or {},
                **({"categories": tpl["ticket_categories"]} if tpl.get("ticket_categories") else {}),
            },
            "logs": {
                **{
                    "messages": str(slots.get("logs.messages") or ""),
                    "moderation": str(slots.get("logs.moderation") or ""),
                    "voice": str(slots.get("logs.voice") or ""),
                    "members": str(slots.get("logs.members") or ""),
                    "joins": str(slots.get("logs.joins") or ""),
                    "alts": str(slots.get("logs.alts") or ""),
                    "hijack": str(slots.get("logs.hijack") or ""),
                    "tickets": str(slots.get("logs.tickets") or ""),
                    "server": str(slots.get("logs.server") or ""),
                    "verification": str(slots.get("logs.verification") or ""),
                }
            },
            "automod": {
                "enabled": True,
                "block_invites": True,
                "hijack": True,
                "hijack_timeout": True,
            },
            "suggestions": {
                "channel": str(slots.get("suggestions") or ""),
            },
        }
        merge(data, patch)
        cur.execute(
            """INSERT INTO guild_configs (guild_id, config_json) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET config_json = excluded.config_json""",
            (int(guild_id), json.dumps(data, ensure_ascii=False)),
        )
        verify_ch = slots.get("verify")
        unverified = slots.get("role.unverified")
        verified = slots.get("role.verified")
        if verify_ch and unverified and verified:
            try:
                cur.execute("ALTER TABLE verification_config ADD COLUMN alts_channel_id INTEGER")
            except Exception:
                pass
            cur.execute(
                """INSERT INTO verification_config
                   (guild_id, enabled, verification_channel_id, unverified_role_id, verified_role_id, verification_type, alts_channel_id)
                   VALUES (?, 1, ?, ?, ?, 'web', ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                     enabled = 1,
                     verification_channel_id = excluded.verification_channel_id,
                     unverified_role_id = excluded.unverified_role_id,
                     verified_role_id = excluded.verified_role_id,
                     verification_type = 'web',
                     alts_channel_id = excluded.alts_channel_id""",
                (int(guild_id), int(verify_ch), int(unverified), int(verified), int(slots.get("logs.alts") or 0) or None),
            )
        conn.commit()
        if slots.get("logs.alts"):
            try:
                from utils import alt_intel
                alt_intel.set_alts_channel(conn, int(guild_id), int(slots["logs.alts"]))
            except Exception:
                pass
    finally:
        conn.close()
