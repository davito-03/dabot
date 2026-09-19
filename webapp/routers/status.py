"""Public bot status. Isolated so dashboard_server.py is not the only entry."""
from __future__ import annotations

import asyncio
import datetime
import os
import sqlite3
import time

import aiohttp
from fastapi import APIRouter, Depends

from webapp.deps import get_db
from webapp.status_payload import assemble_status, heartbeat_online

router = APIRouter()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
DISCORD_USER_AGENT = "DiscordBot (https://dabot.davito.es, 3.1.0)"
_LIVE_STATUS_TTL = 55.0
_live_status_cache: dict = {"ts": 0.0, "data": None}
_live_status_lock = asyncio.Lock()


async def _probe_discord_live() -> dict:
    out = {"ok": False, "latency_ms": None, "guilds": None, "users": None}
    if not DISCORD_TOKEN:
        return out
    try:
        timeout = aiohttp.ClientTimeout(total=8, connect=4)
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "User-Agent": DISCORD_USER_AGENT}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            t0 = time.perf_counter()
            async with session.get("https://discord.com/api/v10/gateway/bot", headers=headers) as res:
                ping_ms = int((time.perf_counter() - t0) * 1000)
                if res.status == 200:
                    out["ok"] = True
                    out["latency_ms"] = ping_ms
            async with session.get(
                "https://discord.com/api/v10/users/@me/guilds?with_counts=true",
                headers=headers,
            ) as res:
                if res.status == 200:
                    guilds = await res.json()
                    if isinstance(guilds, list):
                        out["guilds"] = len(guilds)
                        out["users"] = sum(int(g.get("approximate_member_count") or 0) for g in guilds)
    except Exception:
        return out
    return out


@router.get("/api/status")
async def public_bot_status(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        "SELECT latency_ms, guilds, users, commands, started_at, updated_at, version, username "
        "FROM bot_runtime WHERE id = 1"
    )
    row = cursor.fetchone()
    now = time.monotonic()
    live = None
    if _live_status_cache["data"] and (now - _live_status_cache["ts"]) < _LIVE_STATUS_TTL:
        live = _live_status_cache["data"]
    else:
        async with _live_status_lock:
            now = time.monotonic()
            if _live_status_cache["data"] and (now - _live_status_cache["ts"]) < _LIVE_STATUS_TTL:
                live = _live_status_cache["data"]
            else:
                live = await _probe_discord_live()
                _live_status_cache["ts"] = time.monotonic()
                _live_status_cache["data"] = live
    return assemble_status(
        row,
        live,
        heartbeat=heartbeat_online(row["updated_at"] if row else None),
        now_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
