"""Dabot Premium: monthly / yearly / lifetime for guilds and users."""
from __future__ import annotations

from datetime import datetime, timedelta

from utils.helpers import DASHBOARD_URL

LIFETIME_EXPIRES = "9999-12-31T23:59:59"
PLANS = {
    "monthly": {
        "days": 30,
        "labels": {
            "es": "Mensual", "en": "Monthly", "fr": "Mensuel", "de": "Monatlich",
            "pt": "Mensal", "it": "Mensile", "ja": "月額", "ko": "월간", "zh": "包月",
        },
    },
    "yearly": {
        "days": 365,
        "labels": {
            "es": "Anual", "en": "Yearly", "fr": "Annuel", "de": "Jährlich",
            "pt": "Anual", "it": "Annuale", "ja": "年額", "ko": "연간", "zh": "包年",
        },
    },
    "lifetime": {
        "days": None,
        "labels": {
            "es": "Vitalicio", "en": "Lifetime", "fr": "À vie", "de": "Lebenslang",
            "pt": "Vitalício", "it": "A vita", "ja": "買い切り", "ko": "평생", "zh": "终身",
        },
    },
}

PAYMENT_LINKS = {
    "monthly": "https://buy.stripe.com/fZuaEZapy2Cb9Y4c6w48001",
    "yearly": "https://buy.stripe.com/fZu7sNfJSccL8U09Yo48002",
    "lifetime": "https://buy.stripe.com/bJecN7eFO3Gf5HO2vW48003",
}

# Features that stay free on every server.
FREE_FEATURES = [
    "moderación, tickets, verificación web, multicuentas",
    "radar de cuentas hackeadas (MrBeast / Nitro)",
    "niveles (servidor + global), economía, AutoMod, anti-raid",
    "logs, panel web básico, plantillas, bienvenida",
]

# Features that require an active guild (or user) premium plan.
PREMIUM_FEATURES = [
    "IA: mencionar a Dabot, /tldr, /aimod, dibujar, personalidad",
    "Backups completos (mensajes + archivos)",
    "Comandos personalizados",
    "Cartas de rango / bienvenida a medida y nombre del bot",
    "Notas privadas ampliadas",
]


def normalize_plan(plan: str | None) -> str:
    raw = (plan or "monthly").strip().lower()
    aliases = {
        "month": "monthly", "mensual": "monthly", "30d": "monthly", "30": "monthly",
        "year": "yearly", "anual": "yearly", "annual": "yearly", "365d": "yearly", "1y": "yearly",
        "life": "lifetime", "vitalicio": "lifetime", "forever": "lifetime", "perm": "lifetime",
    }
    return aliases.get(raw, raw if raw in PLANS else "monthly")


def expires_iso(plan: str, from_dt: datetime | None = None) -> str:
    plan = normalize_plan(plan)
    now = from_dt or datetime.now()
    days = PLANS[plan]["days"]
    if days is None:
        return LIFETIME_EXPIRES
    return (now + timedelta(days=days)).isoformat()


def is_active(expires_at, plan: str | None = None) -> bool:
    if normalize_plan(plan) == "lifetime":
        return True
    if not expires_at:
        return False
    text = str(expires_at)
    if text.lower() in ("lifetime", "vitalicio") or text.startswith("9999"):
        return True
    try:
        dt = datetime.fromisoformat(text.replace("Z", ""))
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt > datetime.now()
    except Exception:
        return False


def plan_label(plan: str, lang: str = "es") -> str:
    info = PLANS.get(normalize_plan(plan), PLANS["monthly"])
    code = str(lang or "es").split("-")[0].lower()
    labels = info.get("labels") or {}
    return labels.get(code) or labels.get("en") or info.get("label_en") or plan


DENY_TEXT = {
    "es": (
        "**Dabot Premium** hace falta para esto.\n"
        "Planes: mensual · anual · vitalicio. El creador lo activa desde el panel.\n"
        f"Más info: {DASHBOARD_URL}/premium"
    ),
    "en": (
        "**Dabot Premium** is required for this.\n"
        "Plans: monthly · yearly · lifetime. The bot creator activates it from the dashboard.\n"
        f"Details: {DASHBOARD_URL}/premium"
    ),
    "fr": (
        "**Dabot Premium** est requis pour ceci.\n"
        "Offres : mensuel · annuel · à vie. Le créateur l'active depuis le panel.\n"
        f"Détails : {DASHBOARD_URL}/premium"
    ),
    "de": (
        "**Dabot Premium** wird hierfür benötigt.\n"
        "Pläne: monatlich · jährlich · lebenslang. Der Ersteller aktiviert es im Panel.\n"
        f"Details: {DASHBOARD_URL}/premium"
    ),
    "pt": (
        "**Dabot Premium** é necessário para isto.\n"
        "Planos: mensal · anual · vitalício. O criador ativa-o no painel.\n"
        f"Detalhes: {DASHBOARD_URL}/premium"
    ),
    "it": (
        "**Dabot Premium** è necessario per questo.\n"
        "Piani: mensile · annuale · a vita. Il creatore lo attiva dal pannello.\n"
        f"Dettagli: {DASHBOARD_URL}/premium"
    ),
    "ja": (
        "これには **Dabot Premium** が必要です。\n"
        "プラン: 月額 · 年額 · 買い切り。作成者がパネルから有効化します。\n"
        f"詳細: {DASHBOARD_URL}/premium"
    ),
    "ko": (
        "이 기능에는 **Dabot Premium**이 필요합니다.\n"
        "플랜: 월간 · 연간 · 평생. 제작자가 패널에서 활성화합니다.\n"
        f"자세히: {DASHBOARD_URL}/premium"
    ),
    "zh": (
        "此功能需要 **Dabot Premium**。\n"
        "套餐：包月 · 包年 · 终身。由创建者在面板中开通。\n"
        f"详情：{DASHBOARD_URL}/premium"
    ),
}


def deny_text(lang: str = "es") -> str:
    code = str(lang or "es").split("-")[0].lower()
    return DENY_TEXT.get(code) or DENY_TEXT["en"]


def ensure_schema_sync(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS premium_guilds (
            guild_id INTEGER PRIMARY KEY,
            activated_at TEXT,
            expires_at TEXT,
            custom_background TEXT,
            custom_bot_name TEXT,
            custom_bot_avatar TEXT,
            plan TEXT DEFAULT 'monthly'
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            tier TEXT DEFAULT 'premium',
            activated_at TEXT,
            expires_at TEXT,
            plan TEXT DEFAULT 'monthly'
        )"""
    )
    for sql in (
        "ALTER TABLE premium_guilds ADD COLUMN plan TEXT DEFAULT 'monthly'",
        "ALTER TABLE premium_users ADD COLUMN plan TEXT DEFAULT 'monthly'",
        "ALTER TABLE premium_guilds ADD COLUMN custom_background TEXT",
        "ALTER TABLE premium_guilds ADD COLUMN custom_bot_name TEXT",
        "ALTER TABLE premium_guilds ADD COLUMN custom_bot_avatar TEXT",
    ):
        try:
            cur.execute(sql)
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass


def grant_guild_sync(conn, guild_id: int, plan: str, *, duration_days: int | None = None) -> dict:
    ensure_schema_sync(conn)
    plan = normalize_plan(plan)
    now = datetime.now()
    if plan == "lifetime":
        expires = LIFETIME_EXPIRES
    elif duration_days and plan == "monthly" and duration_days not in (30, None):
        expires = (now + timedelta(days=int(duration_days))).isoformat()
    else:
        expires = expires_iso(plan, now)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO premium_guilds (guild_id, activated_at, expires_at, plan)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(guild_id) DO UPDATE SET
             expires_at = excluded.expires_at,
             plan = excluded.plan""",
        (int(guild_id), now.isoformat(), expires, plan),
    )
    conn.commit()
    return {"guild_id": str(guild_id), "plan": plan, "expires_at": expires, "active": True, "label": plan_label(plan)}


def grant_user_sync(conn, user_id: int, plan: str, *, duration_days: int | None = None) -> dict:
    ensure_schema_sync(conn)
    plan = normalize_plan(plan)
    now = datetime.now()
    expires = LIFETIME_EXPIRES if plan == "lifetime" else (
        (now + timedelta(days=int(duration_days))).isoformat()
        if duration_days and plan == "monthly" and duration_days not in (30, None)
        else expires_iso(plan, now)
    )
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO premium_users (user_id, tier, activated_at, expires_at, plan)
           VALUES (?, 'premium', ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             expires_at = excluded.expires_at,
             plan = excluded.plan,
             tier = 'premium'""",
        (int(user_id), now.isoformat(), expires, plan),
    )
    conn.commit()
    return {"user_id": str(user_id), "plan": plan, "expires_at": expires, "active": True, "label": plan_label(plan)}


def revoke_guild_sync(conn, guild_id: int) -> None:
    """Disable premium on a guild. Superuser-owned servers stay opted-out until granted again."""
    ensure_schema_sync(conn)
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO premium_guilds (guild_id, activated_at, expires_at, plan)
           VALUES (?, ?, ?, 'disabled')
           ON CONFLICT(guild_id) DO UPDATE SET plan = 'disabled', expires_at = excluded.expires_at""",
        (int(guild_id), now, now),
    )
    conn.commit()


def revoke_user_sync(conn, user_id: int) -> None:
    conn.execute("DELETE FROM premium_users WHERE user_id = ?", (int(user_id),))
    conn.commit()


def guild_record_sync(conn, guild_id: int) -> dict | None:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT guild_id, activated_at, expires_at, plan FROM premium_guilds WHERE guild_id = ?",
        (int(guild_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        plan = row["plan"] if "plan" in row.keys() else "monthly"
        exp = row["expires_at"]
        act = row["activated_at"]
    else:
        plan = row[3] if len(row) > 3 else "monthly"
        exp, act = row[2], row[1]
    return {
        "guild_id": str(guild_id),
        "plan": normalize_plan(plan),
        "expires_at": exp,
        "activated_at": act,
        "active": is_active(exp, plan),
        "label": plan_label(plan),
    }


def serialize_guild_row(row) -> dict:
    def g(name, idx, default=None):
        try:
            if hasattr(row, "keys"):
                return row[name] if name in row.keys() else default
            return row[idx]
        except Exception:
            return default
    plan = normalize_plan(g("plan", 3, "monthly"))
    exp = g("expires_at", 2)
    return {
        "guild_id": str(g("guild_id", 0)),
        "activated_at": g("activated_at", 1),
        "expires_at": exp,
        "plan": plan,
        "active": is_active(exp, plan),
        "label": plan_label(plan),
    }


def serialize_user_row(row) -> dict:
    def g(name, idx, default=None):
        try:
            if hasattr(row, "keys"):
                return row[name] if name in row.keys() else default
            return row[idx]
        except Exception:
            return default
    plan = normalize_plan(g("plan", 4) or g("tier", 1) or "monthly")
    exp = g("expires_at", 3)
    return {
        "user_id": str(g("user_id", 0)),
        "tier": g("tier", 1) or "premium",
        "activated_at": g("activated_at", 2),
        "expires_at": exp,
        "plan": plan,
        "active": is_active(exp, plan),
        "label": plan_label(plan),
    }
