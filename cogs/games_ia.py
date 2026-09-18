import logging
import discord
from discord.ext import commands
from discord import app_commands
import os
import aiohttp
import io
import urllib.parse
import json
import asyncio
from PIL import Image, ImageDraw, ImageFont

class GamesIA(commands.Cog):
    """Premium AI-powered entertainment: Interactive RPG Adventure and Custom Meme Generator."""
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.GamesIA')
        self.active_adventures = {} # user_id -> dict state
        
    # ── Option 2: AI Meme Generator (/meme_ia) ─────────────────────────────

    async def meme_ia(self, interaction: discord.Interaction, tema: str):
        if not await self.bot.db.is_guild_premium(interaction.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await interaction.response.send_message(deny_text(guild_lang(self.bot, interaction.guild_id)), ephemeral=True)
            return

        await interaction.response.defer()
        
        chatbot = self.bot.get_cog('Chatbot')
        if not chatbot or not hasattr(chatbot, 'ai'):
            await interaction.followup.send("❌ AI service unavailable.")
            return

        # 1. Ask AI to draft background prompt and text captions
        prompt = (
            f"You are a master meme creator. Draft a hilarious meme based on the topic: '{tema}'. "
            f"Provide your design as a raw JSON structure with exactly two fields:\n"
            f"- 'bg_prompt': A descriptive image generation prompt for /imagine (e.g., 'a shocked cat wearing glasses looking at a computer screen, cartoon style'). Must be in English.\n"
            f"- 'caption': A funny caption or two-line joke to write on the meme in Spanish, in all-caps (e.g. 'CUANDO LOGRAS RESOLVER EL BUG / PERO ROMPES OTRAS TRES COSAS'). Use '/' to separate top and bottom text.\n\n"
            f"Output ONLY the raw JSON block without markdown, backticks, or other text."
        )

        try:
            msgs = [{"role": "user", "content": prompt}]
            response, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False, is_premium=True)
            
            # Clean response if LLM added backticks
            clean_resp = response.strip()
            if clean_resp.startswith("```json"):
                clean_resp = clean_resp[7:]
            if clean_resp.endswith("```"):
                clean_resp = clean_resp[:-3]
            clean_resp = clean_resp.strip()
            
            data = json.loads(clean_resp)
            bg_prompt = data.get('bg_prompt', f"a funny meme background about {tema}")
            caption = data.get('caption', "MEME / IA")
        except Exception as e:
            self.logger.error(f"Failed to draft meme json: {e}")
            bg_prompt = f"a funny cartoon representing {tema}"
            caption = f"CUANDO INTENTAS HACER UN MEME / PERO LA IA DA ERROR"

        # 2. Generate Image via Pollinations
        try:
            enhanced_prompt = f"{bg_prompt}, high resolution meme template, clear contrast, highly detailed"
            encoded = urllib.parse.quote(enhanced_prompt)
            image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=800&height=800&nologo=true&private=true"
            
            async with self.bot.session.get(image_url, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                if resp.status != 200:
                    raise Exception("Image generation failed")
                img_data = await resp.read()
        except Exception as e:
            self.logger.error(f"Image download failed: {e}")
            await interaction.followup.send("❌ Error al generar la imagen del meme.")
            return

        # 3. Draw text using Pillow
        try:
            img = Image.open(io.BytesIO(img_data)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            width, height = img.size

            # Load a bold font, fallback to default
            font = None
            font_size = 48
            # Try to load common bold system fonts
            for font_name in ["arial.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"]:
                try:
                    font = ImageFont.truetype(font_name, font_size)
                    break
                except:
                    pass
            if not font:
                font = ImageFont.load_default()

            # Split caption
            parts = [p.strip() for p in caption.split('/')]
            top_text = parts[0] if parts else ""
            bottom_text = parts[1] if len(parts) > 1 else ""

            def draw_meme_text(text, position_y):
                # Text wrapping or scaling
                if not text: return
                nonlocal font_size, font
                
                # Check text dimensions
                # Draw outline
                outline_range = 3
                for x_offset in range(-outline_range, outline_range + 1):
                    for y_offset in range(-outline_range, outline_range + 1):
                        if abs(x_offset) + abs(y_offset) > 0:
                            draw.text((width/2 + x_offset, position_y + y_offset), text, font=font, fill="black", anchor="mm")
                
                draw.text((width/2, position_y), text, font=font, fill="white", anchor="mm")

            # Draw top text (near y=70) and bottom text (near y=height-70)
            draw_meme_text(top_text, 60)
            draw_meme_text(bottom_text, height - 70)

            # Save edited image
            output_buffer = io.BytesIO()
            img.save(output_buffer, format="PNG")
            output_buffer.seek(0)
            
            file = discord.File(output_buffer, filename="meme.png")
            await interaction.followup.send(file=file)
            
        except Exception as e:
            self.logger.error(f"Pillow editing failed: {e}")
            await interaction.followup.send("❌ Error al procesar y maquetar el texto sobre la imagen del meme.")

    # ── Option 1: AI RPG Aventura (/aventura) ──────────────────────────────

    async def aventura(self, interaction: discord.Interaction, tematica: str):
        if not await self.bot.db.is_guild_premium(interaction.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await interaction.response.send_message(deny_text(guild_lang(self.bot, interaction.guild_id)), ephemeral=True)
            return

        await interaction.response.defer()
        
        user_id = interaction.user.id
        chatbot = self.bot.get_cog('Chatbot')
        if not chatbot or not hasattr(chatbot, 'ai'):
            await interaction.followup.send("❌ AI service unavailable.")
            return

        # Initialize adventure state
        self.active_adventures[user_id] = {
            "tematica": tematica,
            "chapter": 1,
            "history": []
        }

        await self.send_adventure_chapter(interaction, user_id)

    async def send_adventure_chapter(self, interaction_or_res, user_id):
        state = self.active_adventures[user_id]
        chatbot = self.bot.get_cog('Chatbot')
        
        history_context = "\n".join(state["history"])
        prompt = (
            f"You are the Game Master (DM) for an interactive choose-your-own-adventure game in a '{state['tematica']}' setting. "
            f"This is Chapter {state['chapter']}. "
            f"Based on the choices made so far:\n{history_context}\n\n"
            f"Generate: "
            f"1. A thrilling, narrative-heavy description of the current scene (max 150 words) in Spanish.\n"
            f"2. Three exciting and dangerous options labeled exactly 'Opción A', 'Opción B', 'Opción C' in Spanish.\n"
            f"3. A detailed image prompt in English for /imagine (Pollinations AI) describing the visual scene (e.g., 'a dark cinematic wizard tower surrounded by lightning, fantasy art').\n\n"
            f"Provide your answer ONLY in the following raw JSON format, without backticks or markdown:\n"
            f"{{\n"
            f"  \"narrativa\": \"tu narrativa en español\",\n"
            f"  \"opcion_a\": \"texto para la opcion A\",\n"
            f"  \"opcion_b\": \"texto para la opcion B\",\n"
            f"  \"opcion_c\": \"texto para la opcion C\",\n"
            f"  \"img_prompt\": \"your English image prompt\"\n"
            f"}}"
        )

        try:
            msgs = [{"role": "user", "content": prompt}]
            response, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False, is_premium=True)
            
            clean_resp = response.strip()
            if clean_resp.startswith("```json"):
                clean_resp = clean_resp[7:]
            if clean_resp.endswith("```"):
                clean_resp = clean_resp[:-3]
            clean_resp = clean_resp.strip()
            
            data = json.loads(clean_resp)
        except Exception as e:
            self.logger.error(f"Failed to generate adventure json: {e}")
            # Fallback
            data = {
                "narrativa": "Te adentras en lo desconocido. La atmósfera es tensa y no ves salida clara a tu alrededor.",
                "opcion_a": "Avanzar con cautela",
                "opcion_b": "Buscar refugio",
                "opcion_c": "Gritar por ayuda",
                "img_prompt": f"a mysterious dark landscape representing {state['tematica']}"
            }

        # Generate Illustration
        img_prompt = data.get('img_prompt', "a mystical dark adventure scene")
        encoded_prompt = urllib.parse.quote(f"{img_prompt}, 8k resolution, cinematic lighting, masterpiece fantasy illustration")
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=800&height=500&nologo=true&private=true"

        embed = discord.Embed(
            title=f"⚔️ Aventura IA — Capítulo {state['chapter']}",
            description=f"{data.get('narrativa')}\n\n"
                        f"**🔴 A:** {data.get('opcion_a')}\n"
                        f"**🔵 B:** {data.get('opcion_b')}\n"
                        f"**🟢 C:** {data.get('opcion_c')}",
            color=discord.Color.from_rgb(9, 132, 227)
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Partida de {self.bot.get_user(user_id).display_name} • DaBot GM Engine")

        view = AdventureView(self, user_id, data.get('opcion_a'), data.get('opcion_b'), data.get('opcion_c'))

        if isinstance(interaction_or_res, discord.Interaction):
            if interaction_or_res.response.is_done():
                await interaction_or_res.followup.send(embed=embed, view=view)
            else:
                await interaction_or_res.response.send_message(embed=embed, view=view)
        else:
            await interaction_or_res.edit_original_response(embed=embed, view=view)


class AdventureView(discord.ui.View):
    def __init__(self, cog, user_id, op_a, op_b, op_c):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.op_a = op_a
        self.op_b = op_b
        self.op_c = op_c

    async def handle_choice(self, interaction: discord.Interaction, choice_letter, choice_text):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Esta no es tu aventura. Escribe `/aventura` para iniciar la tuya.", ephemeral=True)
            return

        state = self.cog.active_adventures[self.user_id]
        state["chapter"] += 1
        state["history"].append(f"Capítulo {state['chapter']-1}: El jugador eligió la opción {choice_letter}: {choice_text}.")
        
        await interaction.response.defer()
        
        # Edit current buttons to disabled
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(view=self)
        
        # Load next chapter
        await self.cog.send_adventure_chapter(interaction, self.user_id)

    @discord.ui.button(label="Opción A", style=discord.ButtonStyle.danger)
    async def button_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "A", self.op_a)

    @discord.ui.button(label="Opción B", style=discord.ButtonStyle.primary)
    async def button_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "B", self.op_b)

    @discord.ui.button(label="Opción C", style=discord.ButtonStyle.success)
    async def button_c(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "C", self.op_c)

    @discord.ui.button(label="Terminar Partida", style=discord.ButtonStyle.secondary)
    async def button_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Esta no es tu aventura.", ephemeral=True)
            return
            
        self.cog.active_adventures.pop(self.user_id, None)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("🏁 Partida terminada. ¡Gracias por jugar con DaBot!")

async def setup(bot):
    await bot.add_cog(GamesIA(bot))
