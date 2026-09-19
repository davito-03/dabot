import os
from typing import Optional, List, Dict, Any
import re
import sqlite3
import datetime
import json
import logging
import secrets
import asyncio
import time
import random
import base64
import hashlib
import hmac
import urllib.parse
import html
import aiohttp
from fastapi import FastAPI, HTTPException, Request, Depends, Response, Cookie, BackgroundTasks, Body
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from utils.helpers import BOT_INVITE_PERMISSIONS, invite_url, DASHBOARD_URL
from utils import alt_intel
from utils import premium as premium_lib
from utils import health as health_lib
from utils import verify_log
from utils import proxy_detect
from utils.announcements import default_channel_name
from utils import live_cache as live_cache_lib
from utils.lastfm import LastFMClient, get_spotify_search_url

load_dotenv()
from utils.envcheck import require_runtime_env
require_runtime_env("api")

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dabot.Dashboard")

from webapp.routers.health import router as health_router
from webapp.routers.status import router as status_router

app = FastAPI(
    title="Dabot — Panel web",
    description="Dashboard y API de Dabot (davito.es).",
    version="3.1.0"
)
app.include_router(health_router)
app.include_router(status_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dabot.davito.es",
        "https://davito.es",
        "https://www.davito.es",
        "http://localhost:8090",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Strict Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https://davito.es https://cdn.discordapp.com https://*.discord.com https://media.discordapp.net https://*.fastly.net https://*.last.fm https://lastfm-img.freetls.fastly.net; "
        "connect-src 'self' https://discord.com https://davito.es; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self' https://discord.com;"
    )
    response.headers["Content-Security-Policy"] = csp
    if request.url.path.startswith("/static") or request.url.path.startswith("/verify") or request.url.path in (
        "/", "/dashboard", "/help", "/privacy", "/terms", "/cookies", "/premium",
        "/comunidad", "/niveles", "/normas", "/cuenta", "/servers"
    ) or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["CDN-Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    protected = (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
    )
    if protected:
        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("x-csrf-token")
        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
    response = await call_next(request)
    csrf = request.cookies.get("csrf_token")
    if not csrf:
        response.set_cookie(
            "csrf_token", secrets.token_urlsafe(32), httponly=False,
            secure=True, samesite="lax", max_age=7 * 24 * 60 * 60, path="/"
        )
    else:
        _slide_cookie(response, "csrf_token", csrf, httponly=False, max_age=7 * 24 * 60 * 60)
    did = request.cookies.get("dabot_did")
    if did:
        _slide_cookie(response, "dabot_did", did, httponly=True, max_age=DEVICE_COOKIE_MAX_AGE)
    return response

DB_PATH = os.environ.get("DATABASE_PATH", "dabot.db")
SUPER_OWNER_ID = int(os.environ["SUPER_OWNER_ID"])


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "si", "sí")
    return bool(value)


def _require_super(user):
    if not user or user.get("user_id") != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado: solo el superusuario.")

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "https://dabot.davito.es/login/callback")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
# Cloudflare on discord.com blocks requests without a bot-style User-Agent (error 40333).
DISCORD_USER_AGENT = "DiscordBot (https://dabot.davito.es, 3.1.0)"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    try:
        yield conn
    finally:
        conn.close()

# --- INITIALIZE DATABASE FOR SESSIONS & CONFIGS ---
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA cache_size=-32000")
    cursor = conn.cursor()
    # Create web sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS web_sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            avatar TEXT,
            access_token TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS web_oauth_states (
            state TEXT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            next_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            provider TEXT NOT NULL,
            event_id TEXT NOT NULL,
            received_at TEXT NOT NULL,
            PRIMARY KEY (provider, event_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            user_id INTEGER,
            guild_id INTEGER,
            plan TEXT NOT NULL DEFAULT 'monthly',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcement_config (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            updated_by INTEGER,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcement_messages (
            source_message_id TEXT PRIMARY KEY,
            source_guild_id INTEGER,
            source_channel_id INTEGER,
            content TEXT,
            embeds TEXT,
            attachments TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcement_deliveries (
            source_message_id TEXT NOT NULL,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            status TEXT NOT NULL,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source_message_id, guild_id)
        )
    """)
    # Ensure premium tables exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            tier TEXT NOT NULL DEFAULT 'premium',
            activated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_guilds (
            guild_id INTEGER PRIMARY KEY,
            activated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    premium_lib.ensure_schema_sync(conn)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_lastfm (
            user_id INTEGER PRIMARY KEY,
            lastfm_username TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
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
    """)
    cursor.execute("""
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
    """)
    # Create infraction_appeals table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS infraction_appeals (
            infraction_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            appeal_reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            mod_response TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(infraction_id) REFERENCES infractions(id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE infractions ADD COLUMN staff_note TEXT")
    except Exception:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_guilds (
            guild_id INTEGER PRIMARY KEY,
            note TEXT,
            added_by INTEGER,
            added_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER,
            summary TEXT,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
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
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS owner_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            actor_id INTEGER,
            target_id INTEGER,
            guild_id INTEGER,
            detail TEXT,
            created_at TEXT NOT NULL
        )
    """)
    # Create staff_permissions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_permissions (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            permissions TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'global',
            scoped_channels TEXT,
            PRIMARY KEY(guild_id, role_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            backup_data TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_runtime (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            latency_ms INTEGER DEFAULT 0,
            guilds INTEGER DEFAULT 0,
            users INTEGER DEFAULT 0,
            commands INTEGER DEFAULT 0,
            started_at TEXT,
            updated_at TEXT,
            version TEXT,
            user_id TEXT,
            username TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS welcome_config (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            channel_id INTEGER,
            background_url TEXT,
            message_text TEXT DEFAULT '¡Bienvenido {member} a nuestro servidor!',
            card_heading TEXT DEFAULT 'BIENVENIDO',
            member_label TEXT DEFAULT 'Miembro',
            custom_text TEXT DEFAULT '',
            layout_json TEXT DEFAULT '{}'
        )
    """)
    for sql in (
        "ALTER TABLE welcome_config ADD COLUMN card_heading TEXT DEFAULT 'BIENVENIDO'",
        "ALTER TABLE welcome_config ADD COLUMN member_label TEXT DEFAULT 'Miembro'",
        "ALTER TABLE welcome_config ADD COLUMN custom_text TEXT DEFAULT ''",
        "ALTER TABLE welcome_config ADD COLUMN layout_json TEXT DEFAULT '{}'",
    ):
        try:
            cursor.execute(sql)
        except Exception:
            pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS antiraid_config (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            join_threshold INTEGER DEFAULT 10,
            window_seconds INTEGER DEFAULT 10,
            alert_channel_id INTEGER,
            lockdown_minutes INTEGER DEFAULT 5
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            target_id INTEGER,
            channel_id INTEGER,
            summary TEXT,
            extra TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_guild_id ON audit_events(guild_id, id DESC)")
    try:
        cursor.execute("ALTER TABLE server_backups ADD COLUMN status TEXT DEFAULT 'ready'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE server_backups ADD COLUMN kind TEXT DEFAULT 'structure'")
    except Exception:
        pass
    alt_intel.ensure_schema_sync(conn)
    verify_log.ensure_schema_sync(conn)
    try:
        conn.execute(proxy_detect.INTEL_SCHEMA)
    except Exception:
        pass
    try:
        proxy_detect.warmup()
    except Exception:
        pass
    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---
async def get_current_user(session_id: str = Cookie(None), db: sqlite3.Connection = Depends(get_db)):
    if not session_id:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    cursor = db.cursor()
    cursor.execute(
        "SELECT user_id, username, avatar, access_token, expires_at FROM web_sessions WHERE session_id = ?",
        (session_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    
    expires_at = datetime.datetime.fromisoformat(row["expires_at"])
    if expires_at < datetime.datetime.now():
        cursor.execute("DELETE FROM web_sessions WHERE session_id = ?", (session_id,))
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")
        
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "avatar": row["avatar"],
        "access_token": row["access_token"]
    }

async def require_guild_member(user, guild_id: int) -> None:
    """Allow authenticated Discord members to read server-level statistics."""
    if user["user_id"] == SUPER_OWNER_ID:
        return
    try:
        async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
            headers = {"Authorization": f"Bearer {user['access_token']}"}
            async with session.get("https://discord.com/api/v10/users/@me/guilds?limit=200", headers=headers) as res:
                if res.status in (401, 403):
                    raise HTTPException(status_code=401, detail="Sesión de Discord caducada.")
                if res.status != 200:
                    raise HTTPException(status_code=502, detail="No se pudo comprobar tu pertenencia al servidor.")
                guilds = await res.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo comprobar tu pertenencia al servidor.")
    if not any(str(g.get("id")) == str(guild_id) for g in guilds if isinstance(g, dict)):
        raise HTTPException(status_code=403, detail="No perteneces a este servidor.")


def has_manage_guild_permission(permissions_int: int) -> bool:
    return (permissions_int & 0x8) == 0x8 or (permissions_int & 0x20) == 0x20

_DISCORD_TIMEOUT = aiohttp.ClientTimeout(total=25)
_bot_guilds_cache: tuple[float, list[str]] = (0, [])
_bot_guild_objs_cache: tuple[float, list[dict]] = (0.0, [])
_channel_cache: dict[int, tuple[float, list[dict]]] = {}
_http_session: aiohttp.ClientSession | None = None
_CHANNEL_TTL = 180.0
_GUILD_TTL = 180.0


async def _http() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT)
    return _http_session


async def discord_request(method: str, path: str, *, json_body=None, params=None, raise_http=True):
    """Bot REST call with User-Agent and 429 retries. Discord rate-limits hard if we open a session per request."""
    if not DISCORD_TOKEN:
        if raise_http:
            raise HTTPException(status_code=503, detail="Bot token no configurado.")
        return None, 503, "no token"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "User-Agent": DISCORD_USER_AGENT,
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    url = path if str(path).startswith("http") else f"https://discord.com/api/v10{path}"
    session = await _http()
    last_status, last_text = 0, ""
    for attempt in range(8):
        try:
            async with session.request(method, url, headers=headers, json=json_body, params=params) as res:
                last_text = await res.text()
                last_status = res.status
                if res.status == 429:
                    wait = 1.0
                    try:
                        payload = json.loads(last_text) if last_text else {}
                        wait = float(payload.get("retry_after") or res.headers.get("Retry-After") or 1)
                    except Exception:
                        try:
                            wait = float(res.headers.get("Retry-After") or 1)
                        except Exception:
                            wait = 1.0
                    wait = min(max(wait, 0.3), 10)
                    logger.warning("Discord 429 %s %s — retry in %.2fs", method, path, wait)
                    await asyncio.sleep(wait)
                    continue
                if res.status in (200, 201, 204):
                    data = json.loads(last_text) if last_text else {}
                    if raise_http:
                        return data
                    return data, res.status, last_text[:400]
                if res.status >= 500 and attempt < 6:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                logger.error("discord %s %s -> %s %s", method, path, res.status, last_text[:400])
                if raise_http:
                    raise HTTPException(status_code=400, detail=f"Discord no aceptó la acción ({res.status}).")
                return None, res.status, last_text[:400]
        except HTTPException:
            raise
        except Exception as e:
            last_text = str(e)
            last_status = 0
            logger.warning("discord %s %s attempt %s: %s", method, path, attempt + 1, e)
            await asyncio.sleep(0.3 * (attempt + 1))
    if raise_http:
        raise HTTPException(status_code=429, detail="Discord está limitando peticiones. Espera unos segundos y recarga.")
    return None, last_status, last_text[:400]


async def fetch_bot_guild_objects() -> list[dict]:
    global _bot_guild_objs_cache, _bot_guilds_cache
    now = time.time()
    if now - _bot_guild_objs_cache[0] < _GUILD_TTL and _bot_guild_objs_cache[1]:
        return _bot_guild_objs_cache[1]
    if not DISCORD_TOKEN:
        return _bot_guild_objs_cache[1] or []
    objs: list[dict] = []
    after = None
    try:
        for _ in range(10):
            params = {"limit": 200, "with_counts": "true"}
            if after:
                params["after"] = after
            batch = await discord_request("GET", "/users/@me/guilds", params=params)
            if not isinstance(batch, list) or not batch:
                break
            for g in batch:
                objs.append({
                    "id": str(g.get("id") or ""),
                    "name": g.get("name") or "Servidor",
                    "icon": g.get("icon"),
                    "approximate_member_count": int(g.get("approximate_member_count") or 0),
                    "owner": bool(g.get("owner")),
                })
            if len(batch) < 200:
                break
            after = batch[-1]["id"]
    except Exception as e:
        logger.error("fetch_bot_guild_objects failed: %s", e)
        return _bot_guild_objs_cache[1] or objs or []
    if objs:
        _bot_guild_objs_cache = (now, objs)
        _bot_guilds_cache = (now, [o["id"] for o in objs if o.get("id")])
        return objs
    return _bot_guild_objs_cache[1] or []


async def fetch_bot_guilds() -> list[str]:
    objs = await fetch_bot_guild_objects()
    if objs:
        return [o["id"] for o in objs if o.get("id")]
    return _bot_guilds_cache[1] or []

async def fetch_guild_roles(guild_id: int) -> list[dict]:
    try:
        data = await discord_request("GET", f"/guilds/{guild_id}/roles")
        return data if isinstance(data, list) else []
    except Exception:
        return []

async def fetch_guild_channels(guild_id: int) -> list[dict]:
    gid = int(guild_id)
    now = time.time()
    hit = _channel_cache.get(gid)
    if hit and now - hit[0] < _CHANNEL_TTL:
        return hit[1]
    try:
        data = await discord_request("GET", f"/guilds/{gid}/channels")
        channels = data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("fetch_guild_channels %s failed: %s", gid, e)
        return hit[1] if hit else []
    _channel_cache[gid] = (now, channels)
    return channels

async def get_user_permissions(user, guild_id: int, db: sqlite3.Connection) -> dict:
    user_id = user["user_id"]
    if user_id == SUPER_OWNER_ID:
        return {
            "is_admin": True,
            "permissions": ["admin", "ban", "kick", "warn", "timeout", "resolve_appeals", "view_infractions", "manage_config"],
            "scopes": {}
        }
        
    # Fetch user's guilds from Discord to get permissions
    is_native_admin = False
    is_native_manage = False
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bearer {user['access_token']}", "User-Agent": DISCORD_USER_AGENT}
        async with session.get("https://discord.com/api/v10/users/@me/guilds", headers=headers) as res:
            if res.status == 200:
                user_guilds = await res.json()
                for g in user_guilds:
                    if int(g["id"]) == guild_id:
                        perms = int(g.get("permissions", "0"))
                        if g.get("owner", False) or (perms & 0x8) == 0x8:
                            is_native_admin = True
                        if (perms & 0x20) == 0x20:
                            is_native_manage = True
                            
    if is_native_admin:
        return {
            "is_admin": True,
            "permissions": ["admin", "ban", "kick", "warn", "timeout", "resolve_appeals", "view_infractions", "manage_config"],
            "scopes": {}
        }
        
    # Fetch member roles in the guild
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT}
        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}", headers=headers) as res:
            if res.status != 200:
                return {"is_admin": False, "permissions": [], "scopes": {}}
            member_data = await res.json()
            
    user_roles = [int(r) for r in member_data.get("roles", [])]
    
    cursor = db.cursor()
    cursor.execute("SELECT role_id, permissions, scope_type, scoped_channels FROM staff_permissions WHERE guild_id = ?", (guild_id,))
    rows = cursor.fetchall()
    
    granted_perms = set()
    if is_native_manage:
        granted_perms.add("manage_config")
        granted_perms.add("view_infractions")
        
    scopes = {}
    
    for row in rows:
        role_id = row["role_id"]
        if role_id in user_roles:
            try:
                perms_list = json.loads(row["permissions"])
                scope_type = row["scope_type"]
                scoped_chans = json.loads(row["scoped_channels"]) if row["scoped_channels"] else []
            except Exception:
                continue
                
            for p in perms_list:
                granted_perms.add(p)
                if p not in scopes:
                    scopes[p] = {"type": scope_type, "channels": scoped_chans}
                else:
                    if scopes[p]["type"] == "channels" and scope_type == "global":
                        scopes[p] = {"type": "global", "channels": []}
                    elif scopes[p]["type"] == "channels" and scope_type == "channels":
                        scopes[p]["channels"] = list(set(scopes[p]["channels"] + scoped_chans))
                        
    if "admin" in granted_perms:
        return {
            "is_admin": True,
            "permissions": ["admin", "ban", "kick", "warn", "timeout", "resolve_appeals", "view_infractions", "manage_config"],
            "scopes": {}
        }
        
    return {
        "is_admin": False,
        "permissions": list(granted_perms),
        "scopes": scopes
    }

# --- MODEL REPRESENTATIONS ---
class GuildConfigModel(BaseModel):
    prefix: str
    language: str
    leveling_enabled: bool
    text_xp_min: int
    text_xp_max: int
    voice_xp_min: int
    voice_xp_max: int
    level_up_channel: str | None = None
    leaderboard_channel: str | None = None

class PremiumUserModel(BaseModel):
    user_id: str | int
    action: str
    duration_days: int = 30
    plan: str = "monthly"

class PremiumGuildModel(BaseModel):
    guild_id: str | int
    action: str
    duration_days: int = 30
    plan: str = "lifetime"


class LiveSendModel(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class AnnouncementConfigModel(BaseModel):
    channel_id: str | int | None = None


class AnnouncementSendModel(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class AnnouncementEditModel(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    plan: str = "monthly"

class RolePermissionsPayload(BaseModel):
    role_id: int
    permissions: list[str]
    scope_type: str
    scoped_channels: list[str] | None = None

class InfractionPayload(BaseModel):
    user_id: int
    type: str
    reason: str

class AppealPayload(BaseModel):
    infraction_id: int
    reason: str

class AppealResolvePayload(BaseModel):
    action: str
    response: str

# --- AUTHENTICATION & LOGIN FLOW ---

def _safe_next(value: str | None) -> str:
    if not value:
        return "/dashboard"
    value = value.strip()
    if value.startswith("/") and not value.startswith("//") and "://" not in value:
        return value[:200]
    return "/dashboard"


DEVICE_COOKIE_MAX_AGE = 400 * 24 * 60 * 60  # ~13 months; refreshed on each visit (sliding)


def _cookie_already_on_response(response: Response, name: str) -> bool:
    prefix = name.lower() + "="
    for key, val in getattr(response, "raw_headers", []):
        if key.lower() == b"set-cookie" and val.lower().startswith(prefix.encode()):
            return True
    return False


def _slide_cookie(response: Response, name: str, value: str, *, httponly: bool, max_age: int):
    if not value or _cookie_already_on_response(response, name):
        return
    response.set_cookie(
        key=name,
        value=value,
        httponly=httponly,
        secure=True,
        samesite="lax",
        path="/",
        max_age=max_age,
    )


_verify_hits: dict[str, list[float]] = {}
_CAPTCHA_EMOJIS = ["🍎", "🍌", "🍇", "🍉", "🍓", "🍍", "🍋", "🍊", "🍐", "🥝", "🍑", "🍒"]


def _set_device_cookie(response: Response, request: Request) -> str:
    did = request.cookies.get("dabot_did") or secrets.token_hex(16)
    response.set_cookie(
        key="dabot_did",
        value=did,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=DEVICE_COOKIE_MAX_AGE,
    )
    return did


def _verify_rate_ok(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _verify_hits.get(ip, []) if now - t < 600]
    if len(hits) >= 12:
        _verify_hits[ip] = hits
        return False
    hits.append(now)
    _verify_hits[ip] = hits
    return True


@app.get("/login")
def login(request: Request, next: str | None = None, db: sqlite3.Connection = Depends(get_db)):
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return HTMLResponse("<h2>Error: DISCORD_CLIENT_ID o DISCORD_CLIENT_SECRET no configurados en el archivo .env</h2>", status_code=500)
    
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    safe_next = _safe_next(next)
    now = datetime.datetime.now()
    cursor = db.cursor()
    cursor.execute("DELETE FROM web_oauth_states WHERE created_at < ?", ((now - datetime.timedelta(minutes=10)).isoformat(),))
    cursor.execute(
        "INSERT INTO web_oauth_states (state, code_verifier, next_path, created_at) VALUES (?, ?, ?, ?)",
        (state, code_verifier, safe_next, now.isoformat()),
    )
    db.commit()
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if next and "verify" in next:
        params["prompt"] = "consent"
    discord_auth_url = "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    resp = RedirectResponse(discord_auth_url, status_code=302)
    resp.set_cookie("dabot_oauth_state", state, httponly=True, secure=True, samesite="lax", max_age=600, path="/")
    resp.set_cookie("dabot_pkce_verifier", code_verifier, httponly=True, secure=True, samesite="lax", max_age=600, path="/")
    return resp

@app.get("/login/callback")
async def login_callback(request: Request, code: str, state: str | None = None, db: sqlite3.Connection = Depends(get_db), dabot_oauth_state: str | None = Cookie(None), dabot_pkce_verifier: str | None = Cookie(None)):
    if not code:
        raise HTTPException(status_code=400, detail="Code parameter missing")
    if not state or not dabot_oauth_state or not hmac.compare_digest(state, dabot_oauth_state) or not dabot_pkce_verifier:
        raise HTTPException(status_code=400, detail="OAuth state inválido o caducado")

    cursor = db.cursor()
    cursor.execute("SELECT code_verifier, next_path, created_at FROM web_oauth_states WHERE state = ?", (state,))
    oauth_state = cursor.fetchone()
    if not oauth_state:
        raise HTTPException(status_code=400, detail="OAuth state inválido o ya utilizado")
    try:
        created_at = datetime.datetime.fromisoformat(oauth_state[2])
        if created_at < datetime.datetime.now() - datetime.timedelta(minutes=10):
            raise HTTPException(status_code=400, detail="OAuth state caducado")
    finally:
        cursor.execute("DELETE FROM web_oauth_states WHERE state = ?", (state,))
        db.commit()
    if not hmac.compare_digest(str(oauth_state[0]), str(dabot_pkce_verifier)):
        raise HTTPException(status_code=400, detail="OAuth PKCE inválido")
        
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        data = {
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': DISCORD_REDIRECT_URI,
            'code_verifier': dabot_pkce_verifier,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": DISCORD_USER_AGENT,
        }
        
        async with session.post("https://discord.com/api/v10/oauth2/token", data=data, headers=headers) as token_res:
            if token_res.status != 200:
                res_body = await token_res.text()
                logger.error(f"Failed to fetch oauth2 token: {res_body}")
                raise HTTPException(status_code=400, detail="Failed to retrieve access token from Discord")
            token_data = await token_res.json()
            access_token = token_data['access_token']
            
        headers = {"Authorization": f"Bearer {access_token}", "User-Agent": DISCORD_USER_AGENT}
        async with session.get("https://discord.com/api/v10/users/@me", headers=headers) as user_res:
            if user_res.status != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user data")
            user_data = await user_res.json()
            
    session_id = secrets.token_hex(32)
    user_id = int(user_data['id'])
    username = f"{user_data['username']}#{user_data.get('discriminator', '0000')}" if user_data.get('discriminator') and user_data['discriminator'] != '0' else user_data['username']
    avatar = user_data.get('avatar')
    
    expires_at = datetime.datetime.now() + datetime.timedelta(days=7)
    
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO web_sessions (session_id, user_id, username, avatar, access_token, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, user_id, username, avatar, access_token, expires_at.isoformat())
    )
    db.commit()
    
    dest = _safe_next(oauth_state[1])
    response = RedirectResponse(dest, status_code=302)
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=7*24*60*60
    )
    did = _set_device_cookie(response, request)
    response.delete_cookie("dabot_oauth_state", path="/")
    response.delete_cookie("dabot_pkce_verifier", path="/")
    try:
        created = None
        if user_data.get("id"):
            # Discord snowflake -> unix ms
            created = datetime.datetime.utcfromtimestamp(((int(user_data["id"]) >> 22) + 1420070400000) / 1000).isoformat()
        alt_intel.record_sighting(
            db,
            user_id=user_id,
            guild_id=None,
            username=user_data.get("username") or username,
            global_name=user_data.get("global_name") or "",
            account_created=created or "",
            avatar_hash=avatar or "",
            public_flags=int(user_data.get("public_flags") or 0),
            ip=alt_intel.client_ip(request.headers, request.client.host if request.client else ""),
            country=request.headers.get("cf-ipcountry") or request.headers.get("CF-IPCountry") or "",
            device_id=did,
            user_agent=request.headers.get("user-agent") or "",
            source="dashboard",
        )
    except Exception as e:
        logger.warning("alt sighting on login failed: %s", e)
    return response

@app.get("/logout")
def logout(response: Response, session_id: str = Cookie(None), db: sqlite3.Connection = Depends(get_db)):
    if session_id:
        cursor = db.cursor()
        cursor.execute("DELETE FROM web_sessions WHERE session_id = ?", (session_id,))
        db.commit()
    response = RedirectResponse("/")
    response.delete_cookie("session_id", path="/")
    return response

# --- API DASHBOARD ENDPOINTS ---

@app.get("/api/user/me")
async def api_user_me(user = Depends(get_current_user)):
    is_owner = user["user_id"] == SUPER_OWNER_ID
    return {
        "user_id": str(user["user_id"]),
        "username": user["username"],
        "avatar": user["avatar"],
        "is_owner": is_owner
    }

@app.post("/api/dabot/suggestions")
async def api_dabot_suggestion(request: Request, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    from utils.bot_suggestions import (
        SUGGEST_CHANNEL_ID,
        SUGGEST_GUILD_ID,
        components_payload,
        embed_payload,
    )
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if len(text) < 8:
        raise HTTPException(status_code=400, detail="Escribe al menos 8 caracteres.")
    if len(text) > 1800:
        raise HTTPException(status_code=400, detail="Máximo 1800 caracteres.")
    guild_id = body.get("guild_id")
    try:
        guild_id = int(guild_id) if guild_id else None
    except (TypeError, ValueError):
        guild_id = None
    if user["user_id"] != SUPER_OWNER_ID:
        if not guild_id:
            raise HTTPException(status_code=400, detail="Indica el servidor desde el que envías la sugerencia.")
        perm = await get_user_permissions(user, guild_id, db)
        if not perm.get("is_admin"):
            raise HTTPException(status_code=403, detail="Solo owners y administradores pueden enviar sugerencias para Dabot.")
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
    cursor = db.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM bot_suggestions WHERE user_id = ? AND created_at >= ?",
        (user["user_id"], since),
    )
    if (cursor.fetchone()[0] or 0) >= 8:
        raise HTTPException(status_code=429, detail="Límite de 8 sugerencias cada 24 horas.")
    guild_name = None
    if guild_id:
        try:
            async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
                headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT}
                async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}", headers=headers) as res:
                    if res.status == 200:
                        guild_name = (await res.json()).get("name")
        except Exception:
            guild_name = None
    now = datetime.datetime.utcnow().isoformat()
    cursor.execute(
        """INSERT INTO bot_suggestions
           (user_id, username, guild_id, guild_name, text, status, created_at, channel_id)
           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (user["user_id"], user.get("username"), guild_id, guild_name, text, now, SUGGEST_CHANNEL_ID),
    )
    sid = cursor.lastrowid
    db.commit()
    row = {
        "id": sid, "user_id": user["user_id"], "guild_id": guild_id,
        "guild_name": guild_name, "text": text, "status": "pending",
    }
    posted = False
    try:
        async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
            headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT, "Content-Type": "application/json"}
            payload = {"embeds": [embed_payload(row)], "components": components_payload(sid)}
            async with session.post(
                f"https://discord.com/api/v10/channels/{SUGGEST_CHANNEL_ID}/messages",
                headers=headers, json=payload,
            ) as res:
                if res.status in (200, 201):
                    msg = await res.json()
                    cursor.execute(
                        "UPDATE bot_suggestions SET message_id = ? WHERE id = ?",
                        (int(msg["id"]), sid),
                    )
                    db.commit()
                    posted = True
                else:
                    logger.warning("suggestion post HTTP %s: %s", res.status, (await res.text())[:300])
    except Exception as e:
        logger.warning("suggestion post failed: %s", e)
    return {"id": sid, "posted": posted, "guild": SUGGEST_GUILD_ID}

@app.get("/api/user/guilds")
async def api_user_guilds(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    user_guilds = []
    try:
        async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
            headers = {"Authorization": f"Bearer {user['access_token']}"}
            async with session.get("https://discord.com/api/v10/users/@me/guilds?limit=200", headers=headers) as res:
                body = await res.text()
                if res.status in (401, 403):
                    logger.warning("user guilds auth failed %s: %s", res.status, body[:300])
                    raise HTTPException(status_code=401, detail="Sesión de Discord caducada. Vuelve a iniciar sesión.")
                if res.status != 200:
                    logger.error("user guilds HTTP %s: %s", res.status, body[:500])
                    raise HTTPException(status_code=502, detail="Discord no devolvió tus servidores. Inténtalo de nuevo.")
                user_guilds = json.loads(body)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("user guilds fetch error: %s", e)
        raise HTTPException(status_code=502, detail="No se pudieron leer tus servidores.")

    bot_guilds = set(await fetch_bot_guilds())
    is_super_owner = user["user_id"] == SUPER_OWNER_ID
    cursor = db.cursor()
    cursor.execute("SELECT guild_id FROM premium_guilds")
    premium_ids = {str(r[0]) for r in cursor.fetchall()}
    cursor.execute("SELECT DISTINCT guild_id FROM staff_permissions")
    staff_guilds = {str(r[0]) for r in cursor.fetchall()}

    active_admin = []
    invitable = []
    regular_member = []

    for g in user_guilds:
        if not isinstance(g, dict) or "id" not in g:
            continue
        g_id = str(g["id"])
        perms = int(g.get("permissions") or 0)
        has_admin_perms = has_manage_guild_permission(perms) or g.get("owner", False)
        bot_present = g_id in bot_guilds
        user_role = "owner" if g.get("owner") else ("gestor" if has_admin_perms else "usuario")
        guild_info = {
            "id": g_id,
            "name": g.get("name") or "Servidor",
            "icon": g.get("icon"),
            "is_owner": bool(g.get("owner")),
            "is_premium": g_id in premium_ids,
            "client_id": DISCORD_CLIENT_ID,
            "invite_url": invite_url(DISCORD_CLIENT_ID, g_id),
            "permissions": str(BOT_INVITE_PERMISSIONS),
            "user_role": user_role,
        }
        if bot_present:
            if has_admin_perms or is_super_owner or g_id in staff_guilds:
                if is_super_owner and user_role == "usuario":
                    guild_info["user_role"] = "gestor"
                active_admin.append(guild_info)
            else:
                regular_member.append(guild_info)
        elif has_admin_perms or is_super_owner:
            invitable.append(guild_info)

    if is_super_owner:
        seen = {g["id"] for g in active_admin}
        for g in await fetch_bot_guild_objects():
            g_id = str(g.get("id") or "")
            if not g_id or g_id in seen:
                continue
            active_admin.append({
                "id": g_id,
                "name": g.get("name") or "Servidor",
                "icon": g.get("icon"),
                "is_owner": True,
                "is_premium": g_id in premium_ids,
                "client_id": DISCORD_CLIENT_ID,
                "invite_url": invite_url(DISCORD_CLIENT_ID, g_id),
                "permissions": str(BOT_INVITE_PERMISSIONS),
                "user_role": "owner",
                "via_bot": True,
                "member_count": g.get("approximate_member_count") or 0,
            })
            seen.add(g_id)

    logger.info(
        "guilds for %s: user=%s bot=%s active=%s invite=%s member=%s",
        user["user_id"], len(user_guilds), len(bot_guilds),
        len(active_admin), len(invitable), len(regular_member),
    )
    return {
        "active_admin": active_admin,
        "invitable": invitable,
        "regular_member": regular_member
    }

@app.get("/api/guilds/{guild_id}/permissions")
async def get_guild_permissions(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    return perm_data

@app.get("/api/guilds/{guild_id}/roles")
async def get_guild_roles(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    roles = await fetch_guild_roles(guild_id)
    return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in roles if not r.get("managed")]

@app.get("/api/guilds/{guild_id}/channels")
async def get_guild_channels_endpoint(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    channels = await fetch_guild_channels(guild_id)
    filtered = [
        {"id": c["id"], "name": c["name"], "type": c["type"], "parent_id": c.get("parent_id")}
        for c in channels if c["type"] in [0, 2, 4, 5]
    ]
    return filtered

# --- STAFF PERMISSIONS MANAGEMENT ENDPOINTS ---

@app.get("/api/guilds/{guild_id}/staff-permissions")
async def get_staff_permissions(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="Only administrators can manage roles permissions.")
    cursor = db.cursor()
    cursor.execute("SELECT role_id, permissions, scope_type, scoped_channels FROM staff_permissions WHERE guild_id = ?", (guild_id,))
    return [
        {
            "role_id": str(r[0]),
            "permissions": json.loads(r[1]),
            "scope_type": r[2],
            "scoped_channels": json.loads(r[3]) if r[3] else []
        }
        for r in cursor.fetchall()
    ]

@app.post("/api/guilds/{guild_id}/staff-permissions")
async def update_role_permissions(guild_id: int, payload: RolePermissionsPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="Only administrators can modify roles permissions.")
        
    cursor = db.cursor()
    if not payload.permissions:
        cursor.execute("DELETE FROM staff_permissions WHERE guild_id = ? AND role_id = ?", (guild_id, payload.role_id))
    else:
        perms_str = json.dumps(payload.permissions)
        channels_str = json.dumps(payload.scoped_channels) if payload.scoped_channels else "[]"
        cursor.execute(
            """INSERT INTO staff_permissions (guild_id, role_id, permissions, scope_type, scoped_channels) 
               VALUES (?, ?, ?, ?, ?) 
               ON CONFLICT(guild_id, role_id) 
               DO UPDATE SET permissions = excluded.permissions, scope_type = excluded.scope_type, scoped_channels = excluded.scoped_channels""",
            (guild_id, payload.role_id, perms_str, payload.scope_type, channels_str)
        )
    db.commit()
    return {"status": "success"}

from utils.config import DEFAULT_CONFIG

# --- SERVER CONFIGURATION ---

@app.get("/api/guilds/{guild_id}/config")
async def get_guild_config(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="No autorizado para gestionar este servidor.")
            
    cursor = db.cursor()
    cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    
    config_data = {}
    if row:
        try:
            config_data = json.loads(row[0])
        except Exception as e:
            logger.error(f"Error parsing database config for {guild_id}: {e}")
            
    # Deep merge with defaults
    def deep_merge(default, custom):
        if not isinstance(custom, dict):
            return custom
        import copy
        merged = copy.deepcopy(default)
        for k, v in custom.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged
        
    config_data = deep_merge(DEFAULT_CONFIG, config_data)
            
    # Load AI settings from SQLite
    cursor.execute("SELECT personality_prompt, toxicity_threshold FROM ai_settings WHERE guild_id = ?", (guild_id,))
    ai_row = cursor.fetchone()
    
    cb_dict = config_data.setdefault("chatbot", {})
    if ai_row:
        cb_dict["personality_prompt"] = ai_row["personality_prompt"] or ""
        cb_dict["toxicity_threshold"] = ai_row["toxicity_threshold"] or 0.8
    else:
        cb_dict.setdefault("personality_prompt", "")
        cb_dict.setdefault("toxicity_threshold", 0.8)
    cb_dict["enabled"] = _as_bool(cb_dict.get("enabled"))
    if not isinstance(cb_dict.get("channel_ids"), list):
        cb_dict["channel_ids"] = []

    cursor.execute("SELECT enabled, channel_id, message_text, card_heading, member_label, custom_text, layout_json FROM welcome_config WHERE guild_id = ?", (guild_id,))
    wrow = cursor.fetchone()
    if wrow:
        config_data.setdefault("welcome", {})
        config_data["welcome"]["enabled"] = bool(wrow[0])
        if wrow[1]:
            config_data["welcome"]["channel_id"] = str(wrow[1])
        if wrow[2] and not config_data["welcome"].get("message"):
            config_data["welcome"]["message"] = wrow[2]
        if wrow[3]:
            config_data["welcome"]["card_heading"] = wrow[3]
        if wrow[4]:
            config_data["welcome"]["member_label"] = wrow[4]
        if wrow[5] is not None:
            config_data["welcome"]["custom_text"] = wrow[5]
        if wrow[6]:
            try:
                config_data["welcome"]["layout"] = json.loads(wrow[6])
            except (TypeError, ValueError):
                config_data["welcome"]["layout"] = {}

    cursor.execute("SELECT custom_bot_name, custom_bot_avatar FROM premium_guilds WHERE guild_id = ?", (guild_id,))
    persona = cursor.fetchone() if _is_premium_guild(db, guild_id, user["user_id"]) else None
    config_data["premium_persona"] = {
        "name": persona[0] if persona else "",
        "avatar": persona[1] if persona else "",
    }
    
    return config_data

@app.post("/api/guilds/{guild_id}/config")
async def update_guild_config(guild_id: int, request: Request, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="No autorizado para gestionar este servidor.")
        
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload inválido.")

    chatbot_data = payload.get("chatbot", {}) or {}
    persona = payload.pop("premium_persona", None)
    personality = chatbot_data.get("personality_prompt", "")
    toxicity = chatbot_data.get("toxicity_threshold", 0.8)
    if "enabled" in chatbot_data:
        chatbot_data["enabled"] = _as_bool(chatbot_data.get("enabled"))
    elif personality:
        chatbot_data["enabled"] = True
    else:
        chatbot_data["enabled"] = _as_bool(chatbot_data.get("enabled"))
    payload["chatbot"] = chatbot_data

    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO ai_settings (guild_id, personality_prompt, toxicity_threshold)
           VALUES (?, ?, ?)
           ON CONFLICT(guild_id)
           DO UPDATE SET personality_prompt = excluded.personality_prompt,
                         toxicity_threshold = excluded.toxicity_threshold""",
        (guild_id, personality, toxicity)
    )

    cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    existing = {}
    if row:
        try:
            existing = json.loads(row[0])
        except Exception:
            existing = {}

    def deep_merge(default, custom):
        import copy
        if not isinstance(custom, dict):
            return custom
        merged = copy.deepcopy(default) if isinstance(default, dict) else {}
        for k, v in custom.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged

    merged = deep_merge(DEFAULT_CONFIG, existing)
    merged = deep_merge(merged, payload)
    if "lang" in merged and "language" not in payload:
        merged["language"] = merged["lang"]

    if isinstance(persona, dict) and _is_premium_guild(db, guild_id, user["user_id"]):
        custom_name = " ".join(str(persona.get("name") or "").split()).strip()[:32]
        custom_avatar = str(persona.get("avatar") or "").strip()[:1000]
        if custom_avatar and not custom_avatar.startswith(("http://", "https://", "data/")):
            raise HTTPException(status_code=400, detail="El avatar Premium debe ser una URL HTTPS o un archivo persistente.")
        cursor.execute(
            """INSERT INTO premium_guilds (guild_id, activated_at, expires_at, plan, custom_bot_name, custom_bot_avatar)
               VALUES (?, ?, '9999-12-31T23:59:59', 'lifetime', ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET custom_bot_name = excluded.custom_bot_name,
                                                   custom_bot_avatar = excluded.custom_bot_avatar""",
            (guild_id, datetime.datetime.now(datetime.timezone.utc).isoformat(), custom_name or None, custom_avatar or None),
        )

    welcome = merged.get("welcome") or {}
    try:
        cursor.execute(
            """INSERT INTO welcome_config
               (guild_id, enabled, channel_id, message_text, card_heading, member_label, custom_text, layout_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 enabled = excluded.enabled,
                 channel_id = excluded.channel_id,
                 message_text = excluded.message_text,
                 card_heading = excluded.card_heading,
                 member_label = excluded.member_label,
                 custom_text = excluded.custom_text,
                 layout_json = excluded.layout_json""",
            (
                guild_id,
                1 if welcome.get("enabled") else 0,
                int(welcome["channel_id"]) if str(welcome.get("channel_id") or "").isdigit() else None,
                (welcome.get("message") or "¡Bienvenido {member} a nuestro servidor!")
                    .replace("{mention}", "{member}")
                    .replace("{server}", "{guild}"),
                welcome.get("card_heading") or "BIENVENIDO",
                welcome.get("member_label") or "Miembro",
                str(welcome.get("custom_text") or "")[:200],
                json.dumps(welcome.get("layout") if isinstance(welcome.get("layout"), dict) else {}, ensure_ascii=False),
            )
        )
    except Exception as e:
        logger.warning(f"Could not sync welcome_config for {guild_id}: {e}")

    try:
        config_json = json.dumps(merged)
        cursor.execute(
            """INSERT INTO guild_configs (guild_id, config_json)
               VALUES (?, ?)
               ON CONFLICT(guild_id)
                DO UPDATE SET config_json = excluded.config_json""",
            (guild_id, config_json)
        )
        db.commit()

        # Record web dashboard audit log & Discord notification
        try:
            cursor.execute(
                """INSERT INTO audit_events (guild_id, event_type, actor_id, target_id, summary, extra, timestamp)
                   VALUES (?, 'dashboard_config_update', ?, ?, ?, ?, ?)""",
                (guild_id, user["user_id"], str(guild_id), f"{user['username']} guardó cambios en la configuración desde la dashboard web", json.dumps({"modules": list(payload.keys())}), datetime.datetime.utcnow().isoformat())
            )
            db.commit()

            log_ch = (merged.get("logs") or {}).get("mod") or (merged.get("logs") or {}).get("general") or (merged.get("logs") or {}).get("server")
            if log_ch and str(log_ch).isdigit():
                changed_keys = ", ".join([f"`{k}`" for k in list(payload.keys())[:6]])
                embed_data = {
                    "title": "⚙️ Configuración actualizada desde el Panel Web",
                    "description": f"El administrador **{user['username']}** (`{user['user_id']}`) ha guardado cambios en la configuración del bot.",
                    "fields": [
                        {"name": "Módulos modificados", "value": changed_keys or "Ajustes generales", "inline": True},
                    ],
                    "color": 0x00ff88,
                    "footer": {"text": "Dabot Web Dashboard • Audit Log"},
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
                asyncio.create_task(discord_bot("POST", f"/channels/{log_ch}/messages", json={"embeds": [embed_data]}))
        except Exception as e:
            logger.debug(f"Audit log notify error: {e}")
    except Exception as e:
        logger.error(f"Error saving DB config for {guild_id}: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar la configuración del servidor.")

    try:
        alts_ch = (merged.get("logs") or {}).get("alts")
        if alts_ch and str(alts_ch).isdigit():
            alt_intel.set_alts_channel(db, guild_id, int(alts_ch))
    except Exception as e:
        logger.warning("Could not sync alts channel: %s", e)

    try:
        def _flatten(d, prefix=""):
            out = {}
            if not isinstance(d, dict):
                return {prefix or "value": d}
            for k, v in d.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    out.update(_flatten(v, key))
                else:
                    out[key] = v
            return out
        before_map = _flatten(existing)
        after_map = _flatten(merged)
        changed = [k for k in sorted(set(before_map) | set(after_map)) if before_map.get(k) != after_map.get(k)]
        summary = ", ".join(changed[:12]) or "sin cambios de campos"
        cursor.execute(
            """INSERT INTO config_revisions (guild_id, user_id, summary, before_json, after_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                guild_id, user["user_id"], summary[:500],
                json.dumps(existing, ensure_ascii=False)[:80000],
                json.dumps(merged, ensure_ascii=False)[:80000],
                datetime.datetime.now().isoformat(),
            ),
        )
        db.commit()
    except Exception as e:
        logger.warning("config revision skip: %s", e)

    return {"status": "success", "message": "Configuración guardada. El bot la aplica al momento."}

# --- INFRACTIONS & APPEALS ENDPOINTS ---

@app.get("/api/guilds/{guild_id}/infractions")
async def get_infractions(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    has_mod_view = any(p in perm_data["permissions"] for p in ["admin", "ban", "kick", "warn", "timeout", "view_infractions"])
    cursor = db.cursor()
    
    sql_all = "SELECT id, user_id, moderator_id, type, reason, timestamp, status, staff_note FROM infractions WHERE guild_id = ? ORDER BY id DESC"
    sql_mine = "SELECT id, user_id, moderator_id, type, reason, timestamp, status, staff_note FROM infractions WHERE guild_id = ? AND user_id = ? ORDER BY id DESC"
    try:
        if has_mod_view or perm_data["is_admin"]:
            cursor.execute(sql_all, (guild_id,))
        else:
            cursor.execute(sql_mine, (guild_id, user["user_id"]))
        rows = cursor.fetchall()
        return [{
            "id": r[0], "user_id": str(r[1]), "moderator_id": str(r[2]), "type": r[3],
            "reason": r[4], "timestamp": r[5], "status": r[6],
            "staff_note": r[7] if len(r) > 7 and (has_mod_view or perm_data["is_admin"]) else None,
        } for r in rows]
    except Exception:
        if has_mod_view or perm_data["is_admin"]:
            cursor.execute("SELECT id, user_id, moderator_id, type, reason, timestamp, status FROM infractions WHERE guild_id = ? ORDER BY id DESC", (guild_id,))
        else:
            cursor.execute("SELECT id, user_id, moderator_id, type, reason, timestamp, status FROM infractions WHERE guild_id = ? AND user_id = ? ORDER BY id DESC", (guild_id, user["user_id"]))
        return [{"id": r[0], "user_id": str(r[1]), "moderator_id": str(r[2]), "type": r[3], "reason": r[4], "timestamp": r[5], "status": r[6], "staff_note": None} for r in cursor.fetchall()]

@app.post("/api/guilds/{guild_id}/infractions")
async def add_infraction(guild_id: int, payload: InfractionPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    
    required_perm = payload.type
    if required_perm not in perm_data["permissions"] and not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail=f"No tienes el permiso específico de '{required_perm}' para esta acción.")
        
    cursor = db.cursor()
    now = datetime.datetime.now().isoformat()
    
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT}
        if payload.type == "ban":
            async with session.put(
                f"https://discord.com/api/v10/guilds/{guild_id}/bans/{payload.user_id}",
                headers=headers,
                json={"reason": payload.reason}
            ) as res:
                if res.status not in (200, 201, 204):
                    raise HTTPException(status_code=400, detail=f"Discord rechazó el ban ({res.status}).")
        elif payload.type == "kick":
            async with session.delete(
                f"https://discord.com/api/v10/guilds/{guild_id}/members/{payload.user_id}",
                headers=headers
            ) as res:
                if res.status not in (200, 201, 204):
                    raise HTTPException(status_code=400, detail=f"Discord rechazó la expulsión ({res.status}).")
        elif payload.type == "timeout":
            timeout_until = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat() + "Z"
            async with session.patch(
                f"https://discord.com/api/v10/guilds/{guild_id}/members/{payload.user_id}",
                headers=headers,
                json={"communication_disabled_until": timeout_until, "reason": payload.reason}
            ) as res:
                if res.status not in (200, 201, 204):
                    raise HTTPException(status_code=400, detail=f"Discord rechazó el timeout ({res.status}).")
            
    cursor.execute(
        "INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp, status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
        (payload.user_id, guild_id, user["user_id"], payload.type, payload.reason, now)
    )
    db.commit()
    return {"status": "success"}

@app.get("/api/guilds/{guild_id}/appeals")
async def get_appeals(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    has_mod_view = perm_data["is_admin"] or "resolve_appeals" in perm_data["permissions"]
    cursor = db.cursor()
    
    if has_mod_view:
        cursor.execute(
            """SELECT a.infraction_id, a.user_id, a.appeal_reason, a.status, a.mod_response, a.timestamp, i.type, i.reason 
               FROM infraction_appeals a
               JOIN infractions i ON a.infraction_id = i.id
               WHERE a.guild_id = ? ORDER BY a.timestamp DESC""",
            (guild_id,)
        )
    else:
        cursor.execute(
            """SELECT a.infraction_id, a.user_id, a.appeal_reason, a.status, a.mod_response, a.timestamp, i.type, i.reason 
               FROM infraction_appeals a
               JOIN infractions i ON a.infraction_id = i.id
               WHERE a.guild_id = ? AND a.user_id = ? ORDER BY a.timestamp DESC""",
            (guild_id, user["user_id"])
        )
    
    return [{
        "infraction_id": r[0],
        "user_id": str(r[1]),
        "appeal_reason": r[2],
        "status": r[3],
        "mod_response": r[4],
        "timestamp": r[5],
        "infraction_type": r[6],
        "infraction_reason": r[7]
    } for r in cursor.fetchall()]

@app.post("/api/guilds/{guild_id}/appeals")
async def submit_appeal(guild_id: int, payload: AppealPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT user_id, status FROM infractions WHERE id = ? AND guild_id = ?", (payload.infraction_id, guild_id))
    inf = cursor.fetchone()
    if not inf or inf[0] != user["user_id"]:
        raise HTTPException(status_code=403, detail="Infracción no válida o no te pertenece.")
    if inf[1] != 'active':
        raise HTTPException(status_code=400, detail="Esta infracción ya no está activa.")
        
    now = datetime.datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO infraction_appeals (infraction_id, guild_id, user_id, appeal_reason, status, timestamp) VALUES (?, ?, ?, ?, 'pending', ?)",
        (payload.infraction_id, guild_id, user["user_id"], payload.reason, now)
    )
    db.commit()
    return {"status": "success"}

@app.post("/api/guilds/{guild_id}/appeals/{infraction_id}/resolve")
async def resolve_appeal(guild_id: int, infraction_id: int, payload: AppealResolvePayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if "resolve_appeals" not in perm_data["permissions"] and not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="No tienes permisos para resolver apelaciones.")
        
    cursor = db.cursor()
    cursor.execute("SELECT user_id, type FROM infractions WHERE id = ? AND guild_id = ?", (infraction_id, guild_id))
    inf = cursor.fetchone()
    if not inf:
        raise HTTPException(status_code=404, detail="Infracción no encontrada.")
        
    target_user_id = inf[0]
    inf_type = inf[1]
    
    new_inf_status = 'active'
    new_appeal_status = 'rejected'
    
    if payload.action == "approve":
        new_inf_status = 'appealed'
        new_appeal_status = 'approved'
        
        async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
            headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT}
            if inf_type == "ban":
                async with session.delete(f"https://discord.com/api/v10/guilds/{guild_id}/bans/{target_user_id}", headers=headers) as res:
                    if res.status not in (200, 201, 204):
                        raise HTTPException(status_code=400, detail=f"Discord rechazó la retirada del ban ({res.status}).")
            elif inf_type == "timeout":
                async with session.patch(
                    f"https://discord.com/api/v10/guilds/{guild_id}/members/{target_user_id}",
                    headers=headers,
                    json={"communication_disabled_until": None}
                ) as res:
                    if res.status not in (200, 201, 204):
                        raise HTTPException(status_code=400, detail=f"Discord rechazó la retirada del timeout ({res.status}).")
                
    cursor.execute("UPDATE infractions SET status = ? WHERE id = ? AND guild_id = ?", (new_inf_status, infraction_id, guild_id))
    cursor.execute(
        "UPDATE infraction_appeals SET status = ?, mod_response = ? WHERE infraction_id = ? AND guild_id = ?",
        (new_appeal_status, payload.response, infraction_id, guild_id)
    )
    db.commit()
    return {"status": "success"}

@app.get("/api/guilds/{guild_id}/mod-queue")
async def mod_queue(guild_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and not any(p in perm_data["permissions"] for p in ("ban", "kick", "warn", "timeout", "resolve_appeals")):
        raise HTTPException(status_code=403, detail="Sin permiso de mesa.")
    cursor = db.cursor()
    out = {"appeals": [], "tickets": [], "alts": [], "hijacks": []}
    try:
        cursor.execute(
            """SELECT a.infraction_id, a.user_id, a.appeal_reason, a.timestamp, i.type, i.reason
               FROM infraction_appeals a JOIN infractions i ON a.infraction_id = i.id
               WHERE a.guild_id = ? AND a.status = 'pending' ORDER BY a.timestamp DESC LIMIT 20""",
            (guild_id,),
        )
        out["appeals"] = [
            {"infraction_id": r[0], "user_id": str(r[1]), "appeal_reason": r[2], "timestamp": r[3],
             "infraction_type": r[4], "infraction_reason": r[5]}
            for r in cursor.fetchall()
        ]
    except Exception:
        pass
    try:
        cursor.execute(
            "SELECT id, opener_id, status, created_at FROM tickets WHERE guild_id = ? AND status = 'open' ORDER BY id DESC LIMIT 20",
            (guild_id,),
        )
        out["tickets"] = [{"id": r[0], "user_id": str(r[1]), "status": r[2], "created_at": r[3]} for r in cursor.fetchall()]
    except Exception:
        pass
    try:
        cursor.execute(
            "SELECT id, user_id, risk, status, created_at FROM alt_cases WHERE guild_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 20",
            (guild_id,),
        )
        out["alts"] = [{"id": r[0], "user_id": str(r[1]), "risk": r[2], "status": r[3], "created_at": r[4]} for r in cursor.fetchall()]
    except Exception:
        pass
    try:
        cursor.execute(
            "SELECT id, user_id, kind, created_at FROM hijack_events WHERE guild_id = ? ORDER BY id DESC LIMIT 10",
            (guild_id,),
        )
        out["hijacks"] = [{"id": r[0], "user_id": str(r[1]), "kind": r[2], "created_at": r[3]} for r in cursor.fetchall()]
    except Exception:
        pass
    return out

@app.get("/api/guilds/{guild_id}/preview/sanction")
async def preview_sanction(guild_id: int, action: str = "warn", reason: str = "Motivo de ejemplo",
                           user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await get_user_permissions(user, guild_id, db)
    cfg = _guild_config_dict(db, guild_id)
    template = (cfg.get("messages") or {}).get(action) or f"Has recibido una sanción ({action}) en {{server}}. Motivo: {{reason}}"
    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1 FROM verified_guilds WHERE guild_id = ?", (guild_id,))
        verified = bool(cursor.fetchone())
    except Exception:
        verified = False
    body = template.format(user="Usuario", guild="{server}", server="{server}", reason=reason, duration="10m")
    return {
        "title": f"Sanción de Dabot — Caso #123",
        "body": body,
        "fields": {
            "servidor": "(nombre del servidor)",
            "miembros": "(recuento)",
            "antigüedad": "(fecha de creación)",
            "id": str(guild_id),
        },
        "verified": verified,
        "links_warning": "http://" in reason or "https://" in reason,
        "dashboard": DASHBOARD_URL,
    }

@app.get("/api/guilds/{guild_id}/config/revisions")
async def config_revisions(guild_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="Sin permiso.")
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT id, user_id, summary, created_at FROM config_revisions WHERE guild_id = ? ORDER BY id DESC LIMIT 25",
            (guild_id,),
        )
        return [{"id": r[0], "user_id": str(r[1]), "summary": r[2], "created_at": r[3]} for r in cursor.fetchall()]
    except Exception:
        return []

@app.get("/api/guilds/{guild_id}/infractions.csv")
async def infractions_csv(guild_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and not any(p in perm_data["permissions"] for p in ("ban", "kick", "warn")):
        raise HTTPException(status_code=403, detail="Sin permiso.")
    import csv, io
    cursor = db.cursor()
    cursor.execute(
        "SELECT id, user_id, moderator_id, type, reason, timestamp, status FROM infractions WHERE guild_id = ? ORDER BY id",
        (guild_id,),
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "user_id", "moderator_id", "type", "reason", "timestamp", "status"])
    w.writerows(cursor.fetchall())
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=sanciones_{guild_id}.csv"})

# --- GLOBAL ADMINISTRATOR ENDPOINTS (SUPER OWNER ONLY) ---

@app.get("/api/admin/diagnostics")
async def get_admin_diagnostics(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado: Requiere permisos de Superusuario.")
        
    cursor = db.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM premium_users")
    p_users_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM premium_guilds")
    p_guilds_count = cursor.fetchone()[0]
    
    premium_lib.ensure_schema_sync(db)
    try:
        cursor.execute("SELECT user_id, tier, activated_at, expires_at, plan FROM premium_users")
        premium_users = [premium_lib.serialize_user_row(r) for r in cursor.fetchall()]
        cursor.execute("SELECT guild_id, activated_at, expires_at, plan FROM premium_guilds")
        premium_guilds = [premium_lib.serialize_guild_row(r) for r in cursor.fetchall()]
    except Exception:
        cursor.execute("SELECT user_id, tier, activated_at, expires_at FROM premium_users")
        premium_users = [premium_lib.serialize_user_row(r) for r in cursor.fetchall()]
        cursor.execute("SELECT guild_id, activated_at, expires_at FROM premium_guilds")
        premium_guilds = [premium_lib.serialize_guild_row(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT COUNT(*) FROM guild_levels")
    total_levels = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM invite_tracker")
    total_invites = cursor.fetchone()[0]

    alt_stats = alt_intel.overview_stats(db)
    bot_guilds = await fetch_bot_guilds()
    try:
        v_stats = verify_log.stats_sync(db)
    except Exception:
        v_stats = {"people": 0, "events": 0, "today": 0, "pending": 0}

    return {
        "premium_users_count": p_users_count,
        "premium_guilds_count": p_guilds_count,
        "total_level_records": total_levels,
        "total_invite_records": total_invites,
        "premium_users": premium_users,
        "premium_guilds": premium_guilds,
        "bot_guilds": len(bot_guilds),
        "alt_cases_total": alt_stats.get("cases_total", 0),
        "alt_cases_pending": alt_stats.get("cases_pending", 0),
        "alt_sightings": alt_stats.get("sightings", 0),
        "alt_unique_users": alt_stats.get("unique_users", 0),
        "alt_network_guilds": alt_stats.get("network_guilds", 0),
        "alts": alt_stats,
        "verifications_people": v_stats.get("people", 0),
        "verifications_events": v_stats.get("events", 0),
        "verifications_today": v_stats.get("today", 0),
        "verifications_pending": v_stats.get("pending", 0),
    }

@app.post("/api/admin/premium/user")
async def grant_user_premium(payload: PremiumUserModel, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    return {
        "status": "error",
        "message": "El premium ya no es por usuario. Actívalo en el servidor (los servidores del superusuario lo tienen por defecto).",
    }

@app.post("/api/admin/premium/guild")
async def grant_guild_premium(payload: PremiumGuildModel, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    gid = int(str(payload.guild_id).strip())
    if payload.action == "grant":
        rec = premium_lib.grant_guild_sync(db, gid, payload.plan or "lifetime", duration_days=payload.duration_days)
        return {"status": "success", "message": f"Premium {premium_lib.plan_label(rec['plan'])} en servidor {gid} (hasta {rec['expires_at'][:10]}).", "record": rec}
    premium_lib.revoke_guild_sync(db, gid)
    return {"status": "success", "message": f"Premium desactivado en el servidor {gid} (los servidores del superusuario se pueden volver a activar)."}


LIVE_CHANNEL_TYPES = {0, 5}


def _live_serialize_message(m: dict) -> dict:
    author = m.get("author") or {}
    attachments = []
    for att in m.get("attachments") or []:
        attachments.append({
            "url": att.get("url") or att.get("proxy_url"),
            "filename": att.get("filename") or "archivo",
            "content_type": att.get("content_type") or "",
        })
    ref = m.get("referenced_message") or {}
    return {
        "id": str(m.get("id") or ""),
        "content": m.get("content") or "",
        "timestamp": m.get("timestamp"),
        "author": {
            "id": str(author.get("id") or ""),
            "username": author.get("global_name") or author.get("username") or "Usuario",
            "bot": bool(author.get("bot")),
            "avatar": author.get("avatar"),
        },
        "attachments": attachments,
        "reply_to": str(ref.get("id")) if ref.get("id") else None,
    }


async def _live_assert_bot_channel(channel_id: int, db: sqlite3.Connection | None = None) -> dict:
    if db is not None:
        live_cache_lib.ensure_schema_sync(db)
        row = db.execute(
            "SELECT channel_id, guild_id, name, type FROM cached_channels WHERE channel_id = ?",
            (int(channel_id),),
        ).fetchone()
        if row:
            ctype = int(row[3] if not hasattr(row, "keys") else row["type"])
            if ctype not in LIVE_CHANNEL_TYPES:
                raise HTTPException(status_code=400, detail="Solo canales de texto o anuncios.")
            return {"id": str(channel_id), "guild_id": str(row[1] if not hasattr(row, "keys") else row["guild_id"])}
    ch = await discord_bot("GET", f"/channels/{channel_id}")
    guild_id = str(ch.get("guild_id") or "")
    if not guild_id or guild_id not in set(await fetch_bot_guilds()):
        raise HTTPException(status_code=404, detail="Ese canal no pertenece a un servidor del bot.")
    if int(ch.get("type") or -1) not in LIVE_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail="Solo canales de texto o anuncios.")
    return ch


@app.get("/api/admin/live/guilds/{guild_id}/channels")
async def api_admin_live_channels(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    _require_super(user)
    channels = live_cache_lib.list_channels_sync(db, guild_id)
    if channels:
        return {"guild_id": str(guild_id), "channels": channels, "source": "cache"}
    bot_ids = set(await fetch_bot_guilds())
    if str(guild_id) not in bot_ids:
        raise HTTPException(status_code=404, detail="El bot no está en ese servidor.")
    raw = await fetch_guild_channels(guild_id)
    if not raw:
        raise HTTPException(
            status_code=502,
            detail="Aún no hay canales en caché y Discord no los listó. Espera a que el bot sincronice o reintenta en 10 s.",
        )
    categories = {str(c.get("id")): c.get("name") or "categoría" for c in raw if int(c.get("type") or -1) == 4}
    channels = []
    for c in raw:
        ctype = int(c.get("type") or -1)
        if ctype not in LIVE_CHANNEL_TYPES:
            continue
        parent = str(c.get("parent_id") or "")
        channels.append({
            "id": str(c.get("id")),
            "name": c.get("name") or "canal",
            "type": ctype,
            "position": int(c.get("position") or 0),
            "parent_id": parent or None,
            "category": categories.get(parent) if parent else None,
        })
    channels.sort(key=lambda x: ((x.get("category") or "").lower(), x["position"], x["name"].lower()))
    return {"guild_id": str(guild_id), "channels": channels, "source": "discord"}


@app.post("/api/admin/live/watch/{channel_id}")
async def api_admin_live_watch(channel_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    _require_super(user)
    ch = await _live_assert_bot_channel(channel_id, db)
    guild_id = ch.get("guild_id")
    live_cache_lib.set_watch_sync(db, channel_id, guild_id=int(guild_id) if str(guild_id or "").isdigit() else None, user_id=user["user_id"])
    db.commit()
    return {"status": "ok", "channel_id": str(channel_id)}


@app.get("/api/admin/live/channels/{channel_id}/messages")
async def api_admin_live_messages(channel_id: int, after: str | None = None, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    _require_super(user)
    await _live_assert_bot_channel(channel_id, db)
    live_cache_lib.set_watch_sync(db, channel_id, user_id=user["user_id"])
    db.commit()
    messages = live_cache_lib.list_messages_sync(db, channel_id, after=after)
    return {"channel_id": str(channel_id), "messages": messages, "source": "cache"}


@app.post("/api/admin/live/channels/{channel_id}/messages")
async def api_admin_live_send(channel_id: int, payload: LiveSendModel, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    _require_super(user)
    ch = await _live_assert_bot_channel(channel_id, db)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    data = await discord_bot(
        "POST",
        f"/channels/{channel_id}/messages",
        json_body={"content": content, "allowed_mentions": {"parse": ["users"]}},
    )
    serialized = _live_serialize_message(data)
    try:
        author = serialized.get("author") or {}
        live_cache_lib.upsert_message_sync(
            db,
            message_id=int(serialized["id"]),
            channel_id=channel_id,
            guild_id=int(ch["guild_id"]) if str(ch.get("guild_id") or "").isdigit() else None,
            author_id=int(author["id"]) if str(author.get("id") or "").isdigit() else None,
            author_name=author.get("username") or "Dabot",
            author_avatar=author.get("avatar"),
            author_bot=True,
            content=serialized.get("content") or content,
            attachments=serialized.get("attachments") or [],
            timestamp=serialized.get("timestamp"),
        )
        db.commit()
    except Exception as e:
        logger.debug("live send cache write: %s", e)
    return {"status": "success", "message": serialized}

@app.get("/api/admin/bot-guilds")
async def api_admin_bot_guilds(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")

    guilds = await fetch_bot_guild_objects()
    cursor = db.cursor()
    cursor.execute("SELECT guild_id, expires_at, plan FROM premium_guilds")
    premium_ids = [
        str(r[0]) for r in cursor.fetchall()
        if premium_lib.is_active(r[1], r[2] if len(r) > 2 else None)
    ]
    cursor.execute(
        "SELECT guild_id, COUNT(*) FROM alt_cases WHERE status = 'pending' GROUP BY guild_id"
    )
    pending_alts = {str(r[0]): int(r[1] or 0) for r in cursor.fetchall()}
    network = alt_intel.network_guilds(db)

    result = []
    for g in guilds:
        g_id = str(g["id"])
        try:
            cursor.execute(
                "SELECT COUNT(DISTINCT user_id) FROM guild_levels WHERE guild_id = ?",
                (int(g_id),),
            )
            active_users = cursor.fetchone()[0]
        except Exception:
            active_users = 0
        result.append({
            "id": g_id,
            "name": g.get("name") or "Servidor",
            "icon": g.get("icon"),
            "is_premium": g_id in premium_ids,
            "active_users": active_users,
            "member_count": g.get("approximate_member_count") or 0,
            "pending_alts": pending_alts.get(g_id, 0),
            "alt_share": int(g_id) in network,
            "is_owner": True,
            "user_role": "owner",
            "via_bot": True,
        })
    result.sort(key=lambda x: ((x.get("name") or "").lower(), x["id"]))
    return result


async def _announcement_channels(guild_id: int, db: sqlite3.Connection | None = None) -> list[dict]:
    """Return only channels where Discord accepts normal bot messages."""
    if db is not None:
        try:
            cached = live_cache_lib.list_channels_sync(db, guild_id)
            if cached:
                return [{"id": c["id"], "name": c["name"], "type": c["type"]} for c in cached]
        except Exception:
            pass
    channels = await fetch_guild_channels(guild_id)
    return [
        {"id": str(c.get("id")), "name": c.get("name") or "canal", "type": int(c.get("type") or -1)}
        for c in channels
        if int(c.get("type") or -1) in (0, 5)
    ]


def _announcement_effective_channel(channels: list[dict], configured_id: str | None) -> dict | None:
    if configured_id:
        for channel in channels:
            if channel["id"] == str(configured_id):
                return channel
    return next((c for c in channels if default_channel_name(c.get("name"))), None) or (channels[0] if channels else None)


async def _discord_bot_message(channel_id: str, content: str) -> tuple[int | None, str | None]:
    data, status, text = await discord_request(
        "POST",
        f"/channels/{channel_id}/messages",
        json_body={"content": content, "allowed_mentions": {"parse": []}},
        raise_http=False,
    )
    if isinstance(data, dict) and data.get("id"):
        return int(data["id"]), None
    return None, f"Discord HTTP {status}: {text}"


async def _discord_bot_edit(channel_id: int, message_id: int, content: str) -> str | None:
    data, status, text = await discord_request(
        "PATCH",
        f"/channels/{channel_id}/messages/{message_id}",
        json_body={"content": content, "allowed_mentions": {"parse": []}},
        raise_http=False,
    )
    if status in (200, 201, 204) or (isinstance(data, dict) and data.get("id")):
        return None
    return f"Discord HTTP {status}: {text}"


@app.get("/api/admin/announcements")
async def api_admin_announcements(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    cursor = db.cursor()
    cursor.execute("SELECT guild_id, channel_id FROM announcement_config")
    configured = {str(row[0]): (str(row[1]) if row[1] else None) for row in cursor.fetchall()}
    guilds = await fetch_bot_guild_objects()
    sem = asyncio.Semaphore(3)

    async def _one(guild):
        async with sem:
            channels = await _announcement_channels(int(guild["id"]), db)
        effective = _announcement_effective_channel(channels, configured.get(guild["id"]))
        return {
            "guild_id": guild["id"],
            "guild_name": guild.get("name") or guild["id"],
            "configured_channel_id": configured.get(guild["id"]),
            "effective_channel": effective,
            "channels": channels,
        }

    result = await asyncio.gather(*[_one(g) for g in guilds], return_exceptions=True)
    out = []
    for item, guild in zip(result, guilds):
        if isinstance(item, Exception):
            logger.warning("announcement channels %s: %s", guild.get("id"), item)
            out.append({
                "guild_id": guild["id"],
                "guild_name": guild.get("name") or guild["id"],
                "configured_channel_id": configured.get(guild["id"]),
                "effective_channel": None,
                "channels": [],
            })
        else:
            out.append(item)
    out.sort(key=lambda x: (x["guild_name"].casefold(), x["guild_id"]))
    return out


@app.post("/api/admin/announcements/config/{guild_id}")
async def api_admin_announcement_config(guild_id: int, payload: AnnouncementConfigModel,
                                         user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    bot_guild_ids = {str(g["id"]) for g in await fetch_bot_guild_objects()}
    if str(guild_id) not in bot_guild_ids:
        raise HTTPException(status_code=404, detail="El bot no está en ese servidor.")
    channel_id = str(payload.channel_id).strip() if payload.channel_id is not None else ""
    if channel_id:
        if not channel_id.isdigit() or int(channel_id) <= 0:
            raise HTTPException(status_code=400, detail="ID de canal inválido.")
        channels = await _announcement_channels(guild_id, db)
        if channel_id not in {c["id"] for c in channels}:
            raise HTTPException(status_code=400, detail="Ese canal no pertenece al servidor o no admite anuncios.")
        stored_id = int(channel_id)
    else:
        stored_id = None
    if stored_id is None:
        db.execute("DELETE FROM announcement_config WHERE guild_id = ?", (guild_id,))
    else:
        db.execute(
            """INSERT INTO announcement_config (guild_id, channel_id, updated_by, updated_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
            (guild_id, stored_id, user["user_id"], datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
    db.commit()
    return {"status": "success", "guild_id": str(guild_id), "channel_id": str(stored_id) if stored_id else None}


@app.post("/api/admin/announcements/send")
async def api_admin_announcement_send(payload: AnnouncementSendModel, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    source_id = f"dashboard-{secrets.token_urlsafe(18)}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.execute(
        """INSERT INTO announcement_messages (source_message_id, source_guild_id, source_channel_id, content, embeds, attachments, created_at)
           VALUES (?, NULL, NULL, ?, '[]', '[]', ?)""",
        (source_id, payload.content, now),
    )
    delivered = 0
    failed = 0
    failures: list[dict] = []
    cursor = db.cursor()
    cursor.execute("SELECT guild_id, channel_id FROM announcement_config")
    configured = {str(row[0]): (str(row[1]) if row[1] else None) for row in cursor.fetchall()}
    for guild in await fetch_bot_guild_objects():
        guild_id = int(guild["id"])
        channels = await _announcement_channels(guild_id, db)
        preferred = _announcement_effective_channel(channels, configured.get(str(guild_id)))
        ordered: list[dict] = []
        if preferred:
            ordered.append(preferred)
        for ch in channels:
            if all(ch["id"] != x["id"] for x in ordered):
                ordered.append(ch)
        message_id = None
        error = "No hay canal de texto (Discord no listó canales o el bot no puede escribir)."
        used = None
        for target in ordered[:8]:
            message_id, error = await _discord_bot_message(target["id"], payload.content)
            if message_id:
                used = target
                break
            # Missing access / unknown channel → try the next one.
            if error and any(code in error for code in ("403", "50001", "50013", "10003")):
                continue
            if error and "429" in error:
                await asyncio.sleep(1.2)
        if message_id and used:
            delivered += 1
            status = "sent"
            db.execute(
                """INSERT INTO announcement_deliveries (source_message_id, guild_id, channel_id, message_id, status, error, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source_id, guild_id, int(used["id"]), message_id, status, None, now),
            )
        else:
            failed += 1
            failures.append({"guild_id": str(guild_id), "guild_name": guild.get("name"), "error": error})
            db.execute(
                """INSERT INTO announcement_deliveries (source_message_id, guild_id, channel_id, message_id, status, error, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source_id, guild_id, None, None, "skipped" if not ordered else "failed", error, now),
            )
        await asyncio.sleep(0.35)
    db.commit()
    return {
        "status": "success",
        "source_message_id": source_id,
        "delivered": delivered,
        "failed": failed,
        "failures": failures[:12],
    }


@app.get("/api/admin/announcements/recent")
async def api_admin_announcements_recent(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    rows = db.execute(
        """SELECT m.source_message_id, m.content, m.created_at, COUNT(d.guild_id) AS total,
                  SUM(CASE WHEN d.status = 'sent' THEN 1 ELSE 0 END) AS sent
           FROM announcement_messages m LEFT JOIN announcement_deliveries d ON d.source_message_id = m.source_message_id
           GROUP BY m.source_message_id ORDER BY m.created_at DESC LIMIT 20"""
    ).fetchall()
    return [{"source_message_id": r[0], "content": r[1], "created_at": r[2], "total": r[3], "sent": r[4] or 0} for r in rows]


@app.patch("/api/admin/announcements/{source_message_id}")
async def api_admin_announcement_edit(source_message_id: str, payload: AnnouncementEditModel,
                                       user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    if not source_message_id.startswith("dashboard-"):
        raise HTTPException(status_code=400, detail="Los anuncios del canal fuente se editan directamente en Discord.")
    if not db.execute("SELECT 1 FROM announcement_messages WHERE source_message_id = ?", (source_message_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Anuncio no encontrado.")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.execute("UPDATE announcement_messages SET content = ? WHERE source_message_id = ?", (payload.content, source_message_id))
    rows = db.execute(
        "SELECT guild_id, channel_id, message_id FROM announcement_deliveries WHERE source_message_id = ? AND status = 'sent'",
        (source_message_id,),
    ).fetchall()
    edited = 0
    failed = 0
    for guild_id, channel_id, message_id in rows:
        error = await _discord_bot_edit(int(channel_id), int(message_id), payload.content)
        if error:
            failed += 1
            db.execute("UPDATE announcement_deliveries SET status='failed', error=?, updated_at=? WHERE source_message_id=? AND guild_id=?", (error, now, source_message_id, guild_id))
        else:
            edited += 1
            db.execute("UPDATE announcement_deliveries SET error=NULL, updated_at=? WHERE source_message_id=? AND guild_id=?", (now, source_message_id, guild_id))
    db.commit()
    return {"status": "success", "edited": edited, "failed": failed}

@app.post("/api/admin/guilds/{guild_id}/leave")
async def api_admin_leave_guild(guild_id: int, user = Depends(get_current_user)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
        
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT}
        async with session.delete(f"https://discord.com/api/v10/users/@me/guilds/{guild_id}", headers=headers) as res:
            if res.status != 204:
                body = await res.text()
                logger.error(f"Failed to leave guild {guild_id}: {body}")
                raise HTTPException(status_code=res.status, detail="Error de API de Discord al forzar salida.")
                
    return {"status": "success", "message": f"El bot ha salido correctamente del servidor {guild_id}."}

@app.post("/api/admin/guilds/{guild_id}/create-invite")
async def api_admin_create_guild_invite(guild_id: int, user = Depends(get_current_user)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado. Solo el superpropietario puede crear invitaciones remotas.")

    if not DISCORD_TOKEN:
        raise HTTPException(status_code=500, detail="Token de Discord no configurado.")

    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "User-Agent": DISCORD_USER_AGENT,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        # Try fetching existing guild invites first
        try:
            async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/invites", headers=headers) as res:
                if res.status == 200:
                    invites = await res.json()
                    if isinstance(invites, list) and len(invites) > 0:
                        for inv in invites:
                            code = inv.get("code")
                            if code:
                                return {
                                    "status": "success",
                                    "code": code,
                                    "url": f"https://discord.gg/{code}",
                                    "channel_id": inv.get("channel", {}).get("id"),
                                    "source": "existing"
                                }
        except Exception:
            pass

        # Fetch guild channels
        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers) as res:
            if res.status != 200:
                body = await res.text()
                logger.error(f"Error fetching channels for guild {guild_id}: {body}")
                raise HTTPException(status_code=res.status, detail="No se pudieron obtener los canales del servidor.")
            channels = await res.json()

        if not isinstance(channels, list):
            raise HTTPException(status_code=400, detail="Respuesta de canales inválida.")

        text_channels = [c for c in channels if c.get("type") in (0, 5)]
        if not text_channels:
            raise HTTPException(status_code=404, detail="No se encontraron canales de texto en este servidor.")

        last_error = None
        for ch in text_channels:
            ch_id = ch.get("id")
            payload = {
                "max_age": 86400,
                "max_uses": 0,
                "temporary": False,
                "unique": False
            }
            async with session.post(f"https://discord.com/api/v10/channels/{ch_id}/invites", headers=headers, json=payload) as inv_res:
                if inv_res.status in (200, 201):
                    inv_data = await inv_res.json()
                    code = inv_data.get("code")
                    if code:
                        return {
                            "status": "success",
                            "code": code,
                            "url": f"https://discord.gg/{code}",
                            "channel_id": ch_id,
                            "source": "created"
                        }
                else:
                    last_error = await inv_res.text()

        raise HTTPException(
            status_code=400,
            detail=f"No se pudo generar la invitación. El bot podría carecer del permiso 'Crear invitación' (CREATE_INSTANT_INVITE). Error: {last_error or 'Desconocido'}"
        )

# --- STATS LEADERBOARD ENDPOINTS ---

@app.get("/api/guilds/{guild_id}/leaderboard")
async def get_leaderboard(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_member(user, guild_id)
    cursor = db.cursor()
    cursor.execute(
        """SELECT user_id, level, xp, weekly_xp 
           FROM guild_levels 
           WHERE guild_id = ? 
           ORDER BY level DESC, xp DESC 
           LIMIT 20""",
        (guild_id,)
    )
    rows = cursor.fetchall()
    leaderboard = []
    for rank, row in enumerate(rows, start=1):
        leaderboard.append({
            "rank": rank,
            "user_id": str(row["user_id"]),
            "level": row["level"],
            "xp": row["xp"],
            "weekly_xp": row["weekly_xp"]
        })
    return {"guild_id": str(guild_id), "leaderboard": leaderboard}

@app.get("/api/guilds/{guild_id}/invites")
async def get_invites_leaderboard(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_member(user, guild_id)
    cursor = db.cursor()
    cursor.execute(
        """SELECT inviter_id, COUNT(*) as invite_count 
           FROM invite_tracker 
           WHERE guild_id = ? 
           GROUP BY inviter_id 
           ORDER BY invite_count DESC 
           LIMIT 20""",
        (guild_id,)
    )
    rows = cursor.fetchall()
    leaderboard = []
    for rank, row in enumerate(rows, start=1):
        leaderboard.append({
            "rank": rank,
            "inviter_id": str(row["inviter_id"]),
            "invite_count": row["invite_count"]
        })
    return {"guild_id": str(guild_id), "leaderboard": leaderboard}


@app.get("/api/guilds/{guild_id}/economy")
async def get_economy_overview(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    """Read-only economy ranking and shop data for members, staff and owners."""
    await require_guild_member(user, guild_id)
    cursor = db.cursor()
    cursor.execute(
        """SELECT user_id, balance, bank, balance + bank AS total
           FROM guild_economy WHERE guild_id = ? ORDER BY total DESC LIMIT 25""",
        (guild_id,),
    )
    ranking = [{"user_id": str(r[0]), "balance": r[1] or 0, "bank": r[2] or 0, "total": r[3] or 0} for r in cursor.fetchall()]
    cursor.execute("SELECT item_name, price, description FROM guild_shop WHERE guild_id = ? ORDER BY price ASC, item_name ASC LIMIT 100", (guild_id,))
    shop = [{"item_name": r[0], "price": r[1] or 0, "description": r[2] or ""} for r in cursor.fetchall()]
    return {"guild_id": str(guild_id), "ranking": ranking, "shop": shop}

# --- AUTOMATED WEBHOOKS ---

def _valid_hmac_webhook(payload: bytes, signature: str | None, secret: str | None) -> bool:
    if not secret or not signature:
        return False
    supplied = signature.strip()
    if supplied.startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def _valid_stripe_signature(payload: bytes, header: str | None) -> bool:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret or not header:
        return False
    parts = {}
    for item in header.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            parts.setdefault(key.strip(), []).append(value.strip())
    try:
        timestamp = int((parts.get("t") or ["0"])[0])
    except ValueError:
        return False
    if abs(time.time() - timestamp) > 300:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(sig, expected) for sig in parts.get("v1", []))


def _claim_webhook_event(db: sqlite3.Connection, provider: str, event_id: str | None) -> bool:
    """Claim an event once so provider retries cannot grant Premium repeatedly."""
    if not event_id:
        return True
    cursor = db.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO webhook_events (provider, event_id, received_at) VALUES (?, ?, ?)",
        (provider, str(event_id), datetime.datetime.now().isoformat()),
    )
    db.commit()
    return cursor.rowcount == 1


def _payment_fields(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        result = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("name") or item.get("label")
            if key:
                result[str(key)] = item.get("value")
        return result
    return {}


def _stripe_plan(session: dict, metadata: dict) -> str:
    raw_plan = str(metadata.get("plan") or "").strip().lower()
    if raw_plan in premium_lib.PLANS:
        return premium_lib.normalize_plan(raw_plan)
    amount = session.get("amount_subtotal") or session.get("amount_total")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    amount_plans = {
        int(os.environ.get("STRIPE_MONTHLY_AMOUNT_CENTS", "500")): "monthly",
        int(os.environ.get("STRIPE_YEARLY_AMOUNT_CENTS", "5000")): "yearly",
        int(os.environ.get("STRIPE_LIFETIME_AMOUNT_CENTS", "20000")): "lifetime",
    }
    return amount_plans.get(amount, "monthly")

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: sqlite3.Connection = Depends(get_db)):
    payload = await request.body()
    if not _valid_stripe_signature(payload, request.headers.get("stripe-signature")):
        raise HTTPException(status_code=401, detail="Webhook no autorizado")
    try:
        event = json.loads(payload)
        event_type = event.get("type")
        if not _claim_webhook_event(db, "stripe", event.get("id")):
            return {"status": "duplicate"}
        
        if event_type in ["checkout.session.completed", "invoice.payment_succeeded"]:
            session = event.get("data", {}).get("object", {})
            metadata = dict(session.get("metadata") or {})
            for key, value in _payment_fields(session.get("custom_fields")).items():
                metadata.setdefault(key, value)
            user_id = metadata.get("discord_user_id")
            guild_id = metadata.get("discord_guild_id")
            subscription_id = session.get("subscription")
            if event_type == "invoice.payment_succeeded" and subscription_id and not (user_id or guild_id):
                cursor = db.cursor()
                cursor.execute(
                    "SELECT user_id, guild_id, plan FROM premium_subscriptions WHERE subscription_id = ?",
                    (str(subscription_id),),
                )
                subscription = cursor.fetchone()
                if subscription:
                    user_id = subscription[0]
                    guild_id = subscription[1]
                    metadata["plan"] = subscription[2]
            
            cursor = db.cursor()
            plan = _stripe_plan(session, metadata)
            if user_id:
                rec = premium_lib.grant_user_sync(db, int(user_id), plan)
                logger.info(f"💳 Stripe webhook: Premium {rec['plan']} for User {user_id}")
            if guild_id:
                rec = premium_lib.grant_guild_sync(db, int(guild_id), plan)
                logger.info(f"💳 Stripe webhook: Premium {rec['plan']} for Server {guild_id}")
            if subscription_id and (user_id or guild_id):
                cursor.execute(
                    "INSERT INTO premium_subscriptions (subscription_id, user_id, guild_id, plan, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(subscription_id) DO UPDATE SET user_id = excluded.user_id, guild_id = excluded.guild_id, plan = excluded.plan",
                    (str(subscription_id), int(user_id) if user_id else None, int(guild_id) if guild_id else None, plan, datetime.datetime.now().isoformat()),
                )
                db.commit()
                
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling Stripe webhook: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhooks/sellix")
async def sellix_webhook(request: Request, db: sqlite3.Connection = Depends(get_db)):
    payload = await request.body()
    if not _valid_hmac_webhook(payload, request.headers.get("x-sellix-signature"), os.environ.get("SELLIX_WEBHOOK_SECRET")):
        raise HTTPException(status_code=401, detail="Webhook no autorizado")
    try:
        data = json.loads(payload)
        event = str(data.get("event") or request.headers.get("x-sellix-event") or "").lower()
        event_id = data.get("id") or request.headers.get("x-sellix-event-id")
        if not _claim_webhook_event(db, "sellix", event_id):
            return {"status": "duplicate"}
        
        if event in {"order.paid", "order:paid", "order_paid"}:
            payload_data = data.get("data") or {}
            order_data = payload_data.get("order") if isinstance(payload_data, dict) else {}
            order_data = order_data if isinstance(order_data, dict) else payload_data
            custom_fields = _payment_fields(
                order_data.get("custom_fields")
                or order_data.get("metadata")
                or data.get("custom_fields")
                or data.get("metadata")
            )
            user_id = custom_fields.get("discord_user_id")
            guild_id = custom_fields.get("discord_guild_id")
            
            plan = custom_fields.get("plan") or "monthly"
            if user_id:
                rec = premium_lib.grant_user_sync(db, int(user_id), plan)
                logger.info(f"🛍️ Sellix webhook: Premium {rec['plan']} for User {user_id}")
            if guild_id:
                rec = premium_lib.grant_guild_sync(db, int(guild_id), plan)
                logger.info(f"🛍️ Sellix webhook: Premium {rec['plan']} for Server {guild_id}")
                
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling Sellix webhook: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhooks/discord")
async def discord_entitlements_webhook(request: Request, db: sqlite3.Connection = Depends(get_db)):
    payload = await request.body()
    expected_secret = os.environ.get("DISCORD_ENTITLEMENTS_WEBHOOK_SECRET")
    supplied_secret = request.headers.get("x-dabot-webhook-secret")
    if not expected_secret or not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
        raise HTTPException(status_code=401, detail="Webhook no autorizado")
    try:
        data = json.loads(payload)
        event_type = data.get("type")
        
        entitlement = data.get("data", {}).get("entitlement", {})
        if not entitlement:
            entitlement = data.get("entitlement", {})
            
        if event_type in ["ENTITLEMENT_CREATE", 4]:
            user_id = entitlement.get("user_id")
            guild_id = entitlement.get("guild_id")
            
            cursor = db.cursor()
            now = datetime.datetime.now()
            expires = now + datetime.timedelta(days=32)
            
            if user_id:
                user_id = int(user_id)
                cursor.execute(
                    "INSERT INTO premium_users (user_id, tier, activated_at, expires_at) VALUES (?, 'premium', ?, ?) ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
                    (user_id, now.isoformat(), expires.isoformat())
                )
                db.commit()
                logger.info(f"👾 Discord native entitlement: Premium granted to User {user_id}")
                
            if guild_id:
                guild_id = int(guild_id)
                cursor.execute(
                    "INSERT INTO premium_guilds (guild_id, activated_at, expires_at) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET expires_at = excluded.expires_at",
                    (guild_id, now.isoformat(), expires.isoformat())
                )
                db.commit()
                logger.info(f"👾 Discord native entitlement: Premium granted to Server {guild_id}")
                
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling Discord entitlement webhook: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# --- OWNER DATABASE BACKUP AND SERVER BACKUP API ENDPOINTS ---
@app.get("/api/admin/backup/download")
async def download_db_backup(user = Depends(get_current_user)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado. Solo para el Super Owner.")
    
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Base de datos no encontrada.")
        
    os.makedirs(BACKUP_ROOT, mode=0o700, exist_ok=True)
    backup_file = os.path.join(BACKUP_ROOT, f"dashboard-{secrets.token_hex(8)}.db")
    try:
        conn = sqlite3.connect(DB_PATH)
        bck = sqlite3.connect(backup_file)
        with bck:
            conn.backup(bck)
        bck.close()
        conn.close()
        os.chmod(backup_file, 0o600)
        return FileResponse(backup_file, filename="dabot.db", media_type="application/octet-stream")
    except Exception as e:
        logger.error(f"Error generating DB backup: {e}")
        raise HTTPException(status_code=500, detail=f"Error al generar backup: {str(e)}")

@app.get("/api/admin/live-logs")
async def get_admin_live_logs(
    lines: int = 150,
    user = Depends(get_current_user),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Acceso denegado: Requiere permisos de Superusuario.")
    
    lines = min(max(lines, 10), 1000)
    log_dir = "logs"
    if not os.path.exists(log_dir):
        return {"filename": None, "lines": [], "total_lines": 0, "returned_lines": 0}
    
    files = [f for f in os.listdir(log_dir) if f.startswith("session_") and f.endswith(".txt")]
    if not files:
        return {"filename": None, "lines": [], "total_lines": 0, "returned_lines": 0}
    
    files.sort(reverse=True)
    latest_file = os.path.join(log_dir, files[0])
    
    try:
        with open(latest_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            tail = [l.rstrip("\r\n") for l in all_lines[-lines:]]
        return {
            "filename": files[0],
            "total_lines": len(all_lines),
            "returned_lines": len(tail),
            "lines": tail
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading logs: {e}")


async def restore_guild_backup_task(guild_id: int, backup_data: dict):
    headers = {'Authorization': f'Bot {DISCORD_TOKEN}'}
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        # 1. Fetch current channels and roles to map what to delete later
        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers) as res:
            old_channels = await res.json() if res.status == 200 else []
            
        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=headers) as res:
            old_roles = await res.json() if res.status == 200 else []
            
        # 2. Recreate Roles (except @everyone and managed)
        role_map = {} # {old_id: new_id}
        backup_roles = backup_data.get("roles", [])
        for r in backup_roles:
            payload = {
                "name": r["name"],
                "permissions": r["permissions"],
                "color": r["color"],
                "hoist": r["hoist"],
                "mentionable": r["mentionable"]
            }
            async with session.post(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=headers, json=payload) as res:
                if res.status in (200, 201):
                    new_role = await res.json()
                    role_map[r["id"]] = new_role["id"]
            await asyncio.sleep(0.5)
            
        # 3. Recreate Categories (type = 4)
        category_map = {} # {old_id: new_id}
        backup_channels = backup_data.get("channels", [])
        categories = [c for c in backup_channels if c["type"] == 4]
        for cat in categories:
            payload = {
                "name": cat["name"],
                "type": 4,
                "position": cat.get("position", 0)
            }
            async with session.post(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers, json=payload) as res:
                if res.status in (200, 201):
                    new_cat = await res.json()
                    category_map[cat["id"]] = new_cat["id"]
            await asyncio.sleep(0.5)
            
        # 4. Recreate Text and Voice Channels (type = 0, 2)
        non_categories = [c for c in backup_channels if c["type"] != 4]
        non_categories.sort(key=lambda x: x.get("position", 0))
        
        created_channel_ids = []
        for ch in non_categories:
            parent_id = category_map.get(ch.get("parent_id")) if ch.get("parent_id") else None
            
            # Map permission overwrites
            overwrites = []
            for ow in ch.get("permission_overwrites", []):
                mapped_id = role_map.get(ow["id"]) if ow["type"] == 0 else ow["id"]
                if mapped_id or ow["id"] == str(guild_id):
                    ow_id = mapped_id if ow["id"] != str(guild_id) else str(guild_id)
                    overwrites.append({
                        "id": ow_id,
                        "type": ow["type"],
                        "allow": ow["allow"],
                        "deny": ow["deny"]
                    })
                    
            payload = {
                "name": ch["name"],
                "type": ch["type"],
                "topic": ch.get("topic", ""),
                "position": ch.get("position", 0),
                "parent_id": parent_id,
                "permission_overwrites": overwrites
            }
            async with session.post(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers, json=payload) as res:
                if res.status in (200, 201):
                    new_ch = await res.json()
                    created_channel_ids.append(new_ch["id"])
            await asyncio.sleep(0.5)
            
        # 5. Delete old channels that were not newly created
        for old_ch in old_channels:
            if old_ch["id"] not in created_channel_ids:
                async with session.delete(f"https://discord.com/api/v10/channels/{old_ch['id']}", headers=headers) as res:
                    pass
                await asyncio.sleep(0.5)

BACKUP_ROOT = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")


def _is_premium_guild(db, guild_id, user_id) -> bool:
    if user_id == SUPER_OWNER_ID:
        return True
    rec = premium_lib.guild_record_sync(db, guild_id)
    return bool(rec and rec.get("active"))


@app.get("/api/guilds/{guild_id}/backup")
async def get_guild_backup_info(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="No autorizado.")
    cursor = db.cursor()
    cursor.execute(
        "SELECT id, created_at, status, kind, backup_data FROM server_backups WHERE guild_id = ? ORDER BY id DESC LIMIT 8",
        (guild_id,),
    )
    rows = cursor.fetchall()
    items = []
    for r in rows:
        stats = {}
        try:
            stats = json.loads(r[4] or "{}")
            if isinstance(stats, dict) and "stats" in stats:
                stats = stats["stats"]
        except Exception:
            stats = {}
        items.append({
            "id": r[0],
            "created_at": r[1],
            "status": r[2] or "ready",
            "kind": r[3] or "structure",
            "stats": stats if isinstance(stats, dict) else {},
        })
    latest = items[0] if items else None
    return {
        "is_premium": _is_premium_guild(db, guild_id, user["user_id"]),
        "has_backup": bool(items),
        "created_at": latest["created_at"] if latest else None,
        "status": latest["status"] if latest else None,
        "kind": latest["kind"] if latest else None,
        "backups": items,
    }


async def _run_full_backup(backup_id: int, guild_id: int, message_limit: int):
    folder = os.path.join(BACKUP_ROOT, str(guild_id), str(backup_id))
    os.makedirs(os.path.join(folder, "files"), exist_ok=True)
    os.makedirs(os.path.join(folder, "messages"), exist_ok=True)
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
    stats = {"channels": 0, "roles": 0, "messages": 0, "files": 0, "error": None}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}", headers=headers) as res:
                guild = await res.json() if res.status == 200 else {}
            async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers) as res:
                channels = await res.json() if res.status == 200 else []
            async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=headers) as res:
                roles = await res.json() if res.status == 200 else []
            stats["channels"] = len(channels) if isinstance(channels, list) else 0
            stats["roles"] = len(roles) if isinstance(roles, list) else 0
            structure = {
                "guild": {"id": str(guild_id), "name": guild.get("name"), "icon": guild.get("icon")},
                "roles": roles if isinstance(roles, list) else [],
                "channels": channels if isinstance(channels, list) else [],
            }
            with open(os.path.join(folder, "structure.json"), "w", encoding="utf-8") as f:
                json.dump(structure, f, ensure_ascii=False)
            text_types = {0, 5, 15}
            for ch in structure["channels"]:
                if ch.get("type") not in text_types:
                    continue
                collected = []
                before = None
                remaining = message_limit
                while remaining > 0:
                    batch = min(100, remaining)
                    url = f"https://discord.com/api/v10/channels/{ch['id']}/messages?limit={batch}"
                    if before:
                        url += f"&before={before}"
                    async with session.get(url, headers=headers) as res:
                        if res.status != 200:
                            break
                        msgs = await res.json()
                    if not msgs:
                        break
                    for m in msgs:
                        collected.append({
                            "id": m.get("id"),
                            "author": {
                                "id": (m.get("author") or {}).get("id"),
                                "username": (m.get("author") or {}).get("username"),
                            },
                            "content": m.get("content"),
                            "timestamp": m.get("timestamp"),
                            "attachments": [
                                {"id": a.get("id"), "filename": a.get("filename"), "url": a.get("url"), "size": a.get("size")}
                                for a in (m.get("attachments") or [])
                            ],
                            "embeds": m.get("embeds") or [],
                        })
                        for a in m.get("attachments") or []:
                            size = int(a.get("size") or 0)
                            if size > 8 * 1024 * 1024:
                                continue
                            url_a = a.get("url") or a.get("proxy_url")
                            if not url_a:
                                continue
                            try:
                                async with session.get(url_a) as ar:
                                    if ar.status == 200:
                                        data = await ar.read()
                                        fname = f"{m.get('id')}_{a.get('filename') or 'file'}"
                                        fname = "".join(c if c.isalnum() or c in "._-" else "_" for c in fname)[:120]
                                        with open(os.path.join(folder, "files", fname), "wb") as out:
                                            out.write(data)
                                        stats["files"] += 1
                            except Exception:
                                pass
                    remaining -= len(msgs)
                    before = msgs[-1]["id"]
                    if len(msgs) < batch:
                        break
                    await asyncio.sleep(0.35)
                stats["messages"] += len(collected)
                with open(os.path.join(folder, "messages", f"{ch['id']}.json"), "w", encoding="utf-8") as f:
                    json.dump({"channel": ch["id"], "name": ch.get("name"), "messages": collected}, f, ensure_ascii=False)
        payload = {"folder": folder, "stats": stats, "roles": structure["roles"], "channels": structure["channels"]}
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE server_backups SET backup_data = ?, status = 'ready', kind = 'full' WHERE id = ?",
            (json.dumps(payload), backup_id),
        )
        conn.commit()
        conn.close()
        logger.info("full backup %s guild %s done %s", backup_id, guild_id, stats)
    except Exception as e:
        logger.error("full backup failed: %s", e)
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE server_backups SET status = 'error', backup_data = ? WHERE id = ?",
                (json.dumps({"stats": stats, "error": str(e)}), backup_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


@app.post("/api/guilds/{guild_id}/backup/create")
async def create_guild_backup(guild_id: int, background_tasks: BackgroundTasks, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="No autorizado.")
    if not _is_premium_guild(db, guild_id, user["user_id"]):
        raise HTTPException(status_code=403, detail="La copia de seguridad completa es Premium.")
    now = datetime.datetime.now().isoformat()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO server_backups (guild_id, backup_data, created_by, created_at, status, kind) VALUES (?, ?, ?, ?, 'running', 'full')",
        (guild_id, json.dumps({"stats": {"note": "en curso"}}), int(user["user_id"]), now),
    )
    backup_id = cursor.lastrowid
    db.commit()
    limit = 400 if _is_premium_guild(db, guild_id, user["user_id"]) else 50
    background_tasks.add_task(_run_full_backup, backup_id, guild_id, limit)
    return {"status": "running", "id": backup_id, "created_at": now, "message": "Copia completa en segundo plano (canales, roles, mensajes y archivos)."}


@app.get("/api/guilds/{guild_id}/backup/{backup_id}/download")
async def download_guild_backup_zip(guild_id: int, backup_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="No autorizado.")
    folder = os.path.join(BACKUP_ROOT, str(guild_id), str(backup_id))
    if not os.path.isdir(folder):
        raise HTTPException(status_code=404, detail="No hay archivos de esta copia.")
    zip_path = os.path.join(BACKUP_ROOT, str(guild_id), f"{backup_id}.zip")
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, folder))
    return FileResponse(zip_path, filename=f"dabot-backup-{guild_id}-{backup_id}.zip")


async def _discord_try(method: str, path: str, json_body=None, retries: int = 3):
    last = None
    for attempt in range(max(1, retries)):
        try:
            return True, await discord_bot(method, path, json_body)
        except HTTPException as e:
            last = e
            detail = str(e.detail or "")
            if "429" in detail and attempt < retries - 1:
                await asyncio.sleep(1.2 * (attempt + 1))
                continue
            logger.warning("discord %s %s failed: %s", method, path, detail[:240])
            return False, None
        except Exception as e:
            last = e
            logger.warning("discord %s %s error: %s", method, path, e)
            if attempt < retries - 1:
                await asyncio.sleep(0.6)
                continue
            return False, None
    return False, last


async def _wipe_guild_discord(guild_id: int) -> dict:
    """Delete every channel and deletable role. Creates a staging channel first so Discord is never empty."""
    staging = None
    ok, created = await _discord_try("POST", f"/guilds/{guild_id}/channels", {"name": "dabot-rebuild", "type": 0})
    if ok and created:
        staging = str(created.get("id") or "")
    if staging:
        g = None
        ok_g, g = await _discord_try("GET", f"/guilds/{guild_id}")
        if ok_g and g:
            patch = {"system_channel_id": staging}
            if g.get("rules_channel_id"):
                patch["rules_channel_id"] = staging
            if g.get("public_updates_channel_id"):
                patch["public_updates_channel_id"] = staging
            await _discord_try("PATCH", f"/guilds/{guild_id}", patch)
    ok, channels = await _discord_try("GET", f"/guilds/{guild_id}/channels")
    channels = channels if ok and isinstance(channels, list) else []
    deleted_ch = 0
    # Children first (not categories), then categories. Never delete the staging channel until the caller says so.
    ordered = [c for c in channels if int(c.get("type") or 0) != 4] + [c for c in channels if int(c.get("type") or 0) == 4]
    for ch in ordered:
        cid = str(ch.get("id") or "")
        if not cid or cid == staging:
            continue
        ok, _ = await _discord_try("DELETE", f"/channels/{cid}", retries=4)
        if ok:
            deleted_ch += 1
        await asyncio.sleep(0.28)
    ok, roles = await _discord_try("GET", f"/guilds/{guild_id}/roles")
    roles = roles if ok and isinstance(roles, list) else []
    deleted_roles = 0
    for role in sorted(roles, key=lambda r: int(r.get("position") or 0), reverse=True):
        rid = str(role.get("id") or "")
        if not rid or rid == str(guild_id) or role.get("managed"):
            continue
        ok, _ = await _discord_try("DELETE", f"/guilds/{guild_id}/roles/{rid}", retries=3)
        if ok:
            deleted_roles += 1
        await asyncio.sleep(0.28)
    logger.info("wipe guild %s: channels=%s roles=%s staging=%s", guild_id, deleted_ch, deleted_roles, staging)
    return {"channels": deleted_ch, "roles": deleted_roles, "staging": staging}


class TemplateApplyPayload(BaseModel):
    template_id: str
    lang: str = "es"
    wipe: bool = True


@app.get("/api/templates")
async def api_list_templates(lang: str = "es"):
    from utils.server_templates import list_templates
    return {"templates": list_templates(lang), "lang": "en" if str(lang).lower().startswith("en") else "es"}


@app.post("/api/guilds/{guild_id}/templates/apply")
async def api_apply_template(guild_id: int, payload: TemplateApplyPayload, background_tasks: BackgroundTasks, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    from utils.server_templates import resolve_template
    tpl = resolve_template(payload.template_id, payload.lang or "es")
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla desconocida")
    wipe = payload.wipe is not False
    background_tasks.add_task(_apply_template_rest, guild_id, tpl, wipe)
    msg = (
        f"Reconstruyendo el servidor con **{tpl['name']}**: se borran canales y roles actuales y se monta la plantilla (logs, verify, tickets)."
        if wipe else
        f"Aplicando plantilla {tpl['name']} sin borrar lo existente."
    )
    return {"status": "running", "message": msg}


async def _apply_template_rest(guild_id: int, tpl: dict, wipe: bool = True):
    from utils.server_templates import save_template_config
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
    VIEW, SEND, HISTORY = 1 << 10, 1 << 11, 1 << 16
    TTS, MANAGE_MSG, EMBED, ATTACH = 1 << 12, 1 << 13, 1 << 14, 1 << 15
    REACT = 1 << 6
    USE_APPS = 1 << 31
    PUB_THREAD, PRIV_THREAD, SEND_THREAD = 1 << 35, 1 << 36, 1 << 38
    READ_ONLY_DENY = SEND | TTS | PUB_THREAD | PRIV_THREAD | SEND_THREAD | ATTACH | EMBED | USE_APPS
    READ_ONLY_ALLOW = VIEW | HISTORY | REACT
    TALK_ALLOW = VIEW | SEND | HISTORY | EMBED | ATTACH | REACT | USE_APPS
    STAFF_ALLOW = TALK_ALLOW | MANAGE_MSG | PUB_THREAD | SEND_THREAD
    slots = {}
    staff_ids = []
    staff_names = []
    verified_id = unverified_id = None
    staging_id = None
    if wipe:
        try:
            wiped = await _wipe_guild_discord(guild_id)
            staging_id = wiped.get("staging")
            logger.info("template wipe %s -> %s", guild_id, wiped)
        except Exception as e:
            logger.warning("template wipe failed %s: %s", guild_id, e)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=headers) as res:
            existing_roles = await res.json() if res.status == 200 else []
        names = {r.get("name"): r for r in existing_roles if isinstance(r, dict)}
        for spec in tpl["roles"]:
            role = names.get(spec["name"])
            if not role:
                async with session.post(
                    f"https://discord.com/api/v10/guilds/{guild_id}/roles",
                    headers=headers,
                    json={"name": spec["name"], "color": spec.get("color") or 0, "hoist": spec.get("hoist") or False, "permissions": str(spec.get("permissions") or "0")},
                ) as res:
                    if res.status in (200, 201):
                        role = await res.json()
                        names[spec["name"]] = role
                await asyncio.sleep(0.45)
            if not role:
                continue
            tags = spec.get("tags") or []
            if "staff" in tags:
                staff_ids.append(str(role["id"]))
                staff_names.append(spec["name"])
            if "verified" in tags:
                verified_id = str(role["id"])
                slots["role.verified"] = int(role["id"])
            if "unverified" in tags:
                unverified_id = str(role["id"])
                slots["role.unverified"] = int(role["id"])

        def cat_overwrites(access: str, slot: str | None = None):
            everyone = str(guild_id)
            ow = []
            if access == "staff":
                ow = [{"id": everyone, "type": 0, "allow": "0", "deny": str(VIEW)}]
            elif access == "info":
                ow = [{"id": everyone, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)}]
                if verified_id:
                    ow.append({"id": verified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
                if unverified_id:
                    ow.append({"id": unverified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
            elif access == "verify":
                ow = [{"id": everyone, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)}]
                if unverified_id:
                    ow.append({"id": unverified_id, "type": 0, "allow": str(TALK_ALLOW), "deny": "0"})
            elif access == "tickets":
                ow = [{"id": everyone, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)}]
                if verified_id:
                    ow.append({"id": verified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
                if unverified_id:
                    ow.append({"id": unverified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
            else:
                ow = [{"id": everyone, "type": 0, "allow": "0", "deny": str(VIEW)}]
                if verified_id:
                    ow.append({"id": verified_id, "type": 0, "allow": str(TALK_ALLOW), "deny": "0"})
            if slot == "commands":
                ow = [{"id": everyone, "type": 0, "allow": str(TALK_ALLOW), "deny": "0"}]
                if verified_id:
                    ow.append({"id": verified_id, "type": 0, "allow": str(TALK_ALLOW), "deny": "0"})
            elif slot == "autorole":
                ow = [{"id": everyone, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)}]
                if verified_id:
                    ow.append({"id": verified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
            elif slot in ("rules", "announcements", "welcome", "levels"):
                ow = [{"id": everyone, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)}]
                if verified_id:
                    ow.append({"id": verified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
                if unverified_id:
                    ow.append({"id": unverified_id, "type": 0, "allow": str(READ_ONLY_ALLOW), "deny": str(READ_ONLY_DENY)})
            for sid in staff_ids:
                ow.append({"id": sid, "type": 0, "allow": str(STAFF_ALLOW), "deny": "0"})
            return ow

        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers) as res:
            existing_ch = await res.json() if res.status == 200 else []
        existing_names = {c.get("name") for c in existing_ch if isinstance(c, dict)}
        for cat in tpl["categories"]:
            access = cat.get("access") or ("staff" if cat.get("staff_only") else "verified")
            parent_id = None
            for c in existing_ch:
                if c.get("type") == 4 and c.get("name") == cat["name"]:
                    parent_id = c["id"]
                    break
            if not parent_id:
                payload = {"name": cat["name"], "type": 4, "permission_overwrites": cat_overwrites(access)}
                async with session.post(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers, json=payload) as res:
                    if res.status in (200, 201):
                        created = await res.json()
                        parent_id = created.get("id")
                        existing_ch.append(created)
                await asyncio.sleep(0.45)
            for ch in cat["channels"]:
                slug = ch["name"].lower().replace(" ", "-")
                if slug in existing_names or ch["name"] in existing_names:
                    # still map slot if we can
                    for c in existing_ch:
                        if c.get("name") in (slug, ch["name"]) and ch.get("slot") and c.get("id"):
                            slots[ch["slot"]] = int(c["id"])
                    continue
                body = {
                    "name": ch["name"],
                    "type": ch.get("type") or 0,
                    "parent_id": parent_id,
                    "topic": (ch.get("topic") or "")[:1024],
                    "permission_overwrites": cat_overwrites(access, ch.get("slot")),
                }
                async with session.post(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers, json=body) as res:
                    if res.status in (200, 201):
                        created = await res.json()
                        existing_names.add(slug)
                        existing_ch.append(created)
                        if ch.get("slot") and created.get("id"):
                            slots[ch["slot"]] = int(created["id"])
                await asyncio.sleep(0.45)
        try:
            save_template_config(guild_id, slots, tpl, staff_names)
        except Exception as e:
            logger.warning("template config: %s", e)
        lang = tpl.get("lang") or "es"
        url = f"{DASHBOARD_URL}/verify/{guild_id}"
        posts = []
        from utils.template_posts import (
            announcements_payload,
            catalog_payloads,
            commands_payload,
            economy_payload,
            howto_buy_payload,
            levels_payload,
            rules_payloads,
            verify_payload,
            welcome_payload,
        )
        if slots.get("rules"):
            for emb in rules_payloads(tpl, lang, slots):
                posts.append((slots["rules"], {"embeds": [emb]}))
        if slots.get("verify"):
            posts.append((slots["verify"], {
                "embeds": [verify_payload(tpl, lang, slots, guild_id)],
                "components": [{"type": 1, "components": [{"type": 2, "style": 5, "label": "dabot.davito.es/verify", "url": url}]}],
            }))
        if slots.get("tickets"):
            log_url = f"{DASHBOARD_URL}/dashboard?guild={guild_id}"
            log_mention = f"<#{slots['logs.tickets']}>" if slots.get("logs.tickets") else "dabot.davito.es"
            extra = f"Cada ticket se registra en {log_mention} con **nombre + enlace web**.\n{log_url}"
            from cogs.tickets import ticket_panel_payloads
            tickets_cfg = {
                "categories": tpl.get("ticket_categories") or None,
                "panel": tpl.get("ticket_panel") or {},
            }
            posts.append((slots["tickets"], {
                "embeds": ticket_panel_payloads(tickets_cfg, extra=extra)[:10],
                "components": _ticket_panel_components(tickets_cfg),
            }))
        if slots.get("logs.tickets"):
            log_url = f"{DASHBOARD_URL}/dashboard?guild={guild_id}"
            posts.append((slots["logs.tickets"], {
                "embeds": [{
                    "title": "🎫 Logs de tickets",
                    "description": (
                        "Aquí se publica **cada ticket** al abrirse y al cerrarse:\n"
                        "• Nombre del canal (`ticket-pedidos-…`)\n"
                        "• Tipo, usuario y canal\n"
                        f"• Enlace directo: {log_url}"
                    ),
                    "color": 0x00FF88,
                    "footer": {"text": "Dabot · dabot.davito.es"},
                }],
            }))
        if slots.get("logs.verification"):
            log_url = f"{DASHBOARD_URL}/dashboard?guild={guild_id}"
            posts.append((slots["logs.verification"], {
                "embeds": [{
                    "title": "🛡️ Logs de verificación",
                    "description": (
                        "Aquí se publica **cada verificación** de este servidor:\n"
                        "• Usuario, método y estado\n"
                        "• Riesgo de multicuenta\n"
                        "• Códigos de red `ip:` (exacta) y `net:` (misma subred). Nunca la IP en claro.\n"
                        f"• Listado: {log_url}"
                    ),
                    "color": 0x00FF88,
                    "footer": {"text": "Dabot · dabot.davito.es"},
                }],
            }))
        if slots.get("commands"):
            posts.append((slots["commands"], {"embeds": [commands_payload(tpl, lang, slots)]}))
        if slots.get("welcome"):
            posts.append((slots["welcome"], {"embeds": [welcome_payload(tpl, lang, slots)]}))
        if slots.get("levels"):
            posts.append((slots["levels"], {"embeds": [levels_payload(tpl, lang, slots)]}))
        if slots.get("announcements"):
            posts.append((slots["announcements"], {"embeds": [announcements_payload(tpl, lang, slots)]}))
        for slot, kind in (("economy", "main"), ("economy.top", "top"), ("economy.shop", "shop")):
            if slots.get(slot):
                posts.append((slots[slot], {"embeds": [economy_payload(tpl, lang, slots, kind)]}))
        if slots.get("catalog"):
            posts.append((slots["catalog"], {"embeds": catalog_payloads(tpl, lang, slots)[:10]}))
        if slots.get("howto"):
            posts.append((slots["howto"], {"embeds": [howto_buy_payload(tpl, lang, slots)]}))
        info_channel_ids = {int(slots[key]) for key in ("rules", "announcements", "welcome", "commands", "levels", "autorole") if slots.get(key)}
        for cid, body in posts:
            try:
                async with session.post(f"https://discord.com/api/v10/channels/{cid}/messages", headers=headers, json=body) as res:
                    if res.status not in (200, 201):
                        logger.warning("template post %s -> %s", cid, res.status)
                    elif int(cid) not in info_channel_ids:
                        posted = await res.json()
                        message_id = posted.get("id")
                        if message_id:
                            async with session.put(
                                f"https://discord.com/api/v10/channels/{cid}/pins/{message_id}",
                                headers=headers,
                            ) as pin_res:
                                if pin_res.status not in (200, 204):
                                    logger.warning("template pin %s/%s -> %s", cid, message_id, pin_res.status)
            except Exception as e:
                logger.warning("template post failed: %s", e)
        if staging_id:
            try:
                async with session.delete(f"https://discord.com/api/v10/channels/{staging_id}", headers=headers) as res:
                    if res.status not in (200, 204):
                        logger.warning("staging delete %s -> %s", staging_id, res.status)
            except Exception as e:
                logger.warning("staging delete failed: %s", e)
    logger.info("template %s applied to %s slots=%s", tpl["id"], guild_id, list(slots))


class NukePayload(BaseModel):
    confirm_name: str


@app.post("/api/guilds/{guild_id}/nuke")
async def api_nuke_guild(guild_id: int, payload: NukePayload, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    g = await discord_bot("GET", f"/guilds/{guild_id}")
    owner_id = int(g.get("owner_id") or 0)
    if user["user_id"] != SUPER_OWNER_ID and int(user["user_id"]) != owner_id:
        raise HTTPException(status_code=403, detail="Solo el dueño del servidor o el superusuario pueden nukear.")
    if (payload.confirm_name or "").strip() != (g.get("name") or ""):
        raise HTTPException(status_code=400, detail="El nombre del servidor no coincide.")
    background_tasks.add_task(_nuke_guild_rest, guild_id)
    return {"status": "running", "message": "Nuke en marcha: se borran canales y roles. En un rato quedará #general."}


async def _nuke_guild_rest(guild_id: int):
    wiped = await _wipe_guild_discord(guild_id)
    landing = wiped.get("staging")
    try:
        if landing:
            await _discord_try("PATCH", f"/channels/{landing}", {"name": "general"})
            await _discord_try("POST", f"/channels/{landing}/messages", {
                "content": "Servidor reiniciado. Aplica una plantilla de Dabot desde el panel (Plantillas) para montarlo de nuevo."
            })
        else:
            ok, created = await _discord_try("POST", f"/guilds/{guild_id}/channels", {"name": "general", "type": 0})
            landing = created.get("id") if ok and created else None
            if landing:
                await _discord_try("POST", f"/channels/{landing}/messages", {
                    "content": "Servidor reiniciado. Aplica una plantilla de Dabot desde el panel (Plantillas) para montarlo de nuevo."
                })
    except Exception as e:
        logger.warning("nuke landing: %s", e)
    logger.info("nuke done %s %s", guild_id, wiped)


@app.get("/api/guilds/{guild_id}/audit")
async def get_guild_audit(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db), type: str | None = None, limit: int = 50):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "view_infractions" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    limit = max(1, min(limit, 100))
    cursor = db.cursor()
    if type:
        cursor.execute(
            "SELECT id, event_type, actor_id, target_id, channel_id, summary, timestamp FROM audit_events WHERE guild_id = ? AND event_type = ? ORDER BY id DESC LIMIT ?",
            (guild_id, type, limit),
        )
    else:
        cursor.execute(
            "SELECT id, event_type, actor_id, target_id, channel_id, summary, timestamp FROM audit_events WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
            (guild_id, limit),
        )
    return {
        "events": [
            {
                "id": r[0],
                "type": r[1],
                "actor_id": str(r[2]) if r[2] else None,
                "target_id": str(r[3]) if r[3] else None,
                "channel_id": str(r[4]) if r[4] else None,
                "summary": r[5],
                "timestamp": r[6],
            }
            for r in cursor.fetchall()
        ]
    }

@app.post("/api/guilds/{guild_id}/backup/restore")
async def restore_guild_backup(guild_id: int, background_tasks: BackgroundTasks, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="No autorizado.")
        
    cursor = db.cursor()
    cursor.execute("SELECT 1 FROM premium_guilds WHERE guild_id = ?", (guild_id,))
    is_premium = cursor.fetchone() is not None
    if not is_premium and user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="La copia de seguridad es una función Premium.")
        
    cursor.execute("SELECT backup_data, status FROM server_backups WHERE guild_id = ? ORDER BY id DESC LIMIT 1", (guild_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No hay copias de seguridad creadas para este servidor.")
    if (row[1] or "") == "running":
        raise HTTPException(status_code=400, detail="La copia todavía se está generando.")
    backup_data = json.loads(row[0] or "{}")
    if "roles" not in backup_data and os.path.isdir(backup_data.get("folder") or ""):
        struct_path = os.path.join(backup_data["folder"], "structure.json")
        if os.path.isfile(struct_path):
            with open(struct_path, encoding="utf-8") as f:
                backup_data = {**backup_data, **json.load(f)}
    background_tasks.add_task(restore_guild_backup_task, guild_id, backup_data)
    
    return {"status": "success", "message": "Restauración iniciada en segundo plano."}

# --- LIVE BOT STATUS, USER RESOLVE, PANELS ---

_user_cache: dict[str, tuple[float, dict]] = {}
USER_CACHE_TTL = 600


async def resolve_discord_user(user_id: str) -> dict:
    cached = _user_cache.get(str(user_id))
    now = time.time()
    if cached and now - cached[0] < USER_CACHE_TTL:
        return cached[1]
    profile = {
        "id": str(user_id),
        "username": str(user_id),
        "global_name": None,
        "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"
    }
    if not DISCORD_TOKEN:
        return profile
    try:
        async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
            headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
            async with session.get(f"https://discord.com/api/v10/users/{user_id}", headers=headers) as res:
                if res.status == 200:
                    data = await res.json()
                    avatar = data.get("avatar")
                    uid = data["id"]
                    profile = {
                        "id": uid,
                        "username": data.get("username") or uid,
                        "global_name": data.get("global_name"),
                        "avatar_url": (
                            f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.png?size=64"
                            if avatar else "https://cdn.discordapp.com/embed/avatars/0.png"
                        )
                    }
    except Exception as e:
        logger.warning(f"resolve user {user_id}: {e}")
    _user_cache[str(user_id)] = (now, profile)
    return profile


@app.post("/api/users/resolve")
async def resolve_users(request: Request, user = Depends(get_current_user)):
    body = await request.json()
    ids = body.get("ids") or []
    ids = [str(i) for i in ids][:40]
    results = {}
    for uid in ids:
        results[uid] = await resolve_discord_user(uid)
        await asyncio.sleep(0.05)
    return {"users": results}


def _guild_config_dict(db, guild_id: int) -> dict:
    cursor = db.cursor()
    try:
        cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        if row:
            raw = row[0] if not hasattr(row, "keys") else row["config_json"]
            return json.loads(raw or "{}")
    except Exception:
        pass
    return {}


@app.get("/api/guilds/{guild_id}/overview")
async def guild_overview(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        await require_guild_member(user, guild_id)

    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM guild_levels WHERE guild_id = ?", (guild_id,))
    levels = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM infractions WHERE guild_id = ?", (guild_id,))
    infractions = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM invite_tracker WHERE guild_id = ?", (guild_id,))
    invites = cursor.fetchone()[0]
    rec = premium_lib.guild_record_sync(db, guild_id)
    is_premium = bool(rec and rec.get("active")) or user["user_id"] == SUPER_OWNER_ID
    cursor.execute("SELECT enabled, channel_id FROM welcome_config WHERE guild_id = ?", (guild_id,))
    welcome_row = cursor.fetchone()
    cursor.execute("SELECT enabled, join_threshold, window_seconds FROM antiraid_config WHERE guild_id = ?", (guild_id,))
    raid_row = cursor.fetchone()

    approx_members = 0
    guild_name = None
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
        async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}?with_counts=true", headers=headers) as res:
            if res.status == 200:
                g = await res.json()
                approx_members = g.get("approximate_member_count") or 0
                guild_name = g.get("name")

    runtime = await public_bot_status(db)
    try:
        v_stats = verify_log.stats_sync(db, guild_id)
    except Exception:
        v_stats = {"people": 0, "events": 0, "today": 0}
    return {
        "guild_id": str(guild_id),
        "name": guild_name,
        "members": approx_members,
        "level_records": levels,
        "infractions": infractions,
        "invites": invites,
        "verifications": v_stats.get("people") or 0,
        "verification_events": v_stats.get("events") or 0,
        "is_premium": is_premium,
        "premium": rec,
        "welcome_enabled": bool(welcome_row and welcome_row[0]),
        "antiraid_enabled": bool(raid_row and raid_row[0]),
        "health": health_lib.evaluate(db, guild_id, _guild_config_dict(db, guild_id)),
        "bot": runtime
    }


@app.get("/api/guilds/{guild_id}/tickets")
async def api_guild_tickets(guild_id: int, status: str | None = None, user=Depends(get_current_user),
                            db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config", "warn", "kick"])
    cur = db.cursor()
    if status:
        cur.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND status = ? ORDER BY id DESC LIMIT 80",
            (guild_id, status),
        )
    else:
        cur.execute(
            "SELECT * FROM tickets WHERE guild_id = ? ORDER BY id DESC LIMIT 80",
            (guild_id,),
        )
    out = []
    for r in cur.fetchall():
        out.append({k: (r[k] if k != "id" else r["id"]) for k in r.keys()})
        out[-1]["id"] = r["id"]
        out[-1]["guild_id"] = str(r["guild_id"])
        out[-1]["opener_id"] = str(r["opener_id"]) if r["opener_id"] else None
        out[-1]["channel_id"] = str(r["channel_id"]) if r["channel_id"] else None
    return {"tickets": out}


@app.get("/api/guilds/{guild_id}/tickets/{ticket_id}")
async def api_guild_ticket(guild_id: int, ticket_id: int, user=Depends(get_current_user),
                           db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config", "warn", "kick"])
    cur = db.cursor()
    cur.execute("SELECT * FROM tickets WHERE id = ? AND guild_id = ?", (ticket_id, guild_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    ticket = {k: row[k] for k in row.keys()}
    ticket["id"] = row["id"]
    ticket["guild_id"] = str(row["guild_id"])
    ticket["opener_id"] = str(row["opener_id"]) if row["opener_id"] else None
    cur.execute(
        "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY id ASC LIMIT 500",
        (ticket_id,),
    )
    msgs = []
    for r in cur.fetchall():
        atts = []
        try:
            atts = json.loads(r["attachments"] or "[]")
        except Exception:
            atts = []
        edited = False
        prev = None
        try:
            edited = bool(r["edited"])
            prev = r["previous_content"]
        except Exception:
            pass
        msgs.append({
            "id": r["id"],
            "user_id": str(r["user_id"]) if r["user_id"] else None,
            "username": r["username"],
            "avatar": r["avatar"],
            "content": r["content"],
            "previous_content": prev,
            "attachments": atts,
            "deleted": bool(r["deleted"]),
            "edited": edited,
            "created_at": r["created_at"],
        })
    return {"ticket": ticket, "messages": msgs}


@app.get("/api/guilds/{guild_id}/ticket_ratings")
async def api_guild_ticket_ratings(guild_id: int, user=Depends(get_current_user),
                                  db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config", "warn", "kick"])
    cur = db.cursor()
    cur.execute("""
        SELECT r.ticket_id, r.user_id, r.staff_id, r.staff_name, r.rating, r.comment, r.rated_at,
               t.opener_name
        FROM ticket_ratings r
        LEFT JOIN tickets t ON r.ticket_id = t.id
        WHERE r.guild_id = ?
        ORDER BY r.rated_at DESC LIMIT 50
    """, (guild_id,))
    reviews = []
    total_stars = 0
    staff_scores = {}
    for r in cur.fetchall():
        rev = {
            "ticket_id": r["ticket_id"],
            "user_id": str(r["user_id"]),
            "opener_name": r["opener_name"] or "Usuario",
            "staff_id": str(r["staff_id"]) if r["staff_id"] else None,
            "staff_name": r["staff_name"] or "Equipo de Soporte",
            "rating": r["rating"],
            "comment": r["comment"] or "",
            "rated_at": r["rated_at"]
        }
        reviews.append(rev)
        total_stars += rev["rating"]

        s_key = rev["staff_name"]
        if s_key not in staff_scores:
            staff_scores[s_key] = {"staff_name": s_key, "total_stars": 0, "count": 0, "staff_id": rev["staff_id"]}
        staff_scores[s_key]["total_stars"] += rev["rating"]
        staff_scores[s_key]["count"] += 1

    count = len(reviews)
    avg_score = round(total_stars / count, 2) if count > 0 else 0.0

    leaderboard = []
    for s_name, data in staff_scores.items():
        leaderboard.append({
            "staff_name": s_name,
            "staff_id": data["staff_id"],
            "avg_rating": round(data["total_stars"] / data["count"], 2),
            "total_reviews": data["count"]
        })
    leaderboard.sort(key=lambda x: (x["avg_rating"], x["total_reviews"]), reverse=True)

    return {
        "average_csat": avg_score,
        "total_reviews": count,
        "leaderboard": leaderboard,
        "reviews": reviews
    }


@app.get("/api/guilds/{guild_id}/snippets")
async def api_guild_snippets(guild_id: int, user=Depends(get_current_user),
                             db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config", "warn", "kick"])
    cur = db.cursor()
    cur.execute("SELECT id, name, content, created_by, usage_count FROM ticket_snippets WHERE guild_id = ? ORDER BY name ASC", (guild_id,))
    snippets = [{"id": r["id"], "name": r["name"], "content": r["content"], "usage_count": r["usage_count"] or 0} for r in cur.fetchall()]
    return {"snippets": snippets}


@app.get("/api/guilds/{guild_id}/voice_stats")
async def api_guild_voice_stats(guild_id: int, user=Depends(get_current_user),
                                db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config"])
    cur = db.cursor()
    cur.execute("""
        SELECT user_id, weekly_seconds, total_seconds, last_channel_name, last_active
        FROM voice_time
        WHERE guild_id = ?
        ORDER BY total_seconds DESC LIMIT 20
    """, (guild_id,))
    members = []
    for r in cur.fetchall():
        members.append({
            "user_id": str(r["user_id"]),
            "weekly_seconds": r["weekly_seconds"] or 0,
            "total_seconds": r["total_seconds"] or 0,
            "last_channel": r["last_channel_name"] or "—",
            "last_active": r["last_active"]
        })
    return {"members": members}


@app.get("/api/guilds/{guild_id}/antinuke")
async def api_guild_antinuke(guild_id: int, user=Depends(get_current_user),
                             db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    cur = db.cursor()
    cur.execute("SELECT * FROM antinuke_config WHERE guild_id = ?", (guild_id,))
    cfg_row = cur.fetchone()
    config = dict(cfg_row) if cfg_row else {
        "guild_id": str(guild_id), "enabled": 0, "max_channel_deletes": 3,
        "max_role_deletes": 3, "max_bans": 5, "max_kicks": 5,
        "window_seconds": 10, "action": "strip_roles", "log_channel_id": None
    }
    cur.execute("SELECT * FROM antinuke_logs WHERE guild_id = ? ORDER BY id DESC LIMIT 20", (guild_id,))
    logs = [dict(r) for r in cur.fetchall()]
    return {"config": config, "logs": logs}


@app.post("/api/guilds/{guild_id}/antinuke")
async def api_guild_antinuke_save(guild_id: int, payload: dict = Body(...),
                                 user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    cur = db.cursor()
    enabled = 1 if payload.get("enabled") else 0
    action = str(payload.get("action") or "strip_roles")
    if action not in ["strip_roles", "quarantine", "ban"]:
        action = "strip_roles"
    max_channels = max(1, int(payload.get("max_channel_deletes") or 3))
    max_roles = max(1, int(payload.get("max_role_deletes") or 3))
    max_bans = max(1, int(payload.get("max_bans") or 5))
    max_kicks = max(1, int(payload.get("max_kicks") or 5))
    window_seconds = max(5, min(300, int(payload.get("window_seconds") or 10)))
    raw_log_ch = payload.get("log_channel_id")
    log_channel_id = int(raw_log_ch) if raw_log_ch and str(raw_log_ch).strip() else None

    cur.execute("""
        INSERT INTO antinuke_config (guild_id, enabled, max_channel_deletes, max_role_deletes, max_bans, max_kicks, window_seconds, action, log_channel_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            enabled = excluded.enabled,
            max_channel_deletes = excluded.max_channel_deletes,
            max_role_deletes = excluded.max_role_deletes,
            max_bans = excluded.max_bans,
            max_kicks = excluded.max_kicks,
            window_seconds = excluded.window_seconds,
            action = excluded.action,
            log_channel_id = excluded.log_channel_id
    """, (guild_id, enabled, max_channels, max_roles, max_bans, max_kicks, window_seconds, action, log_channel_id))
    db.commit()
    return {"ok": True}


@app.get("/api/guilds/{guild_id}/autoresponses")
async def api_guild_autoresponses(guild_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    cur = db.cursor()
    cur.execute("SELECT id, trigger, response, created_by FROM auto_responses WHERE guild_id = ? ORDER BY id DESC", (guild_id,))
    rows = [dict(r) for r in cur.fetchall()]
    return rows


@app.post("/api/guilds/{guild_id}/autoresponses")
async def api_guild_autoresponse_add(guild_id: int, payload: dict = Body(...),
                                    user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    trigger = (payload.get("trigger") or "").strip()
    response = (payload.get("response") or "").strip()
    if not trigger or not response:
        raise HTTPException(status_code=400, detail="El activador y la respuesta son obligatorios.")
    if len(trigger) > 100 or len(response) > 2000:
        raise HTTPException(status_code=400, detail="Longitud de texto excedida.")

    cur = db.cursor()
    cur.execute("INSERT INTO auto_responses (guild_id, trigger, response, created_by) VALUES (?, ?, ?, ?)",
                (guild_id, trigger, response, int(user["user_id"])))
    db.commit()
    return {"ok": True, "id": cur.lastrowid}


@app.delete("/api/guilds/{guild_id}/autoresponses/{resp_id}")
async def api_guild_autoresponse_delete(guild_id: int, resp_id: int,
                                       user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    cur = db.cursor()
    cur.execute("DELETE FROM auto_responses WHERE id = ? AND guild_id = ?", (resp_id, guild_id))
    db.commit()
    return {"ok": True}


@app.get("/api/guilds/{guild_id}/customcommands")
async def api_guild_customcommands(guild_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    cur = db.cursor()
    cur.execute("SELECT trigger, response, usage_count, created_by FROM custom_commands WHERE guild_id = ? ORDER BY trigger ASC", (guild_id,))
    return [dict(r) for r in cur.fetchall()]


@app.post("/api/guilds/{guild_id}/customcommands")
async def api_guild_customcommand_add(guild_id: int, payload: dict = Body(...),
                                     user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    trigger = (payload.get("trigger") or "").strip().lower().lstrip("!/.")
    response = (payload.get("response") or "").strip()
    if not trigger or not response:
        raise HTTPException(status_code=400, detail="El comando y la respuesta son obligatorios.")
    if len(trigger) > 32 or len(response) > 2000:
        raise HTTPException(status_code=400, detail="Longitud de texto excedida.")

    cur = db.cursor()
    cur.execute("""
        INSERT INTO custom_commands (guild_id, trigger, response, created_by, usage_count)
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(guild_id, trigger) DO UPDATE SET
            response = excluded.response
    """, (guild_id, trigger, response, int(user["user_id"])))
    db.commit()
    return {"ok": True}


@app.delete("/api/guilds/{guild_id}/customcommands/{trigger}")
async def api_guild_customcommand_delete(guild_id: int, trigger: str,
                                        user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["manage_config"])
    cur = db.cursor()
    cur.execute("DELETE FROM custom_commands WHERE guild_id = ? AND trigger = ?", (guild_id, trigger.strip().lower()))
    db.commit()
    return {"ok": True}


@app.post("/api/guilds/{guild_id}/tickets/{ticket_id}/reply")
async def api_guild_ticket_reply(guild_id: int, ticket_id: int, payload: dict = Body(...),
                                user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config", "warn", "kick"])
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")

    cur = db.cursor()
    cur.execute("SELECT id, channel_id, status FROM tickets WHERE id = ? AND guild_id = ?", (ticket_id, guild_id))
    t_row = cur.fetchone()
    if not t_row:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    if t_row["status"] == "closed":
        raise HTTPException(status_code=400, detail="No puedes responder a un ticket cerrado.")

    channel_id = t_row["channel_id"]
    author_name = user.get("username") or "Staff"
    now_str = datetime.datetime.utcnow().isoformat()

    # Insert into ticket_messages
    cur.execute("""
        INSERT INTO ticket_messages (ticket_id, user_id, username, avatar, content, attachments, deleted, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (ticket_id, int(user["user_id"]), f"[Web] {author_name}", user.get("avatar") or "", content, "[]", 0, now_str))
    db.commit()

    # Mirror to Discord channel if exists
    if channel_id:
        try:
            embed_msg = {
                "embeds": [{
                    "author": {
                        "name": f"{author_name} (Panel Web)",
                        "icon_url": f"https://cdn.discordapp.com/avatars/{user['user_id']}/{user.get('avatar')}.png" if user.get("avatar") else "https://cdn.discordapp.com/embed/avatars/0.png"
                    },
                    "description": content,
                    "color": 0x00ff88,
                    "footer": {"text": "Respuesta enviada desde la Dashboard Web"}
                }]
            }
            await discord_bot("POST", f"/channels/{channel_id}/messages", json_body=embed_msg)
        except Exception as e:
            logger.warning("Could not mirror ticket reply to Discord channel %s: %s", channel_id, e)

    return {"ok": True, "message": "Respuesta enviada y sincronizada con Discord."}


@app.post("/api/guilds/{guild_id}/tickets/{ticket_id}/close")
async def api_guild_ticket_close(guild_id: int, ticket_id: int, payload: dict = Body(default={}),
                                user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "manage_config", "warn", "kick"])
    cur = db.cursor()
    cur.execute("SELECT * FROM tickets WHERE id = ? AND guild_id = ?", (ticket_id, guild_id))
    t_row = cur.fetchone()
    if not t_row:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    if t_row["status"] == "closed":
        return {"ok": True, "message": "El ticket ya estaba cerrado."}

    now_str = datetime.datetime.utcnow().isoformat()
    closer_name = user.get("username") or "Staff"
    cur.execute("""
        UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ?, closed_name = ?
        WHERE id = ? AND guild_id = ?
    """, (now_str, int(user["user_id"]), f"[Web] {closer_name}", ticket_id, guild_id))
    if t_row["channel_id"]:
        cur.execute("DELETE FROM active_tickets WHERE channel_id = ?", (t_row["channel_id"],))
    db.commit()

    channel_id = t_row["channel_id"]
    if channel_id:
        try:
            close_embed = {
                "embeds": [{
                    "title": "🔒 Ticket Cerrado desde la Dashboard Web",
                    "description": f"El ticket ha sido finalizado por **{closer_name}**.\nEste canal será archivado.",
                    "color": 0xec4899,
                    "timestamp": now_str
                }]
            }
            await discord_bot("POST", f"/channels/{channel_id}/messages", json_body=close_embed)
        except Exception as e:
            logger.warning("Could not send ticket close notification to Discord channel %s: %s", channel_id, e)

    return {"ok": True, "message": "Ticket cerrado y sincronizado con Discord."}


@app.get("/tickets/{ticket_id}/transcript", response_class=HTMLResponse)
async def get_ticket_html_transcript(ticket_id: int, request: Request, user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")

    guild_id = row["guild_id"]
    perms = await get_user_permissions(user, guild_id, db)
    is_staff = perms.get("is_admin") or "tickets" in perms.get("permissions", [])
    is_opener = str(row["opener_id"]) == str(user["user_id"])
    if not (is_staff or is_opener):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver este transcript.")

    cur.execute(
        "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY id ASC LIMIT 500",
        (ticket_id,)
    )
    rows = cur.fetchall()

    messages_html = []
    for r in rows:
        uname = html.escape(r["username"] or "Usuario")
        avatar = r["avatar"] or "https://davito.es/media/dabot.png"
        content = html.escape(r["content"] or "").replace("\n", "<br>")
        ts = str(r["created_at"] or "")[:19].replace("T", " ")

        atts = []
        try:
            atts = json.loads(r["attachments"] or "[]")
        except Exception:
            atts = []

        atts_html = ""
        for a in atts:
            fname = html.escape(a.get("filename", "adjunto"))
            furl = html.escape(a.get("url", "#"))
            if furl.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                atts_html += f'<div style="margin-top:8px"><img src="{furl}" alt="{fname}" style="max-width:380px;max-height:260px;border-radius:8px;border:1px solid #334155;"></div>'
            else:
                atts_html += f'<div style="margin-top:6px"><a href="{furl}" target="_blank" class="att-link">📎 {fname}</a></div>'

        messages_html.append(f"""
        <div class="msg-row">
            <img src="{avatar}" class="msg-avatar" alt="{uname}" onerror="this.src='https://davito.es/media/dabot.png'">
            <div class="msg-body">
                <div class="msg-header">
                    <span class="msg-author">{uname}</span>
                    <span class="msg-time">{ts}</span>
                </div>
                <div class="msg-text">{content}</div>
                {atts_html}
            </div>
        </div>
        """)

    title = html.escape(f"Ticket #{ticket_id} — {row['category'] or 'Soporte'}")
    opener_name = html.escape(row["opener_name"] or str(row["opener_id"]) or "Usuario")
    status = html.escape(row["status"] or "cerrado")

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | Dabot Transcript</title>
    <link rel="icon" href="https://davito.es/media/dabot.png">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #060913;
            --card: rgba(14, 22, 44, 0.85);
            --border: rgba(255, 255, 255, 0.08);
            --primary: #00ff88;
            --text: #f8fafc;
            --muted: #94a3b8;
        }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: 'Inter', system-ui, sans-serif;
            margin: 0;
            padding: 24px 16px;
            display: flex;
            justify-content: center;
        }}
        .container {{
            width: 100%;
            max-width: 900px;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 16px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
            overflow: hidden;
            backdrop-filter: blur(12px);
        }}
        .header {{
            padding: 24px;
            background: rgba(0,0,0,0.3);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .badge {{
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
            background: rgba(0,255,136,0.12);
            color: var(--primary);
            border: 1px solid rgba(0,255,136,0.3);
        }}
        .meta {{
            font-size: 13px;
            color: var(--muted);
            margin-top: 6px;
        }}
        .chat {{
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 18px;
        }}
        .msg-row {{
            display: flex;
            gap: 14px;
            align-items: flex-start;
        }}
        .msg-avatar {{
            width: 42px;
            height: 42px;
            border-radius: 50%;
            object-fit: cover;
            flex-shrink: 0;
        }}
        .msg-body {{
            flex: 1;
            min-width: 0;
        }}
        .msg-header {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 4px;
        }}
        .msg-author {{
            font-weight: 600;
            font-size: 15px;
            color: #fff;
        }}
        .msg-time {{
            font-size: 11.5px;
            color: var(--muted);
            font-family: 'IBM Plex Mono', monospace;
        }}
        .msg-text {{
            font-size: 14px;
            line-height: 1.5;
            color: #cbd5e1;
            word-break: break-word;
        }}
        .att-link {{
            color: #38bdf8;
            text-decoration: none;
            font-size: 13px;
        }}
        .att-link:hover {{ text-decoration: underline; }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            background: rgba(255,255,255,0.06);
            color: #fff;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .btn:hover {{
            background: rgba(255,255,255,0.12);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>🎫 Ticket #{ticket_id} <span class="badge">{status.upper()}</span></h1>
                <div class="meta">Abierto por <b>{opener_name}</b> • Categoría: <b>{html.escape(row['category'] or 'General')}</b></div>
            </div>
            <div>
                <button class="btn" onclick="window.print()">🖨️ Imprimir / Guardar PDF</button>
            </div>
        </div>
        <div class="chat">
            {''.join(messages_html) if messages_html else '<p style="color:var(--muted);text-align:center">No hay mensajes registrados en este ticket.</p>'}
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(html_content)


class PanelPayload(BaseModel):
    channel_id: str
    message: str | None = None


async def require_channel_in_guild(channel_id: str, guild_id: int) -> dict:
    """Prevent a guild-scoped action from writing to another guild's channel."""
    if not str(channel_id).isdigit():
        raise HTTPException(status_code=400, detail="Canal inválido.")
    channel = await discord_bot("GET", f"/channels/{channel_id}")
    if str(channel.get("guild_id")) != str(guild_id):
        raise HTTPException(status_code=403, detail="El canal no pertenece a este servidor.")
    if int(channel.get("type") or 0) not in (0, 5, 10, 11, 12):
        raise HTTPException(status_code=400, detail="El canal no admite mensajes.")
    return channel


def _ticket_panel_components(tickets_cfg: dict | None) -> list[dict]:
    from cogs.tickets import categories_from_cfg, TICKET_CATEGORIES
    cats = categories_from_cfg(tickets_cfg)
    if not cats:
        cats = list(TICKET_CATEGORIES)
    rows = []
    chunks = [cats[i:i + 25] for i in range(0, min(len(cats), 125), 25)]
    total = max(len(chunks), 1)
    for page, chunk in enumerate(chunks):
        cid = "dabot:ticket_category" if page == 0 else f"dabot:ticket_category:{page}"
        ph = "Elige el tipo de ticket…" if total == 1 else f"Elige el tipo de ticket… ({page + 1}/{total})"
        options = []
        for c in chunk:
            opt = {
                "label": str(c.get("label") or "Ticket")[:100],
                "value": str(c.get("id") or "other")[:100],
                "description": str(c.get("description") or c.get("label") or "")[:100],
            }
            raw = str(c.get("emoji") or "📩")
            m = re.match(r"<a?:([\w~]+):(\d+)>", raw)
            if m:
                opt["emoji"] = {"name": m.group(1), "id": m.group(2), "animated": raw.startswith("<a:")}
            elif raw:
                opt["emoji"] = {"name": raw[:32]}
            options.append(opt)
        rows.append({
            "type": 1,
            "components": [{
                "type": 3,
                "custom_id": cid,
                "placeholder": ph[:150],
                "min_values": 1,
                "max_values": 1,
                "options": options,
            }],
        })
    return rows


@app.post("/api/guilds/{guild_id}/actions/ticket-panel")
async def post_ticket_panel(guild_id: int, payload: PanelPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await require_channel_in_guild(payload.channel_id, guild_id)
    cur = db.cursor()
    cur.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
    row = cur.fetchone()
    tickets_cfg = {}
    try:
        data = json.loads(row[0] if row else "{}")
        tickets_cfg = (data or {}).get("tickets") or {}
    except Exception:
        tickets_cfg = {}
    cats = []
    try:
        from cogs.tickets import categories_from_cfg
        cats = categories_from_cfg(tickets_cfg)
    except Exception:
        cats = []
    from cogs.tickets import ticket_panel_payloads
    extra = payload.message or None
    embeds = ticket_panel_payloads(tickets_cfg, extra=extra)
    body = {
        "embeds": embeds[:10],
        "components": _ticket_panel_components(tickets_cfg),
    }
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
        async with session.post(
            f"https://discord.com/api/v10/channels/{payload.channel_id}/messages",
            headers=headers, json=body
        ) as res:
            if res.status not in (200, 201):
                text = await res.text()
                logger.error(f"ticket panel failed: {res.status} {text}")
                raise HTTPException(status_code=400, detail="No se pudo enviar el panel. Revisa el canal y los permisos del bot.")
    return {"status": "success"}


@app.post("/api/guilds/{guild_id}/actions/verification-panel")
async def post_verification_panel(guild_id: int, payload: PanelPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await require_channel_in_guild(payload.channel_id, guild_id)
    cursor = db.cursor()
    cursor.execute("SELECT verification_type FROM verification_config WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    vtype = (row[0] if row else "web") or "web"
    url = f"{DASHBOARD_URL}/verify/{guild_id}"
    comps = [{
        "type": 2,
        "style": 5,
        "label": "Verificarse · dabot.davito.es",
        "url": url,
    }]
    if vtype in ("emoji", "math"):
        comps.append({
            "type": 2,
            "style": 3,
            "label": "Verificar",
            "emoji": {"name": "🛡️"},
            "custom_id": "verify_panel_button_v1",
        })
    body = {
        "embeds": [{
            "title": "🛡️ Verificación",
            "description": payload.message or (
                f"Pulsa el botón y abre **dabot.davito.es/verify** con Discord.\n{url}"
            ),
            "color": 0x00FF88,
            "footer": {"text": "dabot.davito.es/verify"}
        }],
        "components": [{"type": 1, "components": comps}]
    }
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
        async with session.post(
            f"https://discord.com/api/v10/channels/{payload.channel_id}/messages",
            headers=headers, json=body
        ) as res:
            if res.status not in (200, 201):
                text = await res.text()
                logger.error(f"verification panel failed: {res.status} {text}")
                raise HTTPException(status_code=400, detail="No se pudo enviar el panel de verificación.")
    return {"status": "success"}


class AntiraidPayload(BaseModel):
    enabled: bool = False
    join_threshold: int = 10
    window_seconds: int = 10
    alert_channel_id: str | None = None
    lockdown_minutes: int = 5


@app.get("/api/guilds/{guild_id}/antiraid")
async def get_antiraid(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    cursor = db.cursor()
    cursor.execute(
        "SELECT enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes FROM antiraid_config WHERE guild_id = ?",
        (guild_id,)
    )
    row = cursor.fetchone()
    if not row:
        return {
            "enabled": False,
            "join_threshold": 10,
            "window_seconds": 10,
            "alert_channel_id": "",
            "lockdown_minutes": 5
        }
    return {
        "enabled": bool(row[0]),
        "join_threshold": row[1],
        "window_seconds": row[2],
        "alert_channel_id": str(row[3] or ""),
        "lockdown_minutes": row[4]
    }


@app.post("/api/guilds/{guild_id}/antiraid")
async def save_antiraid(guild_id: int, payload: AntiraidPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm_data = await get_user_permissions(user, guild_id, db)
    if not perm_data["is_admin"] and "manage_config" not in perm_data["permissions"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    channel_id = int(payload.alert_channel_id) if payload.alert_channel_id and str(payload.alert_channel_id).isdigit() else None
    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO antiraid_config
           (guild_id, enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(guild_id) DO UPDATE SET
             enabled = excluded.enabled,
             join_threshold = excluded.join_threshold,
             window_seconds = excluded.window_seconds,
             alert_channel_id = excluded.alert_channel_id,
             lockdown_minutes = excluded.lockdown_minutes""",
        (guild_id, 1 if payload.enabled else 0, payload.join_threshold,
         payload.window_seconds, channel_id, payload.lockdown_minutes)
    )
    db.commit()
    return {"status": "success"}


async def _scope_alts_to_guild_members(guild_id: int, dossier, alerts, cases):
    """Drop linked accounts that are not currently in this Discord server."""
    ids = []
    if dossier:
        try:
            ids.append(int(dossier.get("user_id")))
        except (TypeError, ValueError):
            pass
        for a in dossier.get("alts") or []:
            try:
                ids.append(int(a.get("user_id")))
            except (TypeError, ValueError):
                pass
    for a in alerts or []:
        try:
            ids.append(int(a.get("user_a")))
            ids.append(int(a.get("user_b")))
        except (TypeError, ValueError):
            pass
    for c in cases or []:
        try:
            ids.append(int(c.get("user_id")))
        except (TypeError, ValueError):
            pass
        for m in c.get("matches") or []:
            try:
                ids.append(int(m.get("user_id")))
            except (TypeError, ValueError):
                pass
    present = await discord_members_present(guild_id, ids)
    if dossier is not None:
        dossier["alts"] = [a for a in (dossier.get("alts") or []) if int(a.get("user_id") or 0) in present]
        dossier["score"] = (dossier["alts"][0]["score"] if dossier["alts"] else 0)
        dossier["alts_in_guild_only"] = True
    if alerts is not None:
        alerts = [
            a for a in alerts
            if int(a.get("user_a") or 0) in present and int(a.get("user_b") or 0) in present
        ]
    if cases is not None:
        for c in cases:
            c["matches"] = [m for m in (c.get("matches") or []) if int(m.get("user_id") or 0) in present]
    return dossier, alerts, cases


async def discord_members_present(guild_id: int, user_ids) -> set[int]:
    """User IDs that are currently members of this guild. 404 = not in the server."""
    present: set[int] = set()
    seen = []
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid in present or uid in seen:
            continue
        seen.append(uid)
        try:
            await discord_bot("GET", f"/guilds/{int(guild_id)}/members/{uid}")
            present.add(uid)
        except Exception:
            continue
        await asyncio.sleep(0.04)
    return present


async def discord_bot(method: str, path: str, json_body=None, params=None):
    return await discord_request(method, path, json_body=json_body, params=params)


async def require_guild_staff(user, guild_id, db, extra=None):
    perm = await get_user_permissions(user, guild_id, db)
    extra = extra or []
    if perm["is_admin"] or any(p in perm["permissions"] for p in extra):
        return perm
    raise HTTPException(status_code=403, detail="Sin permisos de staff en este servidor.")


class ChannelPayload(BaseModel):
    name: str | None = None
    type: int = 0
    topic: str | None = None
    parent_id: str | None = None
    nsfw: bool | None = None
    rate_limit_per_user: int | None = None
    bitrate: int | None = None
    user_limit: int | None = None
    position: int | None = None


class RolePayload(BaseModel):
    name: str | None = None
    color: int | None = None
    hoist: bool | None = None
    mentionable: bool | None = None
    permissions: str | None = None


class MemberPatchPayload(BaseModel):
    nick: str | None = None
    roles: list[str] | None = None
    timeout_minutes: int | None = None
    reason: str | None = None


class KickBanPayload(BaseModel):
    reason: str = "Acción desde el panel de Dabot"


class GuildDiscordPayload(BaseModel):
    name: str | None = None
    verification_level: int | None = None
    default_message_notifications: int | None = None
    afk_timeout: int | None = None
    rules: str | None = None


class RulesPayload(BaseModel):
    rules: str


@app.get("/api/guilds/{guild_id}/discord")
async def get_guild_discord(guild_id: int, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["manage_config"])
    g = await discord_bot("GET", f"/guilds/{guild_id}?with_counts=true")
    cursor = db.cursor()
    cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    rules = ""
    if row:
        try:
            cfg = json.loads(row[0] or "{}")
            rules = ((cfg.get("community") or {}).get("rules")) or ""
        except Exception:
            rules = ""
    return {
        "id": g.get("id"),
        "name": g.get("name"),
        "icon": g.get("icon"),
        "member_count": g.get("approximate_member_count") or g.get("member_count"),
        "verification_level": g.get("verification_level"),
        "default_message_notifications": g.get("default_message_notifications"),
        "afk_timeout": g.get("afk_timeout"),
        "premium_tier": g.get("premium_tier"),
        "rules": rules,
    }


@app.patch("/api/guilds/{guild_id}/discord")
async def patch_guild_discord(guild_id: int, payload: GuildDiscordPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    perm = await require_guild_staff(user, guild_id, db, ["manage_config"])
    if not perm["is_admin"] and "manage_config" not in perm["permissions"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    body = {}
    if payload.name:
        body["name"] = payload.name[:100]
    if payload.verification_level is not None:
        body["verification_level"] = payload.verification_level
    if payload.default_message_notifications is not None:
        body["default_message_notifications"] = payload.default_message_notifications
    if payload.afk_timeout is not None:
        body["afk_timeout"] = payload.afk_timeout
    if body:
        await discord_bot("PATCH", f"/guilds/{guild_id}", body)
    if payload.rules is not None:
        cursor = db.cursor()
        cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        cfg = {}
        if row:
            try:
                cfg = json.loads(row[0] or "{}")
            except Exception:
                cfg = {}
        cfg.setdefault("community", {})["rules"] = payload.rules
        cursor.execute(
            "INSERT INTO guild_configs (guild_id, config_json) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET config_json = excluded.config_json",
            (guild_id, json.dumps(cfg)),
        )
        db.commit()
    return {"status": "success"}


@app.get("/api/guilds/{guild_id}/members")
async def list_guild_members(guild_id: int, q: str = "", user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["view_infractions", "ban", "kick", "warn", "timeout", "manage_config"])
    if q:
        data = await discord_bot("GET", f"/guilds/{guild_id}/members/search", params={"query": q[:32], "limit": 25})
    else:
        data = await discord_bot("GET", f"/guilds/{guild_id}/members", params={"limit": 80})
    if not isinstance(data, list):
        data = []
    out = []
    for m in data:
        u = m.get("user") or {}
        out.append({
            "id": u.get("id"),
            "username": u.get("username"),
            "global_name": u.get("global_name"),
            "avatar": u.get("avatar"),
            "nick": m.get("nick"),
            "roles": m.get("roles") or [],
            "joined_at": m.get("joined_at"),
            "bot": u.get("bot", False),
        })
    return {"members": out}


@app.patch("/api/guilds/{guild_id}/members/{member_id}")
async def patch_member(guild_id: int, member_id: str, payload: MemberPatchPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["timeout", "manage_config"])
    body = {}
    if payload.nick is not None:
        body["nick"] = payload.nick
    if payload.roles is not None:
        body["roles"] = payload.roles
    if payload.timeout_minutes is not None:
        if payload.timeout_minutes <= 0:
            body["communication_disabled_until"] = None
        else:
            until = datetime.datetime.utcnow() + datetime.timedelta(minutes=payload.timeout_minutes)
            body["communication_disabled_until"] = until.isoformat() + "Z"
    await discord_bot("PATCH", f"/guilds/{guild_id}/members/{member_id}", body)
    if payload.timeout_minutes and payload.timeout_minutes > 0:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp, status) VALUES (?, ?, ?, 'timeout', ?, ?, 'active')",
            (int(member_id), guild_id, user["user_id"], payload.reason or "Timeout desde el panel", datetime.datetime.now().isoformat()),
        )
        db.commit()
    return {"status": "success"}


@app.delete("/api/guilds/{guild_id}/members/{member_id}")
async def kick_member(guild_id: int, member_id: str, payload: KickBanPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["kick"])
    await discord_bot("DELETE", f"/guilds/{guild_id}/members/{member_id}")
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp, status) VALUES (?, ?, ?, 'kick', ?, ?, 'active')",
        (int(member_id), guild_id, user["user_id"], payload.reason, datetime.datetime.now().isoformat()),
    )
    db.commit()
    return {"status": "success"}


@app.put("/api/guilds/{guild_id}/bans/{user_id}")
async def ban_member(guild_id: int, user_id: str, payload: KickBanPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["ban"])
    await discord_bot("PUT", f"/guilds/{guild_id}/bans/{user_id}", {"delete_message_seconds": 0, "reason": payload.reason})
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp, status) VALUES (?, ?, ?, 'ban', ?, ?, 'active')",
        (int(user_id), guild_id, user["user_id"], payload.reason, datetime.datetime.now().isoformat()),
    )
    db.commit()
    return {"status": "success"}


@app.post("/api/guilds/{guild_id}/channels")
async def create_channel(guild_id: int, payload: ChannelPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["manage_config"])
    body = {"name": payload.name or "nuevo-canal", "type": payload.type}
    if payload.topic is not None:
        body["topic"] = payload.topic
    if payload.parent_id:
        body["parent_id"] = payload.parent_id
    if payload.nsfw is not None:
        body["nsfw"] = payload.nsfw
    created = await discord_bot("POST", f"/guilds/{guild_id}/channels", body)
    return created


@app.patch("/api/channels/{channel_id}")
async def edit_channel(channel_id: str, payload: ChannelPayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    ch = await discord_bot("GET", f"/channels/{channel_id}")
    guild_id = int(ch.get("guild_id") or 0)
    if guild_id:
        await require_guild_staff(user, guild_id, db, ["manage_config"])
    body = {}
    if payload.name:
        body["name"] = payload.name
    if payload.topic is not None:
        body["topic"] = payload.topic
    if payload.nsfw is not None:
        body["nsfw"] = payload.nsfw
    if payload.rate_limit_per_user is not None:
        body["rate_limit_per_user"] = payload.rate_limit_per_user
    if payload.parent_id is not None:
        body["parent_id"] = payload.parent_id or None
    if payload.position is not None:
        body["position"] = payload.position
    updated = await discord_bot("PATCH", f"/channels/{channel_id}", body)
    return updated


@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: str, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    ch = await discord_bot("GET", f"/channels/{channel_id}")
    guild_id = int(ch.get("guild_id") or 0)
    if guild_id:
        await require_guild_staff(user, guild_id, db, ["manage_config"])
    await discord_bot("DELETE", f"/channels/{channel_id}")
    return {"status": "success"}


@app.post("/api/guilds/{guild_id}/roles")
async def create_role(guild_id: int, payload: RolePayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["manage_config"])
    body = {"name": payload.name or "nuevo-rol"}
    if payload.color is not None:
        body["color"] = payload.color
    if payload.hoist is not None:
        body["hoist"] = payload.hoist
    created = await discord_bot("POST", f"/guilds/{guild_id}/roles", body)
    return created


@app.patch("/api/guilds/{guild_id}/roles/{role_id}")
async def edit_role(guild_id: int, role_id: str, payload: RolePayload, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["manage_config"])
    body = {}
    if payload.name:
        body["name"] = payload.name
    if payload.color is not None:
        body["color"] = payload.color
    if payload.hoist is not None:
        body["hoist"] = payload.hoist
    if payload.mentionable is not None:
        body["mentionable"] = payload.mentionable
    if payload.permissions is not None:
        body["permissions"] = payload.permissions
    return await discord_bot("PATCH", f"/guilds/{guild_id}/roles/{role_id}", body)


@app.delete("/api/guilds/{guild_id}/roles/{role_id}")
async def delete_role(guild_id: int, role_id: str, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, ["manage_config"])
    await discord_bot("DELETE", f"/guilds/{guild_id}/roles/{role_id}")
    return {"status": "success"}


def _format_time_ago(iso_str: str) -> str:
    if not iso_str:
        return "Nunca"
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        seconds = max(0, int((now - dt).total_seconds()))
        if seconds < 60:
            return "Hace unos segundos"
        elif seconds < 3600:
            m = seconds // 60
            return f"Hace {m} min"
        elif seconds < 86400:
            h = seconds // 3600
            return f"Hace {h}h"
        else:
            d = seconds // 86400
            return f"Hace {d}d"
    except Exception:
        return "Reciente"


@app.get("/api/public/servers")
async def public_servers(
    search: Optional[str] = None,
    category: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    query = """
        SELECT guild_id, name, description, icon, invite_url, tags, category,
               member_count, bump_count, last_bump_at
        FROM server_discovery
        WHERE is_public = 1
    """
    params = []

    if category and category.strip() and category.lower() not in ("all", "todos"):
        query += " AND LOWER(category) = ?"
        params.append(category.strip().lower())

    if search and search.strip():
        s = f"%{search.strip().lower()}%"
        query += " AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(tags) LIKE ?)"
        params.extend([s, s, s])

    query += " ORDER BY COALESCE(last_bump_at, created_at) DESC LIMIT 100"

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    servers = []

    for r in rows:
        gid = str(r[0])
        name = r[1]
        desc = r[2] or f"Servidor {name} en la comunidad de Dabot."
        icon_hash = r[3]
        invite = r[4]
        tags_raw = r[5] or ""
        cat = r[6] or "Comunidad"
        members = r[7] or 0
        bumps = r[8] or 0
        last_bump = r[9]

        icon_url = (
            f"https://cdn.discordapp.com/icons/{gid}/{icon_hash}.png"
            if icon_hash
            else "https://davito.es/media/dabot.png"
        )
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        servers.append({
            "guild_id": gid,
            "name": name,
            "description": desc,
            "icon_url": icon_url,
            "invite_url": invite or f"https://discord.com/channels/{gid}",
            "tags": tags,
            "category": cat,
            "member_count": members,
            "bump_count": bumps,
            "last_bump_at": last_bump,
            "time_ago": _format_time_ago(last_bump),
        })

    return {"total": len(servers), "servers": servers}


@app.get("/api/public/guilds")
async def public_guilds():
    ids = await fetch_bot_guilds()
    out = []
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        for gid in ids[:24]:
            try:
                async with session.get(f"https://discord.com/api/v10/guilds/{gid}?with_counts=true", headers=headers) as res:
                    if res.status != 200:
                        continue
                    g = await res.json()
                    out.append({
                        "id": g.get("id"),
                        "name": g.get("name"),
                        "icon": g.get("icon"),
                        "members": g.get("approximate_member_count") or 0,
                    })
            except Exception:
                continue
    out.sort(key=lambda x: x.get("members") or 0, reverse=True)
    return {"guilds": out}


@app.get("/api/public/leaderboard")
async def public_leaderboard(guild_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        """SELECT user_id, level, xp, weekly_xp FROM guild_levels
           WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 25""",
        (guild_id,),
    )
    rows = cursor.fetchall()
    board = []
    for i, r in enumerate(rows, start=1):
        profile = await resolve_discord_user(str(r[0]))
        board.append({
            "rank": i,
            "user_id": str(r[0]),
            "level": r[1],
            "xp": r[2],
            "weekly_xp": r[3],
            "username": profile.get("global_name") or profile.get("username"),
            "avatar_url": profile.get("avatar_url"),
        })
        await asyncio.sleep(0.04)
    return {"guild_id": str(guild_id), "leaderboard": board}


@app.get("/api/public/leaderboard-global")
async def public_leaderboard_global(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        "SELECT user_id, level, xp, weekly_xp FROM users ORDER BY level DESC, xp DESC LIMIT 25"
    )
    rows = cursor.fetchall()
    board = []
    for i, r in enumerate(rows, start=1):
        profile = await resolve_discord_user(str(r[0]))
        board.append({
            "rank": i,
            "user_id": str(r[0]),
            "level": r[1],
            "xp": r[2],
            "weekly_xp": r[3] or 0,
            "username": profile.get("global_name") or profile.get("username"),
            "avatar_url": profile.get("avatar_url"),
        })
        await asyncio.sleep(0.04)
    return {"leaderboard": board}


@app.get("/api/public/rules")
def public_rules(guild_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    rules = ""
    name = ""
    if row:
        try:
            cfg = json.loads(row[0] or "{}")
            rules = ((cfg.get("community") or {}).get("rules")) or ""
        except Exception:
            rules = ""
    return {"guild_id": str(guild_id), "rules": rules}


@app.get("/api/me/profile")
async def me_profile(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    bot_ids = set(await fetch_bot_guilds())
    async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
        headers = {"Authorization": f"Bearer {user['access_token']}"}
        async with session.get("https://discord.com/api/v10/users/@me/guilds?limit=200", headers=headers) as res:
            if res.status != 200:
                raise HTTPException(status_code=401, detail="Sesión caducada")
            user_guilds = await res.json()
    cursor = db.cursor()
    out = []
    for g in user_guilds:
        gid = str(g.get("id"))
        if gid not in bot_ids:
            continue
        cursor.execute(
            "SELECT level, xp, weekly_xp FROM guild_levels WHERE guild_id = ? AND user_id = ?",
            (int(gid), user["user_id"]),
        )
        lvl = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) FROM infractions WHERE guild_id = ? AND user_id = ?",
            (int(gid), user["user_id"]),
        )
        n = cursor.fetchone()[0]
        out.append({
            "id": gid,
            "name": g.get("name"),
            "icon": g.get("icon"),
            "level": lvl[0] if lvl else 1,
            "xp": lvl[1] if lvl else 0,
            "weekly_xp": lvl[2] if lvl else 0,
            "infractions": n,
        })
    cursor.execute("SELECT xp, level FROM users WHERE user_id = ?", (user["user_id"],))
    glob = cursor.fetchone()
    return {
        "user_id": str(user["user_id"]),
        "username": user["username"],
        "avatar": user["avatar"],
        "global_xp": glob[0] if glob else 0,
        "global_level": glob[1] if glob else 1,
        "guilds": out,
    }


_shared_lastfm_client = LastFMClient()


@app.on_event("shutdown")
async def _shutdown_lastfm():
    await _shared_lastfm_client.close()


class LastFMSetRequest(BaseModel):
    username: str


@app.get("/api/me/lastfm")
async def get_my_lastfm(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT lastfm_username, updated_at FROM user_lastfm WHERE user_id = ?", (user["user_id"],))
    row = cursor.fetchone()
    if not row:
        return {"linked": False, "username": None, "profile": None}

    username = row[0]
    profile = await _shared_lastfm_client.get_user_info(username)
    return {
        "linked": True,
        "username": username,
        "updated_at": row[1],
        "profile": profile
    }


@app.post("/api/me/lastfm")
async def set_my_lastfm(req: LastFMSetRequest, user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    username = (req.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Debes indicar un nombre de usuario de Last.fm.")

    profile = await _shared_lastfm_client.get_user_info(username)
    if not profile:
        raise HTTPException(status_code=400, detail=f"El usuario de Last.fm '{username}' no existe o no se pudo verificar.")

    cursor = db.cursor()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute(
        """INSERT INTO user_lastfm (user_id, lastfm_username, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               lastfm_username = excluded.lastfm_username,
               updated_at = excluded.updated_at""",
        (user["user_id"], profile["name"], now)
    )
    db.commit()
    return {"ok": True, "username": profile["name"], "profile": profile}


@app.delete("/api/me/lastfm")
async def delete_my_lastfm(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("DELETE FROM user_lastfm WHERE user_id = ?", (user["user_id"],))
    db.commit()
    return {"ok": True}


@app.get("/api/me/lastfm/nowplaying")
async def get_my_lastfm_nowplaying(user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT lastfm_username FROM user_lastfm WHERE user_id = ?", (user["user_id"],))
    row = cursor.fetchone()
    if not row:
        return {"linked": False}

    username = row[0]
    rec = await _shared_lastfm_client.get_recent_tracks(username, limit=2)
    if not rec or not rec.get("current"):
        return {"linked": True, "username": username, "now_playing": False, "current": None}

    current = rec["current"]
    track_info, artist_info = await asyncio.gather(
        _shared_lastfm_client.get_track_info(current["artist"], current["name"], username=username),
        _shared_lastfm_client.get_artist_info(current["artist"], username=username)
    )

    return {
        "linked": True,
        "username": username,
        "now_playing": rec.get("now_playing", False),
        "total_scrobbles": rec.get("total_scrobbles", 0),
        "track": {
            **current,
            "user_playcount": track_info.get("userplaycount", 0),
            "artist_playcount": artist_info.get("userplaycount", 0),
            "userloved": track_info.get("userloved", False),
            "tags": track_info.get("tags", []) or artist_info.get("tags", [])
        }
    }


@app.get("/api/me/lastfm/top")
async def get_my_lastfm_top(period: str = "7day", user = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT lastfm_username FROM user_lastfm WHERE user_id = ?", (user["user_id"],))
    row = cursor.fetchone()
    if not row:
        return {"linked": False, "artists": [], "tracks": []}

    username = row[0]
    artists, tracks = await asyncio.gather(
        _shared_lastfm_client.get_top_artists(username, period=period, limit=5),
        _shared_lastfm_client.get_top_tracks(username, period=period, limit=5)
    )
    return {
        "linked": True,
        "username": username,
        "period": period,
        "artists": artists,
        "top_artists": artists,
        "tracks": tracks,
        "top_tracks": tracks
    }


class VerifyFingerprint(BaseModel):
    guild_id: str | int
    timezone: str = ""
    lang: str = ""
    platform: str = ""
    hardware: int | float = 0
    memory: int | float = 0
    screen: str = ""
    touch: int | float = 0
    canvas: str = ""
    webgl: str = ""
    webrtc_ips: list[str] = Field(default_factory=list)
    js_device_id: str = ""
    challenge_token: str = ""
    challenge_pick: int | None = None
    website: str = ""  # honeypot; must be empty


class AltNetworkPayload(BaseModel):
    guild_id: int
    enabled: bool = True
    note: str = ""


class AltCaseActionPayload(BaseModel):
    action: str


def _snowflake_created(user_id: int) -> str:
    try:
        return datetime.datetime.utcfromtimestamp(((int(user_id) >> 22) + 1420070400000) / 1000).isoformat()
    except Exception:
        return ""


@app.get("/verify")
@app.get("/verify/{guild_id}")
def verify_page(request: Request, session_id: str | None = Cookie(None), guild_id: int | None = None):
    if not session_id:
        nxt = f"/verify/{guild_id}" if guild_id else "/verify"
        return RedirectResponse("/login?next=" + nxt)
    resp = FileResponse("templates/verify.html")
    _set_device_cookie(resp, request)
    return resp


@app.get("/api/verify/switch-account")
async def verify_logout(request: Request, g: int | None = None,
                       session_id: str | None = Cookie(None),
                       db: sqlite3.Connection = Depends(get_db)):
    """Log out of the wrong Discord account but keep the device cookie and store this account."""
    nxt = f"/verify/{g}" if g else "/verify"
    if session_id:
        cursor = db.cursor()
        cursor.execute(
            "SELECT user_id, username, avatar FROM web_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if row:
            try:
                uid = int(row["user_id"] if hasattr(row, "keys") else row[0])
                uname = row["username"] if hasattr(row, "keys") else row[1]
                did = request.cookies.get("dabot_did") or secrets.token_hex(16)
                alt_intel.record_sighting(
                    db,
                    user_id=uid,
                    guild_id=int(g) if g else None,
                    username=uname or "",
                    account_created=_snowflake_created(uid),
                    ip=alt_intel.client_ip(request.headers, request.client.host if request.client else ""),
                    country=request.headers.get("cf-ipcountry") or request.headers.get("CF-IPCountry") or "",
                    device_id=did,
                    user_agent=request.headers.get("user-agent") or "",
                    source="verify_switch",
                )
            except Exception as e:
                logger.warning("verify logout sighting: %s", e)
            cursor.execute("DELETE FROM web_sessions WHERE session_id = ?", (session_id,))
            db.commit()
    resp = RedirectResponse("/login?next=" + nxt, status_code=302)
    resp.delete_cookie("session_id", path="/")
    _set_device_cookie(resp, request)
    return resp


async def _inspect_request(request: Request, webrtc_ips=None, timezone: str = "") -> tuple[dict, str]:
    peer = request.client.host if request.client else ""
    ip = alt_intel.client_ip(request.headers, peer)
    hdrs = {k: v for k, v in request.headers.items()}
    rtc = list(webrtc_ips or [])

    def _run():
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            return proxy_detect.inspect(
                conn, ip, headers=hdrs, webrtc_ips=rtc, timezone=timezone or "",
            )
        finally:
            conn.close()

    intel = await asyncio.get_running_loop().run_in_executor(None, _run)
    return intel, ip


@app.get("/api/verify/network")
async def api_verify_network(request: Request, user=Depends(get_current_user)):
    intel, _ip = await _inspect_request(request)
    return proxy_detect.public_payload(intel)


@app.get("/api/verify/challenge")
async def api_verify_challenge(db: sqlite3.Connection = Depends(get_db), user=Depends(get_current_user)):
    alt_intel.ensure_schema_sync(db)
    token = secrets.token_urlsafe(18)
    options = random.sample(_CAPTCHA_EMOJIS, 5) + ["🦞"]
    random.shuffle(options)
    answer = options.index("🦞")
    db.execute(
        "INSERT INTO alt_captcha (token, answer, created_at, used) VALUES (?, ?, ?, 0)",
        (token, answer, datetime.datetime.utcnow().isoformat()),
    )
    db.commit()
    return {"token": token, "options": options, "hint": "lobster"}


@app.get("/api/verify/targets")
async def api_verify_targets(user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    bot_ids = set(await fetch_bot_guilds())
    user_guilds = []
    try:
        async with aiohttp.ClientSession(timeout=_DISCORD_TIMEOUT) as session:
            headers = {"Authorization": f"Bearer {user['access_token']}"}
            async with session.get("https://discord.com/api/v10/users/@me/guilds?limit=200", headers=headers) as res:
                if res.status == 200:
                    user_guilds = await res.json()
    except Exception as e:
        logger.warning("verify targets guilds: %s", e)
    cursor = db.cursor()
    out = []
    for g in user_guilds:
        gid = str(g.get("id") or "")
        if gid not in bot_ids:
            continue
        cursor.execute(
            "SELECT enabled FROM verification_config WHERE guild_id = ?",
            (int(gid),),
        )
        row = cursor.fetchone()
        configured = bool(row and int(row[0] or 0) == 1)
        out.append({
            "id": gid,
            "name": g.get("name") or gid,
            "icon": g.get("icon"),
            "configured": configured,
        })
    out.sort(key=lambda x: (not x["configured"], (x["name"] or "").lower()))
    return {"guilds": out}


@app.get("/api/verify/preview/{guild_id}")
async def api_verify_preview(guild_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        "SELECT enabled, unverified_role_id, verified_role_id FROM verification_config WHERE guild_id = ?",
        (guild_id,),
    )
    cfg = cursor.fetchone()
    configured = bool(cfg and int(cfg[0] or 0) == 1)
    name, icon = str(guild_id), None
    try:
        g = await discord_bot("GET", f"/guilds/{guild_id}")
        name = g.get("name") or name
        icon = g.get("icon")
    except Exception:
        pass
    in_guild = False
    already = False
    try:
        member = await discord_bot("GET", f"/guilds/{guild_id}/members/{user['user_id']}")
        in_guild = True
        if configured and cfg:
            already = str(cfg[2]) in [str(r) for r in member.get("roles", [])]
    except Exception:
        in_guild = False
    return {
        "id": str(guild_id),
        "name": name,
        "icon": icon,
        "configured": configured,
        "in_guild": in_guild,
        "already_verified": already,
    }


async def _record_verification_event(db, **kwargs):
    """Persist a verification row, audit event, and Discord staff log."""
    try:
        verify_log.ensure_schema_sync(db)
        eid, ch_id, embed = verify_log.record_full_sync(db, **kwargs)
    except Exception as e:
        logger.warning("verification event write failed: %s", e)
        return None
    if ch_id:
        try:
            await discord_bot("POST", f"/channels/{int(ch_id)}/messages", {"embeds": [embed]})
        except Exception as e:
            logger.warning("verification discord log failed: %s", e)
    return eid


async def _post_alt_case_embed(guild_id: int, case_id: int, user: dict, risk: dict, matches: list,
                               evidence: dict, pending: bool, db=None):
    channel_id = alt_intel.alts_channel_id(db, guild_id) if db is not None else alt_intel.yaml_alts_channel(guild_id)
    if not channel_id:
        logger.warning("No logs.alts channel for guild %s — skip Discord alt alert", guild_id)
        return
    label = {"critical": "CRÍTICO", "high": "ALTO", "medium": "MEDIO", "low": "BAJO"}.get(risk.get("label"), "?")
    color = {"critical": 0xFB7185, "high": 0xF97316, "medium": 0xFBBF24, "low": 0x34D399}.get(risk.get("label"), 0xFBBF24)
    lines = []
    for m in (matches or [])[:8]:
        reasons = ", ".join(m.get("reasons") or [])
        lines.append(f"• <@{m['user_id']}> `{m['user_id']}` — {m.get('score')}% · {reasons}")
    desc = (
        f"**Cuenta:** <@{user['user_id']}> `{user['user_id']}` · {user.get('username') or ''}\n"
        f"**Riesgo:** **{risk.get('score', 0)}/100 · {label}**\n"
        f"**Edad de cuenta:** {risk.get('age_days') if risk.get('age_days') is not None else '?'} días\n"
        f"**Red:** `{evidence.get('ip_code') or '—'} · {evidence.get('net_code') or '—'}`\n"
        f"**Cliente:** {evidence.get('ua_summary') or '—'}\n"
        f"**Estado:** {'pendiente de staff' if pending else 'auto-verificado'}\n"
    )
    if lines:
        desc += "\n**Cuentas ligadas**\n" + "\n".join(lines)
    body = {
        "embeds": [{
            "title": "🦞 Intento de verificación · multicuenta",
            "description": desc[:4000],
            "color": color,
            "footer": {"text": f"Caso #{case_id} · dabot.davito.es/verify"},
        }],
        "components": [{
            "type": 1,
            "components": [
                {"type": 2, "style": 3, "label": "Aprobar", "custom_id": f"dabot:alt:ok:{case_id}"},
                {"type": 2, "style": 2, "label": "Denegar", "custom_id": f"dabot:alt:no:{case_id}"},
                {"type": 2, "style": 4, "label": "Banear", "custom_id": f"dabot:alt:ban:{case_id}"},
                {"type": 2, "style": 1, "label": "Permitir siempre", "custom_id": f"dabot:alt:always:{case_id}"},
            ],
        }] if (pending or matches) else [],
    }
    try:
        msg = await discord_bot("POST", f"/channels/{channel_id}/messages", body)
        mid = msg.get("id")
        if mid:
            # attach later via caller with db
            return int(channel_id), int(mid)
    except Exception as e:
        logger.warning("alt case discord post failed: %s", e)
    return None


@app.post("/api/verify/complete")
async def api_verify_complete(payload: VerifyFingerprint, request: Request,
                              user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    try:
        guild_id = int(str(payload.guild_id).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Servidor inválido.")
    ip = alt_intel.client_ip(request.headers, request.client.host if request.client else "")
    if not _verify_rate_ok(ip or "0"):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos.")
    if (payload.website or "").strip():
        raise HTTPException(status_code=400, detail="Captcha inválido.")
    alt_intel.ensure_schema_sync(db)
    cur = db.cursor()
    cur.execute("SELECT answer, used, created_at FROM alt_captcha WHERE token = ?", (payload.challenge_token or "",))
    cap = cur.fetchone()
    if not cap:
        raise HTTPException(status_code=400, detail="Captcha caducado. Recarga la página.")
    answer = cap[0] if not hasattr(cap, "keys") else cap["answer"]
    used = cap[1] if not hasattr(cap, "keys") else cap["used"]
    created = cap[2] if not hasattr(cap, "keys") else cap["created_at"]
    if int(used or 0) == 1:
        raise HTTPException(status_code=400, detail="Captcha ya usado. Recarga.")
    try:
        age_s = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(str(created))).total_seconds()
        if age_s > 300:
            raise HTTPException(status_code=400, detail="Captcha caducado. Recarga la página.")
        if age_s < 0.8:
            raise HTTPException(status_code=400, detail="Demasiado rápido. Inténtalo de nuevo.")
    except HTTPException:
        raise
    except Exception:
        pass
    if payload.challenge_pick is None or int(payload.challenge_pick) != int(answer):
        raise HTTPException(status_code=400, detail="Captcha incorrecto. Pulsa la langosta 🦞.")
    cur.execute("UPDATE alt_captcha SET used = 1 WHERE token = ?", (payload.challenge_token,))
    db.commit()

    cookie_did = request.cookies.get("dabot_did") or ""
    js_did = (payload.js_device_id or "").strip()[:64]
    did = cookie_did or js_did or secrets.token_hex(16)
    fp = payload.dict()
    for k in ("guild_id", "js_device_id", "challenge_token", "challenge_pick", "website", "webrtc_ips"):
        fp.pop(k, None)

    intel, ip = await _inspect_request(
        request, webrtc_ips=payload.webrtc_ips or [], timezone=payload.timezone or "",
    )
    # Re-bind ip from trusted extractor (already done inside inspect). Keep CF country.
    ip = intel.get("ip") or ip
    proxy_extra = {
        "blocked": bool(intel.get("blocked")),
        "kinds": intel.get("kinds") or [],
        "reasons": intel.get("reasons") or [],
        "isp": intel.get("isp") or "",
        "org": intel.get("org") or "",
        "asn": intel.get("asn") or "",
        "city": intel.get("city") or "",
        "hosting": bool(intel.get("hosting")),
        "proxy_flag": bool(intel.get("proxy_flag")),
        "mobile": bool(intel.get("mobile")),
        "cf_country": intel.get("cf_country") or "",
        "webrtc": intel.get("webrtc") or [],
        "source": intel.get("source") or "",
    }
    try:
        result = alt_intel.record_sighting(
            db,
            user_id=int(user["user_id"]),
            guild_id=guild_id,
            username=user.get("username") or "",
            account_created=_snowflake_created(user["user_id"]),
            avatar_hash=user.get("avatar") or "",
            ip=ip,
            country=request.headers.get("cf-ipcountry") or request.headers.get("CF-IPCountry") or "",
            device_id=did,
            fingerprint=fp,
            user_agent=request.headers.get("user-agent") or "",
            source="verify",
        )
        if js_did and js_did != did:
            alt_intel.record_sighting(
                db,
                user_id=int(user["user_id"]),
                guild_id=guild_id,
                username=user.get("username") or "",
                account_created=_snowflake_created(user["user_id"]),
                ip=ip,
                device_id=js_did,
                fingerprint=fp,
                user_agent=request.headers.get("user-agent") or "",
                source="verify_js",
            )
    except Exception as e:
        logger.error("verify complete record failed: %s", e)
        raise HTTPException(status_code=500, detail="No se pudo registrar el dispositivo.")

    cursor = db.cursor()
    cursor.execute(
        "SELECT enabled, unverified_role_id, verified_role_id FROM verification_config WHERE guild_id = ?",
        (guild_id,),
    )
    cfg = cursor.fetchone()
    verified = False
    already = False
    in_guild = False
    pending = False
    guild_name = str(guild_id)
    try:
        ginfo = await discord_bot("GET", f"/guilds/{guild_id}")
        guild_name = ginfo.get("name") or guild_name
    except Exception:
        pass

    event_extra = {
        "code": "",
        "guild_name": guild_name,
        "proxy": proxy_extra,
        "ua": request.headers.get("user-agent") or "",
        "timezone": payload.timezone or "",
        "lang": payload.lang or "",
        "platform": payload.platform or "",
        "screen": payload.screen or "",
        "hardware": payload.hardware,
        "cf_country": request.headers.get("cf-ipcountry") or request.headers.get("CF-IPCountry") or "",
    }

    if intel.get("blocked"):
        try:
            await _record_verification_event(
                db,
                guild_id=guild_id,
                user_id=int(user["user_id"]),
                username=user.get("username") or "",
                avatar=user.get("avatar") or "",
                method="web",
                status="vpn",
                risk_score=None,
                risk_label=(intel.get("kinds") or ["vpn"])[0],
                ip=ip,
                ip_masked=(result.get("ip_masked") if isinstance(result, dict) else "") or "",
                country=intel.get("country") or event_extra["cf_country"],
                device_id=did,
                extra={**event_extra, "code": "vpn"},
            )
        except Exception as e:
            logger.warning("vpn verification log failed: %s", e)
        resp = JSONResponse({
            "verified": False,
            "already_verified": False,
            "pending": False,
            "in_guild": False,
            "guild_name": guild_name,
            "code": "vpn",
            "proxy": proxy_detect.public_payload(intel),
        })
        _set_device_cookie(resp, request)
        return resp

    matches = result.get("matches") or []
    device_accounts = alt_intel.accounts_on_device(db, did)
    candidate_ids = [int(user["user_id"])]
    for m in matches:
        try:
            candidate_ids.append(int(m["user_id"]))
        except (TypeError, ValueError, KeyError):
            pass
    candidate_ids.extend(device_accounts)
    present = await discord_members_present(guild_id, candidate_ids)
    present.add(int(user["user_id"]))
    matches = alt_intel.matches_in_guild(matches, present)
    device_n = len([u for u in device_accounts if int(u) in present])
    risk = alt_intel.compute_risk(
        matches,
        account_created=_snowflake_created(user["user_id"]),
        user_id=int(user["user_id"]),
        device_account_count=device_n,
    )
    policy = alt_intel.get_policy(db, guild_id, int(user["user_id"]))
    linked_allow = False
    for m in matches:
        if alt_intel.get_policy(db, guild_id, int(m["user_id"])) == "allow_always":
            linked_allow = True
            break

    detected = bool(matches)
    auto_ok = (not detected) or policy == "allow_always" or linked_allow
    if policy == "deny":
        auto_ok = False
    hold = detected and not auto_ok

    ip_codes = alt_intel.public_ip_codes(ip)
    evidence = {
        "ip_code": ip_codes.get("exact"),
        "net_code": ip_codes.get("net"),
        "country": (intel.get("cf_country") or intel.get("country") or "")[:8],
        "ua_summary": alt_intel.ua_summary(request.headers.get("user-agent") or ""),
        "device_accounts": device_n,
    }
    case_id = None
    if detected:
        case_id = alt_intel.create_case(
            db,
            guild_id=guild_id,
            user_id=int(user["user_id"]),
            username=user.get("username") or "",
            risk=risk,
            matches=matches,
            evidence=evidence,
        )
        posted = await _post_alt_case_embed(
            guild_id, case_id, user, risk, matches, evidence, pending=hold, db=db,
        )
        if posted:
            alt_intel.attach_case_message(db, case_id, posted[0], posted[1])
        try:
            cursor.execute(
                """INSERT INTO audit_events (guild_id, event_type, actor_id, target_id, channel_id, summary, extra, timestamp)
                   VALUES (?, 'verification', ?, ?, NULL, ?, ?, ?)""",
                (
                    guild_id, user["user_id"], user["user_id"],
                    f"Verificación riesgo {risk['score']}/100 ({risk['label']}) · {len(matches)} ligadas",
                    json.dumps({"case_id": case_id, "matches": matches[:8], "risk": risk}, ensure_ascii=False),
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            db.commit()
        except Exception as e:
            logger.warning("alt audit write failed: %s", e)

    message = "noconfig"
    if cfg and int(cfg[0] or 0) == 1:
        unverified_id, verified_id = int(cfg[1]), int(cfg[2])
        try:
            member = await discord_bot("GET", f"/guilds/{guild_id}/members/{user['user_id']}")
            in_guild = True
            roles = [int(r) for r in member.get("roles", [])]
            if verified_id in roles:
                already = True
                verified = True
                message = "already"
            elif hold:
                pending = True
                message = "pending"
            else:
                roles.append(verified_id)
                roles = [r for r in roles if r != unverified_id]
                await discord_bot(
                    "PATCH",
                    f"/guilds/{guild_id}/members/{user['user_id']}",
                    {"roles": [str(r) for r in roles]},
                )
                verified = True
                message = "ok"
        except HTTPException as e:
            message = "role"
            logger.warning("verify role grant failed: %s", e.detail)
        except Exception as e:
            message = "role"
            logger.warning("verify role grant failed: %s", e)

    resp = {
        "verified": verified,
        "already_verified": already,
        "pending": pending,
        "in_guild": in_guild,
        "guild_name": guild_name,
        "code": message,
        "matches": len(matches),
        "risk": risk,
        "case_id": case_id,
    }
    status_map = {
        "ok": "ok",
        "already": "already",
        "pending": "pending",
        "role": "fail",
        "noconfig": "fail",
    }
    try:
        await _record_verification_event(
            db,
            guild_id=guild_id,
            user_id=int(user["user_id"]),
            username=user.get("username") or "",
            avatar=user.get("avatar") or "",
            method="web",
            status=status_map.get(message, "ok"),
            risk_score=(risk or {}).get("score"),
            risk_label=(risk or {}).get("label") or "",
            ip=ip,
            ip_masked=result.get("ip_masked") or "",
            country=result.get("country") or request.headers.get("cf-ipcountry") or request.headers.get("CF-IPCountry") or "",
            device_id=did,
            case_id=case_id,
            extra={**event_extra, "code": message, "matches": len(matches)},
        )
    except Exception as e:
        logger.warning("verification complete log failed: %s", e)
    response = JSONResponse(resp)
    _set_device_cookie(response, request)
    return response


_ALT_ACTION_STATUS = {"ok": "approved", "no": "denied", "ban": "banned", "always": "allow_always"}
_ALT_ACTION_COLOR = {"ok": 0x00FF88, "always": 0x00FF88, "no": 0xF97316, "ban": 0xFB7185}


async def _patch_alt_case_message(case: dict, result_txt: str, actor: dict, new_status: str, color: int):
    ch, mid = case.get("channel_id"), case.get("message_id")
    if not ch or not mid:
        return
    uname = actor.get("username") or str(actor.get("user_id"))
    desc = (
        f"**Cuenta:** <@{case.get('user_id')}> `{case.get('user_id')}` · {case.get('username') or ''}\n"
        f"**Riesgo:** **{case.get('score', 0)}/100 · {(case.get('risk') or '').upper()}**\n"
        f"**Resolución:** {result_txt}\n"
        f"Por **{uname}** (`{actor.get('user_id')}`) desde el panel · `{new_status}`"
    )
    try:
        await discord_bot("PATCH", f"/channels/{ch}/messages/{mid}", {
            "embeds": [{
                "title": "🦞 Caso de multicuenta resuelto",
                "description": desc[:4000],
                "color": color,
                "footer": {"text": f"Caso #{case.get('id')} · dabot.davito.es"},
            }],
            "components": [],
        })
    except Exception as e:
        logger.warning("alt case discord patch failed: %s", e)


async def _grant_verified_roles(guild_id: int, target_id: int, db: sqlite3.Connection) -> str:
    cursor = db.cursor()
    cursor.execute(
        "SELECT unverified_role_id, verified_role_id FROM verification_config WHERE guild_id = ?",
        (int(guild_id),),
    )
    cfg = cursor.fetchone()
    if not cfg:
        return " (sin configuración de verificación)"
    unverified_id = int(cfg[0] or 0)
    verified_id = int(cfg[1] or 0)
    try:
        member = await discord_bot("GET", f"/guilds/{guild_id}/members/{target_id}")
    except Exception:
        return " (el usuario no está en el servidor)"
    roles = [str(r) for r in (member.get("roles") or [])]
    if unverified_id and str(unverified_id) in roles:
        roles = [r for r in roles if r != str(unverified_id)]
    if verified_id and str(verified_id) not in roles:
        roles.append(str(verified_id))
    try:
        await discord_bot("PATCH", f"/guilds/{guild_id}/members/{target_id}", {"roles": roles})
    except Exception as e:
        logger.warning("alt case role grant failed: %s", e)
        return " (no pude cambiar roles: jerarquía o permisos)"
    return ""


async def apply_alt_case_action(db: sqlite3.Connection, case_id: int, action: str, actor: dict) -> dict:
    action = (action or "").strip().lower()
    if action not in _ALT_ACTION_STATUS:
        raise HTTPException(status_code=400, detail="Acción inválida. Usa ok, no, ban o always.")
    row = alt_intel.get_case(db, case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Caso no encontrado.")
    case = alt_intel.serialize_case(row, show_full_ip=True)
    if case["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"El caso ya está resuelto ({case['status']}).")
    guild_id = int(case["guild_id"])
    target_id = int(case["user_id"])
    new_status = _ALT_ACTION_STATUS[action]
    note = ""
    if action in ("ok", "always"):
        note = await _grant_verified_roles(guild_id, target_id, db)
        if action == "always":
            alt_intel.set_policy(db, guild_id, target_id, "allow_always", actor["user_id"])
            result_txt = f"Permitido siempre meter multicuentas.{note}"
        else:
            result_txt = f"Multicuenta aprobada. Acceso concedido.{note}"
    elif action == "no":
        alt_intel.set_policy(db, guild_id, target_id, "deny", actor["user_id"])
        result_txt = "Multicuenta denegada. Se queda sin rol verificado."
    else:
        try:
            await discord_bot(
                "PUT",
                f"/guilds/{guild_id}/bans/{target_id}",
                {"delete_message_seconds": 0, "reason": f"Multicuenta caso #{case_id} desde el panel"},
            )
            result_txt = "Usuario baneado por multicuenta."
        except HTTPException as e:
            raise HTTPException(status_code=400, detail=f"No se pudo banear: {e.detail}")
        try:
            db.execute(
                """INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp, status)
                   VALUES (?, ?, ?, 'ban', ?, ?, 'active')""",
                (
                    target_id, guild_id, actor["user_id"],
                    f"Multicuenta caso #{case_id} desde el panel",
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            db.commit()
        except Exception as e:
            logger.warning("alt case infraction write failed: %s", e)

    alt_intel.resolve_case(db, case_id, new_status, actor["user_id"])
    await _patch_alt_case_message(case, result_txt, actor, new_status, _ALT_ACTION_COLOR[action])
    try:
        v_status = "ok" if action in ("ok", "always") else "denied"
        await _record_verification_event(
            db,
            guild_id=guild_id,
            user_id=target_id,
            username=case.get("username") or "",
            avatar="",
            method="alt_approve",
            status=v_status,
            risk_score=case.get("score"),
            risk_label=case.get("risk") or "",
            ip=alt_intel.ip_meta(str(case.get("ip") or "").split()[0]).get("ip_full") or "",
            case_id=case_id,
            actor_id=actor["user_id"],
            extra={"action": action, "new_status": new_status, "source": "dashboard"},
        )
    except Exception as e:
        logger.warning("alt verification log failed: %s", e)
    try:
        db.execute(
            """INSERT INTO audit_events (guild_id, event_type, actor_id, target_id, channel_id, summary, extra, timestamp)
               VALUES (?, 'alts', ?, ?, NULL, ?, ?, ?)""",
            (
                guild_id, actor["user_id"], target_id,
                f"Caso #{case_id} → {new_status}",
                json.dumps({"case_id": case_id, "action": action, "status": new_status}, ensure_ascii=False),
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        db.commit()
    except Exception as e:
        logger.warning("alt case audit write failed: %s", e)
    case["status"] = new_status
    case["resolved_by"] = str(actor["user_id"])
    return {"status": "success", "case_id": case_id, "new_status": new_status, "message": result_txt, "case": case}


def _guild_name_map(guilds: list[dict]) -> dict[str, str]:
    return {str(g.get("id")): (g.get("name") or str(g.get("id"))) for g in guilds}


@app.get("/api/guilds/{guild_id}/alts")
async def api_guild_alts(guild_id: int, q: str | None = None, user=Depends(get_current_user),
                         db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "kick", "ban", "warn", "manage_config"])
    show_full = user["user_id"] == SUPER_OWNER_ID
    alerts = alt_intel.recent_alerts(db, current_guild=guild_id, viewer_id=user["user_id"], limit=40)
    digits = "".join(ch for ch in (q or "") if ch.isdigit())
    uid = int(digits) if digits else None
    cases = alt_intel.list_cases(
        db, guild_id=guild_id, user_id=uid, limit=50, show_full_ip=show_full,
    )
    dossier = None
    if uid:
        dossier = alt_intel.user_dossier(db, uid, current_guild=guild_id, viewer_id=user["user_id"])
    dossier, alerts, cases = await _scope_alts_to_guild_members(guild_id, dossier, alerts, cases)
    net = int(guild_id) in alt_intel.network_guilds(db)
    return {
        "network": net,
        "is_super_owner": show_full,
        "alerts": alerts,
        "cases": cases,
        "dossier": dossier,
        "alts_scope": "guild_members",
    }


@app.get("/api/guilds/{guild_id}/alts/{user_id}")
async def api_guild_alt_user(guild_id: int, user_id: int, user=Depends(get_current_user),
                             db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "kick", "ban", "warn", "manage_config"])
    dossier = alt_intel.user_dossier(db, user_id, current_guild=guild_id, viewer_id=user["user_id"])
    dossier, _, _ = await _scope_alts_to_guild_members(guild_id, dossier, None, None)
    return dossier


@app.post("/api/guilds/{guild_id}/alts/cases/{case_id}")
async def api_guild_alt_resolve(guild_id: int, case_id: int, payload: AltCaseActionPayload,
                               user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    await require_guild_staff(user, guild_id, db, extra=["ban", "kick", "warn", "manage_config"])
    row = alt_intel.get_case(db, case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Caso no encontrado.")
    case = alt_intel.serialize_case(row)
    if int(case["guild_id"]) != int(guild_id):
        raise HTTPException(status_code=403, detail="Este caso no es de este servidor.")
    return await apply_alt_case_action(db, case_id, payload.action, user)


@app.get("/api/admin/alts")
async def api_admin_alts(status: str | None = None, guild_id: int | None = None,
                         q: str | None = None, limit: int = 80,
                         user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede ver todos los casos.")
    digits = "".join(ch for ch in (q or "") if ch.isdigit())
    uid = int(digits) if digits and len(digits) >= 15 else None
    gid = guild_id
    if uid is None and digits and len(digits) >= 17 and guild_id is None:
        # snowflake could be a guild id typed in the search box
        try:
            probe = int(digits)
            names = {int(g["id"]) for g in await fetch_bot_guild_objects()}
            if probe in names:
                gid = probe
        except Exception:
            pass
    cases = alt_intel.list_cases(
        db, guild_id=gid, status=status or None, user_id=uid, limit=limit, show_full_ip=True,
    )
    guilds = await fetch_bot_guild_objects()
    names = _guild_name_map(guilds)
    for c in cases:
        c["guild_name"] = names.get(c.get("guild_id") or "", c.get("guild_id") or "")
    dossier = None
    if uid:
        dossier = alt_intel.user_dossier(db, uid, current_guild=None, viewer_id=user["user_id"])
    alerts = alt_intel.recent_alerts(db, current_guild=0, viewer_id=user["user_id"], limit=40)
    for a in alerts:
        a["guild_name"] = names.get(a.get("guild_id") or "", a.get("guild_id") or "")
    return {
        "is_super_owner": True,
        "stats": alt_intel.overview_stats(db),
        "cases": cases,
        "alerts": alerts,
        "dossier": dossier,
        "guilds": [{"id": g["id"], "name": g.get("name") or g["id"]} for g in guilds],
    }


@app.post("/api/admin/alts/cases/{case_id}")
async def api_admin_alt_resolve(case_id: int, payload: AltCaseActionPayload,
                               user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede resolver desde Admin global.")
    return await apply_alt_case_action(db, case_id, payload.action, user)


@app.post("/api/admin/alt-network")
async def api_admin_alt_network(payload: AltNetworkPayload, user=Depends(get_current_user),
                                db: sqlite3.Connection = Depends(get_db)):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el super owner puede aprobar la red de inteligencia.")
    alt_intel.set_network(db, payload.guild_id, payload.enabled, user["user_id"], payload.note)
    return {"status": "success", "guild_id": str(payload.guild_id), "enabled": payload.enabled}


@app.get("/api/guilds/{guild_id}/verifications")
async def api_guild_verifications(
    guild_id: int,
    q: str | None = None,
    method: str | None = None,
    status: str | None = None,
    people: int = 1,
    limit: int = 120,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    await require_guild_staff(user, guild_id, db, extra=["view_infractions", "kick", "ban", "warn", "manage_config"])
    show_full = user["user_id"] == SUPER_OWNER_ID
    verify_log.ensure_schema_sync(db)
    stats = verify_log.stats_sync(db, guild_id)
    people_rows = verify_log.list_people_sync(
        db, guild_id=guild_id, q=q, limit=min(int(limit or 120), 400), show_full_ip=show_full,
    )
    events = verify_log.list_events_sync(
        db,
        guild_id=guild_id,
        method=method or None,
        status=status or None,
        q=q,
        limit=min(int(limit or 120), 400),
        show_full_ip=show_full,
    )
    log_ch = verify_log.channel_id_sync(db, guild_id)
    return {
        "is_super_owner": show_full,
        "stats": stats,
        "people": people_rows,
        "events": events,
        "log_channel_id": str(log_ch) if log_ch else "",
    }


@app.get("/api/admin/verifications")
async def api_admin_verifications(
    q: str | None = None,
    guild_id: int | None = None,
    method: str | None = None,
    status: str | None = None,
    limit: int = 150,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede ver todas las verificaciones.")
    verify_log.ensure_schema_sync(db)
    events = verify_log.list_events_sync(
        db,
        guild_id=guild_id,
        method=method or None,
        status=status or None,
        q=q,
        limit=min(int(limit or 150), 400),
        show_full_ip=True,
    )
    stats = verify_log.stats_sync(db, guild_id)
    guilds = await fetch_bot_guild_objects()
    names = _guild_name_map(guilds)
    for e in events:
        e["guild_name"] = names.get(e.get("guild_id") or "", e.get("guild_id") or "")
    people = []
    if guild_id:
        people = verify_log.list_people_sync(db, guild_id=int(guild_id), q=q, limit=200, show_full_ip=True)
        for p in people:
            p["guild_name"] = names.get(p.get("guild_id") or "", p.get("guild_id") or "")
    return {
        "is_super_owner": True,
        "stats": stats,
        "events": events,
        "people": people,
        "guilds": [{"id": g["id"], "name": g.get("name") or g["id"]} for g in guilds],
    }


@app.get("/api/admin/verifications/{event_id}")
async def api_admin_verification_one(
    event_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede ver el detalle completo.")
    row = verify_log.get_event_sync(db, event_id, show_full_ip=True)
    if not row:
        raise HTTPException(status_code=404, detail="Verificación no encontrada.")
    names = _guild_name_map(await fetch_bot_guild_objects())
    row["guild_name"] = names.get(row.get("guild_id") or "", row.get("guild_id") or "")
    return row


# --- SUPERUSER GDPR / PRIVACY MANAGEMENT ENDPOINTS ---

@app.get("/api/admin/privacy_requests")
async def api_admin_privacy_requests(
    status: str | None = None,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede gestionar solicitudes RGPD.")
    
    cur = db.cursor()
    if status:
        cur.execute(
            "SELECT id, user_id, user_name, request_type, status, data_snapshot, requested_at, processed_at, processed_by, encrypted_ip_backup, admin_notes FROM privacy_requests WHERE status = ? ORDER BY id DESC LIMIT 150",
            (status,)
        )
    else:
        cur.execute(
            "SELECT id, user_id, user_name, request_type, status, data_snapshot, requested_at, processed_at, processed_by, encrypted_ip_backup, admin_notes FROM privacy_requests ORDER BY id DESC LIMIT 150"
        )
    
    cols = ["id", "user_id", "user_name", "request_type", "status", "data_snapshot", "requested_at", "processed_at", "processed_by", "encrypted_ip_backup", "admin_notes"]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"ok": True, "requests": rows}


@app.post("/api/admin/privacy_requests/{request_id}/approve")
async def api_admin_privacy_approve(
    request_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede aprobar solicitudes RGPD.")
    
    cur = db.cursor()
    cur.execute("SELECT user_id, request_type, status FROM privacy_requests WHERE id = ?", (request_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    
    target_user_id = row[0]
    from utils.privacy_crypto import execute_gdpr_erasure_sync
    result = execute_gdpr_erasure_sync(
        db,
        user_id=target_user_id,
        processed_by=user["user_id"],
        admin_notes=f"Aprobado formalmente por superusuario ({user.get('username', 'admin')})"
    )
    return {"ok": True, "message": "Datos personales eliminados con éxito y copia de seguridad de IP encriptada.", "detail": result}


@app.post("/api/admin/privacy_requests/{request_id}/reject")
async def api_admin_privacy_reject(
    request_id: int,
    payload: dict = Body(default={}),
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede rechazar solicitudes RGPD.")
    
    cur = db.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    reason = payload.get("reason", "Denegado por el administrador según directrices de seguridad.")
    cur.execute(
        "UPDATE privacy_requests SET status = 'rejected', processed_at = ?, processed_by = ?, admin_notes = ? WHERE id = ?",
        (now_iso, user["user_id"], reason, request_id)
    )
    db.commit()
    return {"ok": True, "message": "Solicitud rechazada."}


@app.post("/api/admin/privacy/manual_deletion")
async def api_admin_privacy_manual_deletion(
    payload: dict = Body(...),
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    if user["user_id"] != SUPER_OWNER_ID:
        raise HTTPException(status_code=403, detail="Solo el superusuario puede ejecutar eliminaciones manuales.")
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Debe especificar user_id.")
    
    try:
        uid = int(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id inválido.")
        
    notes = payload.get("notes", "Eliminación forzosa manual solicitada desde dashboard.")
    from utils.privacy_crypto import execute_gdpr_erasure_sync
    result = execute_gdpr_erasure_sync(
        db,
        user_id=uid,
        processed_by=user["user_id"],
        admin_notes=notes
    )
    return {
        "ok": True,
        "message": f"Eliminación forzosa ejecutada para el usuario {uid}. Datos personales suprimidos e IP respaldada de forma encriptada.",
        "detail": result
    }


# --- SERVING STATIC FRONTEND FILES ---

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=FileResponse)
def home_page():
    return FileResponse("templates/index.html")

@app.get("/dashboard", response_class=FileResponse)
def dashboard_page(session_id: str = Cookie(None)):
    if not session_id:
        return RedirectResponse("/login")
    return FileResponse("templates/dashboard.html")

@app.get("/help", response_class=FileResponse)
def help_page():
    return FileResponse("templates/help.html")

@app.get("/comunidad", response_class=FileResponse)
def comunidad_page():
    return FileResponse("templates/comunidad.html")

@app.get("/servers", response_class=FileResponse)
def servers_page():
    return FileResponse("templates/servers.html")

@app.get("/niveles", response_class=FileResponse)
def niveles_page():
    return FileResponse("templates/niveles.html")

@app.get("/normas", response_class=FileResponse)
def normas_page():
    return FileResponse("templates/normas.html")

@app.get("/cuenta", response_class=FileResponse)
def cuenta_page(session_id: str = Cookie(None)):
    if not session_id:
        return RedirectResponse("/login")
    return FileResponse("templates/cuenta.html")

@app.get("/premium", response_class=FileResponse)
def premium_page():
    return FileResponse("templates/premium.html")

@app.get("/privacy", response_class=FileResponse)
def privacy_page():
    return FileResponse("templates/privacy.html")

@app.get("/cookies", response_class=FileResponse)
def cookies_page():
    return FileResponse("templates/cookies.html")

@app.get("/terms", response_class=FileResponse)
def terms_page():
    return FileResponse("templates/terms.html")

@app.get("/invite")
def invite_redirect():
    if not DISCORD_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Client ID no configurado")
    return RedirectResponse(invite_url(DISCORD_CLIENT_ID))

@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("https://davito.es/media/dabot.png")
