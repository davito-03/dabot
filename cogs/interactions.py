import logging
import discord
from discord.ext import commands
import random
from discord import app_commands
from typing import List

class Interactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')
        self.session = bot.session  # Use shared aiohttp session

        # Define NSFW categories and their configs
        # Define NSFW categories and their configs
        self.nsfw_categories = {
            # Waifu.pics replacers
            "waifu": {
                "source": "waifu_im", 
                "api_key": "waifu",
                "action": "{user} shares a waifu picture with {target}.",
                "solo": "{user} is looking at a waifu picture."
            },
            "neko": {
                "source": "nekobot", 
                "api_key": "hneko",
                "action": "{user} shares a neko picture with {target}.",
                "solo": "{user} is looking at a neko picture."
            },
            "trap": {
                "source": "nekobot", 
                "api_key": "futa",
                "action": "{user} shares a trap picture with {target}.",
                "solo": "{user} is looking at a trap picture."
            },
            "blowjob": {
                "source": "nekobot", 
                "action": "{user} gives {target} a blowjob.",
                "solo": "{user} is looking at a blowjob picture."
            },
            
            # Nekobot
            "hentai": {
                "source": "nekobot",
                "action": "{user} shares a hot hentai picture with {target}.",
                "solo": "{user} is looking at a hentai picture."
            },
            "ass": {
                "source": "nekobot",
                "action": "{user} shows their ass to {target}!",
                "solo": "{user} is looking at an ass picture."
            },
            "pussy": {
                "source": "nekobot",
                "action": "{user} shows their pussy to {target}!",
                "solo": "{user} is looking at a pussy picture."
            },
            "thigh": {
                "source": "nekobot",
                "action": "{user} shares a thigh picture with {target}.",
                "solo": "{user} is looking at a thigh picture."
            },
            "hthigh": {
                "source": "nekobot",
                "action": "{user} shares a hot thigh picture with {target}.",
                "solo": "{user} is looking at a hot thigh picture."
            },
            "boobs": {
                "source": "nekobot",
                "action": "{user} shows their boobs to {target}!",
                "solo": "{user} is looking at a boobs picture."
            },
            "hboobs": {
                "source": "nekobot",
                "action": "{user} shows their boobs to {target}!",
                "solo": "{user} is looking at a hot boobs picture."
            },
            "paizuri": {
                "source": "nekobot", 
                "action": "{user} uses their chest on {target}.",
                "solo": "{user} is looking at a paizuri picture."
            },
            "pantsu": {
                "source": "nekobot",
                "action": "{user} shows their pantsu to {target}!",
                "solo": "{user} is looking at a pantsu picture."
            },
            "feet": {
                "source": "nekobot", 
                "action": "{user} worships {target}'s feet.",
                "solo": "{user} is looking at a feet picture."
            },
            "anal": {
                "source": "nekobot", 
                "action": "{user} fucks {target} in the ass.",
                "solo": "{user} is looking at an anal picture."
            },
            "hanal": {
                "source": "nekobot", 
                "api_key": "hentai_anal", 
                "action": "{user} fucks {target} in the ass.",
                "solo": "{user} is looking at an anal picture."
            },
            "futa": {
                "source": "nekobot",
                "action": "{user} shares a futa picture with {target}.",
                "solo": "{user} is looking at a futa picture."
            },
            "yaoi": {
                "source": "nekobot", 
                "action": "{user} engages in yaoi with {target}.",
                "solo": "{user} is looking at a yaoi picture."
            },
            "yuri": {
                "source": "nekobot", 
                "api_key": "hyuri", 
                "action": "{user} engages in yuri with {target}.",
                "solo": "{user} is looking at a yuri picture."
            },
            "tentacle": {
                "source": "nekobot", 
                "action": "{user} sends tentacles after {target}!",
                "solo": "{user} is looking at a tentacle picture."
            },
            "gonewild": {
                "source": "nekobot",
                "action": "{user} shares a gonewild picture with {target}.",
                "solo": "{user} is looking at a gonewild picture."
            },
            "gif": {
                "source": "nekobot", 
                "api_key": "pgif",
                "action": "{user} shares a hot GIF with {target}.",
                "solo": "{user} is looking at a hot GIF."
            },
            "kemonomimi": {
                "source": "nekobot",
                "action": "{user} shares a kemonomimi picture with {target}.",
                "solo": "{user} is looking at a kemonomimi picture."
            },
            "kanna": {
                "source": "nekobot",
                "action": "{user} shares a Kanna picture with {target}.",
                "solo": "{user} is looking at a Kanna picture."
            },
            "bukkake": {
                "source": "nekobot", 
                "api_key": "nakadashi", 
                "action": "{user} creampies {target}.",
                "solo": "{user} is looking at a creampie picture."
            },
            "creampie": {
                "source": "nekobot", 
                "api_key": "nakadashi", 
                "action": "{user} creampies {target}.",
                "solo": "{user} is looking at a creampie picture."
            },
            "kitsune": {
                "source": "nekobot", 
                "api_key": "hkitsune",
                "action": "{user} shares a kitsune picture with {target}.",
                "solo": "{user} is looking at a kitsune picture."
            },
            "swimsuit": {
                "source": "nekobot",
                "action": "{user} shows their swimsuit to {target}.",
                "solo": "{user} is looking at a swimsuit picture."
            },
            "hass": {
                "source": "nekobot",
                "action": "{user} shows their ass to {target}!",
                "solo": "{user} is looking at a hot ass picture."
            },
            "hmidriff": {
                "source": "nekobot",
                "action": "{user} shares a midriff picture with {target}.",
                "solo": "{user} is looking at a midriff picture."
            },
            "pee": {
                "source": "nekobot", 
                "action": "{user} pees on {target}?!",
                "solo": "{user} is looking at a pee picture."
            },
            "4k": {
                "source": "nekobot",
                "action": "{user} shares a 4K picture with {target}.",
                "solo": "{user} is looking at a 4K picture."
            },
            "lewd": {
                "source": "nekobot", 
                "api_key": "lewdneko",
                "action": "{user} shares a lewd picture with {target}.",
                "solo": "{user} is looking at a lewd picture."
            },
        }
        
        # Define SFW Categories
        self.sfw_categories = {
            "hug": {"action": "{user} hugs {target}!", "solo": "{user} hugs themselves... aww."},
            "kiss": {"action": "{user} kisses {target}!", "solo": "{user} kisses... the air?"},
            "pat": {"action": "{user} pats {target}.", "solo": "{user} pats themselves."},
            "slap": {"action": "{user} slaps {target}!", "solo": "{user} slaps themselves. Ouch!"},
            "cuddle": {"action": "{user} cuddles {target}.", "solo": "{user} cuddles with a pillow."},
            "poke": {"action": "{user} pokes {target}.", "solo": "{user} pokes themselves."},
            "tickle": {"action": "{user} tickles {target}!", "solo": "{user} tickles the air."},
            "bite": {"action": "{user} bites {target}!", "solo": "{user} bites themselves. Why?"},
            "bonk": {"action": "{user} bonks {target}!", "solo": "{user} bonks themselves."},
            "yeet": {"action": "{user} yeets {target}!", "solo": "{user} yeets themselves into the void."},
            "highfive": {"action": "{user} high-fives {target}!", "solo": "{user} high-fives... nobody :("},
            "handhold": {"action": "{user} holds {target}'s hand.", "solo": "{user} holds their own hand."},
            "nom": {"action": "{user} noms on {target}!", "solo": "{user} is eating something delicious."},
            "blush": {"solo": "{user} is blushing!"},
            "smile": {"solo": "{user} smiles!"},
            "wave": {"solo": "{user} waves!"},
            "wink": {"solo": "{user} winks!"},
            "dance": {"solo": "{user} is dancing!"},
            "cry": {"solo": "{user} is crying..."},
            "lick": {"action": "{user} licks {target}!", "solo": "{user} licks a lollipop."},
            "bully": {"action": "{user} bullies {target}. That's mean!", "solo": "{user} bullies the air."},
            "kill": {"action": "{user} kills {target}. Wasted.", "solo": "{user} chose violence."},
            "kick": {"action": "{user} kicks {target}!", "solo": "{user} kicks the air."},
            "glomp": {"action": "{user} glomps {target}!", "solo": "{user} glomps a plushie."},
            "smug": {"solo": "{user} looks smug."},
            "cringe": {"solo": "{user} cringes."},
            "awoo": {"solo": "{user} awoos!"},
            "happy": {"solo": "{user} is happy!"},
            "shinobu": {"solo": "{user} is looking at Shinobu."},
            "megumin": {"solo": "{user} is looking at Megumin."},
        }

    # Session is shared — do not close it here

    async def _get_waifu_image(self, category: str, nsfw: bool = False) -> str:
        # Repurpose to fetch SFW categories from nekos.best
        category_map = {
            "lick": "nom",
            "bully": "slap",
            "kill": "shoot",
            "glomp": "hug",
            "cringe": "facepalm",
            "awoo": "smile",
            "shinobu": "waifu",
            "megumin": "waifu",
        }
        mapped_category = category_map.get(category.lower(), category.lower())
        url = f"https://nekos.best/api/v2/{mapped_category}"
        headers = {
            'User-Agent': 'Dabot/3.0 (Discord Bot; contact dadod)',
            'Accept': 'application/json'
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get('results', [])
                    if results:
                        return results[0]['url']
        except Exception as e:
            self.logger.error(f"Error fetching image from nekos.best for {category} (mapped to {mapped_category}): {e}")
        return None

    async def _get_waifu_im_image(self, category: str, nsfw: bool = False) -> str:
        nsfw_str = "True" if nsfw else "False"
        url = f"https://api.waifu.im/images?included_tags={category}&IsNsfw={nsfw_str}"
        headers = {
            'User-Agent': 'Dabot/3.0 (Discord Bot; contact dadod)',
            'Accept': 'application/json'
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get('items', [])
                    if items:
                        return items[0]['url']
        except Exception as e:
            self.logger.error(f"Error fetching image from waifu.im for {category}: {e}")
        return None

    async def _get_nekobot_image(self, category: str) -> str:
        url = f"https://nekobot.xyz/api/image?type={category}"
        headers = {
            'User-Agent': 'Dabot/3.0 (Discord Bot; contact dadod)',
            'Accept': 'application/json'
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['message']
        except Exception as e:
            self.logger.error(f"Error fetching image from nekobot for {category}: {e}")
        return None

    async def _interaction_embed(self, ctx_or_interaction, category: str, member: discord.Member = None):
        config = self.sfw_categories.get(category)
        if not config:
            return

        image_url = await self._get_waifu_image(category, nsfw=False)
        if not image_url:
            # Handle both Context and Interaction for error message
            if isinstance(ctx_or_interaction, discord.Interaction):
                 await ctx_or_interaction.response.send_message("❌ Could not fetch image. Try again later.", ephemeral=True)
            else:
                 await ctx_or_interaction.send("❌ Could not fetch image. Try again later.")
            return

        embed = discord.Embed(color=discord.Color.random())
        embed.set_image(url=image_url)

        # Determine user/author based on type
        if isinstance(ctx_or_interaction, discord.Interaction):
            author = ctx_or_interaction.user
        else:
            author = ctx_or_interaction.author

        action_text = config.get("action")
        solo_text = config.get("solo")
        description = ""

        if member:
            if action_text:
                description = action_text.format(user=author.mention, target=member.mention)
            else:
                description = solo_text.format(user=author.mention) # Fallback if no action text
        else:
            description = solo_text.format(user=author.mention)
        
        embed.description = description
        embed.set_footer(text=f"Requested by {author.display_name}", icon_url=author.avatar.url if author.avatar else author.default_avatar.url)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

    async def _nsfw_embed(self, ctx_or_interaction, category: str, member: discord.Member = None):
        config = self.nsfw_categories.get(category)
        if not config:
            return

        source = config.get("source")
        api_key = config.get("api_key", category)
        action_text = config.get("action")

        image_url = None
        if source == "waifu":
            image_url = await self._get_waifu_image(api_key, nsfw=True)
        elif source == "waifu_im":
            image_url = await self._get_waifu_im_image(api_key, nsfw=True)
        elif source == "nekobot":
            image_url = await self._get_nekobot_image(api_key)
        
        if not image_url:
             if isinstance(ctx_or_interaction, discord.Interaction):
                 await ctx_or_interaction.response.send_message("❌ Could not fetch image.", ephemeral=True)
             else:
                 await ctx_or_interaction.send("❌ Could not fetch image.")
             return
        
        # Determine user/author
        if isinstance(ctx_or_interaction, discord.Interaction):
            author = ctx_or_interaction.user
        else:
            author = ctx_or_interaction.author

        solo_text = config.get("solo")
        description = ""
        
        if member:
            if action_text:
                description = action_text.format(user=author.mention, target=member.mention)
            else:
                description = f"{author.mention} shares a **{category}** picture with {member.mention}."
        else:
            if solo_text:
                description = solo_text.format(user=author.mention)
            else:
                description = f"{author.mention} requested a **{category}** picture."
            
        embed = discord.Embed(description=description, color=discord.Color.red())
        embed.set_image(url=image_url)
        
        avatar_url = author.avatar.url if author.avatar else author.default_avatar.url
        embed.set_footer(text=f"Requested by {author.display_name}", icon_url=avatar_url)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)


    # --- SFW Slash Command ---
    
    async def interact_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = list(self.sfw_categories.keys())
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in choices if current.lower() in cat.lower()
        ][:25]

    @app_commands.command(name="interact", description="Perform a social interaction (hug, kiss, etc.)")
    @app_commands.describe(action="The action to perform", member="The user to interact with")
    @app_commands.autocomplete(action=interact_autocomplete)
    async def interact(self, interaction: discord.Interaction, action: str, member: discord.Member = None):
        action = action.lower()
        if action not in self.sfw_categories:
            await interaction.response.send_message("❌ Invalid interaction.", ephemeral=True)
            return
        await self._interaction_embed(interaction, action, member)

    # --- SFW Prefix Commands (Legacy Support) ---
    # Manually defining these to ensure they work as text commands without using Slash slots

    async def _prefix_handler(self, ctx, category, member=None):
        if member is None:
            # Check if command requires member
            if "action" in self.sfw_categories[category] and "solo" not in self.sfw_categories[category]:
                 # Try to fallback to solo text if available, but if strictly action-based (like 'kill' maybe?), standard is to need member.
                 # But our config has solo text for almost everything.
                 pass 
        
        # If member is required but not provided, internal logic handles it or we could raise MissingRequiredArgument
        # But for simplicity, we pass None and let logic decide (most have solo text)
        await self._interaction_embed(ctx, category, member)

    @commands.command(name="hug")
    async def hug(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "hug", member)
    @commands.command(name="kiss")
    async def kiss(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "kiss", member)
    @commands.command(name="pat")
    async def pat(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "pat", member)
    @commands.command(name="slap")
    async def slap(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "slap", member)
    @commands.command(name="cuddle")
    async def cuddle(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "cuddle", member)
    @commands.command(name="poke")
    async def poke(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "poke", member)
    @commands.command(name="tickle")
    async def tickle(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "tickle", member)
    @commands.command(name="bite")
    async def bite(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "bite", member)
    @commands.command(name="bonk")
    async def bonk(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "bonk", member)
    @commands.command(name="yeet")
    async def yeet(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "yeet", member)
    @commands.command(name="highfive")
    async def highfive(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "highfive", member)
    @commands.command(name="handhold")
    async def handhold(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "handhold", member)
    @commands.command(name="nom")
    async def nom(self, ctx, member: discord.Member=None): await self._prefix_handler(ctx, "nom", member)
    @commands.command(name="blush")
    async def blush(self, ctx): await self._prefix_handler(ctx, "blush")
    @commands.command(name="smile")
    async def smile(self, ctx): await self._prefix_handler(ctx, "smile")
    @commands.command(name="wave")
    async def wave(self, ctx): await self._prefix_handler(ctx, "wave")
    @commands.command(name="wink")
    async def wink(self, ctx): await self._prefix_handler(ctx, "wink")
    @commands.command(name="dance")
    async def dance(self, ctx): await self._prefix_handler(ctx, "dance")
    @commands.command(name="cry")
    async def cry(self, ctx): await self._prefix_handler(ctx, "cry")
    @commands.command(name="lick")
    async def lick(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "lick", member)
    @commands.command(name="bully")
    async def bully(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "bully", member)
    @commands.command(name="kill")
    async def kill(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "kill", member)
    @commands.command(name="kick")
    async def kick(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "kick", member)
    @commands.command(name="glomp")
    async def glomp(self, ctx, member: discord.Member): await self._prefix_handler(ctx, "glomp", member)
    @commands.command(name="smug")
    async def smug(self, ctx): await self._prefix_handler(ctx, "smug")
    @commands.command(name="cringe")
    async def cringe(self, ctx): await self._prefix_handler(ctx, "cringe")
    @commands.command(name="awoo")
    async def awoo(self, ctx): await self._prefix_handler(ctx, "awoo")
    @commands.command(name="happy")
    async def happy(self, ctx): await self._prefix_handler(ctx, "happy")
    @commands.command(name="shinobu")
    async def shinobu(self, ctx): await self._prefix_handler(ctx, "shinobu")
    @commands.command(name="megumin")
    async def megumin(self, ctx): await self._prefix_handler(ctx, "megumin")

    # NSFW is prefix-only (hidden) so these names never appear in the Discord
    # slash-command registry. App Directory / Discovery rejects explicit slash
    # names such as anal, blowjob and yaoi even when gated to NSFW channels.
    @commands.command(name="nsfw", hidden=True)
    @commands.is_nsfw()
    async def nsfw(self, ctx, category: str, member: discord.Member = None):
        category = (category or "").lower()
        if category not in self.nsfw_categories:
            await ctx.send("❌ Categoría no válida. Usa el prefijo en un canal marcado como NSFW.")
            return
        await self._nsfw_embed(ctx, category, member=member)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.NSFWChannelRequired):
            embed = discord.Embed(
                title="Canal no válido",
                description="Ese comando solo funciona en canales marcados como NSFW.",
                color=discord.Color.red()
            )
            try:
                if ctx.interaction:
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed)
            except Exception:
                pass
            return

    @commands.command(name="blowjob", aliases=["bj"], hidden=True)
    @commands.is_nsfw()
    async def blowjob(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "blowjob", member)

    @commands.command(name="anal", hidden=True)
    @commands.is_nsfw()
    async def anal(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "anal", member)

    @commands.command(name="feet", hidden=True)
    @commands.is_nsfw()
    async def feet(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "feet", member)

    @commands.command(name="yuri", hidden=True)
    @commands.is_nsfw()
    async def yuri(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "yuri", member)

    @commands.command(name="yaoi", hidden=True)
    @commands.is_nsfw()
    async def yaoi(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "yaoi", member)

    @commands.command(name="creampie", aliases=["bukkake"], hidden=True)
    @commands.is_nsfw()
    async def creampie(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "creampie", member)

    @commands.command(name="tentacle", hidden=True)
    @commands.is_nsfw()
    async def tentacle(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "tentacle", member)

    @commands.command(name="pee", hidden=True)
    @commands.is_nsfw()
    async def pee(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "pee", member)

    @commands.command(name="paizuri", hidden=True)
    @commands.is_nsfw()
    async def paizuri(self, ctx, member: discord.Member = None):
        await self._nsfw_embed(ctx, "paizuri", member)

async def setup(bot):
    await bot.add_cog(Interactions(bot))
