import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
from datetime import datetime, timedelta
import re
from deep_translator import GoogleTranslator

log = logging.getLogger('Dabot.UserInstall')

LANGUAGES = {
    'es': 'Spanish',
    'en': 'English',
    'fr': 'French',
    'de': 'German',
    'pt': 'Portuguese',
    'it': 'Italian',
    'ja': 'Japanese',
    'ko': 'Korean',
    'zh-CN': 'Chinese (Simplified)',
    'ru': 'Russian',
    'ar': 'Arabic'
}

def parse_time(time_str: str) -> int:
    """Parses a time string like '10m', '1h', '2h30m' into seconds."""
    time_str = time_str.lower()
    total_seconds = 0
    pattern = re.compile(r'(\d+)([dhms])')
    matches = pattern.findall(time_str)
    
    if not matches:
        return 0
        
    for value, unit in matches:
        value = int(value)
        if unit == 'd':
            total_seconds += value * 86400
        elif unit == 'h':
            total_seconds += value * 3600
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 's':
            total_seconds += value
            
    return total_seconds

class UserInstall(commands.GroupCog, group_name="user", group_description="Utilidades personales (también en MD)"):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()
        
    def cog_unload(self):
        self.check_reminders.cancel()
        
    @tasks.loop(seconds=30)
    async def check_reminders(self):
        try:
            now = datetime.utcnow().isoformat()
            reminders = await self.bot.db.fetch_all(
                "SELECT id, user_id, message FROM reminders WHERE remind_at <= ? AND delivered = 0", 
                now
            )
            for r_id, user_id, message in reminders:
                try:
                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                    if user:
                        embed = discord.Embed(
                            title="⏰ ¡Recordatorio!", 
                            description=message, 
                            color=discord.Color.brand_green()
                        )
                        await user.send(embed=embed)
                except Exception as e:
                    log.error(f"Failed to DM user {user_id} for reminder {r_id}: {e}")
                
                await self.bot.db.execute(
                    "UPDATE reminders SET delivered = 1 WHERE id = ?", 
                    r_id
                )
        except Exception as e:
            log.error(f"Error in check_reminders task: {e}")
            
    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="translate", description="Traduce texto (también funciona en MD)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def traducir(self, interaction: discord.Interaction, text: str, to_language: str):
        if to_language not in LANGUAGES:
            await interaction.response.send_message(f"❌ Código de idioma inválido. Usa uno de estos: {', '.join(LANGUAGES.keys())}", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            translator = GoogleTranslator(source='auto', target=to_language)
            translation = translator.translate(text)
            embed = discord.Embed(title="Traducción", color=discord.Color.blue())
            embed.add_field(name="Original", value=text[:1024], inline=False)
            embed.add_field(name=f"Traducción ({LANGUAGES[to_language]})", value=(translation or "—")[:1024], inline=False)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            log.error(f"Translation error: {e}")
            await interaction.followup.send("❌ Hubo un error al traducir el texto.", ephemeral=True)

    @traducir.autocomplete('to_language')
    async def traducir_autocomplete(self, interaction: discord.Interaction, current: str):
        choices = []
        for code, name in LANGUAGES.items():
            if current.lower() in code.lower() or current.lower() in name.lower():
                choices.append(app_commands.Choice(name=f"{name} ({code})", value=code))
        return choices[:25]

    @app_commands.command(name="info", description="Muestra información tuya o de otro usuario")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def userinfo(self, interaction: discord.Interaction, user: discord.User = None):
        user = user or interaction.user
        
        embed = discord.Embed(title=f"Información de {user.name}", color=discord.Color.purple())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=user.id, inline=True)
        embed.add_field(name="Bot?", value="Sí" if user.bot else "No", inline=True)
        embed.add_field(name="Cuenta Creada", value=f"<t:{int(user.created_at.timestamp())}:F>", inline=False)
        
        if interaction.guild:
            member = interaction.guild.get_member(user.id)
            if member:
                embed.add_field(name="Se unió al servidor", value=f"<t:{int(member.joined_at.timestamp())}:F>", inline=False)
                roles = [role.mention for role in reversed(member.roles[1:])]
                if roles:
                    embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles)[:1024], inline=False)
                    
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Muestra el avatar en tamaño completo")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def avatar(self, interaction: discord.Interaction, user: discord.User = None):
        user = user or interaction.user
        
        embed = discord.Embed(title=f"Avatar de {user.name}", color=discord.Color.magenta())
        
        # Check if in guild to get server avatar
        if interaction.guild:
            member = interaction.guild.get_member(user.id)
            if member and member.guild_avatar:
                embed.description = f"[Global Avatar]({user.avatar.url if user.avatar else user.default_avatar.url}) | [Server Avatar]({member.guild_avatar.url})"
                embed.set_image(url=member.guild_avatar.url)
                await interaction.response.send_message(embed=embed)
                return
                
        embed.description = f"[Global Avatar]({user.display_avatar.url})"
        embed.set_image(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remind", description="Establece un recordatorio personal (ej. 10m, 1h, 2h30m)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        seconds = parse_time(time)
        if seconds <= 0:
            await interaction.response.send_message("❌ Formato de tiempo inválido. Usa formatos como '10m', '1h', '1d'.", ephemeral=True)
            return
            
        if seconds > 31536000: # 1 year
            await interaction.response.send_message("❌ El recordatorio no puede ser para más de un año.", ephemeral=True)
            return

        active_reminders = await self.bot.db.fetch_all(
            "SELECT COUNT(*) FROM reminders WHERE user_id = ? AND delivered = 0", 
            interaction.user.id
        )
        if active_reminders and active_reminders[0][0] >= 25:
            await interaction.response.send_message("❌ Has alcanzado el límite de 25 recordatorios activos.", ephemeral=True)
            return

        remind_time = datetime.utcnow() + timedelta(seconds=seconds)
        now_time = datetime.utcnow()
        
        guild_id = interaction.guild_id if interaction.guild else None
        channel_id = interaction.channel_id if interaction.channel else None

        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, channel_id, guild_id, message, remind_at, created_at, delivered) VALUES (?, ?, ?, ?, ?, ?, 0)",
            interaction.user.id, channel_id, guild_id, message, remind_time.isoformat(), now_time.isoformat()
        )
        
        await interaction.response.send_message(f"✅ Te recordaré: **{message}** en <t:{int(remind_time.timestamp())}:R>.", ephemeral=True)

    @app_commands.command(name="color", description="Previsualiza un color a partir de su código hexadecimal")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def colorhex(self, interaction: discord.Interaction, hex_code: str):
        hex_code = hex_code.lstrip('#')
        
        if not re.match(r'^[0-9a-fA-F]{6}$', hex_code):
            await interaction.response.send_message("❌ Código hexadecimal inválido. Usa un formato de 6 caracteres como 'FF0000'.", ephemeral=True)
            return
            
        r = int(hex_code[0:2], 16)
        g = int(hex_code[2:4], 16)
        b = int(hex_code[4:6], 16)
        
        # Calculate HSL
        r_norm, g_norm, b_norm = r / 255.0, g / 255.0, b / 255.0
        cmax = max(r_norm, g_norm, b_norm)
        cmin = min(r_norm, g_norm, b_norm)
        delta = cmax - cmin
        
        l = (cmax + cmin) / 2
        
        if delta == 0:
            h = 0
            s = 0
        else:
            if cmax == r_norm:
                h = 60 * (((g_norm - b_norm) / delta) % 6)
            elif cmax == g_norm:
                h = 60 * (((b_norm - r_norm) / delta) + 2)
            else:
                h = 60 * (((r_norm - g_norm) / delta) + 4)
                
            s = delta / (1 - abs(2 * l - 1))
            
        h, s, l = round(h), round(s * 100), round(l * 100)
        
        embed = discord.Embed(title=f"Color #{hex_code.upper()}", color=discord.Color.from_rgb(r, g, b))
        embed.add_field(name="HEX", value=f"#{hex_code.upper()}", inline=True)
        embed.add_field(name="RGB", value=f"{r}, {g}, {b}", inline=True)
        embed.add_field(name="HSL", value=f"{h}°, {s}%, {l}%", inline=True)
        
        # Small hack to show a solid block of color using a generated image URL via a placeholder service
        # Alternatively, the embed color itself shows it
        embed.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_code}/100x100")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(UserInstall(bot))
