import asyncio
import datetime
import json
import logging

import discord
from discord.ext import commands

from utils.announcements import SOURCE_CHANNEL_ID, SOURCE_GUILD_ID, default_channel_name, is_source


class Announcements(commands.Cog):
    """Mirrors messages from the owner's private source channel to all guilds."""

    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Dabot.Announcements")
        self._fanout_lock = asyncio.Lock()

    async def cog_load(self):
        asyncio.create_task(self._check_source_access())

    async def _check_source_access(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(SOURCE_GUILD_ID)
        channel = self.bot.get_channel(SOURCE_CHANNEL_ID)
        if not guild or not channel:
            self.logger.error("Announcement source is not visible: guild=%s channel=%s", SOURCE_GUILD_ID, SOURCE_CHANNEL_ID)
            return
        if not guild.me:
            self.logger.error("Announcement source bot member is not available in guild %s", SOURCE_GUILD_ID)
            return
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.read_message_history):
            self.logger.error("Announcement source needs View Channel and Read Message History: %s", SOURCE_CHANNEL_ID)
            return
        self.logger.info("Announcement source ready: %s/%s", SOURCE_GUILD_ID, SOURCE_CHANNEL_ID)

    @staticmethod
    def _content(message) -> str:
        content = message.content or ""
        attachment_urls = [a.url for a in (message.attachments or []) if getattr(a, "url", None)]
        if attachment_urls:
            content = (content + "\n" if content else "") + "\n".join(attachment_urls)
        return content[:2000]

    @staticmethod
    def _embeds(message):
        result = []
        for embed in message.embeds or []:
            try:
                result.append(discord.Embed.from_dict(embed.to_dict()))
            except Exception:
                continue
        return result[:10]

    async def _target_channel(self, guild):
        row = await self.bot.db.fetch(
            "SELECT channel_id FROM announcement_config WHERE guild_id = ?", guild.id
        )
        configured = int(row[0]) if row and row[0] else None
        if configured:
            channel = guild.get_channel(configured)
            # News channels are exposed as TextChannel-compatible objects by discord.py;
            # threads are intentionally not valid configured destinations.
            if channel and isinstance(channel, discord.TextChannel):
                perms = channel.permissions_for(guild.me)
                if perms.view_channel and perms.send_messages:
                    return channel

        candidates = [c for c in guild.text_channels if default_channel_name(c.name)]
        candidates += [c for c in guild.text_channels if c not in candidates]
        for channel in candidates:
            perms = channel.permissions_for(guild.me)
            if perms.view_channel and perms.send_messages:
                return channel
        return None

    async def _store_source(self, message):
        await self.bot.db.execute(
            """INSERT INTO announcement_messages
               (source_message_id, source_guild_id, source_channel_id, content, embeds, attachments, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_message_id) DO UPDATE SET
                 content = excluded.content, embeds = excluded.embeds, attachments = excluded.attachments""",
            str(message.id), message.guild.id, message.channel.id, self._content(message),
            json.dumps([e.to_dict() for e in (message.embeds or [])], ensure_ascii=False),
            json.dumps([a.url for a in (message.attachments or [])], ensure_ascii=False),
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    async def _publish(self, message):
        async with self._fanout_lock:
            await self._store_source(message)
            content = self._content(message) or "\u200b"
            embeds = self._embeds(message)
            for guild in list(self.bot.guilds):
                channel = await self._target_channel(guild)
                if not channel:
                    await self.bot.db.execute(
                        """INSERT INTO announcement_deliveries
                           (source_message_id, guild_id, channel_id, message_id, status, error, updated_at)
                           VALUES (?, ?, NULL, NULL, 'skipped', ?, ?)
                           ON CONFLICT(source_message_id, guild_id) DO UPDATE SET status=excluded.status, error=excluded.error, updated_at=excluded.updated_at""",
                        str(message.id), guild.id, "No hay canal enviable", datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    )
                    continue
                try:
                    sent = await channel.send(
                        content=content,
                        embeds=embeds,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    await self.bot.db.execute(
                        """INSERT INTO announcement_deliveries
                           (source_message_id, guild_id, channel_id, message_id, status, error, updated_at)
                           VALUES (?, ?, ?, ?, 'sent', NULL, ?)
                           ON CONFLICT(source_message_id, guild_id) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id, status=excluded.status, error=NULL, updated_at=excluded.updated_at""",
                        str(message.id), guild.id, channel.id, sent.id, datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    )
                except (discord.Forbidden, discord.HTTPException) as exc:
                    self.logger.warning("Announcement failed in guild %s: %s", guild.id, exc)
                    await self.bot.db.execute(
                        """INSERT INTO announcement_deliveries
                           (source_message_id, guild_id, channel_id, message_id, status, error, updated_at)
                           VALUES (?, ?, ?, NULL, 'failed', ?, ?)
                           ON CONFLICT(source_message_id, guild_id) DO UPDATE SET status=excluded.status, error=excluded.error, updated_at=excluded.updated_at""",
                        str(message.id), guild.id, channel.id, str(exc)[:500], datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    )

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or message.author.id != self.bot.super_owner_id:
            return
        if is_source(message.guild.id, message.channel.id):
            await self._publish(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not after.guild or after.author.bot or after.author.id != self.bot.super_owner_id:
            return
        if not is_source(after.guild.id, after.channel.id):
            return
        content = self._content(after) or "\u200b"
        embeds = self._embeds(after)
        await self._store_source(after)
        rows = await self.bot.db.fetch_all(
            "SELECT guild_id, channel_id, message_id FROM announcement_deliveries WHERE source_message_id = ? AND status = 'sent'",
            str(after.id),
        )
        for guild_id, channel_id, message_id in rows:
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    continue
                target = await channel.fetch_message(int(message_id))
                await target.edit(content=content, embeds=embeds, allowed_mentions=discord.AllowedMentions.none())
                await self.bot.db.execute(
                    "UPDATE announcement_deliveries SET updated_at = ?, error = NULL WHERE source_message_id = ? AND guild_id = ?",
                    datetime.datetime.now(datetime.timezone.utc).isoformat(), str(after.id), int(guild_id),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                self.logger.warning("Announcement edit failed in guild %s: %s", guild_id, exc)
                await self.bot.db.execute(
                    "UPDATE announcement_deliveries SET status = 'failed', error = ?, updated_at = ? WHERE source_message_id = ? AND guild_id = ?",
                    str(exc)[:500], datetime.datetime.now(datetime.timezone.utc).isoformat(), str(after.id), int(guild_id),
                )

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Delete every mirrored copy when the source announcement is deleted."""
        if not message.guild or message.author.bot or message.author.id != self.bot.super_owner_id:
            return
        if not is_source(message.guild.id, message.channel.id):
            return
        rows = await self.bot.db.fetch_all(
            "SELECT guild_id, channel_id, message_id FROM announcement_deliveries WHERE source_message_id = ? AND status IN ('sent', 'failed')",
            str(message.id),
        )
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for guild_id, channel_id, message_id in rows:
            if not channel_id or not message_id:
                await self.bot.db.execute(
                    "UPDATE announcement_deliveries SET status = 'deleted', error = NULL, updated_at = ? WHERE source_message_id = ? AND guild_id = ?",
                    now, str(message.id), int(guild_id),
                )
                continue
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    raise RuntimeError("Canal de destino no disponible")
                target = await channel.fetch_message(int(message_id))
                await target.delete()
                await self.bot.db.execute(
                    "UPDATE announcement_deliveries SET status = 'deleted', error = NULL, updated_at = ? WHERE source_message_id = ? AND guild_id = ?",
                    now, str(message.id), int(guild_id),
                )
            except discord.NotFound:
                # Already gone is the desired final state.
                await self.bot.db.execute(
                    "UPDATE announcement_deliveries SET status = 'deleted', error = NULL, updated_at = ? WHERE source_message_id = ? AND guild_id = ?",
                    now, str(message.id), int(guild_id),
                )
            except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
                self.logger.warning("Announcement deletion failed in guild %s: %s", guild_id, exc)
                await self.bot.db.execute(
                    "UPDATE announcement_deliveries SET status = 'delete_failed', error = ?, updated_at = ? WHERE source_message_id = ? AND guild_id = ?",
                    str(exc)[:500], now, str(message.id), int(guild_id),
                )


async def setup(bot):
    await bot.add_cog(Announcements(bot))
