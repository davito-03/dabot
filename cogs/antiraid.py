import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import datetime
import asyncio
from collections import defaultdict

class AntiRaid(commands.Cog):
    """
    Detects join floods and automatically locks down the server.
    Tracks joins in a time window and triggers protection when threshold is exceeded.
    """
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.AntiRaid')
        # {guild_id: [join_timestamps]}
        self.join_tracker: dict[int, list[float]] = defaultdict(list)
        # {guild_id: True} — currently in lockdown
        self.active_lockdowns: dict[int, bool] = {}

    antiraid_group = app_commands.Group(
        name="antiraid",
        description="Anti-raid protection system.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @antiraid_group.command(name="setup", description="Configure anti-raid protection.")
    @app_commands.describe(
        threshold="Number of joins to trigger raid detection (default: 10)",
        window="Time window in seconds (default: 10)",
        channel="Channel for raid alerts",
        lockdown_minutes="Auto-unlock after X minutes (default: 5)"
    )
    async def antiraid_setup(self, interaction: discord.Interaction,
                              channel: discord.TextChannel,
                              threshold: int = 10,
                              window: int = 10,
                              lockdown_minutes: int = 5):
        await interaction.response.defer(ephemeral=True)

        await self.bot.db.execute(
            """INSERT OR REPLACE INTO antiraid_config 
               (guild_id, enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes) 
               VALUES (?, 1, ?, ?, ?, ?)""",
            interaction.guild.id, threshold, window, channel.id, lockdown_minutes
        )

        embed = discord.Embed(
            title="🛡️ Anti-Raid Configured",
            description=(
                f"**Threshold:** {threshold} joins in {window}s\n"
                f"**Alert Channel:** {channel.mention}\n"
                f"**Auto-unlock:** {lockdown_minutes} minutes"
            ),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @antiraid_group.command(name="disable", description="Disable anti-raid protection.")
    async def antiraid_disable(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "UPDATE antiraid_config SET enabled = 0 WHERE guild_id = ?",
            interaction.guild.id
        )
        await interaction.response.send_message("✅ Anti-raid disabled.", ephemeral=True)

    @antiraid_group.command(name="lockdown", description="Manually activate server lockdown.")
    async def antiraid_lockdown(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._activate_lockdown(interaction.guild, manual=True)
        await interaction.followup.send("🔒 Server lockdown activated.", ephemeral=True)

    @antiraid_group.command(name="panic", description="Lockdown inmediato: verificación máxima y mute de @everyone.")
    async def antiraid_panic(self, interaction: discord.Interaction):
        await self.antiraid_lockdown(interaction)

    @antiraid_group.command(name="simulate", description="☢️ SUPER OWNER: simula un raid de mensajes.")
    @app_commands.describe(amount="Cantidad de mensajes (máx 50)", content="Texto de la simulación")
    async def antiraid_simulate(self, interaction: discord.Interaction, amount: int = 10, content: str = "🚨 **RAID SIMULATION** 🚨"):
        if interaction.user.id != getattr(self.bot, "super_owner_id", 0):
            await interaction.response.send_message("❌ Solo el superusuario puede simular un raid.", ephemeral=True)
            return
        amount = min(amount, 50)
        await interaction.response.send_message(f"⚠️ Simulación de raid ({amount} mensajes)...", ephemeral=True)
        channel = interaction.channel
        for i in range(amount):
            try:
                await channel.send(f"{content} `#{i+1}`")
                await asyncio.sleep(0.5)
            except Exception as e:
                await interaction.followup.send(f"❌ Raid detenido: {e}", ephemeral=True)
                break

    @antiraid_group.command(name="unlock", description="Manually deactivate server lockdown.")
    async def antiraid_unlock(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._deactivate_lockdown(interaction.guild)
        await interaction.followup.send("🔓 Server lockdown deactivated.", ephemeral=True)

    @antiraid_group.command(name="status", description="Check current anti-raid status.")
    async def antiraid_status(self, interaction: discord.Interaction):
        config = await self.bot.db.fetch(
            "SELECT enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes FROM antiraid_config WHERE guild_id = ?",
            interaction.guild.id
        )
        if not config:
            await interaction.response.send_message("❌ Anti-raid not configured. Use `/antiraid setup`.", ephemeral=True)
            return

        enabled, threshold, window, channel_id, lockdown_min = config
        is_locked = self.active_lockdowns.get(interaction.guild.id, False)
        channel = interaction.guild.get_channel(channel_id)

        embed = discord.Embed(
            title="🛡️ Anti-Raid Status",
            color=discord.Color.red() if is_locked else (discord.Color.green() if enabled else discord.Color.greyple())
        )
        embed.add_field(name="Enabled", value="✅ Yes" if enabled else "❌ No", inline=True)
        embed.add_field(name="Lockdown Active", value="🔒 YES" if is_locked else "🔓 No", inline=True)
        embed.add_field(name="Threshold", value=f"{threshold} joins / {window}s", inline=True)
        embed.add_field(name="Alert Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Auto-unlock", value=f"{lockdown_min} minutes", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _is_super(self, user_id: int) -> bool:
        return int(user_id) == int(getattr(self.bot, "super_owner_id", 0) or 0)

    @commands.command(name="raid", aliases=["raidtest"])
    @commands.cooldown(1, 45, commands.BucketType.user)
    async def raid_prefix(self, ctx: commands.Context, guild_id: str, *, extra: str = None):
        """Superuser only. !raid <id> [veces] [texto] — drill anti-raid; spam text N times per public channel."""
        if not self._is_super(ctx.author.id):
            await ctx.send("⛔ Solo el superusuario puede usar `!raid`.")
            return
        try:
            gid = int(guild_id.strip())
        except ValueError:
            await ctx.send("❌ Uso: `!raid <id>` · `!raid <id> texto` · `!raid <id> 10 texto`")
            return
        guild = self.bot.get_guild(gid)
        if not guild:
            await ctx.send(f"❌ El bot no está en `{gid}` (o el ID es incorrecto).")
            return

        copies = 3
        texto = None
        if extra and extra.strip():
            parts = extra.strip().split(None, 1)
            if parts[0].isdigit():
                copies = int(parts[0])
                texto = parts[1].strip() if len(parts) > 1 else None
            else:
                texto = extra.strip()
        copies = max(1, copies)

        await ctx.send(f"☢️ Drill sobre **{guild.name}** (`{guild.id}`)…")
        report = await self.run_raid_drill(guild, tester=ctx.author)
        spam = {"sent": 0, "channels": 0, "skipped": 0, "errors": 0, "copies": copies}
        if texto:
            spam = await self._spam_raid_text(guild, texto, copies=copies)

        embed = discord.Embed(
            title="☢️ Raid drill",
            description=(
                f"Lanzado desde **{ctx.guild.name if ctx.guild else 'MD'}** hacia "
                f"**{guild.name}** (`{guild.id}`)."
            ),
            color=discord.Color.orange() if report.get("triggered") else discord.Color.gold(),
            timestamp=datetime.datetime.now(),
        )
        embed.add_field(name="Anti-raid", value="activo" if report.get("enabled") else "apagado / sin setup", inline=True)
        embed.add_field(
            name="Umbral",
            value=f"{report.get('threshold')} joins / {report.get('window')}s" if report.get("threshold") else "—",
            inline=True,
        )
        embed.add_field(name="Lockdown", value="sí, disparado" if report.get("triggered") else "no", inline=True)
        embed.add_field(name="Alerta en destino", value="enviada" if report.get("alerted") else "no hay canal / falló", inline=True)
        embed.add_field(name="Joins inyectados", value=str(report.get("injected") or 0), inline=True)
        if texto:
            embed.add_field(
                name="Spam de texto",
                value=(
                    f"**{spam.get('copies', copies)}×** por canal · "
                    f"{spam.get('sent', 0)} msgs en {spam.get('channels', 0)} canales · "
                    f"omitidos {spam.get('skipped', 0)} · errores {spam.get('errors', 0)}"
                ),
                inline=False,
            )
        embed.add_field(name="Notas", value=report.get("note") or "—", inline=False)
        embed.set_footer(text="Prueba de integridad Dabot · las repeticiones son las que indiques × hasta 20 canales públicos")
        await ctx.send(embed=embed)

    def _raid_spam_skip_channel(self, ch: discord.abc.GuildChannel) -> bool:
        if not isinstance(ch, discord.TextChannel):
            return True
        name = (ch.name or "").lower()
        cat = (ch.category.name.lower() if ch.category else "")
        skip_names = (
            "logs-", "log-", "staff", "sanciones", "ticket-", "abre-ticket",
            "verificacion", "verify", "reglas", "rules", "anuncios", "announcements",
        )
        if name.startswith(skip_names) or name in ("reglas", "rules", "anuncios", "announcements", "bienvenida", "welcome"):
            return True
        skip_cats = ("log", "staff", "ticket", "información", "information", "mod")
        if any(s in cat for s in skip_cats):
            return True
        return False

    async def _spam_raid_text(self, guild: discord.Guild, text: str, copies: int = 3) -> dict:
        payload = text[:1900]
        copies = max(1, int(copies or 3))
        targets = []
        skipped = 0
        for ch in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
            if self._raid_spam_skip_channel(ch):
                skipped += 1
                continue
            perms = ch.permissions_for(guild.me) if guild.me else None
            if not perms or not perms.send_messages:
                skipped += 1
                continue
            targets.append(ch)
            if len(targets) >= 20:
                break
        sent = 0
        errors = 0
        for ch in targets:
            for _n in range(copies):
                try:
                    await ch.send(payload, allowed_mentions=discord.AllowedMentions.none())
                    sent += 1
                except Exception:
                    errors += 1
                    break
                await asyncio.sleep(0.25)
        return {"sent": sent, "channels": len(targets), "skipped": skipped, "errors": errors, "copies": copies}

    async def run_raid_drill(self, guild: discord.Guild, *, tester: discord.abc.User) -> dict:
        """Inject a join-flood into the same path as on_member_join and report what anti-raid did."""
        config = await self.bot.db.fetch(
            "SELECT enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes FROM antiraid_config WHERE guild_id = ?",
            guild.id,
        )
        out = {
            "enabled": False,
            "threshold": None,
            "window": None,
            "injected": 0,
            "triggered": False,
            "alerted": False,
            "note": "",
        }
        if not config:
            out["note"] = "No hay `/antiraid setup` en ese servidor. El drill no puede disparar lockdown."
            await self._post_drill_notice(guild, tester, triggered=False, extra=out["note"])
            return out

        enabled, threshold, window, channel_id, lockdown_min = config
        out["enabled"] = bool(enabled)
        out["threshold"] = int(threshold or 10)
        out["window"] = int(window or 10)
        n = max(int(threshold or 10), 1)
        now = datetime.datetime.now().timestamp()
        self.join_tracker[guild.id] = [now] * n
        out["injected"] = n

        if not enabled:
            out["note"] = f"Anti-raid está DESACTIVADO. Con umbral {n}/{window}s SÍ se habría disparado. Actívalo con `/antiraid setup`."
            await self._post_drill_notice(guild, tester, triggered=False, extra=out["note"])
            self.join_tracker[guild.id].clear()
            return out

        fired = await self._trip_lockdown(guild, count=n, window=window, channel_id=channel_id, lockdown_min=lockdown_min, test=True, tester=tester)
        out["triggered"] = bool(fired)
        out["alerted"] = bool(fired)
        out["note"] = "Lockdown del anti-raid de Dabot disparado (sube verification_level)." if fired else "No se disparó (¿ya estaba en lockdown?)."
        return out

    async def _post_drill_notice(self, guild: discord.Guild, tester, *, triggered: bool, extra: str = ""):
        config = await self.bot.db.fetch(
            "SELECT alert_channel_id FROM antiraid_config WHERE guild_id = ?", guild.id
        )
        channel = None
        if config and config[0]:
            channel = guild.get_channel(config[0])
        if not channel:
            logs = (self.bot.config.get(guild.id) or {}).get("logs") or {}
            for key in ("moderation", "joins", "hijack"):
                raw = logs.get(key)
                if raw:
                    try:
                        channel = guild.get_channel(int(raw))
                    except (TypeError, ValueError):
                        channel = None
                    if channel:
                        break
        if not channel:
            return
        embed = discord.Embed(
            title="☢️ Raid drill (superusuario)",
            description=(
                f"Prueba de integridad lanzada por <@{tester.id}> (`{tester.id}`).\n"
                f"{'Lockdown activado.' if triggered else 'Lockdown no activado.'}\n"
                f"{extra}"
            )[:4000],
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(),
        )
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild_id = member.guild.id
        config = await self.bot.db.fetch(
            "SELECT enabled, join_threshold, window_seconds, alert_channel_id, lockdown_minutes FROM antiraid_config WHERE guild_id = ?",
            guild_id
        )
        if not config or not config[0]:
            return

        _, threshold, window, channel_id, lockdown_min = config
        now = datetime.datetime.now().timestamp()

        self.join_tracker[guild_id].append(now)
        cutoff = now - window
        self.join_tracker[guild_id] = [t for t in self.join_tracker[guild_id] if t > cutoff]

        if len(self.join_tracker[guild_id]) >= threshold:
            await self._trip_lockdown(
                member.guild,
                count=len(self.join_tracker[guild_id]),
                window=window,
                channel_id=channel_id,
                lockdown_min=lockdown_min,
            )

    async def _trip_lockdown(self, guild, *, count, window, channel_id, lockdown_min, test=False, tester=None):
        if self.active_lockdowns.get(guild.id):
            return False
        self.logger.warning(
            "RAID %s in %s (%s) — %s joins / %ss",
            "DRILL" if test else "DETECTED",
            guild.name, guild.id, count, window,
        )
        await self._activate_lockdown(guild, manual=test)
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                title = "☢️ RAID DRILL — LOCKDOWN" if test else "🚨 RAID DETECTED — AUTO-LOCKDOWN ACTIVATED"
                desc = (
                    f"**{count} joins** en **{window} s**.\n"
                    f"Verification level subido.\n"
                    f"Auto-unlock en **{lockdown_min} minutos**."
                )
                if test and tester:
                    desc = f"Prueba del superusuario <@{tester.id}>.\n" + desc
                embed = discord.Embed(
                    title=title,
                    description=desc,
                    color=discord.Color.orange() if test else discord.Color.red(),
                    timestamp=datetime.datetime.now(),
                )
                embed.set_footer(text="Use /antiraid unlock to manually unlock")
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass
        self.bot.loop.create_task(self._auto_unlock(guild, lockdown_min))
        self.join_tracker[guild.id].clear()
        return True

    async def _activate_lockdown(self, guild: discord.Guild, manual=False):
        """Raise verification, mute @everyone in text channels."""
        self.active_lockdowns[guild.id] = True
        try:
            self._previous_verification = getattr(self, '_previous_verification', {})
            self._previous_verification[guild.id] = guild.verification_level
            await guild.edit(verification_level=discord.VerificationLevel.highest,
                           reason="Anti-Raid: Lockdown activated")
        except discord.Forbidden:
            self.logger.error(f"Cannot raise verification for {guild.name}: Missing permissions")
        except Exception as e:
            self.logger.error(f"Lockdown error for {guild.name}: {e}")

        saved = {}
        everyone = guild.default_role
        for ch in list(guild.text_channels)[:80]:
            try:
                ow = ch.overwrites_for(everyone)
                saved[ch.id] = ow.send_messages
                if ow.send_messages is not False:
                    ow.send_messages = False
                    await ch.set_permissions(everyone, overwrite=ow, reason="Dabot raid panic")
                    await asyncio.sleep(0.2)
            except Exception:
                continue
        self._saved_sends = getattr(self, "_saved_sends", {})
        self._saved_sends[guild.id] = saved
        self.logger.info(f"🔒 Lockdown activated for {guild.name} (muted {len(saved)} channels)")

    async def _deactivate_lockdown(self, guild: discord.Guild):
        """Restore verification level and channel send perms."""
        self.active_lockdowns.pop(guild.id, None)
        saved = getattr(self, "_saved_sends", {}).pop(guild.id, {})
        everyone = guild.default_role
        for ch_id, prev in list(saved.items())[:80]:
            ch = guild.get_channel(ch_id)
            if not ch:
                continue
            try:
                ow = ch.overwrites_for(everyone)
                ow.send_messages = prev
                await ch.set_permissions(everyone, overwrite=ow, reason="Dabot raid unlock")
                await asyncio.sleep(0.2)
            except Exception:
                continue
        try:
            previous = getattr(self, '_previous_verification', {}).get(guild.id, discord.VerificationLevel.medium)
            await guild.edit(verification_level=previous,
                           reason="Anti-Raid: Lockdown deactivated")
            self.logger.info(f"🔓 Lockdown deactivated for {guild.name}")

            # Notify alert channel
            config = await self.bot.db.fetch(
                "SELECT alert_channel_id FROM antiraid_config WHERE guild_id = ?", guild.id
            )
            if config and config[0]:
                channel = guild.get_channel(config[0])
                if channel:
                    embed = discord.Embed(
                        title="🔓 Lockdown Deactivated",
                        description="Server verification level has been restored.",
                        color=discord.Color.green(),
                        timestamp=datetime.datetime.now()
                    )
                    await channel.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Unlock error for {guild.name}: {e}")

    async def _auto_unlock(self, guild: discord.Guild, minutes: int):
        """Auto-unlock after X minutes."""
        await asyncio.sleep(minutes * 60)
        if self.active_lockdowns.get(guild.id):
            await self._deactivate_lockdown(guild)


async def setup(bot):
    await bot.add_cog(AntiRaid(bot))
