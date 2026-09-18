import logging
import discord
from discord.ext import commands
from discord import app_commands
import os
import urllib.parse
import asyncio

class TTS(commands.Cog):
    """Voice Text-to-Speech (TTS) Reader with dynamic music pausing/resuming."""
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.TTS')
        self.tts_queues = {}     # guild_id -> list of strings
        self.speaking = {}       # guild_id -> bool
        self.paused_music = {}   # guild_id -> bool

    @commands.Cog.listener()
    async def on_ready(self):
        # Create table to persist TTS toggle channels
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS tts_channels (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER
            )
        """)
        self.logger.info("TTS Cog loaded and tables checked.")

    def get_queue(self, guild_id):
        if guild_id not in self.tts_queues:
            self.tts_queues[guild_id] = []
        return self.tts_queues[guild_id]

    # ── Slash Commands ─────────────────────────────────────────────────────

    @app_commands.command(name="ttsjoin", description="🔊 Joins your active voice channel to start reading chat.")
    async def ttsjoin(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You are not connected to a voice channel.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        await interaction.response.defer()
        try:
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(channel)
            else:
                await channel.connect()
            await interaction.followup.send(f"✅ Joined **{channel.name}** and ready to speak! Use `/tts` to link a chat channel.")
        except Exception as e:
            self.logger.error("ttsjoin failed: %s", e, exc_info=True)
            await interaction.followup.send("❌ No pude unirme al canal de voz. Revisa mis permisos.", ephemeral=True)

    @app_commands.command(name="ttsleave", description="👋 Leaves the voice channel and stops reading chat.")
    async def ttsleave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client if interaction.guild else None
        if not vc:
            await interaction.response.send_message("❌ I am not connected to any voice channel.", ephemeral=True)
            return

        await interaction.response.defer()
        gid = interaction.guild.id
        self.tts_queues[gid] = []
        self.speaking[gid] = False
        self.paused_music[gid] = False
        try:
            await vc.disconnect()
        except Exception:
            pass
        await interaction.followup.send("👋 Disconnected from voice channel and cleared TTS queue.")

    @app_commands.command(name="tts", description="💬 Toggles TTS chat reading in the current channel.")
    @app_commands.describe(action="Choose whether to enable or disable chat reading.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Enable (Read chat in this channel)", value="enable"),
        app_commands.Choice(name="Disable (Stop reading chat)", value="disable")
    ])
    async def tts_toggle(self, interaction: discord.Interaction, action: str):
        gid = interaction.guild.id
        cid = interaction.channel.id

        if action == "enable":
            await self.bot.db.execute("INSERT OR REPLACE INTO tts_channels (guild_id, channel_id) VALUES (?, ?)", gid, cid)
            await interaction.response.send_message(f"🗣️ TTS Enabled! I will now read all messages sent in {interaction.channel.mention}.")
        else:
            await self.bot.db.execute("DELETE FROM tts_channels WHERE guild_id = ?", gid)
            await interaction.response.send_message("🔇 TTS Disabled. Message reading has been stopped.")

    # ── TTS Core Engine & Queue Processing ─────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Check if this channel has TTS enabled
        db_channel = await self.bot.db.fetch("SELECT channel_id FROM tts_channels WHERE guild_id = ?", message.guild.id)
        if not db_channel or db_channel[0] != message.channel.id:
            return

        # Check if connected to voice
        vc = message.guild.voice_client
        if not vc or not vc.is_connected():
            return

        # Skip attachments or blank messages
        content = message.clean_content.strip()
        if not content:
            return

        # Cap length to prevent spam abuses
        if len(content) > 150:
            content = content[:147] + "..."

        # Format: Name says text
        text_to_speak = f"{message.author.display_name} dice: {content}"
        
        # Add to queue
        queue = self.get_queue(message.guild.id)
        queue.append(text_to_speak)
        
        # Process
        self.bot.loop.create_task(self.process_tts_queue(message.guild))

    async def process_tts_queue(self, guild):
        gid = guild.id
        queue = self.get_queue(gid)
        
        if self.speaking.get(gid, False) or not queue:
            return

        self.speaking[gid] = True
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            queue.clear()
            self.speaking[gid] = False
            return

        text = queue.pop(0)
        
        # Detect server language for correct pronunciation
        lang = self.bot.config.get(gid, 'language') or 'es'
        
        # Generate Google Translate's free speech endpoint URL
        encoded_text = urllib.parse.quote(text)
        tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl={lang}&client=tw-ob&q={encoded_text}"

        # Setup connection options to prevent stream cutting
        ffmpeg_options = {
            'options': '-vn',
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
        }

        try:
            # Handle music pause if something is playing
            if vc.is_playing() and not self.paused_music.get(gid, False):
                self.paused_music[gid] = True
                vc.pause()
                await asyncio.sleep(0.2) # smooth transition

            source = discord.FFmpegPCMAudio(tts_url, **ffmpeg_options)
            
            def after_playback(error):
                if error:
                    self.logger.error(f"TTS playback error: {error}")
                self.speaking[gid] = False
                # Trigger next queue item
                self.bot.loop.create_task(self.next_tts(guild))

            vc.play(source, after=after_playback)

        except Exception as e:
            self.logger.error(f"Failed to play TTS: {e}")
            self.speaking[gid] = False
            self.bot.loop.create_task(self.next_tts(guild))

    async def next_tts(self, guild):
        gid = guild.id
        queue = self.get_queue(gid)
        vc = guild.voice_client

        if queue:
            # Continue speaking
            await self.process_tts_queue(guild)
        else:
            # Finished speaking everything. Resume music if it was paused
            if vc and vc.is_connected() and self.paused_music.get(gid, False):
                self.paused_music[gid] = False
                if vc.is_paused():
                    vc.resume()

async def setup(bot):
    # TTS removed: this VPS cannot run a stable ffmpeg/gTTS pipeline.
    return
