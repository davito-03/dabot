import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import datetime
import os
import aiohttp
import json
import time
from collections import defaultdict

# Pre-filter keywords to save on HTTP requests (optional, but good for performance)
TOXICITY_KEYWORDS = [
    "kill", "die", "kys", "hate", "stfu", "fuck", "shit", "bitch",
    "retard", "faggot", "nigger", "whore", "slut", "cunt", "rape",
    "suicide", "cutting", "noose", "shoot", "bomb", "threat",
    "matar", "morir", "puta", "mierda", "joder", "odio", "suicid",
    "marica", "zorra", "violación"
]

class AIModeration(commands.Cog):
    """
    Advanced Moderation System.
    Uses OpenAI's Moderation API for text toxicity and Google Safe Browsing API for malicious links.
    """
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.AIMod')
        self._recent_cache: dict[str, dict] = {}
        self._cache_max = 500
        self.message_windows = {}
        self.last_alert = {}
        self._guild_minute_analyses = defaultdict(list)
        
        # Load API keys
        self.openai_key = os.getenv('OPENAI_API_KEY')
        self.safebrowsing_key = os.getenv('GOOGLE_SAFE_BROWSING_KEY')

        if not self.openai_key:
            self.logger.warning("⚠️ OPENAI_API_KEY not found. Text moderation will be disabled.")
        if not self.safebrowsing_key:
            self.logger.warning("⚠️ GOOGLE_SAFE_BROWSING_KEY not found. Link scanning will be disabled.")

    aimod_group = app_commands.Group(
        name="aimod",
        description="🛡️ AI-powered security and moderation settings.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @aimod_group.command(name="enable", description="Activa la moderación inteligente con IA.")
    @app_commands.describe(channel="Canal donde se enviarán las alertas de seguridad")
    async def aimod_enable(self, interaction: discord.Interaction, channel: discord.TextChannel):
        is_premium = await self.bot.db.is_guild_premium(interaction.guild, self.bot)
        tier_label = "⭐ **Premium** (Hasta **100 mensajes/min** analizados con IA)" if is_premium else "🌱 **Gratuito** (Hasta **10 mensajes/min** analizados con IA)"

        await self.bot.db.execute(
            """INSERT INTO ai_settings (guild_id, moderation_channel_id) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET moderation_channel_id = excluded.moderation_channel_id""",
            interaction.guild.id, channel.id
        )
        embed = discord.Embed(
            title="🛡️ Moderación con IA Activada",
            description=(
                f"Las alertas de moderación IA se enviarán a {channel.mention}.\n\n"
                f"📊 **Nivel de análisis:** {tier_label}\n"
                f"{'' if is_premium else '💡 *Pasa a Premium para aumentar la capacidad de análisis a 100 mensajes por minuto.*'}"
            ),
            color=discord.Color.green()
        )
        if not self.openai_key or not self.safebrowsing_key:
            embed.set_footer(text="⚠️ Nota: Algunas APIs externas no están disponibles.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @aimod_group.command(name="disable", description="Desactiva la moderación inteligente con IA.")
    async def aimod_disable(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "UPDATE ai_settings SET moderation_channel_id = NULL WHERE guild_id = ?",
            interaction.guild.id
        )
        await interaction.response.send_message("✅ Moderación IA desactivada.", ephemeral=True)

    @aimod_group.command(name="status", description="Muestra el estado y límite de análisis de la moderación IA.")
    async def aimod_status(self, interaction: discord.Interaction):
        config = await self.bot.db.fetch(
            "SELECT moderation_channel_id FROM ai_settings WHERE guild_id = ?",
            interaction.guild.id
        )
        
        channel = interaction.guild.get_channel(config[0]) if config and config[0] else None
        is_premium = await self.bot.db.is_guild_premium(interaction.guild, self.bot)
        max_analyses = 100 if is_premium else 10
        tier_label = "⭐ Premium (100 msgs/min)" if is_premium else "🌱 Gratuito (10 msgs/min)"

        now = time.time()
        recent_count = len([t for t in self._guild_minute_analyses[interaction.guild.id] if now - t < 60.0])

        embed = discord.Embed(title="🛡️ Estado de la Moderación IA", color=discord.Color.teal())
        embed.add_field(name="Canal de alertas", value=channel.mention if channel else "❌ Desactivado", inline=False)
        embed.add_field(name="Nivel de análisis", value=tier_label, inline=True)
        embed.add_field(name="Uso en el último minuto", value=f"`{recent_count}` / `{max_analyses}` msgs", inline=True)
        embed.add_field(name="Filtro de Toxicidad (IA)", value="✅ Activo" if self.openai_key else "❌ Sin clave", inline=True)
        embed.add_field(name="Escáner de Enlaces (SafeBrowsing)", value="✅ Activo" if self.safebrowsing_key else "❌ Sin clave", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def check_urls(self, urls: list[str]) -> list[dict]:
        """Checks a list of URLs against Google Safe Browsing API."""
        if not self.safebrowsing_key or not urls:
            return []

        endpoint = f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={self.safebrowsing_key}"
        payload = {
            "client": {
                "clientId": "dabot-v3",
                "clientVersion": "3.0.0"
            },
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url} for url in urls]
            }
        }
        
        try:
            async with self.bot.session.post(endpoint, json=payload, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('matches', [])
        except Exception as e:
            self.logger.error(f"Safe Browsing Error: {e}")
        return []

    async def check_text(self, text: str) -> dict:
        """Checks text against OpenAI Moderation API."""
        if not self.openai_key or not text:
            return None

        endpoint = "https://api.openai.com/v1/moderations"
        headers = {"Authorization": f"Bearer {self.openai_key}"}
        payload = {"input": text}

        try:
            async with self.bot.session.post(endpoint, headers=headers, json=payload, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and "results" in data:
                        return data["results"][0]
        except Exception as e:
            self.logger.error(f"OpenAI Moderation Error: {e}")
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return

        # Rate limiter per guild: 10 analyses/min (Free) or 100 analyses/min (Premium)
        is_premium = await self.bot.db.is_guild_premium(message.guild, self.bot)
        max_analyses_per_min = 100 if is_premium else 10

        now = time.time()
        recent_analyses = [t for t in self._guild_minute_analyses[message.guild.id] if now - t < 60.0]
        self._guild_minute_analyses[message.guild.id] = recent_analyses

        if len(recent_analyses) >= max_analyses_per_min:
            # Reached rate limit for this minute. Skip to conserve quota without spending needlessly.
            return

        self._guild_minute_analyses[message.guild.id].append(now)

        # Check if enabled
        config = await self.bot.db.fetch(
            "SELECT moderation_channel_id FROM ai_settings WHERE guild_id = ?",
            message.guild.id
        )
        if not config or not config[0]:
            return

        mod_channel_id = config[0]
        mod_channel = message.guild.get_channel(mod_channel_id)
        if not mod_channel:
            return

        # Track conversation rolling window (last 10 messages)
        cid = message.channel.id
        if cid not in self.message_windows:
            self.message_windows[cid] = []
        self.message_windows[cid].append({
            'author': message.author.display_name,
            'content': message.content[:150]
        })
        if len(self.message_windows[cid]) > 10:
            self.message_windows[cid].pop(0)

        # Trigger conflict analysis if a toxicity keyword is used
        content_lower = message.content.lower()
        if any(kw in content_lower for kw in TOXICITY_KEYWORDS):
            self.bot.loop.create_task(self.check_conversation_tension(message, mod_channel))

        # 1. URL SCANNING (Safe Browsing)
        urls = re.findall(r'(https?://[^\s]+)', message.content)
        if urls and self.safebrowsing_key:
            threats = await self.check_urls(urls)
            if threats:
                # Malicious URL found! Take immediate action.
                try:
                    await message.delete()
                    deleted = True
                except:
                    deleted = False
                
                # Warn the user
                try:
                    await message.channel.send(f"⚠️ {message.author.mention}, you sent a malicious link. The message has been deleted.", delete_after=10)
                except:
                    pass

                # Alert the admins
                embed = discord.Embed(
                    title="🚨 MALICIOUS LINK DETECTED 🚨",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now()
                )
                embed.add_field(name="User", value=f"{message.author.mention} ({message.author.id})", inline=True)
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                embed.add_field(name="Action Taken", value="Message Deleted" if deleted else "Failed to Delete", inline=True)
                
                threat_info = "\\n".join([f"**URL:** `{t.get('threat', {}).get('url')}`\\n**Type:** {t.get('threatType')}" for t in threats])
                embed.add_field(name="Threat Details", value=threat_info[:1024], inline=False)
                
                await mod_channel.send(embed=embed)
                return # Stop processing further if it's a malicious link

        # 2. TEXT MODERATION (OpenAI)
        if self.openai_key:
            content_lower = message.content.lower()
            # Pre-filter to save requests
            if any(kw in content_lower for kw in TOXICITY_KEYWORDS):
                
                content_hash = str(hash(message.content[:500]))
                if content_hash in self._recent_cache:
                    return

                result = await self.check_text(message.content[:2000]) # Limit to 2000 chars
                if result:
                    self._recent_cache[content_hash] = result
                    if len(self._recent_cache) > self._cache_max:
                        keys = list(self._recent_cache.keys())
                        for k in keys[:50]: del self._recent_cache[k]

                    if result.get("flagged", False):
                        categories = result.get("categories", {})
                        scores = result.get("category_scores", {})
                        
                        # Get all flagged categories
                        flagged_cats = [k for k, v in categories.items() if v]
                        cat_str = ", ".join(flagged_cats).replace("-", " ").title()
                        highest_score = max([scores.get(c, 0) for c in flagged_cats]) if flagged_cats else 0
                        
                        severity = "🔴 SEVERE" if highest_score >= 0.9 else "🟠 HIGH" if highest_score >= 0.7 else "🟡 MODERATE"

                        action_taken = "Alert Sent"
                        is_severe = highest_score >= 0.85 or "severe-toxicity" in flagged_cats
                        is_admin_or_mod = message.author.guild_permissions.administrator or message.author.guild_permissions.manage_messages
                        
                        if is_severe and not is_admin_or_mod:
                            try:
                                await message.delete()
                                action_taken = "Message Deleted"
                            except Exception:
                                pass
                                
                            try:
                                await message.author.timeout(
                                    datetime.timedelta(minutes=10),
                                    reason=f"Toxicity detected by AI automod: {cat_str}"
                                )
                                action_taken += " & User Timed Out (10m)"
                                try:
                                    await message.channel.send(
                                        f"🔇 {message.author.mention} ha sido silenciado temporalmente por 10 minutos debido a comportamiento tóxico extremo.",
                                        delete_after=10
                                    )
                                except Exception:
                                    pass
                            except Exception as te:
                                self.logger.error(f"Failed to timeout toxic member: {te}")

                        embed = discord.Embed(
                            title=f"{severity} Toxicity Detected",
                            color=discord.Color.red() if highest_score >= 0.8 else discord.Color.orange(),
                            timestamp=datetime.datetime.now()
                        )
                        embed.add_field(name="User", value=f"{message.author.mention} ({message.author.id})", inline=True)
                        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                        embed.add_field(name="Confidence", value=f"`{highest_score:.2f}` / 1.0", inline=True)
                        
                        embed.add_field(name="Categories", value=f"**{cat_str}**", inline=False)
                        embed.add_field(name="Action Taken", value=f"**{action_taken}**", inline=True)
                        embed.add_field(name="Content", value=message.content[:1024], inline=False)
                        if "Deleted" not in action_taken:
                            embed.add_field(name="Message Link", value=f"[Jump to message]({message.jump_url})", inline=False)

                        await mod_channel.send(embed=embed)
                        self.logger.info(f"🤖 OpenAI Toxicity alert: {message.author} ({cat_str}) - Action: {action_taken}")

    async def check_conversation_tension(self, message, mod_channel):
        """Analyzes a sliding window of recent messages in a channel to detect rising toxic arguments."""
        cid = message.channel.id
        now = datetime.datetime.now()
        
        # 5-minute cooldown per channel to prevent API spamming
        last = self.last_alert.get(cid)
        if last and (now - last).total_seconds() < 300:
            return

        chatbot = self.bot.get_cog('Chatbot')
        if not chatbot or not hasattr(chatbot, 'ai'):
            return

        window = self.message_windows.get(cid, [])
        if len(window) < 3:
            return # need at least a few messages to analyze dynamics

        conversation = "\n".join([f"[{m['author']}]: {m['content']}" for m in window])
        
        prompt = (
            "Analyze the following recent chat messages in a Discord channel. "
            "Evaluate if there is an active heated argument, high tension, or passive-aggressive toxicity developing between users. "
            "Provide your assessment in a short JSON structure with keys:\n"
            "- 'argument_detected': boolean\n"
            "- 'tension_score': number (0 to 10 scale)\n"
            "- 'dispute_summary': brief summary in Spanish of what they are arguing about (or empty if no argument)\n"
            "- 'users_involved': list of display names involved\n\n"
            "Output ONLY the raw JSON block without formatting, markdown, or commentary.\n\n"
            f"CONVERSATION:\n{conversation}"
        )

        try:
            msgs = [{"role": "user", "content": prompt}]
            response, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False)
            
            clean_resp = response.strip()
            if clean_resp.startswith("```json"):
                clean_resp = clean_resp[7:]
            if clean_resp.endswith("```"):
                clean_resp = clean_resp[:-3]
            clean_resp = clean_resp.strip()
            
            data = json.loads(clean_resp)
            
            if data.get('argument_detected', False) and data.get('tension_score', 0) >= 6:
                self.last_alert[cid] = now
                
                embed = discord.Embed(
                    title="⚠️ AI Conflict Alert: Heated Argument in Progress",
                    color=discord.Color.from_rgb(255, 159, 67),
                    timestamp=datetime.datetime.now()
                )
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                embed.add_field(name="Tension Level", value=f"🔥 **{data.get('tension_score')}/10**", inline=True)
                
                users = ", ".join(data.get('users_involved', [])) or "Desconocidos"
                embed.add_field(name="Users Involved", value=users, inline=True)
                
                summary = data.get('dispute_summary', 'Disputa general.')
                embed.add_field(name="Argument Summary", value=f"*{summary}*", inline=False)
                
                embed.add_field(name="Recent Context", value=f"```\n{conversation[:900]}\n```", inline=False)
                embed.add_field(name="Message Link", value=f"[Jump to context]({message.jump_url})", inline=False)
                embed.set_footer(text="DaBot Security Sentiments Engine")
                
                await mod_channel.send(embed=embed)
                self.logger.info(f"🛡️ Conflict Alert sent for channel {cid}. Tension: {data.get('tension_score')}/10")
        except Exception as e:
            self.logger.error(f"Failed to check conversation tension: {e}")

async def setup(bot):
    await bot.add_cog(AIModeration(bot))
