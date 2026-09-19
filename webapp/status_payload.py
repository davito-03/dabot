"""Pure status payload. No FastAPI/discord imports so tests run on a bare host."""
from __future__ import annotations

import datetime
import os

DASHBOARD_URL = "https://dabot.davito.es"
BOT_INVITE_PERMISSIONS = 2186104270071


def _invite_url(client_id: str) -> str:
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={client_id}"
        f"&permissions={BOT_INVITE_PERMISSIONS}"
        "&scope=bot%20applications.commands"
    )


def heartbeat_online(updated) -> bool:
    if not updated:
        return False
    try:
        updated_dt = datetime.datetime.fromisoformat(updated)
        if updated_dt.tzinfo is None:
            delta = datetime.datetime.utcnow() - updated_dt
        else:
            delta = datetime.datetime.now(datetime.timezone.utc) - updated_dt
        return delta.total_seconds() < 300
    except Exception:
        return False


def assemble_status(row, live: dict | None, *, heartbeat: bool, now_iso: str) -> dict:
    client_id = os.environ.get("DISCORD_CLIENT_ID", "")
    payload = {
        "online": False,
        "latency_ms": None,
        "gateway_latency_ms": None,
        "guilds": 0,
        "users": 0,
        "commands": 0,
        "started_at": None,
        "updated_at": None,
        "version": "3.1.0",
        "username": "Dabot",
        "invite_url": _invite_url(client_id) if client_id else None,
        "dashboard": DASHBOARD_URL,
        "client_id": client_id,
        "checked_at": now_iso,
        "source": "heartbeat",
    }
    if row:
        payload.update(
            {
                "gateway_latency_ms": row["latency_ms"],
                "latency_ms": row["latency_ms"],
                "guilds": row["guilds"] or 0,
                "users": row["users"] or 0,
                "commands": row["commands"] or 0,
                "started_at": row["started_at"],
                "updated_at": row["updated_at"],
                "version": row["version"] or "3.1.0",
                "username": row["username"] or "Dabot",
            }
        )
    live_ok = bool(live and live.get("ok"))
    if live:
        if live.get("latency_ms") is not None:
            payload["latency_ms"] = live["latency_ms"]
            payload["source"] = "live"
        if live.get("guilds") is not None:
            payload["guilds"] = live["guilds"]
        if live.get("users") is not None:
            payload["users"] = live["users"]
    payload["online"] = bool(live_ok or heartbeat)
    payload["checked_at"] = now_iso
    return payload
