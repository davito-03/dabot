import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
from utils.premium import deny_text
from utils.helpers import guild_lang


class AITools(commands.GroupCog, group_name="ai", group_description="IA de Dabot: resúmenes, imágenes y memoria"):
    """AI-powered tools: TLDR conversation summaries and AI-assisted analysis."""
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.AITools')

    async def _get_ai_response(self, prompt: str, is_premium: bool = False) -> str | None:
        """Use the bot's chatbot AI engine to generate a response."""
        chatbot = self.bot.get_cog('Chatbot')
        if not chatbot or not hasattr(chatbot, 'ai'):
            return None

        msgs = [{"role": "user", "content": prompt}]
        try:
            response, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False, is_premium=is_premium)
            return response
        except Exception as e:
            self.logger.error(f"AI generation error: {e}")
            return None

    @app_commands.command(name="tldr", description="📝 Summarize the last N messages in this channel using AI.")
    @app_commands.describe(
        count="Number of messages to summarize (default 50, max 200)",
        language="Language for the summary"
    )
    @app_commands.choices(language=[
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Spanish", value="es"),
        app_commands.Choice(name="French", value="fr"),
        app_commands.Choice(name="German", value="de"),
        app_commands.Choice(name="Japanese", value="ja"),
    ])
    async def tldr(self, interaction: discord.Interaction, count: int = 50, language: str = "en"):
        # Require manage_messages to prevent abuse
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
            return

        # Check premium status
        if not await self.bot.db.is_guild_premium(interaction.guild_id, self.bot):
            await interaction.response.send_message(deny_text(guild_lang(self.bot, interaction.guild_id)), ephemeral=True)
            return

        count = min(max(count, 10), 200)
        await interaction.response.defer()

        # Fetch messages
        messages = []
        async for msg in interaction.channel.history(limit=count, oldest_first=False):
            if not msg.author.bot and msg.content:
                messages.append(f"[{msg.author.display_name}]: {msg.content[:150]}")

        messages.reverse()  # Chronological order

        if len(messages) < 3:
            await interaction.followup.send("❌ Not enough messages to summarize.")
            return

        lang_names = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "ja": "Japanese"}
        lang_name = lang_names.get(language, "English")

        conversation = "\n".join(messages[:100])  # Cap at 100 for token limits
        prompt = (
            f"Summarize the following Discord conversation in {lang_name}. "
            f"Be concise but capture all key topics, decisions, and important points. "
            f"Format with bullet points. Do NOT include any system messages or meta-commentary.\n\n"
            f"CONVERSATION:\n{conversation}"
        )

        result = await self._get_ai_response(prompt, is_premium=True)

        if not result:
            await interaction.followup.send("❌ AI service unavailable. Make sure the Chatbot cog is loaded.")
            return

        embed = discord.Embed(
            title=f"📝 TLDR — Last {len(messages)} messages",
            description=result[:4000],
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name} • {lang_name}",
            icon_url=interaction.user.display_avatar.url
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="analyze", description="🔍 Analyze the tone and sentiment of recent messages.")
    @app_commands.describe(count="Number of messages to analyze (default 30, max 100)")
    async def aianalyze(self, interaction: discord.Interaction, count: int = 30):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
            return

        # Check premium status
        if not await self.bot.db.is_guild_premium(interaction.guild_id, self.bot):
            await interaction.response.send_message(deny_text(guild_lang(self.bot, interaction.guild_id)), ephemeral=True)
            return

        count = min(max(count, 10), 100)
        await interaction.response.defer()

        messages = []
        async for msg in interaction.channel.history(limit=count, oldest_first=False):
            if not msg.author.bot and msg.content:
                messages.append(f"[{msg.author.display_name}]: {msg.content[:100]}")

        messages.reverse()

        if len(messages) < 3:
            await interaction.followup.send("❌ Not enough messages to analyze.")
            return

        conversation = "\n".join(messages)
        prompt = (
            "Analyze the tone and sentiment of this Discord conversation. Provide:\n"
            "1. **Overall Mood** (e.g., friendly, heated, neutral, toxic)\n"
            "2. **Key Topics** discussed\n"
            "3. **Notable Dynamics** (who's leading discussion, any conflicts)\n"
            "4. **Toxicity Score** (0-10 scale, 0=perfectly healthy, 10=extremely toxic)\n\n"
            "Be brief and factual. Do not moralize.\n\n"
            f"CONVERSATION:\n{conversation}"
        )

        result = await self._get_ai_response(prompt, is_premium=True)

        if not result:
            await interaction.followup.send("❌ AI service unavailable.")
            return

        embed = discord.Embed(
            title=f"🔍 Channel Analysis — Last {len(messages)} messages",
            description=result[:4000],
            color=discord.Color.teal(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="imagine", description="🎨 Generate a beautiful image using AI for free!")
    @app_commands.describe(
        prompt="The description of the image to generate",
        model="Choose the AI model/style to use"
    )
    @app_commands.choices(model=[
        app_commands.Choice(name="Flux (Default - Ultra Detail & Text)", value="flux"),
        app_commands.Choice(name="Turbo (Ultra Fast generation)", value="turbo"),
        app_commands.Choice(name="Anime (Anything V5 Illustration)", value="any"),
        app_commands.Choice(name="PixArt (Cinematic & Artistic)", value="pixart"),
    ])
    @app_commands.checks.cooldown(1, 120.0, key=lambda i: i.user.id)
    async def imagine(self, interaction: discord.Interaction, prompt: str, model: str = "flux"):
        # Check premium status
        if not await self.bot.db.is_guild_premium(interaction.guild_id, self.bot):
            await interaction.response.send_message(deny_text(guild_lang(self.bot, interaction.guild_id)), ephemeral=True)
            return

        await interaction.response.defer()
        
        try:
            import urllib.parse
            # Enhance prompt dynamically depending on the selected model style
            style_tags = {
                "flux": ", 8k resolution, cinematic lighting, highly detailed masterpiece, aesthetic",
                "turbo": ", sharp focus, highly detailed, vibrant colors, clear render",
                "any": ", anime style, manga illustration, highly detailed, masterpieces, 4k",
                "pixart": ", cinematic concept art, fantasy illustration, dramatic lighting, highly detailed, masterpiece"
            }
            tags = style_tags.get(model, style_tags["flux"])
            enhanced = f"{prompt}{tags}"
            encoded = urllib.parse.quote(enhanced)
            image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&private=true&model={model}"
            
            style_names = {
                "flux": "FLUX.1 (Fotorrealismo y Texto)",
                "turbo": "SDXL Turbo (Rápido)",
                "any": "Anything V5 (Anime/Manga)",
                "pixart": "PixArt Sigma (Cinematográfico)"
            }
            model_name = style_names.get(model, "FLUX.1")

            embed = discord.Embed(
                title="🎨 AI Generated Image",
                description=f"**Prompt:** {prompt}\n**Estilo/Modelo:** `{model_name}`",
                color=discord.Color.from_rgb(224, 86, 253),
                timestamp=discord.utils.utcnow()
            )
            embed.set_image(url=image_url)
            embed.set_footer(
                text=f"Requested by {interaction.user.display_name} • Pollinations AI",
                icon_url=interaction.user.display_avatar.url
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            await interaction.followup.send("❌ Failed to generate image. Please try again later.")

    @imagine.error
    async def imagine_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            seconds = int(error.retry_after)
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            
            time_text = f"{minutes}m {remaining_seconds}s" if minutes > 0 else f"{seconds}s"
            
            # Since the command errored before deferring, we can use send_message directly
            await interaction.response.send_message(
                f"⏳ ¡Cálmate mi cielo! Este comando tiene un cooldown. Debes esperar **{time_text}** antes de volver a usarlo. 🌸",
                ephemeral=True
            )
        else:
            self.logger.error(f"Error in imagine command: {error}")
            try:
                await interaction.response.send_message("❌ Ha ocurrido un error al procesar el comando.", ephemeral=True)
            except Exception:
                try:
                    await interaction.followup.send("❌ Ha ocurrido un error al procesar el comando.", ephemeral=True)
                except Exception:
                    pass

    @app_commands.command(name="prompt", description="🪄 Turns a simple idea into 3 highly detailed premium prompts for /ai imagine.")
    @app_commands.describe(idea="Your basic image idea (e.g. 'a pirate cat')")
    async def promptcraft(self, interaction: discord.Interaction, idea: str):
        # Check premium status
        if not await self.bot.db.is_guild_premium(interaction.guild_id, self.bot):
            await interaction.response.send_message(deny_text(guild_lang(self.bot, interaction.guild_id)), ephemeral=True)
            return

        await interaction.response.defer()
        
        prompt = (
            f"You are a master AI artist and prompt engineer. "
            f"Recreate the following basic concept into exactly 3 distinct, highly detailed, and creative image generation prompts. "
            f"Each prompt must be in English (for best generator results) and have a specific style:\n"
            f"1. **Cyberpunk/Sci-Fi**: Highly detailed neon lighting, hyperrealistic, futuristic elements.\n"
            f"2. **Epic Fantasy / Unreal Engine 5**: Cinematic lighting, dramatic environment, hyperrealistic, breathtaking concept art.\n"
            f"3. **Ghibli Anime**: Beautiful hand-drawn anime aesthetic, vibrant soft colors, masterpiece illustration.\n\n"
            f"Format the output exactly in Spanish, but keep the actual prompt text within backticks (in English) ready for copy-pasting. "
            f"Separate each style clearly with a heading and brief description.\n\n"
            f"CONCEPT: {idea}"
        )
        
        result = await self._get_ai_response(prompt)
        
        if not result:
            await interaction.followup.send("❌ AI service unavailable. Make sure the Chatbot cog is loaded.")
            return
            
        embed = discord.Embed(
            title="🪄 AI PromptCraft — Master Prompts",
            description=f"Aquí tienes 3 variaciones premium para tu idea: **{idea}**\n\n{result[:4000]}",
            color=discord.Color.from_rgb(162, 155, 254),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name} • DaBot Crafting Engine",
            icon_url=interaction.user.display_avatar.url
        )
        await interaction.followup.send(embed=embed)

    async def _ctx(self, interaction: discord.Interaction):
        return await commands.Context.from_interaction(interaction)

    @app_commands.command(name="forget", description="El bot olvida todo sobre ti en este servidor.")
    async def forget_slash(self, interaction: discord.Interaction):
        cog = self.bot.get_cog("Chatbot")
        if not cog:
            return await interaction.response.send_message("❌ IA no disponible.", ephemeral=True)
        await cog.forget(await self._ctx(interaction))

    @app_commands.command(name="remember", description="El bot recordará esto para siempre.")
    @app_commands.describe(text="Lo que Dabot debe recordar")
    async def remember_slash(self, interaction: discord.Interaction, text: str):
        cog = self.bot.get_cog("Chatbot")
        if not cog:
            return await interaction.response.send_message("❌ IA no disponible.", ephemeral=True)
        await cog.remember(await self._ctx(interaction), text=text)

    @app_commands.command(name="setup", description="Activa el chatbot de IA en este servidor (Premium).")
    @app_commands.describe(enabled="Activar o desactivar", channel="Canal permitido (opcional)")
    async def setup_slash(self, interaction: discord.Interaction, enabled: bool, channel: discord.TextChannel = None):
        cog = self.bot.get_cog("Chatbot")
        if not cog:
            return await interaction.response.send_message("❌ IA no disponible.", ephemeral=True)
        await cog.chatbotsetup(await self._ctx(interaction), enabled, channel)

    @app_commands.command(name="personality", description="Personalidad del bot en este servidor (Premium).")
    @app_commands.describe(prompt="Cómo debe hablar Dabot")
    async def personality_slash(self, interaction: discord.Interaction, prompt: str):
        cog = self.bot.get_cog("Chatbot")
        if not cog:
            return await interaction.response.send_message("❌ IA no disponible.", ephemeral=True)
        await cog.setpersonality(await self._ctx(interaction), prompt=prompt)

    @app_commands.command(name="recap", description="Resumen inteligente de los últimos mensajes del canal.")
    @app_commands.describe(mensajes="Número de mensajes (10-100)", privado="Solo tú ves el resumen")
    async def recap_slash(self, interaction: discord.Interaction, mensajes: int = 50, privado: bool = False):
        cog = self.bot.get_cog("Recap")
        if not cog:
            return await interaction.response.send_message("❌ Recap no disponible.", ephemeral=True)
        await cog.recap(await self._ctx(interaction), mensajes, privado)

    @app_commands.command(name="meme", description="🎭 Genera un meme único con IA.")
    @app_commands.describe(tema="Tema o chiste del meme")
    async def meme_slash(self, interaction: discord.Interaction, tema: str):
        cog = self.bot.get_cog("GamesIA")
        if not cog:
            return await interaction.response.send_message("❌ No disponible.", ephemeral=True)
        await cog.meme_ia(interaction, tema)

    @app_commands.command(name="rpg", description="⚔️ Aventura RPG narrada por la IA.")
    @app_commands.describe(tematica="Temática de la aventura")
    @app_commands.choices(tematica=[
        app_commands.Choice(name="Fantasía Épica", value="fantasy"),
        app_commands.Choice(name="Cyberpunk", value="cyberpunk"),
        app_commands.Choice(name="Apocalipsis Zombie", value="zombie"),
        app_commands.Choice(name="Misterio Lovecraftiano", value="lovecraft"),
    ])
    async def rpg_slash(self, interaction: discord.Interaction, tematica: str):
        cog = self.bot.get_cog("GamesIA")
        if not cog:
            return await interaction.response.send_message("❌ No disponible.", ephemeral=True)
        await cog.aventura(interaction, tematica)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Check premium status
        if not await self.bot.db.is_guild_premium(message.guild, self.bot):
            return
            
        # Check if message has voice note or audio attachments
        has_voice = False
        voice_attachment = None
        for a in message.attachments:
            if a.filename.endswith(('.ogg', '.mp3', '.m4a', '.wav')) or getattr(a, "is_voice_message", lambda: False)():
                has_voice = True
                voice_attachment = a
                break
                
        if not has_voice or not voice_attachment:
            return
            
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return
            
        try:
            try:
                await message.add_reaction("🎙️")
            except:
                pass
                
            async with self.bot.session.get(voice_attachment.url) as resp:
                if resp.status != 200:
                    return
                audio_data = await resp.read()
                    
            def _transcribe():
                from groq import Groq
                client = Groq(api_key=groq_key)
                file_tuple = ('voice.ogg', audio_data)
                transcription = client.audio.transcriptions.create(
                    file=file_tuple,
                    model="whisper-large-v3",
                    response_format="text"
                )
                return transcription
                
            loop = self.bot.loop
            text = await loop.run_in_executor(None, _transcribe)
            
            if text and text.strip():
                embed = discord.Embed(
                    title="🎙️ Transcripción de Nota de Voz",
                    description=f"{text.strip()}",
                    color=discord.Color.from_rgb(255, 121, 121)
                )
                embed.set_footer(text=f"Voz de {message.author.display_name}", icon_url=message.author.display_avatar.url)
                await message.reply(embed=embed, mention_author=False)
                
        except Exception as e:
            self.logger.error(f"Whisper transcription failed: {e}")

async def setup(bot):
    await bot.add_cog(AITools(bot))
