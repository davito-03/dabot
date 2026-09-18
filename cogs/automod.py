import discord
from discord.ext import commands
import datetime
from collections import defaultdict, deque
import re
import unicodedata

from utils import hijack as hijack_lib
from utils import antilinks as AL

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Spam detection: (guild_id, user_id) -> deque of contents
        self.message_history = defaultdict(lambda: deque(maxlen=5))
        self.flood_tracker = defaultdict(lambda: deque(maxlen=10))
        
    @commands.Cog.listener()
    async def on_message(self, message):
        await self._run(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not after.guild or after.author.bot:
            return
        if (before.content or "") == (after.content or "") and before.embeds == after.embeds:
            return
        await self._run(after)

    async def _run(self, message):
        if message.author.id == self.bot.user.id:
            return
        
        if not message.guild:
            return
        
        config = self.bot.config.get(message.guild.id)
        if not config:
            return
        
        automod_config = config.get('automod', {}) or {}
        links_cfg = automod_config.get("links") or config.get("antilinks") or {}

        automod_on = bool(automod_config.get('enabled', False))
        links_on = bool(links_cfg.get("enabled"))

        if not automod_on and not links_on:
            return

        if automod_on and await self.check_invite_links(message, automod_config):
            return

        if links_on and await self.check_links(message, links_cfg):
            return

        if not automod_on:
            return

        # Check if user is immune (admins, mods) — hijack radar still watches them
        if not message.author.bot and hasattr(message.author, 'guild_permissions'):
            if message.author.guild_permissions.manage_messages:
                return
        
        if await self.check_spam(message, automod_config):
            return
        if await self.check_flood(message, automod_config):
            return
        if await self.check_mention_spam(message, automod_config):
            return
        if await self.check_zalgo(message, automod_config):
            return
        if await self.check_banned_words(message, automod_config):
            return

    def _blob(self, message) -> str:
        parts = [message.content or ""]
        for e in message.embeds or []:
            for piece in (e.title, e.description, e.url, e.footer.text if e.footer else None):
                if piece:
                    parts.append(piece)
        for att in message.attachments:
            if att.filename:
                parts.append(att.filename)
        return "\n".join(parts)
    
    async def check_spam(self, message, config):
        """Detect repeated messages"""
        if message.author.bot:
            return False
        user_id = (message.guild.id, message.author.id)
        history = self.message_history[user_id]
        marker = (message.content or "").strip() or (
            message.attachments[0].filename if message.attachments else ""
        )
        if not marker:
            return False

        # Count identical messages in history
        identical_count = sum(1 for msg in history if msg == marker)
        
        if identical_count >= config.get('spam_threshold', 3):
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention} Stop spamming!",
                    delete_after=5
                )
                
                # Auto-warn if enabled
                if config.get('auto_warn', False):
                    # Create infraction
                    from cogs.moderation import Moderation
                    mod_cog = self.bot.get_cog('Moderation')
                    if mod_cog:
                        await mod_cog.create_infraction(
                            message.author.id,
                            message.guild.id,
                            self.bot.user.id,
                            "warn",
                            "Auto-mod: Spam detection"
                        )
                
                return True
            except:
                pass
        
        history.append(marker)
        return False
    
    async def check_flood(self, message, config):
        """Detect rapid message sending"""
        if message.author.bot:
            return False
        user_id = (message.guild.id, message.author.id)
        now = datetime.datetime.now()
        timestamps = self.flood_tracker[user_id]
        timestamps.append(now)
        
        # Check if 5+ messages in last 5 seconds
        if len(timestamps) >= 5:
            time_diff = (timestamps[-1] - timestamps[-5]).total_seconds()
            if time_diff < 5:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"⚠️ {message.author.mention} Slow down!",
                        delete_after=5
                    )
                    return True
                except:
                    pass
        
        return False
    
    async def check_mention_spam(self, message, config):
        """Detect excessive mentions"""
        if message.author.bot:
            return False
        mention_limit = config.get('mention_limit', 5)
        
        total_mentions = len(message.mentions) + len(message.role_mentions)
        
        if total_mentions > mention_limit:
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention} Too many mentions!",
                    delete_after=5
                )
                return True
            except:
                pass
        
        return False
    
    async def check_banned_words(self, message, config):
        """Filter banned words"""
        if message.author.bot:
            return False
        banned_words = config.get('banned_words', [])
        
        if not banned_words:
            return False
        
        content_lower = self._blob(message).lower()
        
        for word in banned_words:
            if word.lower() in content_lower:
                try:
                    await message.delete()
                    await message.author.send(
                        f"⚠️ Your message in **{message.guild.name}** was deleted for containing prohibited content."
                    )
                    return True
                except:
                    pass
        
        return False
    
    async def check_invite_links(self, message, config):
        """Block Discord invite links if enabled (or if automod is enabled)"""
        if not config.get('block_invites', True):  # Enabled by default if automod is active
            return False
            
        invite_pattern = r'(discord\s*[\[\(\.]+\s*(gg|io|me|li)|discordapp\.com/invite|discord\.com/invite|dsc\.gg|gg/[a-zA-Z0-9]+)'
        blob = self._blob(message)
        if re.search(invite_pattern, blob, re.IGNORECASE):
            try:
                await message.delete()
                try:
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, publicar invitaciones de otros servidores no está permitido.",
                        delete_after=5
                    )
                except:
                    pass
                
                # Auto-warn if enabled and not a bot
                if not message.author.bot and config.get('auto_warn', False):
                    from cogs.moderation import Moderation
                    mod_cog = self.bot.get_cog('Moderation')
                    if mod_cog:
                        await mod_cog.create_infraction(
                            message.author.id,
                            message.guild.id,
                            self.bot.user.id,
                            "warn",
                            "Auto-mod: Envío de invitaciones de Discord"
                        )
                return True
            except Exception:
                pass
        return False

    async def check_zalgo(self, message, config):
        """Mass combining marks — often used to bypass word filters."""
        if message.author.bot:
            return False
        text = message.content or ""
        if len(text) < 12:
            return False
        if hijack_lib.zalgo_ratio(text) < 0.35:
            return False
        try:
            await message.delete()
            await message.channel.send(
                f"⚠️ {message.author.mention} ese texto distorsionado no está permitido.",
                delete_after=5,
            )
            return True
        except Exception:
            return False

    async def check_links(self, message, cfg):
        """Whitelist / blacklist / tracking filter."""
        if message.author.id == getattr(self.bot, "super_owner_id", 0):
            return False
        ignore_staff = cfg.get("ignore_staff", True)
        if ignore_staff and not message.author.bot and getattr(message.author, "guild_permissions", None):
            if message.author.guild_permissions.manage_messages:
                return False

        blob = self._blob(message)
        premium = False
        try:
            premium = await self.bot.db.is_guild_premium(message.guild, self.bot)
        except Exception:
            premium = False
        hit = AL.inspect_text(blob, cfg, premium=premium)
        if not hit:
            return False

        action = hit.get("action") or "delete"
        minutes = max(1, int(cfg.get("timeout_minutes") or 10))
        labels = {
            "blacklist": "dominio bloqueado",
            "not_whitelisted": "no está en la lista permitida",
            "tracking": "parámetros de tracking",
        }
        why = labels.get(hit.get("reason"), hit.get("reason") or "enlace")
        domain = hit.get("domain") or ""
        notice = f"⚠️ {message.author.mention} enlace bloqueado (`{domain}` · {why})."

        try:
            await message.delete()
        except Exception:
            pass

        try:
            await message.channel.send(notice, delete_after=8)
        except Exception:
            pass

        member = message.author
        is_member = isinstance(member, discord.Member) and not member.bot
        mod = self.bot.get_cog("Moderation")
        reason = f"Anti-links: {why} ({domain})"

        if action in {"warn", "timeout", "ban"} and is_member and mod:
            try:
                case_id = await mod.create_infraction(
                    member.id, message.guild.id, self.bot.user.id, action if action != "timeout" else "timeout", reason
                )
                await mod.send_dm_notification(
                    member, "warn" if action == "warn" else action, reason, case_id,
                    message.guild.id, guild=message.guild, moderator_id=self.bot.user.id,
                    duration=f"{minutes}m" if action == "timeout" else "",
                )
            except Exception:
                pass
            try:
                if action == "timeout":
                    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
                elif action == "ban":
                    await message.guild.ban(member, reason=reason)
            except Exception:
                pass
            try:
                await mod.log_action(message.guild, message.guild.me or member, member, action, reason, None)
            except Exception:
                pass

        return True

    @commands.hybrid_group(name="antilinks", description="Filtro de enlaces por servidor.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await self.antilinks_status(ctx)

    @antilinks_group.command(name="status", description="Ver el filtro de enlaces.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_status(self, ctx):
        cfg = ((self.bot.config.get(ctx.guild.id) or {}).get("automod") or {}).get("links") or {}
        allow = ", ".join((cfg.get("whitelist") or [])[:15]) or "—"
        blocked = cfg.get("blocked") or []
        block_txt = ", ".join(
            (b if isinstance(b, str) else f"{b.get('domain')}={b.get('action')}")
            for b in blocked[:15]
        ) or "—"
        embed = discord.Embed(title="Anti-links", color=discord.Color.orange())
        embed.add_field(name="Activo", value="sí" if cfg.get("enabled") else "no", inline=True)
        embed.add_field(name="Bloquear todo", value="sí (solo whitelist)" if cfg.get("block_all") else "no", inline=True)
        embed.add_field(name="Acción por defecto", value=str(cfg.get("default_action") or "delete"), inline=True)
        embed.add_field(name="Permitidos", value=allow[:1000], inline=False)
        embed.add_field(name="Bloqueados", value=block_txt[:1000], inline=False)
        trk = cfg.get("tracking") or {}
        embed.add_field(
            name="Tracking (Premium)",
            value="sí" if trk.get("enabled") else "no",
            inline=True,
        )
        await ctx.send(embed=embed)

    @antilinks_group.command(name="enable", description="Activar o desactivar el filtro de enlaces.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_enable(self, ctx, activo: bool):
        self.bot.config.set_config(ctx.guild.id, "automod.links.enabled", activo)
        await ctx.send("Anti-links **activado**." if activo else "Anti-links **desactivado**.")

    @antilinks_group.command(name="mode", description="Si se bloquean todos los links salvo la whitelist.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_mode(self, ctx, whitelist_only: bool):
        self.bot.config.set_config(ctx.guild.id, "automod.links.block_all", whitelist_only)
        await ctx.send(
            "Modo **solo whitelist**: todo enlace que no esté permitido se bloquea."
            if whitelist_only else
            "Modo **normal**: solo se bloquean los dominios de la lista negra (y el tracking Premium)."
        )

    @antilinks_group.command(name="allow", description="Añadir un dominio permitido.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_allow(self, ctx, dominio: str):
        host = AL.normalize_host(dominio.replace("https://", "").replace("http://", "").split("/")[0])
        if not host:
            await ctx.send("Dominio inválido.")
            return
        cfg = ((self.bot.config.get(ctx.guild.id) or {}).get("automod") or {}).get("links") or {}
        allow = AL._norm_list(cfg.get("whitelist") or [])
        if host not in allow:
            allow.append(host)
        self.bot.config.set_config(ctx.guild.id, "automod.links.whitelist", allow)
        await ctx.send(f"✅ Permitido: `{host}`")

    @antilinks_group.command(name="block", description="Bloquear un dominio con una acción.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_block(self, ctx, dominio: str, accion: str = "delete"):
        host = AL.normalize_host(dominio.replace("https://", "").replace("http://", "").split("/")[0])
        accion = (accion or "delete").lower().strip()
        if accion not in AL.ACTION_RANK:
            await ctx.send("Acción: `delete`, `warn`, `timeout` o `ban`.")
            return
        if not host:
            await ctx.send("Dominio inválido.")
            return
        cfg = ((self.bot.config.get(ctx.guild.id) or {}).get("automod") or {}).get("links") or {}
        blocked = list(cfg.get("blocked") or [])
        blocked = [b for b in blocked if (b if isinstance(b, str) else b.get("domain")) != host]
        blocked.append({"domain": host, "action": accion})
        self.bot.config.set_config(ctx.guild.id, "automod.links.blocked", blocked)
        await ctx.send(f"⛔ `{host}` → **{accion}**")

    @antilinks_group.command(name="remove", description="Quitar un dominio de permitidos o bloqueados.")
    @commands.has_permissions(manage_guild=True)
    async def antilinks_remove(self, ctx, dominio: str):
        host = AL.normalize_host(dominio.replace("https://", "").replace("http://", "").split("/")[0])
        cfg = ((self.bot.config.get(ctx.guild.id) or {}).get("automod") or {}).get("links") or {}
        allow = [d for d in AL._norm_list(cfg.get("whitelist") or []) if d != host]
        blocked = []
        for b in cfg.get("blocked") or []:
            name = b if isinstance(b, str) else (b.get("domain") or "")
            if AL.normalize_host(name) != host:
                blocked.append(b)
        self.bot.config.set_config(ctx.guild.id, "automod.links.whitelist", allow)
        self.bot.config.set_config(ctx.guild.id, "automod.links.blocked", blocked)
        await ctx.send(f"Quitado `{host}`.")

    @commands.command(name="automod")
    @commands.has_permissions(administrator=True)
    async def automod_config(self, ctx, enabled: bool):
        """
        Enable or disable automod for this server.
        """
        self.bot.config.set_config(ctx.guild.id, "automod.enabled", enabled)
        status = "✅ enabled" if enabled else "❌ disabled"
        await ctx.send(f"AutoMod has been {status}.")

async def setup(bot):
    await bot.add_cog(AutoMod(bot))
