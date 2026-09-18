"""Product feedback for Dabot: owners/admins → private review channel."""
from __future__ import annotations

SUGGEST_GUILD_ID = 1413959468365905962
SUGGEST_CHANNEL_ID = 1543279363548782592

STATUS = {
    "pending": ("💡 Nueva sugerencia para Dabot", 0xFBBF24),
    "reviewing": ("🔎 Evaluando sugerencia", 0x38BDF8),
    "accepted": ("✅ Sugerencia aceptada", 0x22C55E),
    "rejected": ("❌ Sugerencia rechazada", 0xEF4444),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    guild_id INTEGER,
    guild_name TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    response TEXT,
    message_id INTEGER,
    channel_id INTEGER,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by INTEGER
)
"""


def embed_payload(row: dict) -> dict:
    status = row.get("status") or "pending"
    title, color = STATUS.get(status, STATUS["pending"])
    fields = [
        {"name": "Autor", "value": f"<@{row['user_id']}> (`{row['user_id']}`)", "inline": True},
        {"name": "Servidor", "value": f"{row.get('guild_name') or '—'} (`{row.get('guild_id') or '—'}`)", "inline": True},
        {"name": "Estado", "value": status, "inline": True},
    ]
    if row.get("response"):
        fields.append({"name": "Respuesta", "value": str(row["response"])[:1024], "inline": False})
    return {
        "title": title,
        "description": (row.get("text") or "")[:4000],
        "color": color,
        "fields": fields,
        "footer": {"text": f"Sugerencia #{row.get('id')} · dabot.davito.es"},
    }


def components_payload(suggestion_id: int) -> list:
    sid = int(suggestion_id)
    return [{
        "type": 1,
        "components": [
            {"type": 2, "style": 3, "label": "Sugerencia aceptada", "custom_id": f"dabot:sug:accepted:{sid}"},
            {"type": 2, "style": 4, "label": "Sugerencia rechazada", "custom_id": f"dabot:sug:rejected:{sid}"},
            {"type": 2, "style": 2, "label": "Evaluando sugerencia", "custom_id": f"dabot:sug:reviewing:{sid}"},
        ],
    }]


def dm_text(status: str, original: str, response: str) -> str:
    labels = {
        "accepted": "aceptada",
        "rejected": "rechazada",
        "reviewing": "en evaluación",
    }
    label = labels.get(status, status)
    return (
        f"**Tu sugerencia para Dabot ha sido marcada como {label}.**\n\n"
        f"**Respuesta:**\n{response}\n\n"
        f"**Tu sugerencia:**\n{original[:1500]}"
    )
