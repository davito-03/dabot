import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import logging

# Flag emoji → language code mapping
FLAG_TO_LANG = {
    "🇪🇸": "es",  # Spanish
    "🇬🇧": "en",  # English
    "🇺🇸": "en",  # English (US)
    "🇫🇷": "fr",  # French
    "🇩🇪": "de",  # German
    "🇮🇹": "it",  # Italian
    "🇵🇹": "pt",  # Portuguese
    "🇧🇷": "pt",  # Portuguese (Brazil)
    "🇯🇵": "ja",  # Japanese
    "🇰🇷": "ko",  # Korean
    "🇨🇳": "zh-CN",  # Chinese Simplified
    "🇷🇺": "ru",  # Russian
    "🇳🇱": "nl",  # Dutch
    "🇸🇦": "ar",  # Arabic
    "🇹🇷": "tr",  # Turkish
    "🇵🇱": "pl",  # Polish
    "🇺🇦": "uk",  # Ukrainian
    "🇸🇪": "sv",  # Swedish
    "🇳🇴": "no",  # Norwegian
    "🇩🇰": "da",  # Danish
    "🇫🇮": "fi",  # Finnish
    "🇬🇷": "el",  # Greek
    "🇮🇱": "he",  # Hebrew
    "🇮🇳": "hi",  # Hindi
    "🇹🇭": "th",  # Thai
    "🇻🇳": "vi",  # Vietnamese
    "🇮🇩": "id",  # Indonesian
    "🇲🇽": "es",  # Spanish (Mexico)
    "🇦🇷": "es",  # Spanish (Argentina)
}

LANG_NAMES = {
    "es": "Spanish", "en": "English", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean",
    "zh-CN": "Chinese", "ru": "Russian", "nl": "Dutch", "ar": "Arabic",
    "tr": "Turkish", "pl": "Polish", "uk": "Ukrainian", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "el": "Greek",
    "he": "Hebrew", "hi": "Hindi", "th": "Thai", "vi": "Vietnamese",
    "id": "Indonesian",
}


class Translator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Dabot")
        self._translator = None

    def get_translator(self):
        """Lazy-load the translator to avoid import errors at startup."""
        if self._translator is None:
            try:
                from deep_translator import GoogleTranslator
                self._translator = GoogleTranslator
            except ImportError:
                return None
        return self._translator

    async def _translate(self, text: str, target_lang: str) -> str | None:
        """Translate text using deep_translator in a thread."""
        Translator_cls = self.get_translator()
        if not Translator_cls:
            return None
        loop = self.bot.loop
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: Translator_cls(source="auto", target=target_lang).translate(text)
                ),
                timeout=10,
            )
        except asyncio.TimeoutError:
            self.logger.warning("Translation timed out")
            return None

    # Slash de traducción: /user translate (UserInstall). Aquí queda el traductor por reacción.

    # ── Reaction-based translation ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        emoji = str(payload.emoji)
        if emoji not in FLAG_TO_LANG:
            return

        target_lang = FLAG_TO_LANG[emoji]

        # Fetch the message
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        if not message.content or message.author.bot:
            return

        result = await self._translate(message.content, target_lang)
        if not result or result.lower() == message.content.lower():
            return  # No change / same language

        lang_name = LANG_NAMES.get(target_lang, target_lang)
        user = self.bot.get_user(payload.user_id)
        user_name = user.display_name if user else f"User {payload.user_id}"

        embed = discord.Embed(
            title=f"🌍 {emoji} Translation to {lang_name}",
            description=result[:2000],
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Requested by {user_name} • Original by {message.author.display_name}")
        try:
            await channel.send(embed=embed, delete_after=60)
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(Translator(bot))
