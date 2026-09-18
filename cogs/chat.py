import discord
from discord.ext import commands
import datetime

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.snipe_cache = {}  # channel_id -> last deleted or edited event

    def _store(self, message, *, kind, before=None):
        if not message or getattr(message.author, "bot", False):
            return
        self.snipe_cache[message.channel.id] = {
            "kind": kind,
            "content": message.content,
            "before": before,
            "author": message.author,
            "time": datetime.datetime.now(),
            "attachments": [a.url for a in (message.attachments or [])],
            "message_id": message.id,
            "channel_id": message.channel.id,
        }

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        self._store(message, kind="deleted")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild:
            return
        if (before.content or "") == (after.content or ""):
            return
        self._store(after, kind="edited", before=before.content)

    @commands.hybrid_command(name="snipe", description="Recover the last deleted or edited message in this channel.")
    async def snipe(self, ctx):
        data = self.snipe_cache.get(ctx.channel.id)
        if not data:
            await ctx.send("❌ There's nothing to snipe!")
            return

        kind = data.get("kind") or "deleted"
        title = "Mensaje eliminado" if kind == "deleted" else "Mensaje editado"
        color = discord.Color.red() if kind == "deleted" else discord.Color.orange()
        embed = discord.Embed(title=title, color=color, timestamp=data["time"])
        author = data["author"]
        embed.set_author(name=f"{author} (`{author.id}`)", icon_url=author.display_avatar.url)
        if kind == "edited":
            embed.add_field(name="Antes", value=(data.get("before") or "*vacío*")[:1024], inline=False)
            embed.add_field(name="Después", value=(data.get("content") or "*vacío*")[:1024], inline=False)
        else:
            embed.description = data.get("content") or "*sin texto*"
        embed.add_field(name="Canal", value=f"{ctx.channel.mention} (`{ctx.channel.id}`)", inline=True)
        if data.get("message_id"):
            embed.add_field(name="Mensaje", value=f"`{data['message_id']}`", inline=True)
        if data.get("attachments"):
            embed.set_image(url=data["attachments"][0])
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Chat(bot))
