"""Anti-abuse helpers: rate limits, owner alerts, global user/guild bans.

Discord never gives bots an IP. If the dashboard or web verification saw one,
alerts include it; otherwise they say it is unknown.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
from collections import defaultdict, deque

import discord

log = logging.getLogger("Dabot.Abuse")

ALERT_GUILD = 1413959468365905962
ALERT_CHANNEL = 1543255775655239741
ALERT_USER = 600041740124160011
PROTECTED_GUILDS = {ALERT_GUILD}

URL_RE = re.compile(r"https?://[^\s<>\]]+", re.IGNORECASE)


def super_owner_id(bot=None) -> int:
    if bot and getattr(bot, "super_owner_id", 0):
        try:
            return int(bot.super_owner_id)
        except (TypeError, ValueError):
            pass
    try:
        return int(os.getenv("SUPER_OWNER_ID", str(ALERT_USER)) or ALERT_USER)
    except (TypeError, ValueError):
        return ALERT_USER


def extract_urls(text: str) -> list[str]:
    return [m.rstrip(").,]>\"'") for m in URL_RE.findall(text or "")]


class AbuseGuard:
    def __init__(self, bot):
        self.bot = bot
        self.events = defaultdict(deque)
        self.alert_at = {}
        self.pause_until = {}
        self._ip_cache = {}

    async def setup(self):
        await self.bot.db.execute(
            """CREATE TABLE IF NOT EXISTS guild_blacklist (
                guild_id INTEGER PRIMARY KEY,
                reason TEXT,
                timestamp TEXT,
                banned_by INTEGER
            )"""
        )

    def now(self) -> float:
        return datetime.datetime.now(datetime.timezone.utc).timestamp()

    def _prune(self, key: str, window: int):
        dq = self.events[key]
        cutoff = self.now() - window
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        return dq

    def record(self, key: str, extra=None):
        self.events[key].append((self.now(), extra))

    def count(self, key: str, window: int, unique: bool = False) -> int:
        dq = self._prune(key, window)
        if unique:
            return len({item[1] for item in dq if item[1] is not None})
        return len(dq)

    def pause(self, key: str, seconds: int):
        self.pause_until[key] = self.now() + seconds

    def is_paused(self, key: str) -> bool:
        return self.pause_until.get(key, 0) > self.now()

    def is_owner(self, user_id) -> bool:
        try:
            return int(user_id) == super_owner_id(self.bot)
        except (TypeError, ValueError):
            return False

    async def user_banned(self, user_id) -> bool:
        if not user_id or self.is_owner(user_id):
            return False
        try:
            row = await self.bot.db.fetch("SELECT user_id FROM blacklist WHERE user_id = ?", int(user_id))
            return bool(row)
        except Exception:
            return False

    async def guild_banned(self, guild_id) -> bool:
        if not guild_id:
            return False
        try:
            row = await self.bot.db.fetch(
                "SELECT guild_id FROM guild_blacklist WHERE guild_id = ?", int(guild_id)
            )
            return bool(row)
        except Exception:
            return False

    async def lookup_ip(self, user_id):
        if not user_id:
            return None
        cached = self._ip_cache.get(int(user_id))
        if cached and cached[0] > self.now():
            return cached[1]
        info = None
        try:
            row = await self.bot.db.fetch(
                """SELECT ip_full, country, created_at FROM alt_sightings
                   WHERE user_id = ? AND ip_full IS NOT NULL AND trim(ip_full) != ''
                   ORDER BY created_at DESC LIMIT 1""",
                int(user_id),
            )
            if row and row[0]:
                info = {"ip": row[0], "country": row[1] or "", "at": row[2] or ""}
        except Exception:
            info = None
        self._ip_cache[int(user_id)] = (self.now() + 300, info)
        return info

    def note_command(self, user_id, guild_id) -> bool:
        """Record a command. True if this user is flooding commands."""
        if self.is_owner(user_id):
            return False
        if self.is_paused(f"user:{user_id}"):
            return True
        key = f"cmd:{user_id}"
        dq = self._prune(key, 45)
        if dq and self.now() - dq[-1][0] < 0.5:
            return False
        self.record(key, guild_id)
        if self.count(key, 45) > 28:
            self.pause(f"user:{user_id}", 120)
            return True
        return False

    def link_fanout(self, *, guild_id, actor_id, dest_id, text: str, limit: int = 4, window: int = 900):
        """Same URL sent to many destinations. Returns the URL if it should be capped."""
        urls = extract_urls(text)
        if not urls or self.is_owner(actor_id):
            return None
        tripped = None
        for url in urls:
            key = f"link:{guild_id}:{url.lower()}"
            self.record(key, dest_id)
            if self.count(key, window, unique=True) >= limit:
                tripped = url
        return tripped

    async def allow_outbound(self, *, guild, actor_id, dest_id, text: str, kind: str = "dm") -> bool:
        """Block copy-pasted links to many people; allow the same text without links."""
        if self.is_owner(actor_id):
            return True
        gid = getattr(guild, "id", guild) or 0
        limit = 3 if kind == "sanction" else 6
        url = self.link_fanout(
            guild_id=gid, actor_id=actor_id, dest_id=dest_id, text=text, limit=limit
        )
        if not url:
            return True
        await self.alert(
            kind=f"link_fanout_{kind}",
            details=f"Mismo enlace enviado a varios destinos (`{kind}`).\n`{url[:300]}`",
            user_id=actor_id,
            guild_id=gid,
            extra={"destino": dest_id, "url": url[:300]},
        )
        return False

    async def alert(self, *, kind: str, details: str, user_id=None, guild_id=None, extra=None):
        cooldown_key = (kind, int(user_id or 0), int(guild_id or 0))
        now = self.now()
        if now - self.alert_at.get(cooldown_key, 0) < 15 * 60:
            return
        self.alert_at[cooldown_key] = now

        channel = self.bot.get_channel(ALERT_CHANNEL)
        if channel is None:
            g = self.bot.get_guild(ALERT_GUILD)
            if g:
                channel = g.get_channel(ALERT_CHANNEL)
        if channel is None:
            log.warning("Abuse alert channel %s not found", ALERT_CHANNEL)
            return

        guild = self.bot.get_guild(int(guild_id)) if guild_id else None
        ip_info = await self.lookup_ip(user_id) if user_id else None
        ip_txt = "no registrada"
        if ip_info and ip_info.get("ip"):
            ip_txt = ip_info["ip"]
            if ip_info.get("country"):
                ip_txt += f" ({ip_info['country']})"
            if ip_info.get("at"):
                ip_txt += f"\nvista {str(ip_info['at'])[:19]}"

        embed = discord.Embed(
            title="Posible abuso de Dabot",
            description=(details or "")[:2000],
            color=0xF97316,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="ID del usuario",
            value=f"`{user_id}`" if user_id else "desconocido",
            inline=True,
        )
        embed.add_field(
            name="ID del servidor",
            value=f"`{guild_id}`" if guild_id else "desconocido",
            inline=True,
        )
        embed.add_field(name="IP del usuario", value=ip_txt[:200], inline=True)
        if user_id:
            embed.add_field(name="Usuario", value=f"<@{user_id}>", inline=True)
        if guild:
            embed.add_field(
                name="Servidor",
                value=f"{guild.name}\n{guild.member_count or '?'} miembros",
                inline=True,
            )
        if extra:
            for k, v in list(extra.items())[:6]:
                if v is None or v == "":
                    continue
                embed.add_field(name=str(k)[:40], value=str(v)[:500], inline=False)
        embed.set_footer(text=f"kind={kind}")

        try:
            await channel.send(content=f"<@{ALERT_USER}>", embed=embed)
        except Exception as e:
            log.warning("Could not send abuse alert: %s", e)


def guard(bot) -> AbuseGuard | None:
    return getattr(bot, "abuse", None)
