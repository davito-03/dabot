"""Radar de cuentas secuestradas.

Detects the MrBeast / Nitro / Steam giveaway malware kit that posts from
stolen Discord tokens: a bait image plus a phishing link. Treats the member
as a victim (timeout + recovery DM) instead of banning them.
Image hashes are remembered across every guild Dabot is in.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import json
import logging
import os
import re

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from utils.helpers import DASHBOARD_URL, guild_lang
from utils import hijack as H
from utils import gemini_client

log = logging.getLogger("Dabot.Hijack")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS hijack_hashes (
        ahash TEXT PRIMARY KEY,
        kind TEXT,
        hits INTEGER NOT NULL DEFAULT 1,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS hijack_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        channel_id INTEGER,
        message_id INTEGER,
        score INTEGER NOT NULL,
        kind TEXT,
        reasons TEXT,
        ahash TEXT,
        action TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS hijack_false_positives (
        ahash TEXT NOT NULL,
        guild_id INTEGER NOT NULL,
        PRIMARY KEY (ahash, guild_id)
    )""",
]

REASON_ES = {
    "celebridad_giveaway": "menciona a MrBeast / sorteo famoso",
    "lenguaje_sorteo": "texto de sorteo / Nitro / gift card",
    "cta_reclamar": "llama a pulsar un enlace",
    "invite_nitro": "invite + Nitro",
    "zalgo": "texto distorsionado",
    "ping_masivo": "ping masivo",
    "url_phishing": "dominio falso de Discord/Nitro/Steam",
    "url_shortener": "acortador de enlaces",
    "url_bait_host": "host con cebo de regalo",
    "url_homoglyph": "URL con caracteres falsos",
    "varios_enlaces_raros": "varios enlaces sospechosos",
    "imagen_mas_enlace": "imagen + enlace (kit típico)",
    "imagen_conocida": "la misma imagen ya saltó en otros servidores",
    "cuenta_callada": "cuenta antigua que de repente suelta el cebo",
    "everyone": "@everyone / @here",
    "cuenta_staff": "la cuenta tiene rango de staff (token robado)",
    "vision_ia": "la imagen parece un sorteo falso",
}


class HijackGuard(commands.Cog):
    """Radar de secuestro: MrBeast, Nitro falso y cuentas con el token robado."""

    def __init__(self, bot):
        self.bot = bot
        self._ready = False
        self._vision_budget: dict[int, list[float]] = {}
        self._recent: dict[int, float] = {}
        self.ctx_menu = app_commands.ContextMenu(
            name="Hijack check",
            callback=self.context_inspect,
        )

    async def cog_load(self):
        for stmt in SCHEMA:
            await self.bot.db.execute(stmt)
        try:
            self.bot.tree.add_command(self.ctx_menu)
        except Exception:
            pass
        self._ready = True

    async def cog_unload(self):
        try:
            self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)
        except Exception:
            pass

    radar = app_commands.Group(
        name="radar",
        description="Hijacked-account radar (MrBeast / Nitro scam images).",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def _cfg(self, guild_id: int) -> dict:
        automod = (self.bot.config.get(guild_id) or {}).get("automod") or {}
        return {
            "enabled": automod.get("hijack", True),
            "timeout": automod.get("hijack_timeout", True),
        }

    def _log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        logs = (self.bot.config.get(guild.id) or {}).get("logs") or {}
        for key in ("hijack", "moderation", "alts", "members"):
            raw = logs.get(key)
            if raw:
                ch = guild.get_channel(int(raw))
                if ch:
                    return ch
        return None

    @radar.command(name="status", description="See hijack-radar status for this server.")
    async def radar_status(self, interaction: discord.Interaction):
        cfg = self._cfg(interaction.guild.id)
        n = await self.bot.db.fetch("SELECT COUNT(*) FROM hijack_events WHERE guild_id = ?", interaction.guild.id)
        hashes = await self.bot.db.fetch("SELECT COUNT(*) FROM hijack_hashes")
        ch = self._log_channel(interaction.guild)
        embed = discord.Embed(
            title="🦞 Radar de secuestro",
            description=(
                "Caza el kit de **cuentas hackeadas** que pegan la imagen de MrBeast / Nitro / Steam "
                "y un enlace falso. No banea: el miembro es la víctima."
            ),
            color=discord.Color.from_rgb(0, 255, 136),
        )
        embed.add_field(name="Activo", value="sí" if cfg["enabled"] else "no", inline=True)
        embed.add_field(name="Timeout", value="sí" if cfg["timeout"] else "solo borrar", inline=True)
        embed.add_field(name="Canal de avisos", value=ch.mention if ch else "mod / alts / members", inline=True)
        embed.add_field(name="Casos aquí", value=str((n or [0])[0]), inline=True)
        embed.add_field(name="Imágenes en memoria global", value=str((hashes or [0])[0]), inline=True)
        embed.set_footer(text=f"Ajustes en {DASHBOARD_URL.replace('https://', '')} → Módulos → AutoMod")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @radar.command(name="recovered", description="I secured my Discord account after a hijack timeout.")
    async def recovered(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Usa este comando en el servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        row = await self.bot.db.fetch(
            """SELECT id, ahash, score FROM hijack_events
               WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1""",
            interaction.guild.id, interaction.user.id,
        )
        if not row:
            await interaction.followup.send("No hay un caso de secuestro reciente tuyo aquí.", ephemeral=True)
            return
        case_id = int(row[0])
        member = interaction.user
        if isinstance(member, discord.Member) and member.is_timed_out():
            pass
        ch = self._log_channel(interaction.guild)
        embed = discord.Embed(
            title="🦞 El usuario dice que ya aseguró la cuenta",
            description=(
                f"{member.mention} (`{member.id}`) ha usado `/recovered`.\n"
                f"Caso #{case_id}. Si cambió contraseña y 2FA, pulsa **Restaurar**."
            ),
            color=discord.Color.from_str("#00FF88"),
        )
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Restaurar", style=discord.ButtonStyle.success,
                                        custom_id=f"dabot:hijack:ok:{case_id}"))
        view.add_item(discord.ui.Button(label="Mantener timeout", style=discord.ButtonStyle.secondary,
                                        custom_id=f"dabot:hijack:keep:{case_id}"))
        if ch:
            await ch.send(embed=embed, view=view)
            await interaction.followup.send(
                "Avisé al staff. Cuando confirmen, te quitan el timeout. "
                "Mientras tanto: contraseña nueva, 2FA y cierra sesiones en Discord.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "No hay canal de avisos. Pide a un moderador que use el botón Restaurar en Admin o en logs.",
                ephemeral=True,
            )

    @radar.command(name="toggle", description="Enable or disable the hijack radar on this server.")
    async def radar_toggle(self, interaction: discord.Interaction, enabled: bool):
        self.bot.config.set_config(interaction.guild.id, "automod.hijack", enabled)
        await interaction.response.send_message(
            f"Radar de secuestro **{'activado' if enabled else 'desactivado'}**.",
            ephemeral=True,
        )

    @radar.command(name="inspect", description="Score a message link as hijack/scam.")
    @app_commands.describe(message="Message ID or jump URL")
    async def radar_inspect(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        msg = await self._resolve_message(interaction, message)
        if not msg:
            await interaction.followup.send("No encontré ese mensaje.", ephemeral=True)
            return
        result = await self.analyze(msg, force_vision=True)
        await interaction.followup.send(embed=self._result_embed(msg, result, inspect=True), ephemeral=True)

    async def context_inspect(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)
        result = await self.analyze(message, force_vision=True)
        await interaction.followup.send(embed=self._result_embed(message, result, inspect=True), ephemeral=True)

    async def _resolve_message(self, interaction: discord.Interaction, raw: str) -> discord.Message | None:
        m = re.search(r"channels/(\d+)/(\d+)/(\d+)", raw)
        try:
            if m:
                ch = interaction.guild.get_channel(int(m.group(2))) or await self.bot.fetch_channel(int(m.group(2)))
                return await ch.fetch_message(int(m.group(3)))
            digits = "".join(c for c in raw if c.isdigit())
            if digits:
                return await interaction.channel.fetch_message(int(digits))
        except Exception:
            return None
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._handle(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.embeds or (after.content or "") != (before.content or ""):
            await self._handle(after)

    async def _handle(self, message: discord.Message):
        if not self._ready or not message.guild or message.author.bot:
            return
        if message.author.id == getattr(self.bot.user, "id", 0):
            return
        cfg = self._cfg(message.guild.id)
        if not cfg["enabled"]:
            return
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        last = self._recent.get(message.author.id, 0)
        if now - last < 1.5:
            return
        # Cheap gate: skip plain chat without links/images/pings/giveaway words.
        content = message.content or ""
        has_media = bool(message.attachments) or any(e.image or e.thumbnail for e in (message.embeds or []))
        has_url = bool(H.URL_RE.search(content)) or any(e.url or e.description for e in (message.embeds or []))
        n = H.normalize(content)
        bait_hint = bool(H.CELEBRITY_RE.search(n) or H.GIVEAWAY_RE.search(n) or "@everyone" in n or "@here" in n)
        if not (has_media or has_url or bait_hint):
            return
        self._recent[message.author.id] = now
        try:
            result = await self.analyze(message)
        except Exception as e:
            log.warning("analyze failed: %s", e)
            return
        if result["score"] < 45:
            return
        await self._act(message, result, timeout=cfg["timeout"] and result["score"] >= 62)

    async def analyze(self, message: discord.Message, force_vision: bool = False) -> dict:
        text_parts = [message.content or ""]
        urls = H.extract_urls(message.content or "")
        for e in message.embeds or []:
            for piece in (e.title, e.description, e.url, e.footer.text if e.footer else None):
                if piece:
                    text_parts.append(piece)
                    urls.extend(H.extract_urls(piece))
            if e.image and e.image.url:
                urls.append(e.image.url)
            if e.thumbnail and e.thumbnail.url:
                urls.append(e.thumbnail.url)
            if e.author and e.author.url:
                urls.append(e.author.url)
        image_urls = []
        for att in message.attachments:
            text_parts.append(att.filename or "")
            if (att.content_type or "").startswith("image") or (att.filename or "").lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".gif")
            ):
                image_urls.append(att.url)
            if att.url:
                urls.append(att.url)
        for e in message.embeds or []:
            if e.image and e.image.url:
                image_urls.append(e.image.url)
            if e.thumbnail and e.thumbnail.url:
                image_urls.append(e.thumbnail.url)

        blob = "\n".join(p for p in text_parts if p)
        text_score, text_reasons = H.score_text(blob)
        # discord CDN of the image itself is not a phishing URL
        ext_urls = [u for u in urls if not H.host_of(u).endswith("discordapp.com")
                    and not H.host_of(u).endswith("discord.com")
                    and "discordapp.net" not in H.host_of(u)]
        url_score, url_reasons = H.score_urls(ext_urls)

        ahash = None
        known = False
        known_kind = None
        img = None
        if image_urls:
            img, raw = await self._download_image(image_urls[0])
            if img is not None:
                ahash = H.dhash(img)
                gid = message.guild.id if message.guild else 0
                hit = await self._hash_hit(ahash, gid)
                if hit:
                    known, known_kind = True, hit[0]

        silent = False
        staff = False
        author = message.author
        if isinstance(author, discord.Member):
            staff = author.guild_permissions.manage_messages or author.guild_permissions.administrator
            joined = author.joined_at
            created = author.created_at
            now = datetime.datetime.now(datetime.timezone.utc)
            if joined and (now - joined).days >= 14:
                silent = True
            elif created and (now - created).days >= 90 and joined and (now - joined).days >= 7:
                silent = True

        everyone = bool(message.mention_everyone)
        score, extra = H.combine_score(
            text_score=text_score,
            url_score=url_score,
            image=bool(img),
            known_hash=known,
            silent_member=silent,
            everyone=everyone,
            staff=staff,
        )
        reasons = text_reasons + url_reasons + extra
        kind = known_kind or ("mrbeast" if any(r == "celebridad_giveaway" for r in reasons) else "giveaway")

        need_vision = force_vision or (img is not None and 40 <= score < 80 and (url_score or everyone or silent))
        if need_vision and img is not None:
            vis = await self._vision(message.guild.id, img, blob[:400])
            if vis:
                if vis.get("scam") and int(vis.get("confidence") or 0) >= 65:
                    score = min(100, score + 28)
                    reasons.append("vision_ia")
                    kind = vis.get("kind") or kind
                elif vis.get("scam") is False and int(vis.get("confidence") or 0) >= 80 and not known:
                    score = max(0, score - 20)

        return {
            "score": int(score),
            "verdict": H.verdict(score),
            "reasons": reasons,
            "kind": kind,
            "ahash": ahash,
            "urls": ext_urls[:6],
            "image": bool(img),
            "silent": silent,
            "staff": staff,
            "known": known,
        }

    async def _download_image(self, url: str):
        session = getattr(self.bot, "session", None)
        if session is None:
            return None, None
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None, None
                data = await resp.read()
            if not data or len(data) > 2_800_000:
                return None, None
            img = Image.open(io.BytesIO(data)).convert("RGB")
            return img, data
        except Exception:
            return None, None

    async def _hash_hit(self, ahash: str, guild_id: int):
        fp = await self.bot.db.fetch(
            "SELECT 1 FROM hijack_false_positives WHERE ahash = ? AND guild_id = ?",
            ahash, guild_id,
        )
        if fp:
            return None
        rows = await self.bot.db.fetch_all(
            "SELECT ahash, kind, hits FROM hijack_hashes ORDER BY last_seen DESC LIMIT 900"
        )
        if not rows:
            return None
        for stored, kind, hits in rows:
            if stored and H.hamming(ahash, stored) <= 12:
                return kind, hits, stored
        return None

    async def _remember_hash(self, ahash: str, kind: str):
        if not ahash:
            return
        now = datetime.datetime.utcnow().isoformat()
        existing = await self.bot.db.fetch("SELECT hits FROM hijack_hashes WHERE ahash = ?", ahash)
        if existing:
            await self.bot.db.execute(
                "UPDATE hijack_hashes SET hits = hits + 1, last_seen = ?, kind = ? WHERE ahash = ?",
                now, kind, ahash,
            )
        else:
            await self.bot.db.execute(
                "INSERT INTO hijack_hashes (ahash, kind, hits, first_seen, last_seen) VALUES (?, ?, 1, ?, ?)",
                ahash, kind, now, now,
            )

    def _vision_ok(self, guild_id: int) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        bucket = [t for t in self._vision_budget.get(guild_id, []) if now - t < 3600]
        self._vision_budget[guild_id] = bucket
        return len(bucket) < 8

    async def _vision(self, guild_id: int, img: Image.Image, caption: str) -> dict | None:
        if not self._vision_ok(guild_id):
            return None
        self._vision_budget.setdefault(guild_id, []).append(
            datetime.datetime.now(datetime.timezone.utc).timestamp()
        )
        prompt = (
            "You moderate Discord. Is this image a phishing giveaway used by hacked accounts "
            "(fake MrBeast, Discord Nitro, Steam gift, 'click the link')? "
            "Answer ONLY JSON: {\"scam\": true|false, \"kind\": \"mrbeast|nitro|steam|other|none\", "
            "\"confidence\": 0-100, \"reason\": \"short\"}."
        )
        if caption:
            prompt += f" Caption: {caption[:300]}"
        try:
            raw = await gemini_client.generate_vision(prompt, img, timeout=8)
        except Exception as e:
            log.info("vision skip: %s", e)
            return None
        if not raw:
            return None
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        return None

    async def _act(self, message: discord.Message, result: dict, timeout: bool):
        guild = message.guild
        member = message.author
        deleted = False
        timed = False
        try:
            await message.delete()
            deleted = True
        except Exception:
            pass

        if timeout and isinstance(member, discord.Member):
            try:
                until = datetime.timedelta(minutes=45)
                await member.timeout(until, reason=f"Radar secuestro ({result['score']}/100 · {result['kind']})")
                timed = True
            except Exception:
                pass

        await self._remember_hash(result.get("ahash") or "", result.get("kind") or "giveaway")
        now = datetime.datetime.utcnow().isoformat()
        case_id = await self.bot.db.execute(
            """INSERT INTO hijack_events
               (guild_id, user_id, channel_id, message_id, score, kind, reasons, ahash, action, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            guild.id, member.id, message.channel.id, message.id,
            result["score"], result.get("kind"), json.dumps(result.get("reasons") or []),
            result.get("ahash"), "timeout" if timed else ("delete" if deleted else "alert"), now,
        )
        case_id = int(case_id or 0)

        try:
            await self.bot.db.execute(
                """INSERT INTO audit_events (guild_id, event_type, actor_id, target_id, channel_id, summary, extra, timestamp)
                   VALUES (?, 'hijack', ?, ?, ?, ?, ?, ?)""",
                guild.id, self.bot.user.id if self.bot.user else 0, member.id, message.channel.id,
                f"Radar secuestro {result['score']}/100 ({result.get('kind')})",
                json.dumps({"reasons": result.get("reasons"), "ahash": result.get("ahash")}, ensure_ascii=False),
                now,
            )
        except Exception:
            pass

        await self._dm_recovery(member, guild)
        ch = self._log_channel(guild)
        if ch:
            embed = self._result_embed(message, result, inspect=False)
            embed.add_field(
                name="Acción",
                value=("Mensaje borrado" if deleted else "No pude borrar")
                + (" · timeout 45 min" if timed else " · sin timeout"),
                inline=False,
            )
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Restaurar", style=discord.ButtonStyle.success,
                                            custom_id=f"dabot:hijack:ok:{case_id}"))
            view.add_item(discord.ui.Button(label="Mantener", style=discord.ButtonStyle.secondary,
                                            custom_id=f"dabot:hijack:keep:{case_id}"))
            view.add_item(discord.ui.Button(label="Falsa alarma", style=discord.ButtonStyle.danger,
                                            custom_id=f"dabot:hijack:no:{case_id}"))
            try:
                await ch.send(embed=embed, view=view)
            except Exception:
                pass
        else:
            try:
                await message.channel.send(
                    f"🦞 Radar: {member.mention} acaba de pegar un sorteo falso típico de **cuenta hackeada**. "
                    f"Mensaje retirado. Si eres tú, cambia la contraseña de Discord.",
                    delete_after=20,
                )
            except Exception:
                pass

    def _result_embed(self, message: discord.Message, result: dict, inspect: bool) -> discord.Embed:
        v = result["verdict"]
        color = {"critical": 0xFB7185, "high": 0xF97316, "medium": 0xFBBF24, "low": 0x34D399}[v]
        title = "¿Es un secuestro?" if inspect else "🦞 Cuenta posiblemente hackeada"
        reasons = ", ".join(REASON_ES.get(r, r) for r in (result.get("reasons") or [])[:8]) or "sin señales fuertes"
        desc = (
            f"**Usuario:** {message.author.mention} `{message.author.id}`\n"
            f"**Canal:** {getattr(message.channel, 'mention', message.channel)}\n"
            f"**Riesgo:** **{result['score']}/100 · {v}** · kit `{result.get('kind')}`\n"
            f"**Señales:** {reasons}"
        )
        embed = discord.Embed(title=title, description=desc[:4000], color=color)
        if result.get("urls"):
            embed.add_field(name="Enlaces", value="\n".join(f"`{u[:80]}`" for u in result["urls"][:4])[:1024], inline=False)
        if result.get("ahash"):
            embed.add_field(name="Huella de imagen", value=f"`{result['ahash'][:20]}…`" if len(result["ahash"]) > 22 else f"`{result['ahash']}`", inline=True)
        if result.get("known"):
            embed.add_field(name="Red", value="Misma imagen vista en otros servidores Dabot", inline=True)
        if inspect:
            note = "Parece el kit de cuentas hackeadas." if result["score"] >= 62 else (
                "Dudoso: míralo tú." if result["score"] >= 45 else "No parece el scam de MrBeast/Nitro."
            )
            embed.add_field(name="Veredicto", value=note, inline=False)
        else:
            embed.set_footer(text="No se banea: es una víctima. Restaurar quita el timeout.")
        return embed

    async def _dm_recovery(self, member: discord.abc.User, guild: discord.Guild):
        lang = guild_lang(self.bot, guild.id)
        if lang == "en":
            text = (
                f"**Your Discord account was used to post a fake giveaway in {guild.name}.**\n\n"
                "That pattern usually means a **stolen token** (a fake MrBeast / Nitro image).\n"
                "1. Change your Discord password now.\n"
                "2. Enable 2FA if you haven't.\n"
                "3. Log out all sessions: Settings → Devices.\n"
                "4. Do **not** click the link you just sent.\n\n"
                "Dabot timed you out for 45 minutes so the malware stops posting. "
                "Ask staff to restore you after you secure the account."
            )
        else:
            text = (
                f"**Tu cuenta de Discord se usó para pegar un sorteo falso en {guild.name}.**\n\n"
                "Ese patrón es el de **token robado** (imagen de MrBeast / Nitro falso).\n"
                "1. Cambia ahora la contraseña de Discord.\n"
                "2. Activa el 2FA si no lo tienes.\n"
                "3. Cierra sesiones: Ajustes → Dispositivos.\n"
                "4. **No pulses** el enlace que se acaba de enviar.\n\n"
                "Dabot te ha silenciado 45 minutos para que deje de publicar el malware. "
                "Cuando asegures la cuenta, pide al staff que te restaure."
            )
        try:
            await member.send(text)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        cid = (interaction.data or {}).get("custom_id") or ""
        if not cid.startswith("dabot:hijack:"):
            return
        parts = cid.split(":")
        if len(parts) < 4:
            return
        action, case_id = parts[2], parts[3]
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Necesitas permiso de moderar mensajes.", ephemeral=True)
            return
        row = await self.bot.db.fetch(
            "SELECT guild_id, user_id, ahash, score FROM hijack_events WHERE id = ?",
            int(case_id),
        )
        if not row:
            await interaction.response.send_message("Caso no encontrado.", ephemeral=True)
            return
        guild_id, user_id, ahash, score = row[0], row[1], row[2], row[3]
        if interaction.guild and interaction.guild.id != guild_id:
            await interaction.response.send_message("Este caso no es de este servidor.", ephemeral=True)
            return
        member = interaction.guild.get_member(user_id)
        note = ""
        if action == "ok":
            if member:
                try:
                    await member.timeout(None, reason=f"Radar restaurado por {interaction.user}")
                    note = f"Timeout quitado a {member.mention}."
                except Exception as e:
                    note = f"No pude quitar el timeout: {e}"
            else:
                note = "El miembro ya no está en el servidor."
        elif action == "no":
            if ahash:
                await self.bot.db.execute(
                    "INSERT OR IGNORE INTO hijack_false_positives (ahash, guild_id) VALUES (?, ?)",
                    ahash, guild_id,
                )
                await self.bot.db.execute("DELETE FROM hijack_hashes WHERE ahash = ?", ahash)
            note = "Marcado como falsa alarma. Esa imagen ya no se bloquea aquí."
        else:
            note = f"Caso #{case_id} dejado en cuarentena (score {score})."
        color = discord.Color.from_str("#00FF88") if action == "ok" else (
            discord.Color.orange() if action == "no" else discord.Color.dark_grey()
        )
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = color
        embed.add_field(name="Staff", value=f"{note}\nPor {interaction.user.mention}", inline=False)
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            if not interaction.response.is_done():
                await interaction.response.send_message(note, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HijackGuard(bot))
