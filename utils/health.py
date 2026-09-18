"""Server setup health checklist for dashboard and /start."""
from __future__ import annotations

import json


def evaluate(conn, guild_id: int, config: dict | None) -> dict:
    cfg = config or {}
    logs = cfg.get("logs") or {}
    automod = cfg.get("automod") or {}
    welcome = cfg.get("welcome") or {}
    tickets = cfg.get("tickets") or {}
    items = []

    def add(key, ok, label, hint, premium=False):
        items.append({"id": key, "ok": bool(ok), "label": label, "hint": hint, "premium": premium})

    cur = conn.cursor()

    def one(sql, args=()):
        try:
            cur.execute(sql, args)
            return cur.fetchone()
        except Exception:
            return None

    add("logs_mod", bool(logs.get("moderation") or logs.get("mod_log")),
        "Canal de logs de moderación", "Configuración → Logs → Moderación")
    add("logs_msg", bool(logs.get("messages")),
        "Canal de logs de mensajes", "Configuración → Logs → Mensajes")
    add("logs_alts", bool(logs.get("alts")),
        "Canal de multicuentas", "Configuración → Logs → Multicuentas, o /verification logs")
    add("logs_verification", bool(logs.get("verification") or logs.get("joins")),
        "Canal de logs de verificación", "Configuración → Logs → Verificaciones, o /verification logchannel")
    add("logs_hijack", bool(logs.get("hijack") or logs.get("moderation")),
        "Avisos de cuentas hackeadas", "Configuración → Logs → Cuentas hackeadas (si no, usa moderación)")
    add("automod", bool(automod.get("enabled")),
        "AutoMod (spam / invitaciones)", "Módulos → AutoMod")
    add("hijack", automod.get("hijack", True),
        "Radar de secuestro MrBeast/Nitro", "Módulos → AutoMod → Radar de secuestro")
    v = one("SELECT enabled, verified_role_id FROM verification_config WHERE guild_id = ?", (int(guild_id),))
    v_ok = bool(v and int((v[0] if not hasattr(v, "keys") else v["enabled"]) or 0) == 1)
    add("verify", v_ok, "Verificación web", "/verification setup y publica el panel en Resumen")
    add("welcome", bool(welcome.get("enabled") and welcome.get("channel_id")),
        "Bienvenida", "Módulos → Bienvenida")
    add("tickets", True,
        "Tickets (registro en la web)", "Resumen → Publicar panel de tickets. El historial vive en dabot.davito.es")
    raid = one("SELECT enabled FROM antiraid_config WHERE guild_id = ?", (int(guild_id),))
    raid_ok = bool(raid and int((raid[0] if not hasattr(raid, "keys") else raid["enabled"]) or 0) == 1)
    add("antiraid", raid_ok, "Anti-raid", "/antiraid setup")
    try:
        from utils.premium import guild_record_sync
        rec = guild_record_sync(conn, int(guild_id))
        prem = bool(rec and rec.get("active"))
    except Exception:
        prem = False
    add("premium", prem, "Dabot Premium", "IA, backups completos y personalización. El creador lo activa.", True)

    done = sum(1 for i in items if i["ok"] and not i["premium"])
    need = sum(1 for i in items if not i["premium"])
    score = int(round(100 * done / need)) if need else 100
    missing = [i for i in items if not i["ok"]]
    return {"score": score, "done": done, "total": need, "items": items, "missing": missing}
