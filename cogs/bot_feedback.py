"""Owners/admins send product ideas for Dabot to a private review channel."""
from __future__ import annotations

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.bot_suggestions import (
    SCHEMA,
    SUGGEST_CHANNEL_ID,
    SUGGEST_GUILD_ID,
    dm_text,
    embed_payload,
)
from utils.helpers import DASHBOARD_URL

log = logging.getLogger("Dabot.Feedback")


def _can_submit(member: discord.Member, bot) -> bool:
    if not member or not member.guild:
        return False
    if member.id == getattr(bot, "super_owner_id", 0):
        return True
    if member.id == member.guild.owner_id:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and perms.administrator)


class SuggestionReplyModal(discord.ui.Modal):
    respuesta = discord.ui.TextInput(
        label="Respuesta que recibirá el autor por MD",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        required=True,
    )

    def __init__(self, cog: "BotFeedback", suggestion_id: int, status: str):
        titles = {
            "accepted": "Sugerencia aceptada",
            "rejected": "Sugerencia rechazada",
            "reviewing": "Evaluando sugerencia",
        }
        super().__init__(title=titles.get(status, "Responder sugerencia")[:45])
        self.cog = cog
        self.suggestion_id = suggestion_id
        self.status = status

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, err = await self.cog.resolve(
            self.suggestion_id,
            self.status,
            str(self.respuesta.value or "").strip(),
            interaction.user.id,
            message=interaction.message,
        )
        if ok:
            await interaction.followup.send("Respuesta enviada al autor por MD (si tiene los privados abiertos).", ephemeral=True)
        else:
            await interaction.followup.send(err or "No se pudo resolver.", ephemeral=True)


class BotFeedback(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(SCHEMA)

    def _view(self, sid: int) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            label="Sugerencia aceptada", style=discord.ButtonStyle.success,
            custom_id=f"dabot:sug:accepted:{sid}",
        ))
        view.add_item(discord.ui.Button(
            label="Sugerencia rechazada", style=discord.ButtonStyle.danger,
            custom_id=f"dabot:sug:rejected:{sid}",
        ))
        view.add_item(discord.ui.Button(
            label="Evaluando sugerencia", style=discord.ButtonStyle.secondary,
            custom_id=f"dabot:sug:reviewing:{sid}",
        ))
        return view

    def _embed_from_row(self, row: dict) -> discord.Embed:
        payload = embed_payload(row)
        embed = discord.Embed(
            title=payload["title"],
            description=payload["description"],
            color=payload["color"],
            timestamp=discord.utils.utcnow(),
        )
        for field in payload["fields"]:
            embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
        embed.set_footer(text=payload["footer"]["text"])
        return embed

    async def _daily_count(self, user_id: int) -> int:
        since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
        row = await self.bot.db.fetch(
            "SELECT COUNT(*) FROM bot_suggestions WHERE user_id = ? AND created_at >= ?",
            user_id, since,
        )
        return (row[0] if row else 0) or 0

    async def submit(self, *, user, guild, text: str) -> tuple[int | None, str]:
        text = (text or "").strip()
        if len(text) < 8:
            return None, "Escribe al menos unas líneas (mínimo 8 caracteres)."
        if len(text) > 1800:
            return None, "Máximo 1800 caracteres."
        if await self._daily_count(user.id) >= 8:
            return None, "Límite de 8 sugerencias cada 24 horas."
        channel = self.bot.get_channel(SUGGEST_CHANNEL_ID)
        if channel is None:
            g = self.bot.get_guild(SUGGEST_GUILD_ID)
            if g:
                channel = g.get_channel(SUGGEST_CHANNEL_ID)
        if channel is None:
            return None, "No encuentro el canal de sugerencias. Avisa al creador de Dabot."
        now = datetime.datetime.utcnow().isoformat()
        sid = await self.bot.db.execute(
            """INSERT INTO bot_suggestions
               (user_id, username, guild_id, guild_name, text, status, created_at, channel_id)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            user.id, str(user), getattr(guild, "id", None), getattr(guild, "name", None),
            text, now, SUGGEST_CHANNEL_ID,
        )
        row = {
            "id": sid, "user_id": user.id, "guild_id": getattr(guild, "id", None),
            "guild_name": getattr(guild, "name", None), "text": text, "status": "pending",
        }
        try:
            msg = await channel.send(embed=self._embed_from_row(row), view=self._view(sid))
            await self.bot.db.execute(
                "UPDATE bot_suggestions SET message_id = ? WHERE id = ?", msg.id, sid
            )
        except Exception as e:
            log.warning("Could not post suggestion %s: %s", sid, e)
            return sid, "Guardada, pero no pude publicarla en el canal de revisión."
        return sid, ""

    async def resolve(self, sid: int, status: str, response: str, resolver_id: int, message=None) -> tuple[bool, str]:
        row = await self.bot.db.fetch(
            """SELECT id, user_id, username, guild_id, guild_name, text, status, message_id, channel_id
               FROM bot_suggestions WHERE id = ?""",
            sid,
        )
        if not row:
            return False, "Sugerencia no encontrada."
        now = datetime.datetime.utcnow().isoformat()
        await self.bot.db.execute(
            """UPDATE bot_suggestions
               SET status = ?, response = ?, resolved_at = ?, resolved_by = ?
               WHERE id = ?""",
            status, response, now, resolver_id, sid,
        )
        data = {
            "id": row[0], "user_id": row[1], "username": row[2], "guild_id": row[3],
            "guild_name": row[4], "text": row[5], "status": status, "response": response,
        }
        embed = self._embed_from_row(data)
        target_msg = message
        if target_msg is None and row[7]:
            ch = self.bot.get_channel(row[8] or SUGGEST_CHANNEL_ID)
            if ch:
                try:
                    target_msg = await ch.fetch_message(row[7])
                except Exception:
                    target_msg = None
        if target_msg:
            try:
                await target_msg.edit(embed=embed, view=self._view(sid))
            except Exception:
                pass
        dm_ok = False
        try:
            user = self.bot.get_user(row[1]) or await self.bot.fetch_user(row[1])
            await user.send(dm_text(status, row[5], response))
            dm_ok = True
        except Exception as e:
            log.info("Could not DM suggestion author %s: %s", row[1], e)
        if not dm_ok and target_msg:
            try:
                await target_msg.reply(f"No pude enviar el MD a <@{row[1]}>.", mention_author=False)
            except Exception:
                pass
        return True, ""

    @commands.hybrid_command(name="sugerir", description="Envía una sugerencia o mejora para Dabot (owners y admins).")
    @app_commands.describe(texto="Tu idea o mejora para Dabot")
    async def sugerir(self, ctx: commands.Context, *, texto: str):
        if not ctx.guild:
            await ctx.send("Usa este comando dentro de un servidor donde seas owner o administrador.")
            return
        if not _can_submit(ctx.author, self.bot):
            await ctx.send("Solo el **dueño** o un **administrador** del servidor puede enviar sugerencias para Dabot.")
            return
        sid, err = await self.submit(user=ctx.author, guild=ctx.guild, text=texto)
        if err and not sid:
            await ctx.send(f"❌ {err}")
            return
        extra = f" ({err})" if err else ""
        kwargs = {"ephemeral": True} if getattr(ctx, "interaction", None) else {}
        await ctx.send(
            f"✅ Sugerencia **#{sid}** enviada al creador de Dabot.{extra}\n"
            f"Te avisaré por MD cuando la revisen. Panel: {DASHBOARD_URL}",
            **kwargs,
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id") or ""
        if not cid.startswith("dabot:sug:"):
            return
        parts = cid.split(":")
        if len(parts) < 4:
            return
        action, raw_id = parts[2], parts[3]
        if action not in {"accepted", "rejected", "reviewing"}:
            return
        if interaction.user.id != getattr(self.bot, "super_owner_id", 0):
            await interaction.response.send_message("Solo el creador de Dabot puede resolver sugerencias.", ephemeral=True)
            return
        try:
            sid = int(raw_id)
        except ValueError:
            return
        await interaction.response.send_modal(SuggestionReplyModal(self, sid, action))


async def setup(bot):
    await bot.add_cog(BotFeedback(bot))
