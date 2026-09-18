import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import shutil
import datetime
import json
import re
import aiohttp
import socket
import asyncio
import ssl
import time
from urllib.parse import urlparse

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info('Utility Cog loaded.')

    # ══════════════════════════════════════════════════════════════════════
    #  /help — Paginated help with updated categories
    # ══════════════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="help", description="Show the help menu.")
    async def help(self, ctx):
        await ctx.defer()
        try:
            guild_id = ctx.guild.id if ctx.guild else None
            from utils.helpers import guild_lang
            lang = guild_lang(self.bot, guild_id)

            view = HelpSelectView(self.bot, ctx.author)

            ping = round(self.bot.latency * 1000)
            cogs_count = len([c for c in self.bot.cogs if c not in HIDDEN_COGS])

            embed = discord.Embed(
                title=self.bot.i18n.get("help.title", lang) or "Ayuda Dabot",
                description=self.bot.i18n.get("help.description", lang) or "Elige una categoría en el menú.",
                color=discord.Color.from_rgb(43, 45, 49)
            )

            if lang == 'es':
                embed.add_field(
                    name="Cómo usarlo",
                    value=(
                        "Elige una categoría abajo. Los **nombres slash van en inglés** (Discord no acepta tildes en el nombre).\n"
                        "`/start` configura el servidor · `/dashboard` abre el panel."
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Web — dabot.davito.es",
                    value=(
                        "• Panel: módulos, Discord, sanciones, backups, plantillas\n"
                        "• Verificación: `/verify` + rastreo de multicuentas\n"
                        "• **Tickets**: el historial se guarda en la web, no hace falta canal de transcripciones\n"
                        "• Admin global (creador): todos los servidores y casos de alts\n"
                        "• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Seguridad",
                    value=(
                        "• `/radar status` — cuentas hackeadas (MrBeast / Nitro). Clic derecho → **Hijack check**\n"
                        "• Clic derecho en un usuario → **Warn / Timeout / Ban**\n"
                        "• `/sugerir` — ideas para Dabot (owners/admins). Te responden por MD\n"
                        "• `/panic` — lockdown inmediato · `/mod timeleft` · `/mod appeal`\n"
                        "• `/recovered` — si te silenciaron por secuestro y ya cambiaste la contraseña\n"
                        "• `/verification setup` — verificación por navegador\n"
                        "• `/antiraid setup` · AutoMod en el panel"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Premium",
                    value=(
                        "Gratis: tickets, niveles, economía, automod, radar, logs, panel.\n"
                        "**De pago** (mensual / anual / vitalicio): IA al mencionar a Dabot, `/tldr`, backups completos, comandos custom, cartas a medida.\n"
                        "`/premium status` · el creador activa con `/premium grant`"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Estado",
                    value=f"Latencia `{ping}ms` · {cogs_count} módulos · {len(self.bot.guilds)} servidores",
                    inline=False
                )
            else:
                embed.add_field(
                    name="How to use it",
                    value=(
                        "Pick a category below. **Slash names stay in English** (Discord rejects accented names).\n"
                        "`/start` sets the server up · `/dashboard` opens the panel."
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Web — dabot.davito.es",
                    value=(
                        "• Dashboard: modules, Discord, sanctions, backups, templates\n"
                        "• Verification: `/verify` + multi-account tracking\n"
                        "• **Tickets**: transcripts live on the website\n"
                        "• Global admin (creator): every server and alt cases\n"
                        "• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Safety",
                    value=(
                        "• `/radar status` — hijacked accounts (MrBeast / Nitro). Right-click → **Hijack check**\n"
                        "• `/recovered` — after a hijack timeout, once you changed your password\n"
                        "• `/verification setup` — browser verification\n"
                        "• `/antiraid setup` · AutoMod in the dashboard"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Premium",
                    value=(
                        "Free: tickets, levels, economy, automod, radar, logs, dashboard.\n"
                        "**Paid** (monthly / yearly / lifetime): AI when you mention Dabot, `/tldr`, full backups, custom commands, custom cards.\n"
                        "`/premium status` · the creator enables it with `/premium grant`"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="Status",
                    value=f"Latency `{ping}ms` · {cogs_count} modules · {len(self.bot.guilds)} servers",
                    inline=False
                )

            embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
            footer = self.bot.i18n.get("help.footer", lang)
            if isinstance(footer, str):
                embed.set_footer(text=footer)
            try:
                await ctx.send(embed=embed, view=view)
            except discord.HTTPException as e:
                self.logger.error("Help view rejected by Discord: %s", e)
                await ctx.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Help command error: {e}", exc_info=True)
            try:
                await ctx.send("❌ No pude montar el menú de ayuda. Prueba `/start` o dabot.davito.es/help")
            except Exception:
                pass

    util = app_commands.Group(name="util", description="Utilidades de Dabot")

    # ══════════════════════════════════════════════════════════════════════
    #  Standalone user commands (these stay as top-level)
    # ══════════════════════════════════════════════════════════════════════
    @commands.hybrid_command(name="ping", description="Check the bot's latency.")
    async def ping(self, ctx):
        from utils.helpers import guild_lang
        lang = guild_lang(self.bot, ctx.guild.id if ctx.guild else None)
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title=self.bot.i18n.get("ping.title", lang),
            description=self.bot.i18n.get("ping.description", lang, latency=latency),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    def _can_say(self, member) -> bool:
        if member is None:
            return False
        if member.id == getattr(self.bot, "super_owner_id", 0):
            return True
        perms = getattr(member, "guild_permissions", None)
        return bool(perms and (perms.administrator or perms.manage_guild))

    @app_commands.command(name="say", description="Envía un mensaje como Dabot. El canal no ve quién lo mandó.")
    @app_commands.describe(mensaje="Texto que enviará el bot", canal="Canal de destino (este, si no eliges otro)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def say(self, interaction: discord.Interaction, mensaje: str, canal: discord.TextChannel = None):
        if not self._can_say(interaction.user):
            await interaction.response.send_message("⛔ Solo administradores.", ephemeral=True)
            return
        dest = canal or interaction.channel
        if dest is None or not hasattr(dest, "send"):
            await interaction.response.send_message("❌ No puedo enviar ahí.", ephemeral=True)
            return
        me = interaction.guild.me if interaction.guild else None
        if me and not dest.permissions_for(me).send_messages:
            await interaction.response.send_message("❌ No tengo permiso para hablar en ese canal.", ephemeral=True)
            return
        text = (mensaje or "").strip()[:2000]
        if not text:
            await interaction.response.send_message("❌ El mensaje está vacío.", ephemeral=True)
            return
        try:
            await dest.send(text)
        except Exception as e:
            await interaction.response.send_message(f"❌ No pude enviar el mensaje: {e}", ephemeral=True)
            return
        await interaction.response.send_message("✅ Enviado.", ephemeral=True)

    @commands.command(name="say", aliases=["decir"])
    @commands.guild_only()
    async def say_prefix(self, ctx, *, mensaje: str):
        if not self._can_say(ctx.author):
            await ctx.send("⛔ Solo administradores.", delete_after=8)
            return
        text = (mensaje or "").strip()[:2000]
        if not text:
            return
        try:
            await ctx.message.delete()
        except Exception:
            pass
        await ctx.send(text)

    @commands.hybrid_command(name="checkweb", description="Extract comprehensive public info from a website.", with_app_command=False)
    async def checkweb(self, ctx, url: str):
        await ctx.defer()
        if not url.startswith("http"):
            url = "https://" + url

        try:
            parsed_url = urlparse(url)
            hostname = parsed_url.netloc or parsed_url.path
            domain = hostname.replace("www.", "")

            # SSRF Protection: Block private/internal IPs
            import ipaddress
            loop = asyncio.get_event_loop()
            try:
                ip_str = await asyncio.wait_for(
                    loop.run_in_executor(None, socket.gethostbyname, hostname),
                    timeout=4,
                )
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                    await ctx.send("❌ Cannot scan private, internal, or reserved IP addresses.")
                    return
            except (socket.gaierror, ValueError):
                pass

            # Resolve IP
            try:
                ip_addr = await asyncio.wait_for(
                    loop.run_in_executor(None, socket.gethostbyname, hostname),
                    timeout=4,
                )
            except Exception:
                ip_addr = "Unknown"

            # Get IP Info
            isp = "Unknown"
            country = "Unknown"
            if ip_addr != "Unknown":
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                        async with session.get(f"http://ip-api.com/json/{ip_addr}") as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                isp = data.get("isp", "Unknown")
                                country = data.get("country", "Unknown")
                except Exception:
                    pass

            # Fetch DNS Records
            dns_records = []
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                    async with session.get(f"https://cloudflare-dns.com/dns-query?name={domain}&type=A", headers={"accept": "application/dns-json"}, timeout=3) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            ips = [ans["data"] for ans in data.get("Answer", []) if ans["type"] == 1]
                            if ips: dns_records.append(f"A: {', '.join(ips[:2])}")
                    async with session.get(f"https://cloudflare-dns.com/dns-query?name={domain}&type=MX", headers={"accept": "application/dns-json"}, timeout=3) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            mxs = [ans["data"] for ans in data.get("Answer", []) if ans["type"] == 15]
                            if mxs: dns_records.append(f"MX: {mxs[0]}")
                    async with session.get(f"https://cloudflare-dns.com/dns-query?name={domain}&type=NS", headers={"accept": "application/dns-json"}, timeout=3) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            nss = [ans["data"] for ans in data.get("Answer", []) if ans["type"] == 2]
                            if nss: dns_records.append(f"NS: {nss[0]}")
            except Exception:
                pass

            dns_info = "\n".join(dns_records) if dns_records else "None resolved"

            # Fetch SSL Info
            ssl_info = "Not HTTPS"
            if url.startswith("https"):
                ssl_info = "Unknown / Invalid"
                try:
                    def get_ssl_cert(host):
                        context = ssl.create_default_context()
                        with socket.create_connection((host, 443), timeout=3) as sock:
                            with context.wrap_socket(sock, server_hostname=host) as ssock:
                                return ssock.getpeercert()

                    cert = await loop.run_in_executor(None, get_ssl_cert, hostname)
                    if cert:
                        issuer = dict(x[0] for x in cert.get('issuer', [])).get('organizationName', 'Unknown')
                        not_after = cert.get('notAfter', '')
                        if not_after:
                            expiry_date = datetime.datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                            days_left = (expiry_date - datetime.datetime.utcnow()).days
                            ssl_info = f"Issuer: {issuer[:20]}\nExpires in: {days_left} days"
                except Exception:
                    pass

            # Perform HTTP request
            start_time = time.time()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(url) as resp:
                    resp_time = round((time.time() - start_time) * 1000)
                    status = resp.status

                    headers = resp.headers
                    server = headers.get("Server", "Unknown")
                    powered_by = headers.get("X-Powered-By", "Unknown")

                    security_headers = []
                    for h in ["Strict-Transport-Security", "X-Frame-Options", "Content-Security-Policy", "X-XSS-Protection"]:
                        if h in headers: security_headers.append(h.replace("-", ""))
                    sec_info = ", ".join(security_headers) if security_headers else "None found"

                    raw = await resp.content.read(200_000)
                    html = raw.decode(errors="ignore")
                    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
                    title = title_match.group(1).strip() if title_match else "No title"
                    if len(title) > 40: title = title[:37] + "..."

                    gen_match = re.search(r'<meta\s+name=["\']generator["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
                    generator = gen_match.group(1).strip() if gen_match else "Unknown"

            embed = discord.Embed(
                title=f"🌐 Web Check: {hostname}",
                description=f"**{title}**\nHTTP Status: {status} {'✅' if status == 200 else '⚠️'}",
                color=discord.Color.green() if status == 200 else discord.Color.orange()
            )
            embed.add_field(name="🔗 URL", value=url, inline=False)
            embed.add_field(name="🌍 IP Address", value=f"{ip_addr} ({country})", inline=True)
            embed.add_field(name="🏢 ISP", value=isp[:25] if isp else "Unknown", inline=True)
            embed.add_field(name="⏱️ Ping", value=f"{resp_time}ms", inline=True)
            tech_str = f"**Server:** {server[:30]}\n"
            if powered_by != "Unknown": tech_str += f"**Powered By:** {powered_by[:30]}\n"
            if generator != "Unknown": tech_str += f"**Generator:** {generator[:30]}"
            embed.add_field(name="🖥️ Technology", value=tech_str, inline=False)
            embed.add_field(name="🔒 SSL/TLS", value=ssl_info, inline=True)
            embed.add_field(name="🛡️ Sec Headers", value=sec_info, inline=True)
            embed.add_field(name="🔍 DNS Records", value=dns_info, inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Failed to reach website or invalid URL: {str(e)[:100]}")

    @util.command(name="web", description="Info pública de una web")
    async def util_web(self, interaction: discord.Interaction, url: str):
        await self.checkweb(await commands.Context.from_interaction(interaction), url)

    @commands.hybrid_command(name="remind", description="Set a reminder.", with_app_command=False)
    async def remind(self, ctx, time: str, *, message: str):
        """Set a reminder. Time format: 10s, 5m, 2h, 1d"""
        time_units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
        match = re.match(r'(\d+)([smhd])', time.lower())
        if not match:
            await ctx.send("Invalid time format. Use: 10s, 5m, 2h, 1d")
            return
        amount, unit = match.groups()
        seconds = int(amount) * time_units[unit]
        expires_at = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        created_at = datetime.datetime.now()
        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, guild_id, channel_id, message, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ctx.author.id, ctx.guild.id if ctx.guild else None, ctx.channel.id, message,
            expires_at.isoformat(), created_at.isoformat()
        )
        await ctx.send(f"⏰ Reminder set for **{time}** from now!")

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        """Check for expired reminders every minute"""
        now = datetime.datetime.now().isoformat()
        reminders = await self.bot.db.fetch_all(
            "SELECT id, user_id, guild_id, channel_id, message FROM reminders WHERE expires_at <= ?",
            now
        )
        for reminder in reminders:
            reminder_id, user_id, guild_id, channel_id, message = reminder
            try:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    user = self.bot.get_user(user_id)
                    mention = user.mention if user else f"<@{user_id}>"
                    embed = discord.Embed(title="⏰ Reminder", description=message, color=discord.Color.blue())
                    await channel.send(f"{mention}", embed=embed)
            except Exception:
                pass
            await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", reminder_id)

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="color", description="Show info about a hex color.", with_app_command=False)
    async def color(self, ctx, hex_color: str):
        """Display color swatch with hex, RGB, and HSL values."""
        import colorsys
        hex_color = hex_color.lstrip("#")
        if len(hex_color) not in (3, 6) or not all(c in "0123456789abcdefABCDEF" for c in hex_color):
            await ctx.send("❌ Invalid hex color. Example: `/color #FF5733`")
            return
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        color_int = int(hex_color, 16)
        embed = discord.Embed(title=f"🎨 Color #{hex_color.upper()}", color=color_int)
        embed.add_field(name="HEX", value=f"`#{hex_color.upper()}`", inline=True)
        embed.add_field(name="RGB", value=f"`rgb({r}, {g}, {b})`", inline=True)
        embed.add_field(name="HSL", value=f"`hsl({round(h*360)}°, {round(s*100)}%, {round(l*100)}%)`", inline=True)
        embed.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_color}/100x100")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="qr", description="Generate a QR code from text or URL.", with_app_command=False)
    async def qr(self, ctx, *, text: str):
        """Generate a QR code image."""
        await ctx.defer()
        try:
            import qrcode
            import io
            qr = qrcode.QRCode(border=2)
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            file = discord.File(buffer, filename="qr.png")
            embed = discord.Embed(title="📱 QR Code", description=f"`{text[:100]}`", color=discord.Color.dark_grey())
            embed.set_image(url="attachment://qr.png")
            await ctx.send(embed=embed, file=file)
        except ImportError:
            await ctx.send("❌ QR code generation is not available (`qrcode` not installed).")
        except Exception as e:
            await ctx.send(f"❌ Error generating QR: {e}")

    @util.command(name="qr", description="Genera un código QR")
    async def util_qr(self, interaction: discord.Interaction, text: str):
        await self.qr(await commands.Context.from_interaction(interaction), text=text)

    @commands.hybrid_command(name="price", description="Get the current price of a crypto or stock.", with_app_command=False)
    async def price(self, ctx, symbol: str):
        """Fetch live crypto price via CoinGecko."""
        await ctx.defer()
        symbol = symbol.lower().strip()
        coingecko_ids = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "ada": "cardano", "doge": "dogecoin", "xrp": "ripple",
            "bnb": "binancecoin", "matic": "matic-network", "dot": "polkadot",
            "avax": "avalanche-2", "link": "chainlink", "ltc": "litecoin",
            "shib": "shiba-inu", "uni": "uniswap", "atom": "cosmos",
        }
        coin_id = coingecko_ids.get(symbol, symbol)
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
            async with self.bot.session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    raise ValueError("Not found")
                data = await resp.json()
            if coin_id not in data:
                await ctx.send(f"❌ `{symbol.upper()}` not found on CoinGecko.")
                return
            info = data[coin_id]
            price_usd = info.get("usd", 0)
            change_24h = info.get("usd_24h_change", 0)
            market_cap = info.get("usd_market_cap", 0)
            change_emoji = "📈" if change_24h >= 0 else "📉"
            change_color = discord.Color.green() if change_24h >= 0 else discord.Color.red()
            embed = discord.Embed(title=f"{change_emoji} {symbol.upper()} Price", color=change_color, timestamp=datetime.datetime.now())
            embed.add_field(name="💵 Price (USD)", value=f"**${price_usd:,.4f}**", inline=True)
            embed.add_field(name="24h Change", value=f"{change_24h:+.2f}%", inline=True)
            if market_cap:
                embed.add_field(name="Market Cap", value=f"${market_cap:,.0f}", inline=True)
            embed.set_footer(text="Source: CoinGecko")
            await ctx.send(embed=embed)
        except Exception:
            await ctx.send(f"❌ Could not retrieve price for `{symbol.upper()}`.")

    @util.command(name="price", description="Precio de crypto o acción")
    async def util_price(self, interaction: discord.Interaction, symbol: str):
        await self.price(await commands.Context.from_interaction(interaction), symbol)


# ══════════════════════════════════════════════════════════════════════════
#  Dynamic Help System — Updated with all cog categories
# ══════════════════════════════════════════════════════════════════════════

COG_EMOJIS = {
    "Economy": "💰", "Games": "🎮", "GamesExtra": "🎯", "Moderation": "🛡️",
    "Voice": "🔊", "Leveling": "⭐", "Management": "⚙️",
    "Utility": "🛠️", "Chatbot": "🤖", "Tickets": "🎫", "Giveaways": "🎉",
    "Social": "🌐", "Starboard": "🌟", "Reputation": "📈", "Admin": "🔒",
    "Roles": "🎭", "Stats": "📊", "Casino": "🎰", "Fun": "🎈",
    "Scheduler": "⏰", "Birthdays": "🎂", "AFK": "💤", "Polls": "📋",
    "Suggestions": "💡", "Interactions": "🤝", "Autoreact": "🔁",
    "Chat": "💬", "Logging": "📜", "Quarantine": "🔒", "Translator": "🌍",
    "NotesPrivate": "📝", "CustomCommands": "🔧", "Achievements": "🏆",
    # New cogs
    "AntiRaid": "🛡️", "Streams": "📡", "RSS": "📰",
    "GitHubHooks": "🐙", "AITools": "🎨", "AIModeration": "🔍",
    "HijackGuard": "🦞",
    "Verification": "🛡️", "Onboarding": "🚀", "ServerTemplates": "📐",
    "WelcomeCards": "👋", "TTS": "🔊", "RoleShop": "🛒", "Colors": "🎨",
    "WebhooksMgr": "🪝", "AutoMod": "🚫", "AutoResponse": "💬",
    "EmbedBuilder": "🖼️", "Digest": "📅",
    "InviteTracker": "📨",
}

# Internal-only. Premium slash lives on Admin but is listed on the landing embed.
HIDDEN_COGS = {"Admin", "Digest"}

HELP_COG_NOTES = {
    "Tickets": "Los tickets se **registran en dabot.davito.es** (panel → Tickets). El canal de transcripciones en Discord es opcional.",
    "HijackGuard": "Clic derecho en un mensaje → **Hijack check**. `/recovered` si te silenciaron por una cuenta hackeada y ya aseguraste Discord.",
    "Verification": "La gente se verifica en dabot.davito.es/verify. El staff decide multicuentas con botones o desde el panel.",
    "Onboarding": "`/start` enseña qué falta (logs, verify, automod). `/dashboard` abre el panel.",
    "Chatbot": "**Premium** al mencionar a Dabot. Personalidad: `/setpersonality` (servidor premium).",
    "AITools": "**Premium:** `/tldr`, análisis e imágenes.",
    "Leveling": "XP por servidor y XP global. Cartas a medida: Premium.",
    "Interactions": "NSFW solo con prefijo en canales NSFW (no sale en Discovery).",
    "ServerTemplates": "`/template apply` monta roles, logs, verificación, bienvenida y niveles. `/nuke` solo dueño o superusuario.",
}


def _one_line(text: str, limit: int = 100) -> str:
    """Discord select descriptions cannot contain newlines and max out at 100 chars."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "…"
    return cleaned


class HelpSelect(discord.ui.Select):
    def __init__(self, bot, author, options, placeholder):
        self.bot = bot
        self.author = author
        super().__init__(
            placeholder=_one_line(placeholder, 150),
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        from utils.helpers import guild_lang
        lang = guild_lang(self.bot, interaction.guild_id)

        if interaction.user.id != getattr(self.author, "id", 0):
            return await interaction.response.send_message(
                self.bot.i18n.get("help.not_for_you", lang) or "Este menú no es para ti.",
                ephemeral=True,
            )

        try:
            cog_name = self.values[0]
            cog = self.bot.get_cog(cog_name)
            if not cog:
                await interaction.response.send_message("Esa categoría ya no está cargada.", ephemeral=True)
                return
            emoji = COG_EMOJIS.get(cog_name, "📂")
            title_fmt = self.bot.i18n.get("help.commands_title", lang, emoji=emoji, cog=cog_name) or f"{emoji} {cog_name}"
            embed = discord.Embed(title=_one_line(str(title_fmt), 256), color=discord.Color.blurple())
            footer_text = self.bot.i18n.get("help.requested_by", lang, user=self.author.display_name) or ""
            if footer_text:
                embed.set_footer(text=_one_line(str(footer_text), 200), icon_url=self.author.display_avatar.url)

            commands_list = cog.get_commands()
            processed_text = []
            processed_names = set()

            def get_command_signature(cmd, parent_name=""):
                prefix = "/" if getattr(cmd, "app_command", None) is not None else "!"
                full_name = f"{parent_name} {cmd.name}".strip()
                if isinstance(cmd, commands.Group):
                    lines = []
                    for child in cmd.commands:
                        lines.extend(get_command_signature(child, full_name))
                    return lines
                desc = cmd.description or "—"
                if isinstance(desc, str) and self.bot.i18n:
                    mapped = self.bot.i18n.get(desc, lang)
                    if isinstance(mapped, str):
                        desc = mapped
                params = []
                try:
                    for name, param in cmd.clean_params.items():
                        params.append(f"<{name}>" if param.required else f"[{name}]")
                except Exception:
                    pass
                param_str = (" " + " ".join(params)) if params else ""
                return [f"`{prefix}{full_name}{param_str}`\n↳ *{desc}*"]

            for command in commands_list:
                if command.hidden:
                    continue
                try:
                    processed_text.extend(get_command_signature(command))
                    processed_names.add(command.name.lower())
                except Exception:
                    continue

            if hasattr(cog, "__cog_app_commands__"):
                for app_cmd in cog.__cog_app_commands__:
                    if app_cmd.name.lower() in processed_names:
                        continue
                    try:
                        if isinstance(app_cmd, discord.app_commands.Group):
                            for sub in app_cmd.commands:
                                desc = sub.description or "—"
                                params = []
                                for p in getattr(sub, "parameters", []) or []:
                                    params.append(f"<{p.name}>" if p.required else f"[{p.name}]")
                                param_str = (" " + " ".join(params)) if params else ""
                                processed_text.append(f"`/{app_cmd.name} {sub.name}{param_str}`\n↳ *{desc}*")
                        else:
                            desc = getattr(app_cmd, "description", None) or "—"
                            params = []
                            for p in getattr(app_cmd, "parameters", []) or []:
                                params.append(f"<{p.name}>" if p.required else f"[{p.name}]")
                            param_str = (" " + " ".join(params)) if params else ""
                            processed_text.append(f"`/{app_cmd.name}{param_str}`\n↳ *{desc}*")
                    except Exception:
                        continue

            extras = HELP_COG_NOTES.get(cog_name)
            if extras:
                processed_text.insert(0, extras)
            total_content = "\n\n".join(processed_text)
            if len(total_content) > 3900:
                total_content = total_content[:3900] + "\n\n… el resto está en dabot.davito.es/help"
            embed.description = total_content or "*No hay comandos en esta categoría.*"
            await interaction.response.edit_message(embed=embed)
        except Exception as e:
            logging.getLogger("Dabot").error("Help select failed: %s", e, exc_info=True)
            msg = "No pude abrir esa categoría. Prueba otra o mira dabot.davito.es/help"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


class HelpSelectView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=180)
        from utils.helpers import guild_lang
        guild_id = getattr(getattr(author, "guild", None), "id", None)
        lang = guild_lang(bot, guild_id)

        options = []
        for cog_name, cog in sorted(bot.cogs.items()):
            if cog_name in HIDDEN_COGS:
                continue
            has_commands = bool(cog.get_commands())
            has_app_commands = bool(getattr(cog, "__cog_app_commands__", []))
            if not has_commands and not has_app_commands:
                continue
            emoji = COG_EMOJIS.get(cog_name, "📂")
            desc = _one_line(cog.description or cog_name, 100)
            try:
                options.append(discord.SelectOption(
                    label=_one_line(cog_name, 100),
                    value=cog_name,
                    description=desc,
                    emoji=emoji,
                ))
            except Exception:
                options.append(discord.SelectOption(
                    label=_one_line(cog_name, 100),
                    value=cog_name,
                    description=desc,
                ))

        if not options:
            return

        base_placeholder = bot.i18n.get("help.select_placeholder", lang)
        if not isinstance(base_placeholder, str):
            base_placeholder = "Elige una categoría"
        # Discord: max 5 rows, max 25 options per select.
        for i in range(0, min(len(options), 125), 25):
            chunk = options[i:i + 25]
            if len(options) > 25:
                placeholder = f"{base_placeholder} ({chunk[0].label[0]}–{chunk[-1].label[0]})"
            else:
                placeholder = base_placeholder
            self.add_item(HelpSelect(bot, author, chunk, placeholder))

    async def on_timeout(self):
        pass


async def setup(bot):
    await bot.add_cog(Utility(bot))
