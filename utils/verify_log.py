"""Persist verification events for the dashboard and Discord log channels."""
from __future__ import annotations

import json
from datetime import datetime

from utils.helpers import DASHBOARD_URL
from utils.alt_intel import public_ip_codes, redact_ips

SCHEMA = """
CREATE TABLE IF NOT EXISTS verification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    avatar TEXT,
    method TEXT NOT NULL DEFAULT 'web',
    status TEXT NOT NULL DEFAULT 'ok',
    risk_score INTEGER,
    risk_label TEXT,
    ip TEXT,
    ip_masked TEXT,
    country TEXT,
    device_id TEXT,
    case_id INTEGER,
    actor_id INTEGER,
    extra TEXT,
    created_at TEXT NOT NULL
)
"""

VERIFIED_STATUSES = ("ok", "already", "manual")

METHOD_LABELS = {
    "web": "Navegador (dabot.davito.es/verify)",
    "emoji": "Reto emoji",
    "math": "Reto matemático",
    "manual": "Staff en Discord",
    "alt_approve": "Aprobación multicuenta",
}


def avatar_cdn(user_id, avatar: str = "") -> str:
    av = (avatar or "").strip()
    if av.startswith("http"):
        return av
    if av and user_id:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{av}.png?size=64"
    return ""


def ensure_schema_sync(conn) -> None:
    cur = conn.cursor()
    cur.execute(SCHEMA)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ve_guild ON verification_events(guild_id, id DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ve_user ON verification_events(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ve_guild_user ON verification_events(guild_id, user_id, id DESC)")
    try:
        conn.commit()
    except Exception:
        pass


def record_sync(
    conn,
    *,
    guild_id: int,
    user_id: int,
    username: str = "",
    avatar: str = "",
    method: str = "web",
    status: str = "ok",
    risk_score=None,
    risk_label: str = "",
    ip: str = "",
    ip_masked: str = "",
    country: str = "",
    device_id: str = "",
    case_id=None,
    actor_id=None,
    extra=None,
) -> int:
    ensure_schema_sync(conn)
    now = datetime.utcnow().isoformat()
    extra_s = extra if isinstance(extra, str) else json.dumps(extra or {}, ensure_ascii=False)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO verification_events
           (guild_id, user_id, username, avatar, method, status, risk_score, risk_label,
            ip, ip_masked, country, device_id, case_id, actor_id, extra, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(guild_id), int(user_id), username or "", avatar or "",
            method or "web", status or "ok",
            int(risk_score) if risk_score is not None else None,
            risk_label or "",
            ip or "", ip_masked or "", country or "",
            (device_id or "")[:64],
            int(case_id) if case_id else None,
            int(actor_id) if actor_id else None,
            extra_s, now,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def channel_id_sync(conn, guild_id: int):
    """Staff verification log. Never the public #verificacion channel."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (int(guild_id),))
        row = cur.fetchone()
        raw = row[0] if row else None
        if hasattr(row, "keys") and row:
            raw = row["config_json"]
        data = json.loads(raw or "{}")
        logs = data.get("logs") or {}
        for key in ("verification", "joins"):
            val = logs.get(key)
            if val and str(val).isdigit():
                return int(val)
    except Exception:
        return None
    return None


def discord_embed(
    *,
    guild_id: int,
    user_id: int,
    username: str,
    method: str,
    status: str,
    risk_score=None,
    risk_label: str = "",
    ip_masked: str = "",
    country: str = "",
    case_id=None,
    actor_id=None,
    event_id=None,
    avatar: str = "",
) -> dict:
    labels = {
        "ok": ("✅ Verificado", 0x00FF88),
        "already": ("✅ Ya estaba verificado", 0x34D399),
        "pending": ("⏳ Pendiente de staff", 0xFBBF24),
        "fail": ("❌ Verificación fallida", 0xFB7185),
        "manual": ("🛠️ Verificación manual", 0x38BDF8),
        "denied": ("🚫 Denegada", 0xF97316),
        "vpn": ("🚫 VPN / proxy / Private Relay", 0xF97316),
    }
    title, color = labels.get(status, ("🛡️ Verificación", 0x00FF88))
    desc = (
        f"**Usuario:** <@{user_id}> `{user_id}` · {username or '—'}\n"
        f"**Método:** {METHOD_LABELS.get(method, method)}\n"
        f"**Estado:** `{status}`"
    )
    if actor_id:
        desc += f"\n**Staff:** <@{actor_id}> `{actor_id}`"
    if risk_score is not None:
        desc += f"\n**Riesgo multicuenta:** **{risk_score}/100** {risk_label or ''}".rstrip()
    if ip_masked or country:
        desc += f"\n**Red:** `{ip_masked or '—'}`"
        if country and len(str(country).strip()) <= 8:
            desc += f" · {country.strip()}"
    if case_id:
        desc += f"\n**Caso alt:** #{case_id}"
    desc += f"\n**Panel:** {DASHBOARD_URL}/dashboard?guild={guild_id}"
    payload = {
        "title": title,
        "description": desc[:4000],
        "color": color,
        "footer": {"text": f"Verificación #{event_id or '—'} · dabot.davito.es"},
    }
    url = avatar_cdn(user_id, avatar)
    if url:
        payload["thumbnail"] = {"url": url}
    return payload


def record_full_sync(conn, **kwargs):
    """Insert event + audit_events row. Returns (event_id, channel_id, embed_dict)."""
    eid = record_sync(conn, **kwargs)
    guild_id = int(kwargs["guild_id"])
    user_id = int(kwargs["user_id"])
    username = kwargs.get("username") or ""
    method = kwargs.get("method") or "web"
    status = kwargs.get("status") or "ok"
    summary = f"{username or user_id} · {method} · {status}"
    extra = {
        "event_id": eid,
        "method": method,
        "status": status,
        "risk": kwargs.get("risk_score"),
        "case_id": kwargs.get("case_id"),
    }
    extra_in = kwargs.get("extra")
    if isinstance(extra_in, str):
        try:
            extra_in = json.loads(extra_in)
        except Exception:
            extra_in = {}
    if isinstance(extra_in, dict):
        proxy = extra_in.get("proxy") or {}
        if proxy.get("blocked") or proxy.get("reasons"):
            extra["proxy"] = {
                "blocked": bool(proxy.get("blocked")),
                "kinds": proxy.get("kinds") or [],
                "reasons": proxy.get("reasons") or [],
                "isp": proxy.get("isp") or "",
            }
    try:
        conn.execute(
            """INSERT INTO audit_events
               (guild_id, event_type, actor_id, target_id, channel_id, summary, extra, timestamp)
               VALUES (?, 'verification', ?, ?, NULL, ?, ?, ?)""",
            (
                guild_id,
                int(kwargs["actor_id"]) if kwargs.get("actor_id") else user_id,
                user_id,
                summary[:180],
                json.dumps(extra, ensure_ascii=False),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    except Exception:
        pass
    cc = str(kwargs.get("country") or "").strip()
    if len(cc) > 8:
        cc = cc[:2].upper() if len(cc) >= 2 else ""
    codes = public_ip_codes(kwargs.get("ip"))
    proxy = (extra_in or {}).get("proxy") or {} if isinstance(extra_in, dict) else {}
    net_label = codes.get("label") or ""
    if status == "vpn" or proxy.get("blocked"):
        kinds = ", ".join((proxy.get("kinds") or [])[:3])
        if kinds:
            net_label = (net_label + f" · {kinds}").strip(" ·")
    embed = discord_embed(
        guild_id=guild_id,
        user_id=user_id,
        username=username,
        method=method,
        status=status,
        risk_score=kwargs.get("risk_score"),
        risk_label=kwargs.get("risk_label") or "",
        ip_masked=net_label,
        country=cc,
        case_id=kwargs.get("case_id"),
        actor_id=kwargs.get("actor_id"),
        event_id=eid,
        avatar=kwargs.get("avatar") or "",
    )
    return eid, channel_id_sync(conn, guild_id), embed


def serialize_row(row, *, show_full_ip: bool = False) -> dict:
    def g(key, idx):
        if hasattr(row, "keys"):
            try:
                return row[key]
            except Exception:
                return None
        try:
            return row[idx]
        except Exception:
            return None

    ip = g("ip", 9) or ""
    codes = public_ip_codes(ip)
    uid = g("user_id", 2)
    av = g("avatar", 4) or ""
    extra_raw = g("extra", 15) or ""
    extra = {}
    if extra_raw:
        try:
            extra = json.loads(extra_raw) if isinstance(extra_raw, str) else (extra_raw or {})
        except Exception:
            extra = {}
    if not isinstance(extra, dict):
        extra = {}
    proxy = dict(extra.get("proxy") or {})
    if not show_full_ip:
        proxy.pop("ip", None)
        proxy.pop("query", None)
        proxy.pop("isp", None)
        proxy.pop("org", None)
        proxy.pop("asn", None)
        proxy.pop("city", None)
        proxy["webrtc"] = []
        proxy["reasons"] = [redact_ips(r) for r in (proxy.get("reasons") or [])]
        extra = {**extra, "proxy": proxy}
        extra.pop("ua", None)
        extra.pop("isp", None)
    did = g("device_id", 12) or ""
    event_count = g("event_count", 17)
    if event_count is None:
        event_count = g("n", None)
    actor = g("actor_id", 14)
    return {
        "id": g("id", 0),
        "guild_id": str(g("guild_id", 1) or ""),
        "user_id": str(uid or ""),
        "username": g("username", 3) or "",
        "avatar": av,
        "avatar_url": avatar_cdn(uid, av),
        "method": g("method", 5) or "",
        "status": g("status", 6) or "",
        "risk_score": g("risk_score", 7),
        "risk_label": g("risk_label", 8) or "",
        "ip": ip if show_full_ip else (codes.get("exact") or ""),
        "ip_masked": codes.get("net") or "",
        "ip_code": codes.get("exact") or "",
        "net_code": codes.get("net") or "",
        "country": g("country", 11) or "",
        "device_id": did if show_full_ip else (did[:16] if did else ""),
        "case_id": g("case_id", 13),
        "actor_id": str(actor or "") or None,
        "created_at": g("created_at", 16) or "",
        "event_count": int(event_count or 1),
        "extra": extra,
        "isp": (proxy.get("isp") or extra.get("isp") or "") if show_full_ip else "",
        "vpn": bool(proxy.get("blocked") or (g("status", 6) == "vpn")),
        "vpn_kinds": proxy.get("kinds") or [],
        "vpn_reasons": proxy.get("reasons") or [],
        "city": proxy.get("city") or "" if show_full_ip else "",
        "asn": proxy.get("asn") or "" if show_full_ip else "",
        "org": proxy.get("org") or "" if show_full_ip else "",
        "ua": extra.get("ua") or "" if show_full_ip else "",
        "timezone": extra.get("timezone") or extra.get("tz") or "",
        "platform": extra.get("platform") or "",
        "screen": extra.get("screen") or "" if show_full_ip else "",
    }


def get_event_sync(conn, event_id: int, *, show_full_ip: bool = False) -> dict | None:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM verification_events WHERE id = ?", (int(event_id),))
    row = cur.fetchone()
    if not row:
        return None
    return serialize_row(row, show_full_ip=show_full_ip)


def _q_filter(sql: str, args: list, q: str | None, user_col: str = "user_id", name_col: str = "username"):
    if not q:
        return sql, args
    q = q.strip()
    if not q:
        return sql, args
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(digits) >= 5:
        sql += f" AND ({user_col} = ? OR {name_col} LIKE ?)"
        try:
            args.append(int(digits))
        except Exception:
            args.append(0)
        args.append(f"%{q}%")
    else:
        sql += f" AND {name_col} LIKE ?"
        args.append(f"%{q}%")
    return sql, args


def list_events_sync(
    conn,
    *,
    guild_id=None,
    user_id=None,
    method=None,
    status=None,
    q=None,
    limit=80,
    offset=0,
    show_full_ip: bool = False,
) -> list[dict]:
    ensure_schema_sync(conn)
    sql = "SELECT * FROM verification_events WHERE 1=1"
    args: list = []
    if guild_id:
        sql += " AND guild_id = ?"
        args.append(int(guild_id))
    if user_id:
        sql += " AND user_id = ?"
        args.append(int(user_id))
    if method:
        sql += " AND method = ?"
        args.append(method)
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql, args = _q_filter(sql, args, q)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args.extend([max(1, min(int(limit or 80), 300)), max(0, int(offset or 0))])
    cur = conn.cursor()
    cur.execute(sql, args)
    return [serialize_row(r, show_full_ip=show_full_ip) for r in cur.fetchall()]


def list_people_sync(
    conn,
    *,
    guild_id: int,
    q=None,
    limit=200,
    show_full_ip: bool = False,
) -> list[dict]:
    """Latest successful verification per user in this guild."""
    ensure_schema_sync(conn)
    placeholders = ",".join("?" for _ in VERIFIED_STATUSES)
    sql = f"""
        SELECT ve.*, cnt.n AS event_count
        FROM verification_events ve
        INNER JOIN (
            SELECT user_id, MAX(id) AS mid, COUNT(*) AS n
            FROM verification_events
            WHERE guild_id = ? AND status IN ({placeholders})
            GROUP BY user_id
        ) cnt ON ve.id = cnt.mid
        WHERE 1=1
    """
    args: list = [int(guild_id), *VERIFIED_STATUSES]
    sql, args = _q_filter(sql, args, q, user_col="ve.user_id", name_col="ve.username")
    sql += " ORDER BY ve.id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 200), 500)))
    cur = conn.cursor()
    cur.execute(sql, args)
    return [serialize_row(r, show_full_ip=show_full_ip) for r in cur.fetchall()]


def stats_sync(conn, guild_id=None) -> dict:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    where = ""
    args: tuple = ()
    if guild_id:
        where = "WHERE guild_id = ?"
        args = (int(guild_id),)

    def one(sql, extra=()):
        cur.execute(sql, args + extra)
        row = cur.fetchone()
        if not row:
            return 0
        return int(row[0] or 0)

    conj = "AND" if where else "WHERE"
    today = datetime.utcnow().date().isoformat()
    placeholders = ",".join("?" for _ in VERIFIED_STATUSES)
    return {
        "events": one(f"SELECT COUNT(*) FROM verification_events {where}"),
        "people": one(
            f"SELECT COUNT(DISTINCT user_id) FROM verification_events {where} {conj} status IN ({placeholders})",
            VERIFIED_STATUSES,
        ),
        "today": one(
            f"SELECT COUNT(*) FROM verification_events {where} {conj} created_at >= ?",
            (today,),
        ),
        "pending": one(
            f"SELECT COUNT(*) FROM verification_events {where} {conj} status = 'pending'",
        ),
        "ok": one(
            f"SELECT COUNT(*) FROM verification_events {where} {conj} status IN ({placeholders})",
            VERIFIED_STATUSES,
        ),
    }
