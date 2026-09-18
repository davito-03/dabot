"""Weekly staff digest: sanctions, tickets, hijacks, alts."""
from __future__ import annotations

import datetime
import logging

import discord
from discord.ext import commands, tasks
from utils.helpers import DASHBOARD_URL, DABOT_GREEN

log = logging.getLogger("Dabot.Digest")


class Digest(commands.Cog):
    """Resumen semanal para el staff del servidor."""

    def __init__(self, bot):
        self.bot = bot
        self.weekly.start()

    def cog_unload(self):
        self.weekly.cancel()

    async def _week_lock(self, guild_id: int, week: str) -> bool:
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS digest_sent (guild_id INTEGER, week TEXT, PRIMARY KEY (guild_id, week))"
        )
        try:
            await self.bot.db.execute(
                "INSERT INTO digest_sent (guild_id, week) VALUES (?, ?)",
                guild_id, week,
            )
            return True
        except Exception:
            return False

    def _channel(self, guild: discord.Guild):
        logs = (self.bot.config.get(guild.id) or {}).get("logs") or {}
        for key in ("digest", "moderation", "hijack", "members"):
            raw = logs.get(key)
            if raw:
                ch = guild.get_channel(int(raw))
                if ch:
                    return ch
        return None

    @tasks.loop(hours=24)
    async def weekly(self):
        now = datetime.datetime.utcnow()
        if now.weekday() != 0:  # Monday
            return
        if now.hour < 17 or now.hour > 19:
            return
        week = now.strftime("%G-W%V")
        since = (now - datetime.timedelta(days=7)).isoformat()
        for guild in list(self.bot.guilds):
            ch = self._channel(guild)
            if not ch:
                continue
            if not await self._week_lock(guild.id, week):
                continue
            try:
                inf = await self.bot.db.fetch(
                    "SELECT COUNT(*) FROM infractions WHERE guild_id = ? AND timestamp >= ?",
                    guild.id, since,
                )
                hij = await self.bot.db.fetch(
                    "SELECT COUNT(*) FROM hijack_events WHERE guild_id = ? AND created_at >= ?",
                    guild.id, since,
                )
                alts = await self.bot.db.fetch(
                    "SELECT COUNT(*) FROM alt_cases WHERE guild_id = ? AND created_at >= ?",
                    guild.id, since,
                )
                tix = await self.bot.db.fetch(
                    "SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND created_at >= ?",
                    guild.id, since,
                )
                pending = None
                try:
                    pending = await self.bot.db.fetch(
                        "SELECT COUNT(*) FROM infraction_appeals WHERE guild_id = ? AND status = 'pending'",
                        guild.id,
                    )
                except Exception:
                    pending = [0]
                embed = discord.Embed(
                    title="🦞 Semana en este servidor",
                    description=f"Resumen de 7 días. Más detalle en {DASHBOARD_URL}/dashboard?guild={guild.id}",
                    color=DABOT_GREEN,
                )
                embed.add_field(name="Sanciones", value=str((inf or [0])[0]), inline=True)
                embed.add_field(name="Tickets", value=str((tix or [0])[0]), inline=True)
                embed.add_field(name="Multicuentas", value=str((alts or [0])[0]), inline=True)
                embed.add_field(name="Cuentas hackeadas", value=str((hij or [0])[0]), inline=True)
                embed.add_field(name="Apelaciones pendientes", value=str((pending or [0])[0]), inline=True)
                embed.set_footer(text="Dabot · digest semanal (lunes)")
                await ch.send(embed=embed)
                if guild.owner:
                    try:
                        await guild.owner.send(embed=embed)
                    except Exception:
                        pass
            except Exception as e:
                log.warning("digest %s: %s", guild.id, e)

    @weekly.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Digest(bot))
