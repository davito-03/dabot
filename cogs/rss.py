import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import datetime
import re
from urllib.parse import urlparse
import ipaddress

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False


class RSS(commands.Cog):
    """RSS Feed reader — polls feeds and posts new entries."""
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.RSS')
        if HAS_FEEDPARSER:
            self.check_feeds.start()

    def cog_unload(self):
        if HAS_FEEDPARSER:
            self.check_feeds.cancel()

    rss_group = app_commands.Group(name="rss", description="RSS Feed management.",
                                   default_permissions=discord.Permissions(manage_guild=True))

    @staticmethod
    def _valid_url(url: str) -> bool:
        try:
            parsed = urlparse(url.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                return False
            host = parsed.hostname.lower().rstrip(".")
            if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
                return False
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
            except ValueError:
                pass
            return True
        except Exception:
            return False

    @rss_group.command(name="add", description="Follow an RSS feed.")
    @app_commands.describe(url="RSS/Atom feed URL", channel="Channel for new entries")
    async def rss_add(self, interaction: discord.Interaction, url: str, channel: discord.TextChannel):
        if not HAS_FEEDPARSER:
            await interaction.response.send_message("❌ `feedparser` not installed.", ephemeral=True)
            return
        if not self._valid_url(url):
            await interaction.response.send_message("❌ Solo se permiten URLs HTTP/HTTPS públicas.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        import asyncio
        try:
            feed = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, feedparser.parse, url),
                timeout=12,
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ El feed tardó demasiado en responder.", ephemeral=True)
            return
        if feed.bozo and not feed.entries:
            await interaction.followup.send("❌ Invalid feed URL.", ephemeral=True)
            return
        last_id = feed.entries[0].get('id', feed.entries[0].get('link', '')) if feed.entries else ''
        try:
            await self.bot.db.execute(
                "INSERT INTO rss_feeds (guild_id, channel_id, url, last_entry_id) VALUES (?, ?, ?, ?)",
                interaction.guild.id, channel.id, url, last_id)
        except Exception:
            await interaction.followup.send("❌ Feed already followed.", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Following `{feed.feed.get('title', url)}` in {channel.mention}.", ephemeral=True)

    @rss_group.command(name="remove", description="Unfollow an RSS feed.")
    @app_commands.describe(url="Feed URL to remove")
    async def rss_remove(self, interaction: discord.Interaction, url: str):
        await self.bot.db.execute("DELETE FROM rss_feeds WHERE guild_id = ? AND url = ?", interaction.guild.id, url)
        await interaction.response.send_message(f"✅ Removed `{url}`.", ephemeral=True)

    @rss_group.command(name="list", description="List followed feeds.")
    async def rss_list(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetch_all("SELECT url, channel_id FROM rss_feeds WHERE guild_id = ?", interaction.guild.id)
        if not rows:
            await interaction.response.send_message("📰 No feeds.", ephemeral=True)
            return
        lines = [f"• `{u[:50]}` → <#{c}>" for u, c in rows]
        embed = discord.Embed(title="📰 RSS Feeds", description="\n".join(lines), color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rss_group.command(name="test", description="Preview latest entry from a feed.")
    @app_commands.describe(url="Feed URL to preview")
    async def rss_test(self, interaction: discord.Interaction, url: str):
        if not HAS_FEEDPARSER:
            await interaction.response.send_message("❌ feedparser missing.", ephemeral=True)
            return
        if not self._valid_url(url):
            await interaction.response.send_message("❌ Solo se permiten URLs HTTP/HTTPS públicas.", ephemeral=True)
            return
        await interaction.response.defer()
        import asyncio
        try:
            feed = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, feedparser.parse, url),
                timeout=12,
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ El feed tardó demasiado en responder.")
            return
        if not feed.entries:
            await interaction.followup.send("❌ No entries.")
            return
        embed = self._entry_embed(feed, feed.entries[0])
        await interaction.followup.send(embed=embed)

    @tasks.loop(minutes=5)
    async def check_feeds(self):
        import asyncio
        feeds = await self.bot.db.fetch_all("SELECT id, guild_id, channel_id, url, last_entry_id FROM rss_feeds")
        for fid, gid, cid, url, last_id in feeds:
            guild = self.bot.get_guild(gid)
            channel = guild.get_channel(cid) if guild else None
            if not channel:
                continue
            try:
                feed = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, feedparser.parse, url),
                    timeout=12,
                )
                if not feed.entries:
                    continue
                new = []
                for e in feed.entries:
                    eid = e.get('id', e.get('link', ''))
                    if eid == last_id:
                        break
                    new.append(e)
                for entry in reversed(new[:3]):
                    try:
                        await channel.send(embed=self._entry_embed(feed, entry))
                    except discord.Forbidden:
                        break
                    await asyncio.sleep(1)
                if new:
                    nid = new[0].get('id', new[0].get('link', ''))
                    await self.bot.db.execute("UPDATE rss_feeds SET last_entry_id = ? WHERE id = ?", nid, fid)
            except Exception as ex:
                self.logger.error(f"RSS error {url}: {ex}")
            await asyncio.sleep(2)

    @check_feeds.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    def _entry_embed(self, feed, entry):
        title = entry.get('title', 'New Entry')[:256]
        link = entry.get('link', '')
        summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:300]
        embed = discord.Embed(title=f"📰 {title}", description=summary or None, url=link,
                              color=discord.Color.orange(), timestamp=datetime.datetime.now())
        embed.set_author(name=feed.feed.get('title', 'RSS')[:256])
        if entry.get('published'):
            embed.set_footer(text=entry['published'][:50])
        return embed


async def setup(bot):
    await bot.add_cog(RSS(bot))
