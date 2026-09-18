"""Multi-account intelligence for Dabot verification.

Discord never sends IP or browser data to bots. Sightings with IP/device come from
the web verification page and dashboard OAuth. Discord-only events (join, captcha)
still record account signals (age, name, flags).

Data is always tagged with the guild where it was captured. Staff of that guild
see local matches. Staff of other guilds only see them if the super owner has
approved both servers into the shared network.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from datetime import datetime, timedelta, timezone

SUPER_OWNER_ID = int(os.environ.get("SUPER_OWNER_ID", "600041740124160011"))
RETENTION_DAYS = 180
MIN_LINK_SCORE = 40

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS alt_share_network (
        guild_id INTEGER PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 1,
        approved_by INTEGER NOT NULL,
        approved_at TEXT NOT NULL,
        note TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS alt_sightings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        guild_id INTEGER,
        username TEXT,
        global_name TEXT,
        account_created TEXT,
        avatar_hash TEXT,
        public_flags INTEGER,
        ip_hash TEXT,
        ip_prefix TEXT,
        ip_full TEXT,
        ip_masked TEXT,
        country TEXT,
        device_id TEXT,
        fingerprint_hash TEXT,
        user_agent TEXT,
        ua_summary TEXT,
        lang TEXT,
        timezone TEXT,
        platform TEXT,
        screen TEXT,
        source TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_alt_s_user ON alt_sightings(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_alt_s_guild ON alt_sightings(guild_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_alt_s_ip ON alt_sightings(ip_hash)",
    "CREATE INDEX IF NOT EXISTS idx_alt_s_dev ON alt_sightings(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_alt_s_fp ON alt_sightings(fingerprint_hash)",
    "CREATE INDEX IF NOT EXISTS idx_alt_s_prefix ON alt_sightings(ip_prefix)",
    """CREATE TABLE IF NOT EXISTS alt_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_a INTEGER NOT NULL,
        user_b INTEGER NOT NULL,
        reason TEXT NOT NULL,
        score INTEGER NOT NULL,
        guild_id INTEGER,
        evidence TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(user_a, user_b, reason)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_alt_links_a ON alt_links(user_a)",
    "CREATE INDEX IF NOT EXISTS idx_alt_links_b ON alt_links(user_b)",
    """CREATE TABLE IF NOT EXISTS alt_device_users (
        device_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        PRIMARY KEY (device_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS alt_policy (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        policy TEXT NOT NULL,
        set_by INTEGER,
        set_at TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS alt_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        score INTEGER NOT NULL DEFAULT 0,
        risk TEXT NOT NULL DEFAULT 'low',
        status TEXT NOT NULL DEFAULT 'pending',
        matches TEXT,
        evidence TEXT,
        channel_id INTEGER,
        message_id INTEGER,
        resolved_by INTEGER,
        resolved_at TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_alt_cases_guild ON alt_cases(guild_id, status, id DESC)",
    """CREATE TABLE IF NOT EXISTS alt_captcha (
        token TEXT PRIMARY KEY,
        answer INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0
    )""",
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _salt() -> str:
    return os.environ.get("ALT_IP_SALT") or (os.environ.get("DISCORD_TOKEN") or "dabot")[:24]


def hash_ip(ip: str | None) -> str:
    if not ip:
        return ""
    return hashlib.sha256(f"{_salt()}|{ip}".encode()).hexdigest()


_IP_RE = re.compile(
    r"\b(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7})\b"
)


def redact_ips(text: str) -> str:
    return _IP_RE.sub("…", text or "")


def public_ip_codes(ip: str | None) -> dict:
    """Staff-visible tokens. Same address → same ip: code. Same /24 or /48 → same net: code."""
    meta = ip_meta(ip)
    if not meta.get("ip_full"):
        return {"exact": "", "net": "", "label": ""}
    exact = hash_ip(meta["ip_full"])[:10]
    net = hash_ip("net|" + (meta.get("ip_prefix") or ""))[:10]
    return {
        "exact": f"ip:{exact}",
        "net": f"net:{net}",
        "label": f"ip:{exact} · net:{net}",
    }


def ip_meta(ip: str | None) -> dict:
    empty = {"ip_full": "", "ip_hash": "", "ip_prefix": "", "ip_masked": ""}
    if not ip:
        return empty
    try:
        addr = ipaddress.ip_address(ip.strip())
    except Exception:
        return empty
    if isinstance(addr, ipaddress.IPv4Address):
        parts = str(addr).split(".")
        prefix = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        masked = f"{parts[0]}.{parts[1]}.{parts[2]}.x"
    else:
        expl = addr.exploded
        prefix = f"{expl[:19]}::/48"
        masked = f"{expl[:19]}:x"
    return {
        "ip_full": str(addr),
        "ip_hash": hash_ip(str(addr)),
        "ip_prefix": prefix,
        "ip_masked": masked,
    }


def client_ip(headers, fallback: str = "") -> str:
    """Visitor IP. Do not trust X-Forwarded-For on a public origin (spoofable)."""
    try:
        from utils.proxy_detect import connecting_ip
        return connecting_ip(headers, fallback or "")
    except Exception:
        pass
    for key in ("cf-connecting-ip", "CF-Connecting-IP"):
        val = None
        if hasattr(headers, "get"):
            val = headers.get(key)
        if val:
            return str(val).split(",")[0].strip()
    return fallback or ""


def ua_summary(ua: str | None) -> str:
    ua = ua or ""
    browser = "Otro"
    for name, pat in (
        ("Edge", "Edg/"),
        ("Opera", "OPR/"),
        ("Chrome", "Chrome/"),
        ("Firefox", "Firefox/"),
        ("Safari", "Safari/"),
    ):
        if pat in ua:
            browser = name
            break
    osname = "Otro"
    for name, pat in (
        ("Android", "Android"),
        ("iOS", "iPhone"),
        ("iPadOS", "iPad"),
        ("Windows", "Windows"),
        ("macOS", "Mac OS"),
        ("Linux", "Linux"),
    ):
        if pat in ua:
            osname = name
            break
    return f"{browser} · {osname}"


def fingerprint_hash(parts: dict) -> str:
    keys = (
        "canvas", "webgl", "timezone", "lang", "platform",
        "screen", "hardware", "memory", "touch",
    )
    blob = "|".join(str(parts.get(k) or "") for k in keys)
    if blob.strip("|") == "":
        return ""
    return hashlib.sha256(blob.encode()).hexdigest()


def ensure_schema_sync(conn) -> None:
    cur = conn.cursor()
    for stmt in SCHEMA:
        cur.execute(stmt)
    try:
        cur.execute("ALTER TABLE verification_config ADD COLUMN alts_channel_id INTEGER")
    except Exception:
        pass
    conn.commit()


async def ensure_schema_async(db) -> None:
    for stmt in SCHEMA:
        await db.execute(stmt)
    try:
        await db.execute("ALTER TABLE verification_config ADD COLUMN alts_channel_id INTEGER")
    except Exception:
        pass


def network_guilds(conn) -> set[int]:
    cur = conn.cursor()
    cur.execute("SELECT guild_id FROM alt_share_network WHERE enabled = 1")
    return {int(r[0]) for r in cur.fetchall()}


def set_network(conn, guild_id: int, enabled: bool, approved_by: int, note: str = "") -> None:
    cur = conn.cursor()
    if enabled:
        cur.execute(
            """INSERT INTO alt_share_network (guild_id, enabled, approved_by, approved_at, note)
               VALUES (?, 1, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 enabled = 1,
                 approved_by = excluded.approved_by,
                 approved_at = excluded.approved_at,
                 note = excluded.note""",
            (int(guild_id), int(approved_by), _now(), note or ""),
        )
    else:
        cur.execute(
            "UPDATE alt_share_network SET enabled = 0 WHERE guild_id = ?",
            (int(guild_id),),
        )
    conn.commit()


def visible_guild_ids(conn, current_guild: int | None, viewer_id: int) -> list[int] | None:
    """None = no filter (super owner). Otherwise the guilds this staff may query."""
    if int(viewer_id) == SUPER_OWNER_ID:
        return None
    if not current_guild:
        return []
    allowed = {int(current_guild)}
    net = network_guilds(conn)
    if int(current_guild) in net:
        allowed |= net
    return list(allowed)


def _in_clause(ids: list[int]) -> tuple[str, list]:
    placeholders = ",".join("?" * len(ids))
    return placeholders, ids


def record_sighting(conn, *, user_id: int, guild_id: int | None, username: str = "",
                    global_name: str = "", account_created: str = "", avatar_hash: str = "",
                    public_flags: int = 0, ip: str = "", country: str = "", device_id: str = "",
                    fingerprint: dict | None = None, user_agent: str = "", source: str = "web") -> dict:
    ensure_schema_sync(conn)
    meta = ip_meta(ip)
    fp = fingerprint or {}
    fp_hash = fingerprint_hash(fp)
    ua = (user_agent or "")[:400]
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO alt_sightings (
            user_id, guild_id, username, global_name, account_created, avatar_hash, public_flags,
            ip_hash, ip_prefix, ip_full, ip_masked, country, device_id, fingerprint_hash,
            user_agent, ua_summary, lang, timezone, platform, screen, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(user_id), int(guild_id) if guild_id else None,
            username or "", global_name or "", account_created or "", avatar_hash or "",
            int(public_flags or 0),
            meta["ip_hash"], meta["ip_prefix"], meta["ip_full"], meta["ip_masked"],
            (country or "")[:8], device_id or "", fp_hash,
            ua, ua_summary(ua),
            str(fp.get("lang") or "")[:32],
            str(fp.get("timezone") or "")[:64],
            str(fp.get("platform") or "")[:80],
            str(fp.get("screen") or "")[:40],
            source, _now(),
        ),
    )
    conn.commit()
    if device_id:
        _touch_device_user(conn, device_id, int(user_id))
    matches = []
    if guild_id:
        matches = _relink(
            conn,
            user_id=int(user_id),
            guild_id=int(guild_id),
            ip_hash=meta["ip_hash"],
            ip_prefix=meta["ip_prefix"],
            device_id=device_id or "",
            fingerprint_hash=fp_hash,
            username=username or "",
            global_name=global_name or "",
        )
        seen = {int(m["user_id"]) for m in matches}
        for other in accounts_on_device(conn, device_id or ""):
            if other == int(user_id) or other in seen:
                continue
            matches.append({"user_id": other, "score": 95, "reasons": ["mismo_dispositivo"]})
            a, b = (int(user_id), other) if int(user_id) < other else (other, int(user_id))
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO alt_links (user_a, user_b, reason, score, guild_id, evidence, created_at)
                   VALUES (?, ?, 'mismo_dispositivo', 95, ?, ?, ?)
                   ON CONFLICT(user_a, user_b, reason) DO UPDATE SET score = MAX(alt_links.score, 95)""",
                (a, b, int(guild_id), json.dumps({"kind": "cookie"}), _now()),
            )
            conn.commit()
            seen.add(other)
    return {"matches": matches, "ip_masked": meta["ip_masked"], "country": country, "device_id": device_id or ""}


def _relink(conn, *, user_id, guild_id, ip_hash, ip_prefix, device_id, fingerprint_hash, username, global_name):
    since = (datetime.now() - timedelta(days=RETENTION_DAYS)).isoformat()
    search_guilds: list[int] | None
    if guild_id:
        search_guilds = [int(guild_id)]
        net = network_guilds(conn)
        if int(guild_id) in net:
            search_guilds = list(net)
    else:
        search_guilds = None

    clauses = ["user_id != ?", "created_at >= ?"]
    args: list = [user_id, since]
    or_bits = []
    if device_id:
        or_bits.append("(device_id != '' AND device_id = ?)")
        args.append(device_id)
    if ip_hash:
        or_bits.append("(ip_hash != '' AND ip_hash = ?)")
        args.append(ip_hash)
    if fingerprint_hash:
        or_bits.append("(fingerprint_hash != '' AND fingerprint_hash = ?)")
        args.append(fingerprint_hash)
    if ip_prefix:
        or_bits.append("(ip_prefix != '' AND ip_prefix = ?)")
        args.append(ip_prefix)
    if not or_bits:
        return []
    clauses.append("(" + " OR ".join(or_bits) + ")")
    if search_guilds:
        ph, ids = _in_clause(search_guilds)
        clauses.append(f"(guild_id IN ({ph}) OR guild_id IS NULL)")
        args.extend(ids)

    cur = conn.cursor()
    cur.execute(
        f"SELECT DISTINCT user_id FROM alt_sightings WHERE {' AND '.join(clauses)} LIMIT 80",
        args,
    )
    others = [int(r[0]) for r in cur.fetchall()]
    links = []
    for other in others:
        reasons = _compare_users(conn, user_id, other, guild_id, search_guilds)
        if not reasons:
            continue
        best = max(reasons, key=lambda r: r["score"])
        a, b = (user_id, other) if user_id < other else (other, user_id)
        for reason in reasons:
            if reason["score"] < MIN_LINK_SCORE:
                continue
            cur.execute(
                """INSERT INTO alt_links (user_a, user_b, reason, score, guild_id, evidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_a, user_b, reason) DO UPDATE SET
                     score = MAX(alt_links.score, excluded.score),
                     evidence = excluded.evidence,
                     created_at = excluded.created_at""",
                (a, b, reason["reason"], reason["score"], guild_id,
                 json.dumps(reason.get("evidence") or {}, ensure_ascii=False), _now()),
            )
        links.append({
            "user_id": other,
            "score": best["score"],
            "reasons": [r["reason"] for r in reasons],
        })
    conn.commit()
    links.sort(key=lambda x: x["score"], reverse=True)
    return links


def _touch_device_user(conn, device_id: str, user_id: int) -> None:
    if not device_id:
        return
    now = _now()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO alt_device_users (device_id, user_id, first_seen, last_seen)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(device_id, user_id) DO UPDATE SET last_seen = excluded.last_seen""",
        (device_id, int(user_id), now, now),
    )
    conn.commit()


def matches_in_guild(matches: list, present_ids) -> list:
    """Keep only linked accounts that are currently members of this Discord server."""
    present = {int(x) for x in (present_ids or []) if x}
    out = []
    for m in matches or []:
        try:
            uid = int(m.get("user_id"))
        except (TypeError, ValueError):
            continue
        if uid in present:
            out.append(m)
    return out


def accounts_on_device(conn, device_id: str) -> list[int]:
    if not device_id:
        return []
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM alt_device_users WHERE device_id = ?", (device_id,))
    return [int(r[0]) for r in cur.fetchall()]


def get_policy(conn, guild_id: int, user_id: int) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT policy FROM alt_policy WHERE guild_id = ? AND user_id = ?",
        (int(guild_id), int(user_id)),
    )
    row = cur.fetchone()
    if not row:
        return "none"
    return row[0] if not hasattr(row, "keys") else row["policy"]


def set_policy(conn, guild_id: int, user_id: int, policy: str, set_by: int | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO alt_policy (guild_id, user_id, policy, set_by, set_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET
             policy = excluded.policy, set_by = excluded.set_by, set_at = excluded.set_at""",
        (int(guild_id), int(user_id), policy, set_by, _now()),
    )
    conn.commit()


def account_age_days(account_created: str, user_id: int | None = None) -> int | None:
    try:
        if account_created:
            dt = datetime.fromisoformat(str(account_created).replace("Z", ""))
            return max(0, (datetime.utcnow() - dt).days)
    except Exception:
        pass
    if user_id:
        try:
            ts = ((int(user_id) >> 22) + 1420070400000) / 1000
            return max(0, int((datetime.utcnow().timestamp() - ts) / 86400))
        except Exception:
            return None
    return None


def compute_risk(matches: list, *, account_created: str = "", user_id: int | None = None,
                 device_account_count: int = 0) -> dict:
    score = 0
    if matches:
        score = max(int(m.get("score") or 0) for m in matches)
        n = len(matches)
        if n >= 2:
            score = min(100, score + 8)
        if n >= 4:
            score = min(100, score + 10)
    if device_account_count >= 3:
        score = min(100, score + 10)
    age = account_age_days(account_created, user_id)
    if age is not None:
        if age < 1:
            score = min(100, score + 25)
        elif age < 7:
            score = min(100, score + 15)
        elif age < 30:
            score = min(100, score + 5)
    if score >= 85:
        label = "critical"
    elif score >= 70:
        label = "high"
    elif score >= 40:
        label = "medium"
    else:
        label = "low"
    return {"score": score, "label": label, "age_days": age}


def create_case(conn, *, guild_id: int, user_id: int, username: str, risk: dict,
                matches: list, evidence: dict) -> int:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO alt_cases (guild_id, user_id, username, score, risk, status, matches, evidence, created_at)
           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (
            int(guild_id), int(user_id), username or "",
            int(risk.get("score") or 0), risk.get("label") or "low",
            json.dumps(matches or [], ensure_ascii=False),
            json.dumps(evidence or {}, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_case(conn, case_id: int):
    cur = conn.cursor()
    cur.execute("SELECT * FROM alt_cases WHERE id = ?", (int(case_id),))
    return cur.fetchone()


def resolve_case(conn, case_id: int, status: str, resolved_by: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE alt_cases SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
        (status, int(resolved_by), _now(), int(case_id)),
    )
    conn.commit()


def attach_case_message(conn, case_id: int, channel_id: int, message_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE alt_cases SET channel_id = ?, message_id = ? WHERE id = ?",
        (int(channel_id), int(message_id), int(case_id)),
    )
    conn.commit()


def yaml_alts_channel(guild_id: int) -> int | None:
    """Dedicated multicuenta channel: logs.alts only (not generic mod logs)."""
    import yaml
    for base in ("configs", "/app/configs", "/opt/dabot/configs"):
        path = os.path.join(base, f"{guild_id}.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            raw = (data.get("logs") or {}).get("alts")
            if raw:
                return int(raw)
        except Exception:
            continue
    return None


def alts_channel_id(conn, guild_id: int) -> int | None:
    """verification_config, then guild_configs.logs.alts, then yaml."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT alts_channel_id FROM verification_config WHERE guild_id = ?",
            (int(guild_id),),
        )
        row = cur.fetchone()
        if row:
            val = row[0] if not hasattr(row, "keys") else row["alts_channel_id"]
            if val:
                return int(val)
    except Exception:
        pass
    try:
        cur.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (int(guild_id),))
        row = cur.fetchone()
        if row:
            raw = row[0] if not hasattr(row, "keys") else row["config_json"]
            data = json.loads(raw or "{}")
            val = (data.get("logs") or {}).get("alts")
            if val:
                return int(val)
    except Exception:
        pass
    return yaml_alts_channel(guild_id)


def set_alts_channel(conn, guild_id: int, channel_id: int) -> None:
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE verification_config ADD COLUMN alts_channel_id INTEGER")
        conn.commit()
    except Exception:
        pass
    cur.execute(
        """UPDATE verification_config SET alts_channel_id = ? WHERE guild_id = ?""",
        (int(channel_id), int(guild_id)),
    )
    if cur.rowcount == 0:
        cur.execute(
            """INSERT INTO verification_config
               (guild_id, enabled, verification_channel_id, unverified_role_id, verified_role_id, verification_type, alts_channel_id)
               VALUES (?, 1, 0, 0, 0, 'web', ?)""",
            (int(guild_id), int(channel_id)),
        )
    conn.commit()


def _compare_users(conn, user_a: int, user_b: int, origin_guild: int | None, search_guilds: list[int] | None):
    cur = conn.cursor()
    extra = ""
    args_a: list = [user_a]
    args_b: list = [user_b]
    if search_guilds:
        ph, ids = _in_clause(search_guilds)
        extra = f" AND (guild_id IN ({ph}) OR guild_id IS NULL)"
        args_a.extend(ids)
        args_b.extend(ids)
    cur.execute(
        f"""SELECT ip_hash, ip_prefix, device_id, fingerprint_hash, username, global_name, guild_id
            FROM alt_sightings WHERE user_id = ?{extra} ORDER BY id DESC LIMIT 40""",
        args_a,
    )
    rows_a = cur.fetchall()
    cur.execute(
        f"""SELECT ip_hash, ip_prefix, device_id, fingerprint_hash, username, global_name, guild_id
            FROM alt_sightings WHERE user_id = ?{extra} ORDER BY id DESC LIMIT 40""",
        args_b,
    )
    rows_b = cur.fetchall()

    def col(row, name):
        if hasattr(row, "keys"):
            return row[name]
        mapping = ["ip_hash", "ip_prefix", "device_id", "fingerprint_hash", "username", "global_name", "guild_id"]
        return row[mapping.index(name)]

    set_a = {k: {col(r, k) for r in rows_a if col(r, k)} for k in ("ip_hash", "ip_prefix", "device_id", "fingerprint_hash", "username", "global_name")}
    set_b = {k: {col(r, k) for r in rows_b if col(r, k)} for k in ("ip_hash", "ip_prefix", "device_id", "fingerprint_hash", "username", "global_name")}

    reasons = []
    if set_a["device_id"] & set_b["device_id"]:
        reasons.append({"reason": "mismo_dispositivo", "score": 95, "evidence": {"kind": "cookie"}})
    if set_a["ip_hash"] & set_b["ip_hash"]:
        reasons.append({"reason": "misma_ip", "score": 90, "evidence": {"kind": "ip"}})
    if set_a["fingerprint_hash"] & set_b["fingerprint_hash"]:
        reasons.append({"reason": "mismo_navegador", "score": 80, "evidence": {"kind": "fingerprint"}})
    if set_a["ip_prefix"] & set_b["ip_prefix"]:
        reasons.append({"reason": "misma_red", "score": 45, "evidence": {"kind": "subnet"}})

    def norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    names_a = {norm(n) for n in set_a["username"] | set_a["global_name"] if norm(n)}
    names_b = {norm(n) for n in set_b["username"] | set_b["global_name"] if norm(n)}
    if names_a & names_b:
        reasons.append({"reason": "mismo_nombre", "score": 30, "evidence": {"kind": "name"}})
    return reasons


def _row_to_sighting(row, show_full_ip: bool) -> dict:
    def g(name, default=""):
        try:
            if hasattr(row, "keys"):
                v = row[name]
            else:
                return default
        except Exception:
            return default
        return v if v is not None else default

    return {
        "id": g("id"),
        "user_id": str(g("user_id")),
        "guild_id": str(g("guild_id")) if g("guild_id") else None,
        "username": g("username"),
        "global_name": g("global_name"),
        "account_created": g("account_created"),
        "ip": g("ip_full") if show_full_ip else public_ip_codes(g("ip_full")).get("exact"),
        "ip_masked": public_ip_codes(g("ip_full")).get("net") if not show_full_ip else g("ip_masked"),
        "ip_code": public_ip_codes(g("ip_full")).get("exact"),
        "net_code": public_ip_codes(g("ip_full")).get("net"),
        "ip_prefix": g("ip_prefix") if show_full_ip else public_ip_codes(g("ip_full")).get("net"),
        "country": g("country"),
        "device_id": (g("device_id") or "")[:12],
        "fingerprint": (g("fingerprint_hash") or "")[:12],
        "ua_summary": g("ua_summary"),
        "lang": g("lang"),
        "timezone": g("timezone"),
        "platform": g("platform"),
        "screen": g("screen"),
        "source": g("source"),
        "created_at": g("created_at"),
    }


def user_dossier(conn, target_id: int, *, current_guild: int | None, viewer_id: int) -> dict:
    ensure_schema_sync(conn)
    show_full = int(viewer_id) == SUPER_OWNER_ID
    allowed = visible_guild_ids(conn, current_guild, viewer_id)
    cur = conn.cursor()
    extra = ""
    args: list = [int(target_id)]
    if allowed is not None:
        if not allowed:
            return {"user_id": str(target_id), "sightings": [], "alts": [], "score": 0, "network": False}
        ph, ids = _in_clause(allowed)
        extra = f" AND guild_id IN ({ph})"
        args.extend(ids)
    cur.execute(
        f"SELECT * FROM alt_sightings WHERE user_id = ?{extra} ORDER BY id DESC LIMIT 40",
        args,
    )
    sightings = [_row_to_sighting(r, show_full) for r in cur.fetchall()]

    cur.execute(
        "SELECT user_a, user_b, reason, score, guild_id, evidence, created_at FROM alt_links WHERE user_a = ? OR user_b = ? ORDER BY score DESC",
        (int(target_id), int(target_id)),
    )
    alts = {}
    for row in cur.fetchall():
        a, b, reason, score, gid, evidence, created = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        other = int(b if int(a) == int(target_id) else a)
        if allowed is not None and gid and int(gid) not in allowed:
            # still allow if both users have local sightings
            cur.execute(
                f"SELECT 1 FROM alt_sightings WHERE user_id = ?{extra} LIMIT 1",
                [other, *args[1:]],
            )
            if not cur.fetchone():
                continue
        bucket = alts.setdefault(other, {"user_id": str(other), "score": 0, "reasons": [], "last_seen": created})
        bucket["score"] = max(bucket["score"], int(score or 0))
        if reason not in bucket["reasons"]:
            bucket["reasons"].append(reason)
    alt_list = sorted(alts.values(), key=lambda x: x["score"], reverse=True)
    net = bool(current_guild and int(current_guild) in network_guilds(conn))
    top = alt_list[0]["score"] if alt_list else 0
    return {
        "user_id": str(target_id),
        "sightings": sightings,
        "alts": alt_list[:25],
        "score": top,
        "network": net,
        "is_super_owner_view": show_full,
    }


def recent_alerts(conn, *, current_guild: int, viewer_id: int, limit: int = 40) -> list[dict]:
    ensure_schema_sync(conn)
    allowed = visible_guild_ids(conn, current_guild, viewer_id)
    cur = conn.cursor()
    extra = ""
    args: list = []
    if allowed is not None:
        if not allowed:
            return []
        ph, ids = _in_clause(allowed)
        extra = f" WHERE (guild_id IN ({ph}) OR guild_id IS NULL)"
        args.extend(ids)
    cur.execute(
        f"SELECT user_a, user_b, reason, score, guild_id, created_at FROM alt_links{extra} ORDER BY id DESC LIMIT ?",
        [*args, int(limit)],
    )
    out = []
    for a, b, reason, score, gid, created in cur.fetchall():
        if int(score or 0) < MIN_LINK_SCORE:
            continue
        out.append({
            "user_a": str(a),
            "user_b": str(b),
            "reason": reason,
            "score": score,
            "guild_id": str(gid) if gid else None,
            "created_at": created,
        })
    return out


def summarize_for_embed(dossier: dict) -> str:
    alts = dossier.get("alts") or []
    if not alts:
        return "Sin coincidencias de multicuenta en el alcance de este servidor."
    lines = []
    for alt in alts[:8]:
        reasons = ", ".join(alt.get("reasons") or [])
        lines.append(f"• <@{alt['user_id']}> (`{alt['user_id']}`) — {alt['score']}% · {reasons}")
    return "\n".join(lines)


def _row_get(row, name, idx=None, default=None):
    if row is None:
        return default
    if hasattr(row, "keys"):
        try:
            v = row[name]
            return default if v is None else v
        except Exception:
            return default
    if idx is not None:
        try:
            v = row[idx]
            return default if v is None else v
        except Exception:
            return default
    return default


def serialize_case(row, show_full_ip: bool = False) -> dict:
    matches = []
    evidence = {}
    raw_matches = _row_get(row, "matches", default="[]")
    raw_evidence = _row_get(row, "evidence", default="{}")
    try:
        matches = json.loads(raw_matches or "[]")
    except Exception:
        matches = []
    try:
        evidence = json.loads(raw_evidence or "{}")
    except Exception:
        evidence = {}
    if isinstance(evidence, dict):
        full = evidence.get("ip_full") or evidence.get("ip") or ""
        codes = public_ip_codes(full) if full and not str(full).startswith("ip:") else {
            "exact": evidence.get("ip_code") or "",
            "net": evidence.get("net_code") or "",
        }
        if not show_full_ip:
            evidence = {
                **evidence,
                "ip_full": None,
                "ip": codes.get("exact") or evidence.get("ip_code") or "",
                "ip_masked": codes.get("net") or evidence.get("net_code") or "",
                "ip_code": codes.get("exact") or evidence.get("ip_code") or "",
                "net_code": codes.get("net") or evidence.get("net_code") or "",
            }
    gid = _row_get(row, "guild_id")
    uid = _row_get(row, "user_id")
    ch = _row_get(row, "channel_id")
    mid = _row_get(row, "message_id")
    resolved_by = _row_get(row, "resolved_by")
    return {
        "id": int(_row_get(row, "id") or 0),
        "guild_id": str(gid) if gid else None,
        "user_id": str(uid) if uid else None,
        "username": _row_get(row, "username") or "",
        "score": int(_row_get(row, "score") or 0),
        "risk": _row_get(row, "risk") or "low",
        "status": _row_get(row, "status") or "pending",
        "matches": matches if isinstance(matches, list) else [],
        "evidence": evidence if isinstance(evidence, dict) else {},
        "channel_id": str(ch) if ch else None,
        "message_id": str(mid) if mid else None,
        "resolved_by": str(resolved_by) if resolved_by else None,
        "resolved_at": _row_get(row, "resolved_at"),
        "created_at": _row_get(row, "created_at"),
    }


def list_cases(conn, *, guild_id: int | None = None, status: str | None = None,
               user_id: int | None = None, limit: int = 80, offset: int = 0,
               show_full_ip: bool = False) -> list[dict]:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    where: list[str] = []
    args: list = []
    if guild_id:
        where.append("guild_id = ?")
        args.append(int(guild_id))
    if status:
        where.append("status = ?")
        args.append(status)
    if user_id:
        where.append("user_id = ?")
        args.append(int(user_id))
    extra = (" WHERE " + " AND ".join(where)) if where else ""
    cur.execute(
        f"SELECT * FROM alt_cases{extra} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, max(1, min(int(limit), 200)), max(0, int(offset))],
    )
    cases = [serialize_case(r, show_full_ip) for r in cur.fetchall()]
    if not cases:
        return cases
    ids = list({int(c["user_id"]) for c in cases if c.get("user_id")})
    if not ids:
        return cases
    ph, in_args = _in_clause(ids)
    cur.execute(
        f"""SELECT user_id, ip_full, ip_masked, device_id, ua_summary, created_at
            FROM alt_sightings
            WHERE id IN (
                SELECT MAX(id) FROM alt_sightings WHERE user_id IN ({ph}) GROUP BY user_id
            )""",
        in_args,
    )
    latest: dict[str, dict] = {}
    for row in cur.fetchall():
        uid = str(_row_get(row, "user_id", 0))
        ip_full = _row_get(row, "ip_full", 1) or ""
        ip_masked = _row_get(row, "ip_masked", 2) or ""
        codes = public_ip_codes(ip_full)
        latest[uid] = {
            "ip": ip_full if show_full_ip else codes.get("exact"),
            "ip_masked": codes.get("net") if not show_full_ip else ip_masked,
            "ip_code": codes.get("exact"),
            "net_code": codes.get("net"),
            "device_id": (_row_get(row, "device_id", 3) or "")[:12],
            "ua_summary": _row_get(row, "ua_summary", 4) or "",
            "created_at": _row_get(row, "created_at", 5),
        }
    for c in cases:
        c["last_sighting"] = latest.get(c["user_id"])
    return cases


def overview_stats(conn) -> dict:
    ensure_schema_sync(conn)
    cur = conn.cursor()

    def _count(sql: str, args: tuple = ()) -> int:
        cur.execute(sql, args)
        row = cur.fetchone()
        return int((row[0] if row else 0) or 0)

    by_status = {}
    cur.execute("SELECT status, COUNT(*) FROM alt_cases GROUP BY status")
    for row in cur.fetchall():
        by_status[str(row[0])] = int(row[1] or 0)
    return {
        "cases_total": _count("SELECT COUNT(*) FROM alt_cases"),
        "cases_pending": by_status.get("pending", 0),
        "cases_approved": by_status.get("approved", 0),
        "cases_denied": by_status.get("denied", 0),
        "cases_banned": by_status.get("banned", 0),
        "cases_allow_always": by_status.get("allow_always", 0),
        "sightings": _count("SELECT COUNT(*) FROM alt_sightings"),
        "unique_users": _count("SELECT COUNT(DISTINCT user_id) FROM alt_sightings"),
        "network_guilds": _count("SELECT COUNT(*) FROM alt_share_network WHERE enabled = 1"),
        "policies": _count("SELECT COUNT(*) FROM alt_policy"),
        "by_status": by_status,
    }
