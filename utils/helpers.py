import asyncio
import aiohttp
import discord
from discord.ext import commands

# Brand colors used across embeds (matches davito.es / dabot dashboard)
DABOT_GREEN = 0x00FF88
DABOT_PURPLE = 0xA855F7
DABOT_PINK = 0xEC4899
DABOT_GOLD = 0xFDE68A

# Shared HTTP timeouts so Discord's event loop never waits forever on a dead API.
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=5, sock_read=10)
HTTP_TIMEOUT_LONG = aiohttp.ClientTimeout(total=45, connect=8, sock_read=40)


async def wait_or_timeout(awaitable, timeout: float, default=None):
    """Await something; return default instead of hanging on TimeoutError."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        return default
    except asyncio.CancelledError:
        raise
    except Exception:
        return default

DASHBOARD_URL = "https://dabot.davito.es"
SUPPORT_URL = "https://davito.es"
PRIVACY_URL = "https://dabot.davito.es/privacy"
TERMS_URL = "https://dabot.davito.es/terms"

# Multipurpose bot invite permissions WITHOUT Administrator.
# Kick/Ban/Timeout, manage channels/roles/nicknames/webhooks/emojis,
# messages + embeds, voice, threads, audit log, manage guild (invite tracker).
BOT_INVITE_PERMISSIONS = 2186104270071


def guild_lang(bot, guild_id) -> str:
    """Resolve a guild's UI language to a langs/*.json code (es, en, ...)."""
    if not guild_id:
        return "es"
    try:
        raw = bot.config.get(guild_id, "lang") or bot.config.get(guild_id, "language") or "es"
    except Exception:
        raw = "es"
    raw = str(raw).lower().strip()
    if raw.startswith("es"):
        return "es"
    if raw.startswith("en"):
        return "en"
    code = raw.split("-")[0]
    if code in ("de", "fr", "it", "ja", "ko", "pt", "zh"):
        return code
    # A configured but unsupported locale must never silently become Spanish;
    # English is the neutral fallback for the bot just like for the dashboard.
    return "en"


def tr(bot, guild_id, key: str, fallback: str = "", **kwargs) -> str:
    """Translate a runtime message using the guild's configured language.

    ``fallback`` is intentionally kept at the call site: a missing key must
    never prevent a moderation/economy command from replying.
    """
    try:
        value = bot.i18n.get(f"runtime.{key}", guild_lang(bot, guild_id), **kwargs)
        return fallback if not value or value.startswith("runtime.") else value
    except Exception:
        return fallback


def invite_url(client_id: str, guild_id: str | None = None) -> str:
    base = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={client_id}"
        f"&permissions={BOT_INVITE_PERMISSIONS}"
        "&scope=bot%20applications.commands"
    )
    if guild_id:
        base += f"&guild_id={guild_id}&disable_guild_select=true"
    return base


class Helpers:
    @staticmethod
    def get_error_embed(error_message):
        embed = discord.Embed(title="Error", description=error_message, color=discord.Color.red())
        return embed

    @staticmethod
    def get_success_embed(message):
        embed = discord.Embed(title="Listo", description=message, color=discord.Color.from_str("#00FF88"))
        return embed
