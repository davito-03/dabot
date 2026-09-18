import logging
import json
import re
import hashlib
import unicodedata
import discord
from discord.ext import commands, tasks
import datetime
import asyncio
import typing
from collections import defaultdict, deque

from utils.helpers import tr, DASHBOARD_URL
from utils import abuse as abuse_mod


_URL_RE = re.compile(r"https?://[^\s<>\]]+", re.IGNORECASE)
_DM_COLORS = {
    "warn": 0xFBBF24,
    "kick": 0xF97316,
    "ban": 0xEF4444,
    "hackban": 0x7F1D1D,
    "timeout": 0xA855F7,
    "tempban": 0xDC2626,
    "unban": 0x22C55E,
    "unwarn": 0x22C55E,
}
_ACTION_KEYS = {
    "warn": "warn",
    "kick": "kick",
    "ban": "ban",
    "hackban": "ban",
    "timeout": "timeout",
    "tempban": "tempban",
    "unban": "unban",
    "unwarn": "unwarn",
}
_PUNISH_ACTIONS = {"warn", "kick", "ban", "hackban", "timeout", "tempban"}
_NEW_GUILD_DAYS = 14


def neutralize_links(text: str) -> tuple[str, bool]:
    """Wrap URLs so they are visible as text instead of looking official."""
    raw = text if text else ""
    found = bool(_URL_RE.search(raw))
    if found:
        raw = _URL_RE.sub(lambda m: f"`{m.group(0)}`", raw)
    return raw, found


def format_guild_age(created_at, guild_id, bot) -> str:
    if created_at is None:
        return tr(bot, guild_id, "moderation.age_unknown", "desconocida")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = now - created_at
    days = max(0, delta.days)
    date = created_at.date().isoformat()
    years, rest = divmod(days, 365)
    if years >= 1:
        return tr(
            bot, guild_id, "moderation.age_years",
            "{years} año(s) y {days} día(s) (creado el {date})",
            years=years, days=rest, date=date,
        )
    return tr(
        bot, guild_id, "moderation.age_days",
        "{days} día(s) (creado el {date})",
        days=days, date=date,
    )


def _guild_age_days(guild) -> int | None:
    created = getattr(guild, "created_at", None)
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    return max(0, (datetime.datetime.now(datetime.timezone.utc) - created).days)


def _normalize_guild_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = text.casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    skip = {"the", "el", "la", "los", "las", "official", "oficial"}
    while tokens and tokens[0] in skip:
        tokens.pop(0)
    return "".join(tokens)


def _reason_fingerprint(reason: str) -> str:
    raw = re.sub(r"\s+", " ", (reason or "").strip().lower()).encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


# --- COG ---

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')
        self._sanction_events = defaultdict(deque)
        self._alert_at = {}
        self._dm_pause_until = {}
        self._twin_cache = {}
        self.tempban_checker.start()
    
    def cog_unload(self):
        self.tempban_checker.cancel()
    
    @tasks.loop(minutes=1)
    async def tempban_checker(self):
        """Check for expired tempbans and auto-unban"""
        now = datetime.datetime.now().isoformat()
        expired = await self.bot.db.fetch_all(
            "SELECT user_id, guild_id FROM tempbans WHERE expires_at <= ?",
            now
        )
        
        for user_id, guild_id in expired:
            guild = self.bot.get_guild(guild_id)
            if guild:
                try:
                    user = await self.bot.fetch_user(user_id)
                    await guild.unban(user, reason="Tempban expired")
                    await self.bot.db.execute(
                        "DELETE FROM tempbans WHERE user_id = ? AND guild_id = ?",
                        user_id, guild_id
                    )
                except:
                    pass
    
    @tempban_checker.before_loop
    async def before_tempban_checker(self):
        await self.bot.wait_until_ready()
    
    def is_immune(self, member):
        return member.id == self.bot.super_owner_id

    async def create_infraction(self, user_id, guild_id, moderator_id, type, reason, staff_note=None):
        timestamp = datetime.datetime.now().isoformat()
        try:
            case_id = await self.bot.db.execute(
                "INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp, status, staff_note) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                user_id, guild_id, moderator_id, type, reason, timestamp, staff_note,
            )
        except Exception:
            case_id = await self.bot.db.execute(
                "INSERT INTO infractions (user_id, guild_id, moderator_id, type, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                user_id, guild_id, moderator_id, type, reason, timestamp,
            )
        if type in _PUNISH_ACTIONS:
            guild = self.bot.get_guild(guild_id)
            if guild:
                asyncio.create_task(self._watch_infraction_rate(
                    guild, user_id, moderator_id, type, reason
                ))
        return case_id

    async def _watch_infraction_rate(self, guild, user_id, moderator_id, action, reason):
        """Bulk warns (a fight, 10 people) are fine. Only insane loops get flagged here."""
        if moderator_id and moderator_id == getattr(self.bot, "super_owner_id", None):
            return
        guard = abuse_mod.guard(self.bot)
        if not guard:
            return
        gid = guild.id
        guard.record(f"inf:{gid}", user_id)
        if guard.count(f"inf:{gid}", 5 * 60) > 80:
            await guard.alert(
                kind="infraction_flood",
                details="Ritmo absurdo de sanciones (posible bucle o script), no un warn masivo normal.",
                user_id=moderator_id,
                guild_id=gid,
                extra={"acción": action, "objetivo": user_id},
            )

    def _t(self, guild_id, key, fallback, **kwargs):
        return tr(self.bot, guild_id, key, fallback, **kwargs)

    def _dm_staff_note(self, guild_id, status: str) -> str:
        mapping = {
            "sent": ("moderation.staff_dm_sent", "📬 MD entregado al usuario."),
            "blocked": ("moderation.staff_dm_blocked", "📬 No se pudo entregar el MD (tiene los privados cerrados o bloqueó al bot)."),
            "not_member": ("moderation.staff_dm_not_member", "📬 No se envió MD: el usuario no está en este servidor (así no se avisa a gente de otros servers)."),
            "failed": ("moderation.staff_dm_failed", "📬 No se pudo entregar el MD."),
            "rate_limited": ("moderation.staff_dm_rate_limited", "📬 MD no enviado: se evitó un envío repetido o un posible abuso."),
        }
        key, fallback = mapping.get(status, mapping["failed"])
        return self._t(guild_id, key, fallback)

    async def _resolve_guild(self, guild_id=None, guild=None, member=None):
        if guild is not None:
            return guild
        if guild_id:
            try:
                found = self.bot.get_guild(int(guild_id))
                if found:
                    return found
            except (TypeError, ValueError):
                pass
        member_guild = getattr(member, "guild", None)
        if member_guild is not None and (not guild_id or member_guild.id == guild_id):
            return member_guild
        return None

    async def _resolve_sanction_recipient(self, target, guild):
        """Only DM people who are actually in the origin guild.

        Sharing another server with the bot is not enough: that is how a
        fake guild with a cloned name can spam sanction DMs (La Cabra-style).
        """
        if guild is None or target is None:
            return None
        target_id = getattr(target, "id", None)
        if not target_id:
            return None
        if isinstance(target, discord.Member) and getattr(target.guild, "id", None) == guild.id:
            return target
        cached = guild.get_member(target_id)
        if cached:
            return cached
        try:
            return await guild.fetch_member(target_id)
        except (discord.NotFound, discord.HTTPException):
            return None

    def _now_ts(self) -> float:
        return datetime.datetime.now(datetime.timezone.utc).timestamp()

    def _prune_events(self, key: str, window: int):
        dq = self._sanction_events[key]
        cutoff = self._now_ts() - window
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        return dq

    def _record_event(self, key: str, extra=None):
        self._sanction_events[key].append((self._now_ts(), extra))

    def _event_count(self, key: str, window: int, unique: bool = False) -> int:
        dq = self._prune_events(key, window)
        if unique:
            return len({item[1] for item in dq if item[1] is not None})
        return len(dq)

    def _name_twins(self, guild):
        now = self._now_ts()
        cached = self._twin_cache.get(guild.id)
        if cached and cached[0] > now:
            return cached[1]
        key = _normalize_guild_name(guild.name)
        twins = []
        if key:
            for other in self.bot.guilds:
                if other.id == guild.id:
                    continue
                if _normalize_guild_name(other.name) == key:
                    twins.append(other)
        self._twin_cache[guild.id] = (now + 300, twins)
        return twins

    def _impersonation_twins(self, guild):
        """Older/larger guilds that share this name — likely the real one."""
        age = _guild_age_days(guild)
        members = guild.member_count or len(guild.members) or 0
        name_key = _normalize_guild_name(guild.name)
        suspects = []
        for twin in self._name_twins(guild):
            twin_age = _guild_age_days(twin)
            twin_members = twin.member_count or len(twin.members) or 0
            twin_older = twin_age is not None and (age is None or twin_age > age)
            recent = age is not None and age < _NEW_GUILD_DAYS
            somewhat_new = age is not None and age < 30
            much_bigger = twin_members >= max(200, members * 5) and twin_members > members
            if recent and twin_older:
                suspects.append(twin)
            elif somewhat_new and much_bigger and len(name_key) >= 8:
                suspects.append(twin)
        return suspects

    async def _alert_abuse(self, guild, kind: str, details: str, moderator_id=None, target_id=None, action=None, reason=None):
        guard = abuse_mod.guard(self.bot)
        extra = {}
        if target_id:
            extra["objetivo"] = target_id
        if action:
            extra["acción"] = action
        if reason:
            extra["motivo"] = str(reason)[:500]
        twins = self._impersonation_twins(guild) if guild else []
        if twins:
            extra["homónimos"] = ", ".join(f"{t.name} (`{t.id}`)" for t in twins[:5])
        if guard:
            await guard.alert(
                kind=kind,
                details=details,
                user_id=moderator_id,
                guild_id=getattr(guild, "id", None),
                extra=extra,
            )

    async def _allow_sanction_dm(self, guild, recipient, action, reason, moderator_id=None) -> str | None:
        """Return a skip reason, or None if the DM may go out.

        10 people getting the same warn (a fight) is allowed. Copying the same
        linked reason to many DMs is not.
        """
        if action not in _PUNISH_ACTIONS:
            return None
        if moderator_id and moderator_id == getattr(self.bot, "super_owner_id", None):
            return None

        gid = guild.id
        uid = recipient.id
        fp = _reason_fingerprint(reason)
        if self._dm_pause_until.get(f"reason:{gid}:{fp}", 0) > self._now_ts():
            return "rate_limited"

        self._record_event(f"pair:{gid}:{uid}:{action}")
        self._record_event(f"user:{gid}:{uid}", action)
        # Two DMs per person (warn + another warn) is normal. A third is noise.
        if self._event_count(f"pair:{gid}:{uid}:{action}", 15 * 60) > 2:
            return "rate_limited"
        if self._event_count(f"user:{gid}:{uid}", 15 * 60) > 3:
            return "rate_limited"

        has_links = bool(_URL_RE.search(reason or ""))
        if not has_links:
            return None

        impersonators = self._impersonation_twins(guild)
        age = _guild_age_days(guild)
        is_new = age is not None and age < _NEW_GUILD_DAYS
        limit = 2 if (impersonators or is_new) else 4
        guard = abuse_mod.guard(self.bot)
        if guard:
            url = guard.link_fanout(
                guild_id=gid, actor_id=moderator_id, dest_id=uid, text=reason or "", limit=limit
            )
            if url:
                self._dm_pause_until[f"reason:{gid}:{fp}"] = self._now_ts() + 20 * 60
                asyncio.create_task(self._alert_abuse(
                    guild, "link_spam",
                    f"Mismo motivo con enlace enviado a varios usuarios.\n`{url[:300]}`",
                    moderator_id=moderator_id, target_id=uid, action=action, reason=reason,
                ))
                self.logger.info("Sanction DM skipped (link_spam) guild=%s user=%s", gid, uid)
                return "rate_limited"
        return None

    async def send_dm_notification(self, member, action, reason, case_id=None, guild_id=None, guild=None, duration="", moderator_id=None):
        """DM a sanction only after confirming the recipient is in this guild.

        Origin metadata (name, member count, age, ID) is always attached and
        cannot be removed by custom message templates.
        """
        origin = await self._resolve_guild(guild_id=guild_id, guild=guild, member=member)
        if origin is None:
            self.logger.warning("Skipping sanction DM: could not resolve origin guild")
            return "failed"

        recipient = await self._resolve_sanction_recipient(member, origin)
        if recipient is None:
            self.logger.info(
                "Skipping sanction DM: %s is not a member of guild %s (%s)",
                getattr(member, "id", member), origin.id, origin.name,
            )
            return "not_member"

        skipped = await self._allow_sanction_dm(
            origin, recipient, action, reason, moderator_id=moderator_id
        )
        if skipped:
            return skipped

        gid = origin.id
        action_key = _ACTION_KEYS.get(action, action)
        action_label = self._t(gid, f"moderation.action_{action_key}", action)
        safe_reason, reason_has_links = neutralize_links(reason or self._t(gid, "moderation.no_reason", "Sin motivo"))
        display = getattr(recipient, "display_name", None) or getattr(recipient, "name", str(recipient))

        config = self.bot.config.get(gid) or {}
        template = (config.get("messages") or {}).get(action)
        fallback_body = self._t(
            gid, "moderation.default_body",
            "Has recibido una sanción (**{action}**) en **{guild}**.\nMotivo: {reason}",
            action=action_label, guild=origin.name, reason=safe_reason,
        )
        if template:
            try:
                message = template.format(
                    user=display,
                    guild=origin.name,
                    server=origin.name,
                    reason=safe_reason,
                    duration=duration or "",
                )
            except Exception:
                message = fallback_body
        else:
            message = fallback_body
        message, body_has_links = neutralize_links(message)

        member_count = origin.member_count or len(origin.members) or 0
        created = getattr(origin, "created_at", None)
        age_text = format_guild_age(created, gid, self.bot)
        created_days = _guild_age_days(origin)
        if created_days is None:
            created_days = 0

        title = (
            self._t(gid, "moderation.dm_title", "Sanción de Dabot — Caso #{case_id}", case_id=case_id)
            if case_id else
            self._t(gid, "moderation.dm_title_nocase", "Sanción de Dabot")
        )
        embed = discord.Embed(
            title=title,
            description=message[:4000],
            color=_DM_COLORS.get(action, 0xEF4444),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name=self._t(gid, "moderation.origin_name", "Servidor de origen"),
            value=f"**{origin.name}**",
            inline=True,
        )
        embed.add_field(
            name=self._t(gid, "moderation.origin_members", "Miembros"),
            value=str(member_count),
            inline=True,
        )
        embed.add_field(
            name=self._t(gid, "moderation.origin_age", "Antigüedad"),
            value=age_text,
            inline=True,
        )
        embed.add_field(
            name=self._t(gid, "moderation.origin_id", "ID del servidor"),
            value=f"`{origin.id}`",
            inline=False,
        )
        impersonators = self._impersonation_twins(origin)
        extra_notes = []
        if impersonators:
            extra_notes.append(self._t(
                gid, "moderation.origin_name_clash",
                "Hay otro servidor con el mismo nombre. Comprueba el ID de arriba para confirmar el origen.",
            ))
        if created_days < _NEW_GUILD_DAYS:
            extra_notes.append(self._t(
                gid, "moderation.origin_new",
                "Este servidor se creó hace menos de 14 días.",
            ))
        verified = None
        try:
            verified = await self.bot.db.fetch("SELECT guild_id FROM verified_guilds WHERE guild_id = ?", gid)
        except Exception:
            verified = None
        if verified:
            extra_notes.append(self._t(
                gid, "moderation.origin_verified",
                "Servidor verificado por Dabot.",
            ))
        if extra_notes:
            embed.add_field(name="\u200b", value="\n".join(extra_notes), inline=False)
        if reason_has_links or body_has_links:
            embed.add_field(
                name="Enlaces",
                value=self._t(
                    gid, "moderation.links_warning",
                    "El motivo incluye enlaces. Dabot no los comprueba; no pulses nada que no reconozcas.",
                ),
                inline=False,
            )
        icon = origin.icon.url if origin.icon else None
        embed.set_author(name=origin.name, icon_url=icon)
        if icon:
            embed.set_thumbnail(url=icon)
        footer = self._t(
            gid, "moderation.footer",
            "Dabot · dabot.davito.es · ID servidor {guild_id}",
            guild_id=origin.id,
        )
        if verified:
            footer = "✓ " + footer
        embed.set_footer(text=footer)

        if created_days < _NEW_GUILD_DAYS and action in _PUNISH_ACTIONS:
            await asyncio.sleep(10)

        try:
            dm = await recipient.create_dm()
        except discord.Forbidden:
            self.logger.info("Cannot open DM with %s for guild %s", recipient.id, origin.id)
            return "blocked"
        except Exception as e:
            self.logger.warning("Could not open DM with %s: %s", recipient, e)
            return "failed"

        try:
            view = None
            if case_id and action in _PUNISH_ACTIONS:
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(
                    label=self._t(gid, "moderation.appeal_button", "Apelar"),
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"dabot:appeal:{gid}:{case_id}",
                ))
                view.add_item(discord.ui.Button(
                    label="Panel",
                    style=discord.ButtonStyle.link,
                    url=f"{DASHBOARD_URL}/dashboard?guild={gid}",
                ))
            await dm.send(embed=embed, view=view)
            return "sent"
        except discord.Forbidden:
            self.logger.info("DM blocked for %s in guild %s", recipient.id, origin.id)
            return "blocked"
        except Exception as e:
            self.logger.warning("Could not DM %s: %s", recipient, e)
            return "failed"

    async def log_action(self, guild, moderator, target, action, reason, case_id=None):
        config = self.bot.config.get(guild.id) or {}
        logs_config = config.get("logs", {})
        raw_id = logs_config.get("moderation") or logs_config.get("mod_log") or logs_config.get("moderation_channel")
        channel = None
        if raw_id:
            try:
                channel = guild.get_channel(int(raw_id))
            except (TypeError, ValueError):
                channel = None

        colors = {
            "warn": 0xFBBF24,
            "kick": 0xF97316,
            "ban": 0xEF4444,
            "hackban": 0x7F1D1D,
            "timeout": 0xA855F7,
            "tempban": 0xDC2626,
            "unban": 0x22C55E,
        }
        prior = 0
        try:
            row = await self.bot.db.fetch(
                "SELECT COUNT(*) FROM infractions WHERE guild_id = ? AND user_id = ?",
                guild.id, getattr(target, "id", 0)
            )
            prior = (row[0] if row else 0) or 0
        except Exception:
            pass

        embed = discord.Embed(
            title=f"Caso #{case_id} · {action.upper()}",
            color=colors.get(action, 0xEF4444),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Usuario", value=f"{target} (`{getattr(target, 'id', '?')}`)", inline=True)
        embed.add_field(name="Moderador", value=f"{moderator.mention}\n`{moderator.id}`", inline=True)
        embed.add_field(name="Historial", value=f"{prior} sanción(es) en este servidor", inline=True)
        embed.add_field(name="Motivo", value=(reason or "Sin motivo")[:1000], inline=False)
        avatar = None
        try:
            avatar = target.display_avatar.url
        except Exception:
            pass
        if avatar:
            embed.set_thumbnail(url=avatar)
        embed.set_footer(text=f"Dabot · ID usuario {getattr(target, 'id', '')} · {guild.name}")

        try:
            await self.bot.db.execute(
                """INSERT INTO audit_events (guild_id, event_type, actor_id, target_id, channel_id, summary, extra, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                guild.id, "moderation", moderator.id, getattr(target, "id", None), None,
                f"{action} · caso #{case_id}",
                json.dumps({"reason": reason, "case_id": case_id}),
                datetime.datetime.utcnow().isoformat(),
            )
        except Exception:
            pass

        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                self.logger.warning(f"Could not send mod log: {e}")

    @commands.hybrid_group(name="mod", description="Moderation commands.")
    @commands.has_permissions(kick_members=True)
    async def mod(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `/mod kick`, `/mod ban`, `/mod warn`, etc.")

    @mod.command(name="hackban", description="Ban a user by ID (they don't need to be in the server).")
    @commands.has_permissions(ban_members=True)
    async def hackban(self, ctx, user_id: str, *, reason: str = "No reason provided"):
        """Ban a user by their Discord ID."""
        await ctx.defer()
        try:
            uid = int(user_id)
        except ValueError:
            await ctx.send("❌ Invalid user ID.")
            return

        try:
            user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            await ctx.send(f"❌ User `{user_id}` not found.")
            return

        try:
            await ctx.guild.ban(user, reason=f"Hackban by {ctx.author}: {reason}")
            case_id = await self.create_infraction(uid, ctx.guild.id, ctx.author.id, "ban", reason)
            embed = discord.Embed(
                title="🔨 Hackban Applied",
                description=f"**User:** {user} (`{uid}`)\n**Reason:** {reason}\n**Case:** #{case_id}",
                color=discord.Color.dark_red()
            )
            await ctx.send(embed=embed)
            await self.log_action(ctx.guild, ctx.author, user, "hackban", reason, case_id)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to ban this user.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @mod.command(name="kick", description="Kick a member from the server.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason=None):
        if member.top_role >= ctx.author.top_role and ctx.author.id != self.bot.super_owner_id:
            await ctx.send("You cannot kick this user due to role hierarchy.")
            return

        if self.is_immune(member):
            await ctx.send("You cannot kick the bot owner.")
            return

        case_id = await self.create_infraction(member.id, ctx.guild.id, ctx.author.id, "kick", reason)
        
        try:
            dm_status = await self.send_dm_notification(
                member, "kick", reason, case_id, ctx.guild.id, guild=ctx.guild, moderator_id=ctx.author.id
            )
            await member.kick(reason=reason)
            await ctx.send(
                f"Kicked {member.display_name}. (Case #{case_id})\n{self._dm_staff_note(ctx.guild.id, dm_status)}"
            )
            await self.log_action(ctx.guild, ctx.author, member, "kick", reason, case_id)
        except Exception as e:
            await ctx.send(f"Failed to kick member: {e}")

    @mod.command(name="ban", description="Ban a member or user ID (Hackban).")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: typing.Union[discord.Member, discord.User], *, reason=None):
        auth_id = ctx.author.id
        
        # Check hierarchy if target is in the server
        if isinstance(member, discord.Member):
            if member.top_role >= ctx.author.top_role and auth_id != self.bot.super_owner_id:
                 await ctx.send("You cannot ban this user due to role hierarchy.")
                 return

            if self.is_immune(member):
                await ctx.send("You cannot ban the bot owner.")
                return

        # Check immunity for User object too just in case
        if member.id == self.bot.super_owner_id:
             await ctx.send("You cannot ban the bot owner.")
             return

        case_id = await self.create_infraction(member.id, ctx.guild.id, auth_id, "ban", reason)

        try:
            # DM only if the target is actually in THIS guild. Never DM a User
            # just because the bot shares another server with them.
            dm_status = await self.send_dm_notification(
                member, "ban", reason, case_id, ctx.guild.id, guild=ctx.guild, moderator_id=ctx.author.id
            )

            await ctx.guild.ban(member, reason=reason)
            
            user_type = "Member" if isinstance(member, discord.Member) else "User"
            conf_msg = f"Banned {member.name} ({user_type}). (Case #{case_id})"
            if user_type == "User":
                conf_msg += " [Hackban Successful]"
            conf_msg += f"\n{self._dm_staff_note(ctx.guild.id, dm_status)}"
                
            await ctx.send(conf_msg)
            await self.log_action(ctx.guild, ctx.author, member, "ban", reason, case_id)
            
        except discord.Forbidden:
            await ctx.send(f"❌ I do not have permission to ban {member.name}.")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Failed to ban member: {e}")
        except Exception as e:
            self.logger.error(f"Ban failed: {e}")
            await ctx.send(f"❌ An unexpected error occurred: {e}")

    @mod.command(name="timeout", description="Timeout a member.")
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, minutes: int, *, reason=None):
        if member.top_role >= ctx.author.top_role and ctx.author.id != self.bot.super_owner_id:
             await ctx.send("You cannot timeout this user due to role hierarchy.")
             return
        
        if self.is_immune(member):
            await ctx.send("You cannot timeout the bot owner.")
            return

        duration = datetime.timedelta(minutes=minutes)
        case_id = await self.create_infraction(member.id, ctx.guild.id, ctx.author.id, "timeout", reason)

        try:
            dm_status = await self.send_dm_notification(
                member, "timeout", reason, case_id, ctx.guild.id, guild=ctx.guild,
                duration=f"{minutes}m", moderator_id=ctx.author.id,
            )
            await member.timeout(duration, reason=reason)
            await ctx.send(
                f"Timed out {member.display_name} for {minutes} minutes. (Case #{case_id})\n"
                f"{self._dm_staff_note(ctx.guild.id, dm_status)}"
            )
            await self.log_action(ctx.guild, ctx.author, member, "timeout", reason, case_id)
        except Exception as e:
            await ctx.send(f"Failed to timeout member: {e}")

    # --- WARN COMMANDS (flat subcommands of /mod, not a sub-subgroup) ---

    @mod.command(name="warn", description="Warn a member.")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        """Warn a member. Usage: /mod warn @user [reason]"""
        await ctx.defer()
        if self.is_immune(member):
            await ctx.send("You cannot warn the bot owner.")
            return

        case_id = await self.create_infraction(member.id, ctx.guild.id, ctx.author.id, "warn", reason)
        dm_status = await self.send_dm_notification(
            member, "warn", reason, case_id, ctx.guild.id, guild=ctx.guild, moderator_id=ctx.author.id
        )
        await ctx.send(
            f"⚠️ Warned **{member.display_name}**. Reason: {reason} (Case #{case_id})\n"
            f"{self._dm_staff_note(ctx.guild.id, dm_status)}"
        )
        await self.log_action(ctx.guild, ctx.author, member, "warn", reason, case_id)
        await self._maybe_escalate(ctx, member)

    async def _maybe_escalate(self, ctx, member):
        cfg = ((self.bot.config.get(ctx.guild.id) or {}).get("moderation") or {}).get("escalate") or {}
        if not cfg.get("enabled"):
            return
        window_h = max(1, int(cfg.get("window_hours") or 24))
        since = (datetime.datetime.utcnow() - datetime.timedelta(hours=window_h)).isoformat()
        row = await self.bot.db.fetch(
            "SELECT COUNT(*) FROM infractions WHERE guild_id = ? AND user_id = ? AND type = 'warn' AND timestamp >= ?",
            ctx.guild.id, member.id, since,
        )
        n = (row[0] if row else 0) or 0
        kick_at = int(cfg.get("warns_kick") or 5)
        to_at = int(cfg.get("warns_timeout") or 3)
        minutes = int(cfg.get("timeout_minutes") or 30)
        try:
            if n >= kick_at and ctx.guild.me.guild_permissions.kick_members:
                await member.kick(reason=f"Escalado automático: {n} warns / {window_h}h")
                await ctx.send(f"⚙️ Escalado: **{member.display_name}** expulsado ({n} warns).")
                await self.create_infraction(member.id, ctx.guild.id, self.bot.user.id, "kick", f"auto-escalate {n} warns")
            elif n >= to_at and ctx.guild.me.guild_permissions.moderate_members:
                await member.timeout(datetime.timedelta(minutes=minutes), reason=f"Escalado automático: {n} warns")
                await ctx.send(f"⚙️ Escalado: **{member.display_name}** timeout {minutes}m ({n} warns).")
                await self.create_infraction(member.id, ctx.guild.id, self.bot.user.id, "timeout", f"auto-escalate {n} warns")
        except Exception as e:
            self.logger.warning("escalate failed: %s", e)

    @mod.command(name="timeleft", description="See remaining timeout for a member.")
    @commands.has_permissions(moderate_members=True)
    async def timeleft(self, ctx, member: discord.Member):
        until = getattr(member, "timed_out_until", None)
        if not until:
            await ctx.send(f"**{member.display_name}** no está en timeout.")
            return
        now = discord.utils.utcnow()
        if until.tzinfo is None:
            until = until.replace(tzinfo=datetime.timezone.utc)
        delta = until - now
        if delta.total_seconds() <= 0:
            await ctx.send(f"**{member.display_name}** no está en timeout.")
            return
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(rem, 60)
        await ctx.send(
            f"**{member.display_name}**: quedan **{hours}h {minutes}m {seconds}s** "
            f"(hasta {until.strftime('%Y-%m-%d %H:%M UTC')})."
        )

    @mod.command(name="export", description="Export a user's cases as CSV.")
    @commands.has_permissions(kick_members=True)
    async def export_cases(self, ctx, member: discord.Member):
        rows = await self.bot.db.fetch_all(
            "SELECT id, type, reason, staff_note, moderator_id, timestamp, status FROM infractions WHERE user_id = ? AND guild_id = ? ORDER BY id",
            member.id, ctx.guild.id,
        )
        if not rows:
            try:
                rows = await self.bot.db.fetch_all(
                    "SELECT id, type, reason, moderator_id, timestamp, status FROM infractions WHERE user_id = ? AND guild_id = ? ORDER BY id",
                    member.id, ctx.guild.id,
                )
            except Exception:
                rows = []
        if not rows:
            await ctx.send("Sin casos.")
            return
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "type", "reason", "staff_note", "moderator_id", "timestamp", "status"])
        for row in rows:
            writer.writerow(list(row) + [""] * (7 - len(row)))
        data = io.BytesIO(buf.getvalue().encode("utf-8"))
        await ctx.send(file=discord.File(data, filename=f"casos_{member.id}.csv"))

    @mod.command(name="appeal", description="Resolve an appeal: accept or reject.")
    @commands.has_permissions(kick_members=True)
    async def appeal_resolve(self, ctx, case_id: int, action: str, *, response: str = "Sin comentario"):
        action = (action or "").lower().strip()
        if action not in {"accept", "approve", "reject", "deny"}:
            await ctx.send("Uso: `/mod appeal <caso> accept|reject [respuesta]`")
            return
        row = await self.bot.db.fetch(
            "SELECT user_id, type FROM infractions WHERE id = ? AND guild_id = ?",
            case_id, ctx.guild.id,
        )
        if not row:
            await ctx.send("Caso no encontrado.")
            return
        approve = action in {"accept", "approve"}
        new_inf = "appealed" if approve else "active"
        new_app = "approved" if approve else "rejected"
        await self.bot.db.execute(
            "UPDATE infractions SET status = ? WHERE id = ? AND guild_id = ?",
            new_inf, case_id, ctx.guild.id,
        )
        await self.bot.db.execute(
            "UPDATE infraction_appeals SET status = ?, mod_response = ? WHERE infraction_id = ? AND guild_id = ?",
            new_app, response, case_id, ctx.guild.id,
        )
        if approve:
            uid, inf_type = row[0], row[1]
            member = ctx.guild.get_member(uid)
            try:
                if inf_type in {"timeout"} and member:
                    await member.timeout(None, reason=f"Apelación aceptada #{case_id}")
                elif inf_type in {"ban", "tempban"}:
                    user = await self.bot.fetch_user(uid)
                    await ctx.guild.unban(user, reason=f"Apelación aceptada #{case_id}")
            except Exception:
                pass
        await ctx.send(f"Apelación del caso #{case_id}: **{new_app}**.")

    @mod.command(name="warnlist", description="View warning history for a member.")
    @commands.has_permissions(kick_members=True)
    async def warn_list(self, ctx, member: discord.Member):
        """View all infractions for a user."""
        await ctx.defer()
        infractions = await self.bot.db.fetch_all(
            "SELECT id, type, reason, moderator_id, timestamp, status FROM infractions WHERE user_id = ? AND guild_id = ? ORDER BY id DESC",
            member.id, ctx.guild.id
        )

        if not infractions:
            await ctx.send(f"{member.display_name} has no infractions.")
            return

        count = len(infractions)
        embed = discord.Embed(title=f"Infractions for {member.display_name}", color=discord.Color.orange())

        desc = ""
        for inf in infractions[:10]:
            case_id, inf_type, reason, mod_id, date, status = inf
            active = "🔴" if status not in ["approved", "denied"] else "⚪"
            reason_text = (reason or "Sin motivo")[:40]
            desc += f"`#{case_id}` {active} **{(inf_type or 'warn').upper()}**: {reason_text}\n"

        if count > 10:
            desc += f"\n*...and {count - 10} more.*"

        embed.description = desc
        embed.set_footer(text=f"Total infractions: {count}")
        await ctx.send(embed=embed)

    @mod.command(name="warninfo", description="View details of a specific case.")
    @commands.has_permissions(kick_members=True)
    async def warn_info(self, ctx, case_id: int):
        """View details of a specific infraction case."""
        await ctx.defer()
        row = await self.bot.db.fetch(
            "SELECT id, user_id, moderator_id, type, reason, timestamp, status FROM infractions WHERE id = ? AND guild_id = ?",
            case_id, ctx.guild.id
        )

        if not row:
            await ctx.send("❌ Case not found.")
            return

        case_id, user_id, mod_id, inf_type, reason, timestamp, status = row
        user = self.bot.get_user(user_id) or f"ID: {user_id}"
        mod = ctx.guild.get_member(mod_id) or f"ID: {mod_id}"

        embed = discord.Embed(title=f"Case #{case_id}", color=discord.Color.red())
        embed.add_field(name="User", value=f"{user}")
        embed.add_field(name="Type", value=inf_type.upper())
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=f"{mod}")
        embed.add_field(name="Time", value=timestamp.split("T")[0])
        embed.add_field(name="Status", value=status or "Active")
        await ctx.send(embed=embed)

    @mod.command(name="warndelete", description="Delete a warning case.")
    @commands.has_permissions(kick_members=True)
    async def warn_delete(self, ctx, case_id: int):
        """Delete an infraction case by ID."""
        await ctx.defer()
        row = await self.bot.db.fetch(
            "SELECT id, user_id, type, reason FROM infractions WHERE id = ? AND guild_id = ?",
            case_id, ctx.guild.id,
        )
        if not row:
            await ctx.send(f"❌ Case #{case_id} not found in this server.")
            return
        _, target_id, inf_type, reason = row
        await self.bot.db.execute("DELETE FROM infractions WHERE id = ?", case_id)
        member = ctx.guild.get_member(target_id)
        if member:
            dm_status = await self.send_dm_notification(
                member,
                "unwarn",
                reason or "Sanción eliminada por el staff",
                case_id,
                ctx.guild.id,
                guild=ctx.guild,
                moderator_id=ctx.author.id,
            )
        else:
            # Do not fetch_user + DM: that is how a fake cloned-name guild
            # can reach people who never joined it.
            dm_status = "not_member"
        await ctx.send(
            f"✅ Deleted case #{case_id}. El usuario ha sido avisado por MD si era posible.\n"
            f"{self._dm_staff_note(ctx.guild.id, dm_status)}"
        )

    @mod.command(name="warnclear", description="Clear all warnings for a user.")
    @commands.has_permissions(administrator=True)
    async def warn_clear(self, ctx, member: discord.Member):
        """Clear all infractions for a member."""
        await ctx.defer()
        await self.bot.db.execute("DELETE FROM infractions WHERE user_id = ? AND guild_id = ?", member.id, ctx.guild.id)
        dm_status = await self.send_dm_notification(
            member, "unwarn", "Se han borrado todas tus sanciones.", None, ctx.guild.id,
            guild=ctx.guild, moderator_id=ctx.author.id,
        )
        await ctx.send(
            f"✅ Cleared all infractions for **{member.display_name}**. Aviso enviado por MD.\n"
            f"{self._dm_staff_note(ctx.guild.id, dm_status)}"
        )

    # --- NOTES COMMANDS (flat subcommands of /mod) ---

    @mod.command(name="noteadd", description="Add a note for a user.")
    @commands.has_permissions(kick_members=True)
    async def notes_add(self, ctx, member: discord.Member, *, note: str):
        """Add a staff note for a member."""
        await ctx.defer()
        timestamp = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT INTO notes (user_id, guild_id, moderator_id, note, timestamp) VALUES (?, ?, ?, ?, ?)",
            member.id, ctx.guild.id, ctx.author.id, note, timestamp
        )
        await ctx.send(f"✅ Note added for **{member.display_name}**.")

    @mod.command(name="notelist", description="View notes for a user.")
    @commands.has_permissions(kick_members=True)
    async def notes_view(self, ctx, member: discord.Member):
        """View all staff notes for a member."""
        await ctx.defer(ephemeral=True)
        notes = await self.bot.db.fetch_all(
            "SELECT id, moderator_id, note, timestamp FROM notes WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC",
            member.id, ctx.guild.id
        )
        if not notes:
            return await ctx.send(f"No notes for **{member.display_name}**.")
        embed = discord.Embed(title=f"Notes: {member.display_name}", color=discord.Color.blue())
        for nid, mid, text, ts in notes:
            mod = ctx.guild.get_member(mid)
            mod_name = mod.display_name if mod else f"ID:{mid}"
            embed.add_field(name=f"Note #{nid} — {mod_name}", value=text, inline=False)
        await ctx.send(embed=embed, ephemeral=True)

    # --- PURGE & other mod commands ---

    @mod.command(name="purge", description="Delete messages from a channel.")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int, member: discord.Member = None):
        if amount > 1000:
            await ctx.send("Limit is 1000.")
            return
        await ctx.defer(ephemeral=True)
        def check(m): return m.author.id == member.id if member else True
        deleted = await ctx.channel.purge(limit=amount, check=check)
        await ctx.send(f"Deleted **{len(deleted)}** messages.", ephemeral=True, delete_after=5)

    @mod.command(name="slowmode", description="Set slowmode.")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        if seconds > 21600: return await ctx.send("Max 6 hours.")
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.send(f"Slowmode set to {seconds}s.")

    @mod.command(name="lock", description="Lock channel.")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(f"🔒 Locked.")

    @mod.command(name="unlock", description="Unlock channel.")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(f"🔓 Unlocked.")

    @mod.command(name="unban", description="Unban a user ID.")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str, *, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await ctx.guild.unban(user, reason=reason)
            await ctx.send(f"✅ Unbanned {user}.")
        except discord.NotFound:
            await ctx.send("❌ User not found.")
        except discord.Forbidden:
            await ctx.send("❌ I do not have permission to unban this user.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @mod.command(name="tempban", description="Temporarily ban a user.")
    @commands.has_permissions(ban_members=True)
    async def tempban(self, ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
        import re
        match = re.match(r'(\d+)([dhm])', duration.lower())
        if not match: return await ctx.send("Format: 1d, 12h, 30m")

        amount, unit = match.groups()
        amount = int(amount)
        if unit == 'd': delta = datetime.timedelta(days=amount)
        elif unit == 'h': delta = datetime.timedelta(hours=amount)
        elif unit == 'm': delta = datetime.timedelta(minutes=amount)

        expires_at = (datetime.datetime.now() + delta).isoformat()
        case_id = await self.create_infraction(member.id, ctx.guild.id, ctx.author.id, "tempban", reason)

        try:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO tempbans (user_id, guild_id, expires_at, reason) VALUES (?, ?, ?, ?)",
                member.id, ctx.guild.id, expires_at, reason
            )
            dm_status = await self.send_dm_notification(
                member, "tempban", reason, case_id, ctx.guild.id, guild=ctx.guild,
                duration=duration, moderator_id=ctx.author.id,
            )
            await member.ban(reason=f"Tempban: {reason} ({duration})")
            await ctx.send(
                f"✅ Tempbanned **{member.display_name}** for {duration}.\n"
                f"{self._dm_staff_note(ctx.guild.id, dm_status)}"
            )
            await self.log_action(ctx.guild, ctx.author, member, "tempban", f"{reason} ({duration})", case_id)
        except Exception as e:
            await ctx.send(f"Error: {e}")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
