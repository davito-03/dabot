import discord
import os
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta, time as dtime
from discord.ext import commands
from dotenv import load_dotenv
from utils.envcheck import require_runtime_env
from utils.database import Database
from utils.config import ConfigManager
from utils.i18n import I18n, DiscordTranslator
from utils.permissions import patch_permissions
from utils.helpers import DASHBOARD_URL, HTTP_TIMEOUT, tr, guild_lang
from utils.abuse import AbuseGuard
import aiohttp
from discord import app_commands

# Setup logging with 24-hour cycle and midnight rollover
if not os.path.exists('logs'):
    os.makedirs('logs')


class DailySessionFileHandler(logging.Handler):
    """Writes logs to logs/session_YYYY-MM-DD_HH-MM-SS.txt.
    - Starts at launch/restart time and writes until 00:00:00 midnight.
    - Rotates automatically at 00:00 midnight to a new file for the next 24-hour window.
    - If restarted in the middle of the day, ends the previous file and starts a new one
      from restart time until 00:00.
    """
    def __init__(self, log_dir='logs', encoding='utf-8'):
        super().__init__()
        self.log_dir = log_dir
        self.encoding = encoding
        os.makedirs(self.log_dir, exist_ok=True)
        self.stream = None
        self.current_filename = None
        self._rollover_at = 0
        self._open_new_file()

    def _next_midnight_timestamp(self, now):
        tomorrow = (now + timedelta(days=1)).date()
        next_midnight = datetime.combine(tomorrow, dtime.min)
        return next_midnight.timestamp()

    def _open_new_file(self):
        if self.stream:
            try:
                self.stream.flush()
                self.stream.close()
            except Exception:
                pass
        now = datetime.now()
        ts_str = now.strftime('%Y-%m-%d_%H-%M-%S')
        self.current_filename = os.path.join(self.log_dir, f"session_{ts_str}.txt")
        self.stream = open(self.current_filename, 'a', encoding=self.encoding)
        self._rollover_at = self._next_midnight_timestamp(now)

    def emit(self, record):
        try:
            import time
            if time.time() >= self._rollover_at:
                self._open_new_file()
            msg = self.format(record)
            self.stream.write(msg + '\n')
            self.stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        if self.stream:
            try:
                self.stream.flush()
                self.stream.close()
            except Exception:
                pass
        super().close()


daily_log_handler = DailySessionFileHandler('logs', encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        daily_log_handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('Dabot')

# Load environment variables
load_dotenv()
require_runtime_env("bot")
TOKEN = os.getenv('DISCORD_TOKEN')
SUPER_OWNER_ID = int(os.environ['SUPER_OWNER_ID'])

# Apply Permission Patch
patch_permissions(SUPER_OWNER_ID)

# Bot Configuration — explicit intents (not Intents.all())
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.moderation = True
intents.voice_states = True
intents.invites = True
intents.webhooks = True
intents.auto_moderation_configuration = True
intents.auto_moderation_execution = True


class LocalizedContext(commands.Context):
    """Compatibility layer for older cogs that still call ``ctx.send`` directly."""
    async def send(self, content=None, *args, **kwargs):
        if getattr(self, "guild", None):
            content, kwargs = _localize_payload(self.bot, self.guild.id, content, kwargs)
        return await super().send(content, *args, **kwargs)


def _localize_payload(client, guild_id, content, kwargs):
    """Localize every plain-text/embed output path used by legacy cogs."""
    if not client or not getattr(client, "i18n", None) or not guild_id:
        return content, kwargs
    try:
        lang = guild_lang(client, guild_id)
        if isinstance(content, str):
            content = client.i18n.translate_text(content, lang)
        payload = dict(kwargs or {})
        if payload.get("embed") is not None:
            payload["embed"] = client.i18n.translate_embed(payload["embed"], lang)
        if payload.get("embeds"):
            payload["embeds"] = [client.i18n.translate_embed(embed, lang) for embed in payload["embeds"]]
        if payload.get("view") is not None:
            payload["view"] = client.i18n.translate_view(payload["view"], lang)
        return content, payload
    except Exception:
        return content, kwargs


def _install_interaction_localization():
    """Cover initial responses, followups and embeds in legacy cogs."""
    original_response = discord.InteractionResponse.send_message
    if not getattr(original_response, "_dabot_localized", False):
        async def localized_send(response, content=None, *args, **kwargs):
            interaction = getattr(response, "_parent", None)
            client = getattr(interaction, "client", None)
            guild_id = getattr(interaction, "guild_id", None)
            content, kwargs = _localize_payload(client, guild_id, content, kwargs)
            try:
                if not response.is_done():
                    return await original_response(response, content, *args, **kwargs)
            except discord.InteractionResponded:
                pass
            except discord.HTTPException:
                if not response.is_done():
                    raise
            return await _followup_after_ack(interaction, content, args, kwargs)

        localized_send._dabot_localized = True
        discord.InteractionResponse.send_message = localized_send

    original_edit = discord.InteractionResponse.edit_message
    if not getattr(original_edit, "_dabot_localized", False):
        async def localized_edit(response, *args, **kwargs):
            interaction = getattr(response, "_parent", None)
            client = getattr(interaction, "client", None)
            guild_id = getattr(interaction, "guild_id", None)
            content = kwargs.pop("content", None) if "content" in kwargs else None
            content, localized = _localize_payload(client, guild_id, content, kwargs)
            if content is not None or "content" in kwargs:
                localized["content"] = content
            try:
                if not response.is_done():
                    return await original_edit(response, *args, **localized)
            except (discord.InteractionResponded, discord.HTTPException):
                if not response.is_done():
                    raise
            if interaction is None:
                raise RuntimeError("No interaction to edit")
            return await interaction.edit_original_response(**localized)

        localized_edit._dabot_localized = True
        discord.InteractionResponse.edit_message = localized_edit

    original_modal = discord.InteractionResponse.send_modal
    if not getattr(original_modal, "_dabot_localized", False):
        async def localized_modal(response, modal, *args, **kwargs):
            interaction = getattr(response, "_parent", None)
            client = getattr(interaction, "client", None)
            guild_id = getattr(interaction, "guild_id", None)
            if client and getattr(client, "i18n", None) and guild_id:
                try:
                    client.i18n.translate_modal(modal, guild_lang(client, guild_id))
                except Exception:
                    pass
            return await original_modal(response, modal, *args, **kwargs)

        localized_modal._dabot_localized = True
        discord.InteractionResponse.send_modal = localized_modal

    original_webhook = discord.Webhook.send
    if not getattr(original_webhook, "_dabot_localized", False):
        async def localized_webhook_send(webhook, content=discord.utils.MISSING, *args, **kwargs):
            webhook_type = getattr(webhook, "type", None)
            if webhook_type == discord.WebhookType.application:
                state = getattr(webhook, "_state", None)
                client = getattr(state, "_client", None)
                if client is None and state is not None and hasattr(state, "_get_client"):
                    client = state._get_client()
                guild_id = getattr(webhook, "guild_id", None)
                if content is not discord.utils.MISSING:
                    content, kwargs = _localize_payload(client, guild_id, content, kwargs)
                else:
                    _, kwargs = _localize_payload(client, guild_id, None, kwargs)
            return await original_webhook(webhook, content, *args, **kwargs)

        localized_webhook_send._dabot_localized = True
        discord.Webhook.send = localized_webhook_send

    original_messageable = discord.abc.Messageable.send
    if not getattr(original_messageable, "_dabot_localized", False):
        async def localized_messageable_send(messageable, content=discord.utils.MISSING, *args, **kwargs):
            state = getattr(messageable, "_state", None)
            client = getattr(state, "_client", None)
            if client is None and state is not None and hasattr(state, "_get_client"):
                client = state._get_client()
            guild_id = getattr(getattr(messageable, "guild", None), "id", None)
            if guild_id:
                if content is not discord.utils.MISSING:
                    content, kwargs = _localize_payload(client, guild_id, content, kwargs)
                else:
                    _, kwargs = _localize_payload(client, guild_id, None, kwargs)
            return await original_messageable(messageable, content, *args, **kwargs)

        localized_messageable_send._dabot_localized = True
        discord.abc.Messageable.send = localized_messageable_send

    original_message_edit = discord.Message.edit
    if not getattr(original_message_edit, "_dabot_localized", False):
        async def localized_message_edit(message, *args, **kwargs):
            state = getattr(message, "_state", None)
            client = getattr(state, "_client", None)
            if client is None and state is not None and hasattr(state, "_get_client"):
                client = state._get_client()
            guild_id = getattr(getattr(message, "guild", None), "id", None)
            if guild_id:
                content = kwargs.pop("content", None) if "content" in kwargs else None
                content, localized = _localize_payload(client, guild_id, content, kwargs)
                if content is not None or "content" in kwargs:
                    localized["content"] = content
                kwargs = localized
            return await original_message_edit(message, *args, **kwargs)

        localized_message_edit._dabot_localized = True
        discord.Message.edit = localized_message_edit


async def _followup_after_ack(interaction, content, args, kwargs):
    """If a slash was already deferred, send_message must become a followup."""
    if interaction is None:
        raise RuntimeError("No interaction to follow up")
    delete_after = kwargs.pop("delete_after", None)
    try:
        msg = await interaction.followup.send(content, *args, **kwargs)
    except Exception:
        edit_kw = {}
        if content is not None:
            edit_kw["content"] = content
        for key in ("embed", "embeds", "view", "allowed_mentions"):
            if key in kwargs:
                edit_kw[key] = kwargs[key]
        msg = await interaction.edit_original_response(**edit_kw)
        delete_after = None
    if delete_after and msg is not None:
        async def _delete_later():
            await asyncio.sleep(float(delete_after))
            try:
                await msg.delete()
            except Exception:
                pass
        asyncio.create_task(_delete_later())
    return msg


def get_prefix(bot, message):
    if not message.guild:
        return '!'
    try:
        prefix = bot.config.get(message.guild.id, 'prefix')
        return prefix or '!'
    except Exception:
        return '!'

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None, context_class=LocalizedContext)
_install_interaction_localization()

# Store Super Owner ID on bot instance
bot.super_owner_id = SUPER_OWNER_ID
bot.started_at = datetime.now(timezone.utc).isoformat()
bot._synced_commands = False
bot._sync_error = None
bot.command_uses = 0


@bot.listen("on_interaction")
async def slash_ack_watchdog(interaction: discord.Interaction):
    """Slash commands expire in 3s. If a command is still working, ACK it."""
    if interaction.type is not discord.InteractionType.application_command:
        return

    async def _defer_if_slow():
        try:
            await asyncio.sleep(1.15)
            if interaction.response.is_done():
                return
            await interaction.response.defer()
        except Exception:
            pass

    asyncio.create_task(_defer_if_slow(), name="slash-ack-watchdog")


def runtime_text(ctx, key, fallback, **kwargs):
    guild_id = getattr(getattr(ctx, "guild", None), "id", None)
    return tr(bot, guild_id, key, fallback, **kwargs)

# Database & Config instance
bot.db = Database()
bot.config = ConfigManager(bot)
bot.i18n = I18n(bot)
bot.i18n.load_languages()


@bot.command(hidden=True)
async def sync(ctx):
    if ctx.author.id != SUPER_OWNER_ID and not await bot.is_owner(ctx.author):
        await ctx.send("⛔ Solo el propietario puede sincronizar comandos.")
        return
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Sincronizados {len(synced)} comandos globalmente.")
    except Exception as e:
        await ctx.send(f"❌ Error al sincronizar: {e}")


async def persist_runtime():
    """Shared SQLite heartbeat so the dashboard always knows if the bot is alive."""
    try:
        import math
        import aiosqlite
        lat = getattr(bot, "latency", None)
        if isinstance(lat, (int, float)) and math.isfinite(lat) and lat >= 0:
            latency_ms = int(lat * 1000)
        else:
            latency_ms = 0
        guilds = len(bot.guilds)
        users = sum((g.member_count or 0) for g in bot.guilds)
        now = datetime.now(timezone.utc).isoformat()
        username = str(bot.user) if bot.user else "Dabot"
        user_id = str(bot.user.id) if bot.user else ""
        await bot.db.execute(
            """INSERT INTO bot_runtime
               (id, latency_ms, guilds, users, commands, started_at, updated_at, version, user_id, username)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 latency_ms = excluded.latency_ms,
                 guilds = excluded.guilds,
                 users = excluded.users,
                 commands = excluded.commands,
                 updated_at = excluded.updated_at,
                 version = excluded.version,
                 user_id = excluded.user_id,
                 username = excluded.username,
                 started_at = COALESCE(bot_runtime.started_at, excluded.started_at)""",
            latency_ms, guilds, users, getattr(bot, "command_uses", 0),
            getattr(bot, "started_at", now), now, "3.1.0", user_id, username
        )
        try:
            with open('/tmp/bot_alive', 'w') as f:
                f.write(str(int(time.time())))
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Heartbeat write failed: {e}")


async def _runtime_heartbeat_loop():
    """Independent of discord.ext.tasks so Discord HTTP rate-limits cannot stall it."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await persist_runtime()
        except Exception as e:
            logger.warning("Heartbeat loop iteration failed: %s", e)
        await asyncio.sleep(15)


async def _presence_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            guilds = len(bot.guilds)
            members = sum(g.member_count or 0 for g in bot.guilds)
            options = [
                discord.Activity(type=discord.ActivityType.watching, name=f"{guilds} servidores 🦞"),
                discord.Activity(type=discord.ActivityType.playing, name="dabot.davito.es"),
                discord.Activity(type=discord.ActivityType.listening, name="/help · /start"),
                discord.Activity(type=discord.ActivityType.watching, name=f"{members:,} langostitas"),
            ]
            idx = int(datetime.now().timestamp() // 45) % len(options)
            await bot.change_presence(status=discord.Status.online, activity=options[idx])
        except Exception:
            pass
        await asyncio.sleep(45)


def _ensure_background_loops():
    hb = getattr(bot, "_runtime_hb_task", None)
    if hb is None or hb.done():
        bot._runtime_hb_task = asyncio.create_task(_runtime_heartbeat_loop(), name="runtime-heartbeat")
    pr = getattr(bot, "_presence_task", None)
    if pr is None or pr.done():
        bot._presence_task = asyncio.create_task(_presence_loop(), name="presence-rotate")


@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logger.info('------')

    logger.info("Checking guild configurations...")
    for guild in bot.guilds:
        bot.config.load_config(guild.id)

    logger.info('Database and Configs initialized.')

    _ensure_background_loops()

    # Unregister removed slash commands (NSFW names) and publish new ones.
    if not bot._synced_commands:
        try:
            synced = await bot.tree.sync()
            bot._synced_commands = True
            bot._sync_error = None
            chat = [c for c in synced if getattr(getattr(c, "type", None), "value", 1) == 1]
            ctx_n = len(synced) - len(chat)
            logger.info(
                "Slash commands synced: %s (chat input=%s, context menus=%s)",
                len(synced), len(chat), ctx_n,
            )
            logger.info("Chat input names (%s): %s", len(chat), ", ".join(sorted(c.name for c in chat)))
        except discord.HTTPException as e:
            bot._sync_error = f"{e.status} {getattr(e, 'code', '')}: {getattr(e, 'text', e)}"
            logger.error("Failed to sync slash commands: %s", bot._sync_error)
        except Exception as e:
            bot._sync_error = str(e)
            logger.error(f"Failed to sync slash commands: {e}")

    await persist_runtime()
    logger.info('Runtime heartbeat and presence started.')


@bot.event
async def on_command(ctx):
    bot.command_uses = getattr(bot, "command_uses", 0) + 1


@bot.event
async def on_app_command_completion(interaction, command):
    bot.command_uses = getattr(bot, "command_uses", 0) + 1


async def _reply_command_error(ctx, msg, *, delete_after=None):
    try:
        await ctx.send(msg, delete_after=delete_after)
    except Exception:
        inter = getattr(ctx, "interaction", None)
        if inter is None:
            return
        try:
            if inter.response.is_done():
                await inter.followup.send(msg, ephemeral=True)
            else:
                await inter.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


def _user_facing_command_error(ctx, error):
    """Return a reply for expected user errors, or None to log+generic."""
    if isinstance(error, commands.CommandNotFound):
        return False
    if isinstance(error, commands.CommandOnCooldown):
        return runtime_text(ctx, "common.cooldown_seconds", "⏳ Espera {seconds:.1f}s antes de volver a usar este comando.", seconds=error.retry_after), {"delete_after": 8}
    if isinstance(error, (commands.MissingPermissions, commands.MissingRole, commands.MissingAnyRole, commands.NotOwner)):
        return runtime_text(ctx, "common.missing_permissions", "⛔ No tienes permisos para usar este comando."), {}
    if isinstance(error, (commands.BotMissingPermissions, commands.BotMissingRole)):
        missing = ", ".join(getattr(error, "missing_permissions", None) or getattr(error, "missing_roles", None) or [])
        return runtime_text(ctx, "common.bot_missing_permissions", "⛔ Me faltan permisos: `{missing}`.", missing=missing or "required"), {}
    if isinstance(error, commands.MissingRequiredArgument):
        prefix = getattr(ctx, "prefix", "/") or "/"
        command = getattr(ctx, "command", None)
        signature = getattr(command, "signature", "") if command else ""
        name = getattr(command, "qualified_name", None) or getattr(command, "name", "")
        return runtime_text(ctx, "common.usage", "ℹ️ Uso: `{prefix}{command} {signature}`", prefix=prefix, command=name, signature=signature), {}
    if isinstance(error, commands.NSFWChannelRequired):
        return runtime_text(ctx, "common.nsfw_only", "🔞 Este comando solo se puede usar en canales NSFW."), {}
    if isinstance(error, commands.NoPrivateMessage):
        return runtime_text(ctx, "common.guild_only", "ℹ️ Este comando se usa dentro de un servidor."), {}
    if isinstance(error, commands.PrivateMessageOnly):
        return runtime_text(ctx, "common.dm_only", "ℹ️ Este comando solo se puede usar por MD."), {}
    if isinstance(error, commands.MaxConcurrencyReached):
        return runtime_text(ctx, "common.busy", "⏳ Ese comando ya se está usando. Espera un momento."), {}
    if isinstance(error, commands.DisabledCommand):
        return runtime_text(ctx, "common.disabled", "⛔ Ese comando está desactivado."), {}
    if isinstance(error, (
        commands.BadArgument, commands.BadUnionArgument, commands.BadLiteralArgument,
        commands.UserNotFound, commands.MemberNotFound, commands.ChannelNotFound,
        commands.RoleNotFound, commands.MessageNotFound, commands.EmojiNotFound,
        commands.GuildNotFound, commands.ThreadNotFound, commands.ConversionError,
        commands.BadBoolArgument, commands.RangeError, commands.ArgumentParsingError,
        commands.UnexpectedQuoteError, commands.InvalidEndOfQuotedStringError,
        commands.ExpectedClosingQuoteError, commands.TooManyArguments,
    )):
        return runtime_text(ctx, "common.bad_argument", "❌ Argumento no válido. Revisa el comando e inténtalo de nuevo."), {}
    if isinstance(error, commands.CheckFailure):
        return runtime_text(ctx, "common.missing_permissions", "⛔ No tienes permisos para usar este comando."), {}
    return None


@bot.event
async def on_command_error(ctx, error):
    error = getattr(error, "original", error)
    if isinstance(error, commands.HybridCommandError):
        error = getattr(error, "original", error)
    mapped = _user_facing_command_error(ctx, error)
    if mapped is False:
        return
    if mapped is not None:
        msg, extra = mapped
        await _reply_command_error(ctx, msg, **extra)
        return
    logger.error(f"Command error in {getattr(ctx.command, 'name', '?')}: {error}", exc_info=error)
    await _reply_command_error(ctx, runtime_text(ctx, "common.command_failed", "❌ Ese comando falló. Inténtalo de nuevo."))


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Slash commands must always reply or Discord shows 'esta aplicación no responde'."""
    orig = getattr(error, "original", error)
    name = getattr(interaction.command, "qualified_name", "?") if interaction.command else "?"
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = runtime_text(interaction, "common.cooldown_seconds", "⏳ Espera {seconds:.1f}s antes de volver a usar este comando.", seconds=error.retry_after)
    elif isinstance(error, app_commands.MissingPermissions):
        msg = runtime_text(interaction, "common.missing_permissions", "⛔ No tienes permisos para usar este comando.")
    elif isinstance(error, app_commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions)
        msg = runtime_text(interaction, "common.bot_missing_permissions", "⛔ Me faltan permisos: `{missing}`.", missing=missing)
    elif isinstance(error, (app_commands.CheckFailure, app_commands.NoPrivateMessage)):
        msg = runtime_text(interaction, "common.missing_permissions", "⛔ No puedes usar este comando aquí.")
    elif isinstance(error, app_commands.TransformerError):
        msg = runtime_text(interaction, "common.bad_argument", "❌ Argumento no válido. Revisa el comando e inténtalo de nuevo.")
    elif isinstance(error, app_commands.CommandSignatureMismatch):
        msg = runtime_text(interaction, "common.stale_command", "⚠️ Ese comando está desactualizado. Espera un minuto y vuelve a escribirlo.")
    else:
        logger.error("Slash error in %s: %s", name, orig, exc_info=orig)
        msg = runtime_text(interaction, "common.command_failed", "❌ Ese comando falló. Inténtalo de nuevo.")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        try:
            await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            pass


@bot.event
async def on_guild_join(guild):
    logger.info(f"Joined new guild: {guild.name} ({guild.id})")
    try:
        banned = await bot.db.fetch(
            "SELECT guild_id FROM guild_blacklist WHERE guild_id = ?", guild.id
        )
        if banned:
            logger.warning("Leaving blacklisted guild %s (%s)", guild.name, guild.id)
            await guild.leave()
            return
    except Exception as e:
        logger.warning("Guild blacklist check failed: %s", e)
    bot.config.load_config(guild.id)

    channel = guild.system_channel
    if not channel or not channel.permissions_for(guild.me).send_messages:
        channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    if channel:
        try:
            embed = discord.Embed(
                title="¡Dabot ya está en tu servidor! 🦞",
                description=(
                    "Soy **Dabot**, el bot de [davito.es](https://davito.es): moderación, niveles, economía, "
                    "tickets, IA y un panel web para configurarlo sin comandos raros."
                ),
                color=discord.Color.from_str("#00FF88")
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)

            embed.add_field(
                name="1. Panel web",
                value=f"Entra en **[{DASHBOARD_URL.replace('https://', '')}]({DASHBOARD_URL})** con Discord y elige este servidor.",
                inline=False
            )
            embed.add_field(
                name="2. Asistente in-server",
                value="Un administrador puede usar `/start` o `/setup` y el panel **dabot.davito.es**.",
                inline=False
            )
            embed.add_field(
                name="3. Comandos",
                value="`/help` · `/ping` · `/interact` · `/eco` · `/poll`\nMencióname para hablar con la IA.",
                inline=False
            )
            embed.set_footer(text="Davito · dabot.davito.es · Política de privacidad en /privacy")
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error sending welcome message to guild {guild.id}: {e}")

async def load_extensions():
    skip = {"tts", "music"}
    for filename in os.listdir('./cogs'):
        if not filename.endswith('.py'):
            continue
        if filename[:-3] in skip:
            logger.info(f'Skipped extension: {filename}')
            continue
        try:
            await bot.load_extension(f'cogs.{filename[:-3]}')
            logger.info(f'Loaded extension: {filename}')
        except Exception as e:
            logger.error(f'Failed to load extension {filename}: {e}', exc_info=True)

async def main():
    if not TOKEN:
        logger.error("Error: DISCORD_TOKEN not found in .env")
        return

    async with bot:
        bot.session = aiohttp.ClientSession(timeout=HTTP_TIMEOUT)
        await bot.db.setup()
        bot.abuse = AbuseGuard(bot)
        await bot.abuse.setup()
        # Descriptions follow the Discord client language. Names stay English
        # (Spanish names like "configuración" fail Discord's charset rules).
        await bot.tree.set_translator(DiscordTranslator(bot.i18n))
        await load_extensions()
        try:
            await bot.start(TOKEN)
        finally:
            if not bot.session.closed:
                await bot.session.close() # Ensure session is closed
                logger.info("Shared ClientSession closed.")
            await bot.db.close()
            logger.info("Database connection closed.")

if __name__ == '__main__':
    # --- CRASH LOOP PROTECTION ---
    import json as _json
    _restart_state_file = 'restart_state.json'
    _MAX_RESTARTS = 3
    _RESTART_WINDOW = 60  # seconds

    def _check_restart_loop():
        """Returns True if safe to restart, False if in a crash loop."""
        import time
        now = time.time()
        state = {'restarts': [], 'last_check': now}
        if os.path.exists(_restart_state_file):
            try:
                with open(_restart_state_file, 'r') as f:
                    state = _json.load(f)
            except Exception:
                pass
        # Filter restarts within the window
        recent = [t for t in state.get('restarts', []) if now - t < _RESTART_WINDOW]
        if len(recent) >= _MAX_RESTARTS:
            return False
        recent.append(now)
        with open(_restart_state_file, 'w') as f:
            _json.dump({'restarts': recent, 'last_check': now}, f)
        return True

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"🔥 FATAL ERROR: {e}")
        
        # --- CRASH RECOVERY SYSTEM ---
        from utils.ai_repair import RepairEngine
        # We can pass None for bot since restore_backup doesn't need it
        engine = RepairEngine(None)
        state = engine.check_repair_state()
        
        if state and state.get('status') == 'pending_restart':
            logger.warning("🔄 Crash detected after repair! Initiating ROLLBACK...")
            
            backup_ids = state.get('backup_ids', [])
            success = True
            for bid in reversed(backup_ids):
                ok, msg = engine.restore_backup(bid)
                if ok:
                    logger.info(f"✅ Restored backup {bid}")
                else:
                    logger.error(f"❌ Failed to restore {bid}: {msg}")
                    success = False
            
            if success:
                logger.info("✨ Rollback complete. Restarting bot to stable state...")
                engine.mark_repair_faulty()
                
                # Check for crash loop before restarting
                if _check_restart_loop():
                    import sys
                    import subprocess
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                else:
                    logger.critical("💀 Crash loop detected! Too many restarts in a short period. Halting.")
            else:
                 logger.critical("💀 Rollback failed. Manual intervention required.")
        else:
             # Standard crash, just log it
             logger.critical("💀 Bot crashed (No repair in progress).")
             raise e
