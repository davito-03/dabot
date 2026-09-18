"""Background cache of server channels and the last 10 messages per text channel."""
from __future__ import annotations

import asyncio
import json
import logging

import discord
from discord.ext import commands, tasks

from utils import live_cache as LC

TEXT_TYPE_VALUES = {0, 5}  # guild text, announcement


def _chan_type(channel) -> int:
    t = getattr(channel, "type", None)
    return int(getattr(t, "value", t) if t is not None else -1)


def _is_text(channel) -> bool:
    return _chan_type(channel) in TEXT_TYPE_VALUES


def _avatar(user) -> str | None:
    if user is None:
        return None
    avatar = getattr(user, "avatar", None)
    if avatar is None:
        return None
    return getattr(avatar, "key", None) or getattr(avatar, "filename", None)


def _attachments(message) -> list[dict]:
    out = []
    for att in message.attachments or []:
        out.append({
            "url": att.url,
            "filename": att.filename or "archivo",
            "content_type": att.content_type or "",
        })
    return out


class LiveCache(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Dabot.LiveCache")
        self._ready = asyncio.Event()
        self._backfilled: set[int] = set()

    async def cog_load(self):
        db = await self.bot.db._get_conn()
        for sql in LC.SCHEMA:
            await db.execute(sql)
        await db.commit()
        self.sync_channels_loop.start()
        self.watch_backfill_loop.start()
        self.slow_backfill_loop.start()

    def cog_unload(self):
        self.sync_channels_loop.cancel()
        self.watch_backfill_loop.cancel()
        self.slow_backfill_loop.cancel()

    async def _commit(self):
        db = await self.bot.db._get_conn()
        await db.commit()

    async def upsert_guild(self, guild: discord.Guild):
        await self.bot.db.execute(
            """INSERT INTO cached_guilds (guild_id, name, icon, member_count, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 name=excluded.name, icon=excluded.icon,
                 member_count=excluded.member_count, updated_at=excluded.updated_at""",
            guild.id, guild.name, getattr(guild.icon, "key", None) if guild.icon else None,
            guild.member_count or 0, LC.now_iso(),
        )

    async def upsert_channel(self, channel):
        if not _is_text(channel):
            return
        parent = getattr(channel, "category", None)
        await self.bot.db.execute(
            """INSERT INTO cached_channels
               (channel_id, guild_id, name, type, position, parent_id, category, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET
                 guild_id=excluded.guild_id, name=excluded.name, type=excluded.type,
                 position=excluded.position, parent_id=excluded.parent_id,
                 category=excluded.category, updated_at=excluded.updated_at""",
            channel.id, channel.guild.id, channel.name or "canal", _chan_type(channel),
            getattr(channel, "position", 0) or 0,
            parent.id if parent else None,
            parent.name if parent else None,
            LC.now_iso(),
        )

    async def sync_guild(self, guild: discord.Guild):
        await self.upsert_guild(guild)
        keep = []
        for channel in guild.channels:
            if _is_text(channel):
                await self.upsert_channel(channel)
                keep.append(channel.id)
        if keep:
            placeholders = ",".join("?" * len(keep))
            await self.bot.db.execute(
                f"DELETE FROM cached_channels WHERE guild_id = ? AND channel_id NOT IN ({placeholders})",
                guild.id, *keep,
            )
        else:
            await self.bot.db.execute("DELETE FROM cached_channels WHERE guild_id = ?", guild.id)

    async def cache_message(self, message: discord.Message):
        if not message.guild or not _is_text(message.channel):
            return
        author = message.author
        await self.bot.db.execute(
            """INSERT INTO cached_messages
               (message_id, channel_id, guild_id, author_id, author_name, author_avatar,
                author_bot, content, attachments_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(message_id) DO UPDATE SET
                 content=excluded.content, attachments_json=excluded.attachments_json,
                 author_name=excluded.author_name, author_avatar=excluded.author_avatar""",
            message.id, message.channel.id, message.guild.id, author.id,
            getattr(author, "display_name", None) or author.name,
            _avatar(author), 1 if author.bot else 0,
            message.content or "",
            json.dumps(_attachments(message), ensure_ascii=False),
            message.created_at.isoformat() if message.created_at else LC.now_iso(),
        )
        await self.bot.db.execute(
            """DELETE FROM cached_messages
               WHERE channel_id = ?
                 AND message_id IN (
                   SELECT message_id FROM (
                     SELECT message_id FROM cached_messages
                     WHERE channel_id = ?
                     ORDER BY message_id DESC
                     LIMIT -1 OFFSET ?
                   )
                 )""",
            message.channel.id, message.channel.id, LC.KEEP_MESSAGES,
        )

    async def backfill_channel(self, channel) -> int:
        if channel is None or not _is_text(channel):
            return 0
        self._backfilled.add(channel.id)
        n = 0
        try:
            async for message in channel.history(limit=LC.KEEP_MESSAGES):
                await self.cache_message(message)
                n += 1
        except discord.Forbidden:
            self.logger.debug("No history access in #%s (%s)", getattr(channel, "name", "?"), channel.id)
        except discord.HTTPException as e:
            self.logger.debug("History fetch %s: %s", channel.id, e)
        return n

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready.is_set():
            return
        self._ready.set()
        self.logger.info("Syncing channel catalog for %s guilds…", len(self.bot.guilds))
        for guild in list(self.bot.guilds):
            try:
                await self.sync_guild(guild)
            except Exception as e:
                self.logger.warning("Channel sync %s failed: %s", guild.id, e)
            await asyncio.sleep(0.05)
        self.logger.info("Channel catalog ready.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.sync_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.bot.db.execute("DELETE FROM cached_channels WHERE guild_id = ?", guild.id)
        await self.bot.db.execute("DELETE FROM cached_messages WHERE guild_id = ?", guild.id)
        await self.bot.db.execute("DELETE FROM cached_guilds WHERE guild_id = ?", guild.id)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.upsert_channel(channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        await self.upsert_channel(after)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        self._backfilled.discard(channel.id)
        await self.bot.db.execute("DELETE FROM cached_channels WHERE channel_id = ?", channel.id)
        await self.bot.db.execute("DELETE FROM cached_messages WHERE channel_id = ?", channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await self.cache_message(message)
        except Exception as e:
            self.logger.debug("cache_message: %s", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.guild and _is_text(after.channel):
            try:
                await self.cache_message(after)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if getattr(message, "id", None):
            try:
                await self.bot.db.execute("DELETE FROM cached_messages WHERE message_id = ?", message.id)
            except Exception:
                pass

    @tasks.loop(minutes=5)
    async def sync_channels_loop(self):
        await self._ready.wait()
        for guild in list(self.bot.guilds):
            try:
                await self.sync_guild(guild)
            except Exception as e:
                self.logger.debug("periodic sync %s: %s", guild.id, e)
            await asyncio.sleep(0.15)

    @sync_channels_loop.before_loop
    async def before_sync_channels_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=6)
    async def watch_backfill_loop(self):
        await self._ready.wait()
        try:
            rows = await self.bot.db.fetch_all(
                "SELECT channel_id FROM live_watch ORDER BY watched_at DESC LIMIT 8"
            )
        except Exception:
            return
        for row in rows or []:
            channel_id = row[0] if not hasattr(row, "keys") else row["channel_id"]
            cid = int(channel_id)
            if cid in self._backfilled:
                continue
            count = await self.bot.db.fetch(
                "SELECT COUNT(*) FROM cached_messages WHERE channel_id = ?", cid
            )
            n = count[0] if count else 0
            if n >= LC.KEEP_MESSAGES:
                self._backfilled.add(cid)
                continue
            channel = self.bot.get_channel(cid)
            if channel is None:
                continue
            await self.backfill_channel(channel)
            await asyncio.sleep(1.1)

    @watch_backfill_loop.before_loop
    async def before_watch_backfill_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=12)
    async def slow_backfill_loop(self):
        """Fill last-10 for text channels across guilds (rate-limit safe and one-shot per channel)."""
        await self._ready.wait()
        filled = 0
        for guild in list(self.bot.guilds):
            text_channels = [c for c in guild.channels if _is_text(c)]
            for channel in text_channels:
                if channel.id in self._backfilled:
                    continue
                try:
                    count = await self.bot.db.fetch(
                        "SELECT COUNT(*) FROM cached_messages WHERE channel_id = ?", channel.id
                    )
                    n = count[0] if count else 0
                    if n >= LC.KEEP_MESSAGES:
                        self._backfilled.add(channel.id)
                        continue
                    got = await self.backfill_channel(channel)
                    if got:
                        filled += 1
                        self.logger.info("Backfilled %s msgs in #%s (%s)", got, channel.name, guild.name)
                        if filled >= 2:
                            return
                    await asyncio.sleep(1.2)
                except Exception as e:
                    self.logger.debug("slow backfill #%s: %s", getattr(channel, "id", "?"), e)

    @slow_backfill_loop.before_loop
    async def before_slow_backfill_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(8)


async def setup(bot):
    await bot.add_cog(LiveCache(bot))
