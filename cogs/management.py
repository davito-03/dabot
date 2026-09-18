import logging
import discord
from discord.ext import commands
import aiohttp
import asyncio
import yaml
import os
import json
import datetime
from typing import Literal
from discord import app_commands

class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(AutoroleView())
        self.logger.info('Management Cog loaded and persistent views registered.')

    # ── Helper: load/save YAML config ─────────────────────────────────────
    def _load_guild_config(self, guild_id):
        return self.bot.config.get(guild_id) or {}

    def _save_guild_config(self, guild_id, config):
        self.bot.config.save_full_config(guild_id, config)

    # ══════════════════════════════════════════════════════════════════════
    #  /setup GROUP — All server configuration commands (1 slash slot)
    # ══════════════════════════════════════════════════════════════════════
    @commands.hybrid_group(name="setup", description="⚙️ Server configuration commands.")
    @commands.has_permissions(administrator=True)
    async def setup(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Configurar Dabot",
                description=(
                    "La forma más rápida es el **panel web**: https://dabot.davito.es\n"
                    "También puedes usar `/start` para un resumen del servidor.\n\n"
                    "`/setup lang` — Idioma\n"
                    "`/setup welcome` — Canal de bienvenida\n"
                    "`/setup goodbye` — Canal de despedida\n"
                    "`/setup prefix` — Prefijo (Premium)\n"
                    "`/setup welcomemsg` — Texto de bienvenida\n"
                    "`/setup welcomedm` — DM de bienvenida\n"
                    "`/setup goodbyemsg` — Texto de despedida\n"
                    "`/setup testwelcome` — Probar bienvenida\n"
                    "`/setup autorole` — Panel de autoroles\n"
                    "`/setup suggestions` — Canal de sugerencias\n"
                    "`/setup config` — Ver config actual\n"
                    "`/setup server_backup` — Backup de estructura\n"
                    "`/setup server_restore` — Restaurar estructura"
                ),
                color=discord.Color.from_str("#00FF88")
            )
            embed.set_footer(text="dabot.davito.es")
            await ctx.send(embed=embed)

    @setup.command(name="lang", description="Set the server language.")
    async def setup_lang(self, ctx, lang: Literal["en", "es", "fr", "de", "pt", "it", "ja", "ko", "zh"]):
        """Set the bot language for this server."""
        await ctx.defer()
        try:
            available_langs = ["en", "es", "fr", "de", "pt", "it", "ja", "ko", "zh"]
            if lang not in available_langs:
                current_lang = self.bot.config.get(ctx.guild.id, 'language') or 'en'
                msg = self.bot.i18n.get('commands.setlang.invalid', current_lang, available=", ".join(available_langs))
                await ctx.send(msg)
                return

            config = self._load_guild_config(ctx.guild.id)
            config['language'] = lang
            config['lang'] = f"{lang}-{lang.upper()}" if lang in ("es", "en") else lang
            if lang == "es":
                config['lang'] = "es-ES"
            elif lang == "en":
                config['lang'] = "en-US"
            self._save_guild_config(ctx.guild.id, config)

            msg = self.bot.i18n.get('commands.setlang.success', lang, lang=lang)
            await ctx.send(msg)
        except Exception as e:
            self.logger.error(f"Error setting language: {e}", exc_info=True)
            await ctx.send(f"❌ Error setting language: {e}")

    @setup.command(name="welcome", description="Set the welcome channel.")
    async def setup_welcome(self, ctx, channel: discord.TextChannel):
        """Set the channel for welcome messages."""
        config = self._load_guild_config(ctx.guild.id)
        if 'welcome' not in config:
            config['welcome'] = {}
        config['welcome']['channel_id'] = channel.id
        config['welcome']['enabled'] = True
        self._save_guild_config(ctx.guild.id, config)

        embed = discord.Embed(title="✅ Welcome Channel Set",
                              description=f"Welcome messages will be sent to {channel.mention}",
                              color=discord.Color.green())
        await ctx.send(embed=embed)

    @setup.command(name="goodbye", description="Set the goodbye channel.")
    async def setup_goodbye(self, ctx, channel: discord.TextChannel):
        """Set the channel for goodbye messages."""
        config = self._load_guild_config(ctx.guild.id)
        if 'goodbye' not in config:
            config['goodbye'] = {}
        config['goodbye']['channel_id'] = channel.id
        config['goodbye']['enabled'] = True
        self._save_guild_config(ctx.guild.id, config)

        embed = discord.Embed(title="✅ Goodbye Channel Set",
                              description=f"Goodbye messages will be sent to {channel.mention}",
                              color=discord.Color.green())
        await ctx.send(embed=embed)

    @setup.command(name="prefix", description="Set a custom prefix (Premium Only).")
    async def setup_prefix(self, ctx, prefix: str):
        """Set a custom prefix for the server. Premium feature."""
        if not await self.bot.db.is_guild_premium(ctx.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await ctx.send(deny_text(guild_lang(self.bot, ctx.guild.id)))
            return

        if len(prefix) > 5:
            await ctx.send("❌ Prefix cannot be longer than 5 characters.")
            return

        config = self._load_guild_config(ctx.guild.id)
        config['prefix'] = prefix
        self._save_guild_config(ctx.guild.id, config)
        await ctx.send(f"✅ Prefix set to `{prefix}`")

    @setup.command(name="welcomemsg", description="Set custom welcome message.")
    async def setup_welcomemsg(self, ctx, *, message: str):
        """Variables: {user}, {mention}, {server}, {count}"""
        config = self._load_guild_config(ctx.guild.id)
        if 'welcome' not in config:
            config['welcome'] = {}
        config['welcome']['message'] = message
        self._save_guild_config(ctx.guild.id, config)

        embed = discord.Embed(title="✅ Welcome Message Updated", description=f"New message: {message}",
                              color=discord.Color.green())
        embed.set_footer(text="Variables: {user}, {mention}, {server}, {count}")
        await ctx.send(embed=embed)

    @setup.command(name="welcomedm", description="Set custom welcome DM message.")
    async def setup_welcomedm(self, ctx, *, message: str = None):
        """Leave message empty to disable DMs. Variables: {user}, {mention}, {server}, {count}"""
        config = self._load_guild_config(ctx.guild.id)
        if 'welcome' not in config:
            config['welcome'] = {}

        if message:
            config['welcome']['dm_enabled'] = True
            config['welcome']['dm_message'] = message
            response = f"✅ Welcome DM enabled and set to: \n> {message}"
        else:
            config['welcome']['dm_enabled'] = False
            response = "✅ Welcome DM disabled."

        self._save_guild_config(ctx.guild.id, config)
        embed = discord.Embed(title="✅ Welcome DM Updated", description=response, color=discord.Color.green())
        if message:
            embed.set_footer(text="Variables: {user}, {mention}, {server}, {count}")
        await ctx.send(embed=embed)

    @setup.command(name="goodbyemsg", description="Set custom goodbye message.")
    async def setup_goodbyemsg(self, ctx, *, message: str):
        """Variables: {user}, {mention}, {server}, {count}"""
        config = self._load_guild_config(ctx.guild.id)
        if 'goodbye' not in config:
            config['goodbye'] = {}
        config['goodbye']['message'] = message
        self._save_guild_config(ctx.guild.id, config)

        embed = discord.Embed(title="✅ Goodbye Message Updated", description=f"New message: {message}",
                              color=discord.Color.green())
        embed.set_footer(text="Variables: {user}, {mention}, {server}, {count}")
        await ctx.send(embed=embed)

    @setup.command(name="testwelcome", description="Test the welcome message.")
    async def setup_testwelcome(self, ctx):
        """Preview the welcome message with your user."""
        config = self.bot.config.get(ctx.guild.id, 'welcome')
        if not config:
            await ctx.send("❌ Welcome system not configured! Use `/setup welcome` first.")
            return

        member_count = len(ctx.guild.members)
        message = config.get('message', 'Welcome {mention} to **{server}**! You are member #{count}!')
        message = message.replace('{user}', ctx.author.display_name)
        message = message.replace('{mention}', ctx.author.mention)
        message = message.replace('{server}', ctx.guild.name)
        message = message.replace('{count}', str(member_count))

        use_embed = config.get('embed', True)
        if use_embed:
            try:
                bg_url = None
                premium = await self.bot.db.fetch("SELECT custom_background FROM premium_guilds WHERE guild_id = ?", ctx.guild.id)
                if premium and premium[0]:
                    bg_url = premium[0]
                else:
                    bg_url = "assets/welcome_background.jpg"
                from utils.images import create_welcome_card
                file = await create_welcome_card(
                    ctx.author, background_source=bg_url,
                    welcome_text=config.get('card_heading', 'BIENVENIDO'),
                    member_label=config.get('member_label', 'Miembro'),
                    custom_text=config.get('custom_text', ''),
                    layout=config.get('layout') or {},
                )
                await ctx.send(content=f"**Preview:** {message}", file=file)
            except Exception as e:
                self.logger.error(f"Error previewing welcome card: {e}")
                try:
                    color_hex = config.get('color', '0x00ff00')
                    color = int(color_hex, 16)
                except Exception:
                    color = 0x00ff00
                embed = discord.Embed(title=f"Welcome to {ctx.guild.name}! 👋", description=message, color=color)
                embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
                embed.set_footer(text=f"Member #{member_count} • This is a preview")
                embed.timestamp = discord.utils.utcnow()
                await ctx.send("**Preview:**", embed=embed)
        else:
            await ctx.send(f"**Preview:** {message}")

    @setup.command(name="steal", description="Steal an emoji from another server.")
    @commands.has_permissions(manage_emojis=True)
    async def setup_steal(self, ctx, emoji: discord.PartialEmoji, *, name=None):
        """Steal an emoji from another server."""
        if not name:
            name = emoji.name
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(emoji.url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        new_emoji = await ctx.guild.create_custom_emoji(name=name, image=data)
                        await ctx.send(f"Stole emoji: {new_emoji} as `:{new_emoji.name}:`")
                    else:
                        await ctx.send("Failed to download emoji.")
        except Exception as e:
            await ctx.send(f"Error stealing emoji: {e}")

    @setup.command(name="autorole", description="Create an autorole panel.")
    async def setup_autorole(self, ctx, *, description="Choose your roles:"):
        """Setup an autorole panel with buttons."""
        view = AutoroleView()
        embed = discord.Embed(title="Self Roles", description=description, color=discord.Color.blurple())
        await ctx.send(embed=embed, view=view)

    @setup.command(name="sticker", description="Create a sticker from a URL.")
    @commands.has_permissions(manage_emojis_and_stickers=True)
    async def setup_sticker(self, ctx, url: str, name: str, emoji: str = "🤖"):
        """Create a sticker from a URL."""
        await ctx.defer()
        try:
            stickers = await ctx.guild.fetch_stickers()
            limit = ctx.guild.sticker_limit
            if len(stickers) >= limit:
                await ctx.send(f"❌ Sticker limit reached ({len(stickers)}/{limit}).")
                return

            from utils.images import prepare_sticker_image
            image_buffer = await prepare_sticker_image(url, session=self.bot.session)
            if not image_buffer:
                await ctx.send("❌ Failed to process image.")
                return

            file = discord.File(image_buffer, filename="sticker.png")
            sticker = await ctx.guild.create_sticker(
                name=name, description=f"Uploaded by {ctx.author.name}",
                emoji=emoji, file=file, reason=f"Added by {ctx.author} via command")
            await ctx.send(f"✅ Sticker created: **{sticker.name}**", stickers=[sticker])
        except discord.HTTPException as e:
            await ctx.send(f"❌ Discord Error: {e.text}")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @setup.command(name="suggestions", description="Set the suggestions channel.")
    async def setup_suggestions(self, ctx, channel: discord.TextChannel):
        """Configure the channel where suggestions will be sent."""
        config = self._load_guild_config(ctx.guild.id)
        if 'suggestions' not in config:
            config['suggestions'] = {}
        config['suggestions']['channel'] = str(channel.id)
        self._save_guild_config(ctx.guild.id, config)
        await ctx.send(f"✅ Suggestions channel set to {channel.mention}.")

    @setup.command(name="config", description="View server configuration.")
    async def setup_config(self, ctx):
        """View current server configuration."""
        config = self.bot.config.get(ctx.guild.id)
        if not config:
            await ctx.send("No configuration found.")
            return
        embed = discord.Embed(title=f"⚙️ Config — {ctx.guild.name}", color=discord.Color.blue())
        for key, value in config.items():
            if isinstance(value, dict):
                val_str = "\n".join([f"  {k}: {v}" for k, v in value.items()])[:1024]
            else:
                val_str = str(value)[:1024]
            embed.add_field(name=key, value=f"```{val_str}```", inline=False)
        await ctx.send(embed=embed)

    @setup.command(name="backup", description="Backup the database (Owner only).")
    async def setup_backup(self, ctx):
        """Backup the bot database."""
        if not await self.bot.is_owner(ctx.author):
            await ctx.send("❌ Only the bot owner can do this.")
            return
        import shutil, datetime
        src = os.environ.get("DATABASE_PATH", "dabot.db")
        dst = f"backups/dabot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        os.makedirs("backups", exist_ok=True)
        shutil.copy2(src, dst)
        await ctx.send(f"✅ Database backed up to `{dst}`")

    @setup.command(name="export", description="Export the server configuration.")
    async def setup_export(self, ctx):
        """Export the server configuration file."""
        config_data = self.bot.config.get(ctx.guild.id)
        if not config_data:
            await ctx.send("❌ No configuration found.")
            return
        import io
        yaml_content = yaml.dump(config_data, default_flow_style=False, allow_unicode=True)
        file = discord.File(io.BytesIO(yaml_content.encode('utf-8')), filename=f"{ctx.guild.name}_config.yaml")
        await ctx.send("📎 Here is your server configuration:", file=file)

    @setup.command(name="import_config", description="Import a server configuration file.")
    async def setup_import(self, ctx, attachment: discord.Attachment = None):
        """Import a server configuration from an attached YAML file."""
        if not ctx.message.attachments and not attachment:
            await ctx.send("❌ Attach a `.yaml` file.")
            return

        att = attachment or ctx.message.attachments[0]
        if not att.filename.endswith(('.yaml', '.yml')):
            await ctx.send("❌ Only `.yaml` files are supported.")
            return

        if att.size > 102400:
            await ctx.send("❌ File too large (max 100KB).")
            return

        content = await att.read()
        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                await ctx.send("❌ Invalid YAML structure.")
                return
        except yaml.YAMLError:
            await ctx.send("❌ Invalid YAML syntax.")
            return

        self.bot.config.save_full_config(ctx.guild.id, data)
        await ctx.send("✅ Configuration imported successfully!")

    @setup.command(name="role_add", description="Give a role to a user.")
    @commands.has_permissions(manage_roles=True)
    async def setup_role_add(self, ctx, member: discord.Member, role: discord.Role):
        """Give a role to a member."""
        try:
            await member.add_roles(role)
            await ctx.send(f"✅ Added {role.mention} to {member.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage that role.")

    @setup.command(name="role_remove", description="Remove a role from a user.")
    @commands.has_permissions(manage_roles=True)
    async def setup_role_remove(self, ctx, member: discord.Member, role: discord.Role):
        """Remove a role from a member."""
        try:
            await member.remove_roles(role)
            await ctx.send(f"✅ Removed {role.mention} from {member.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage that role.")

    # ══════════════════════════════════════════════════════════════════════
    #  SERVER STRUCTURE BACKUP/RESTORE
    # ══════════════════════════════════════════════════════════════════════

    @setup.command(name="server_backup", description="💾 Create a full backup of the server structure.")
    @commands.has_permissions(administrator=True)
    async def setup_server_backup(self, ctx):
        """Backup the full server structure: roles, categories, channels, permissions."""
        await ctx.defer()
        import io as _io

        guild = ctx.guild
        backup = {
            "guild_name": guild.name,
            "guild_id": guild.id,
            "created_at": datetime.datetime.now().isoformat(),
            "created_by": ctx.author.id,
            "roles": [],
            "categories": [],
            "text_channels": [],
            "voice_channels": [],
        }

        # Roles (skip @everyone and managed roles)
        for role in sorted(guild.roles, key=lambda r: r.position):
            if role.is_default() or role.managed:
                continue
            backup["roles"].append({
                "name": role.name,
                "color": role.color.value,
                "permissions": role.permissions.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position,
            })

        # Categories
        for cat in guild.categories:
            cat_data = {
                "name": cat.name,
                "position": cat.position,
                "overwrites": [],
            }
            for target, overwrite in cat.overwrites.items():
                ow_data = {
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "name": target.name if isinstance(target, discord.Role) else str(target.id),
                    "allow": overwrite.pair()[0].value,
                    "deny": overwrite.pair()[1].value,
                }
                cat_data["overwrites"].append(ow_data)
            backup["categories"].append(cat_data)

        # Text Channels
        for ch in guild.text_channels:
            ch_data = {
                "name": ch.name,
                "topic": ch.topic,
                "slowmode_delay": ch.slowmode_delay,
                "nsfw": ch.nsfw,
                "position": ch.position,
                "category": ch.category.name if ch.category else None,
                "overwrites": [],
            }
            for target, overwrite in ch.overwrites.items():
                ow_data = {
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "name": target.name if isinstance(target, discord.Role) else str(target.id),
                    "allow": overwrite.pair()[0].value,
                    "deny": overwrite.pair()[1].value,
                }
                ch_data["overwrites"].append(ow_data)
            backup["text_channels"].append(ch_data)

        # Voice Channels
        for ch in guild.voice_channels:
            ch_data = {
                "name": ch.name,
                "bitrate": ch.bitrate,
                "user_limit": ch.user_limit,
                "position": ch.position,
                "category": ch.category.name if ch.category else None,
                "overwrites": [],
            }
            for target, overwrite in ch.overwrites.items():
                ow_data = {
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "name": target.name if isinstance(target, discord.Role) else str(target.id),
                    "allow": overwrite.pair()[0].value,
                    "deny": overwrite.pair()[1].value,
                }
                ch_data["overwrites"].append(ow_data)
            backup["voice_channels"].append(ch_data)

        # Save to DB
        backup_json = json.dumps(backup, ensure_ascii=False, indent=2)
        await self.bot.db.execute(
            "INSERT INTO server_backups (guild_id, backup_data, created_by, created_at) VALUES (?, ?, ?, ?)",
            guild.id, backup_json, ctx.author.id, datetime.datetime.now().isoformat()
        )

        # Also send as file attachment
        buffer = _io.BytesIO(backup_json.encode('utf-8'))
        file = discord.File(buffer, filename=f"backup_{guild.name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        stats = (
            f"**Roles:** {len(backup['roles'])}\n"
            f"**Categories:** {len(backup['categories'])}\n"
            f"**Text Channels:** {len(backup['text_channels'])}\n"
            f"**Voice Channels:** {len(backup['voice_channels'])}"
        )

        embed = discord.Embed(
            title="💾 Server Structure Backup Created",
            description=f"Full structure snapshot of **{guild.name}**.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📊 Contents", value=stats, inline=False)
        embed.set_footer(text=f"Backup by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

        await ctx.send(embed=embed, file=file)

    @setup.command(name="server_restore", description="🔄 Restore server structure from a backup file.")
    @commands.has_permissions(administrator=True)
    async def setup_server_restore(self, ctx, attachment: discord.Attachment = None):
        """Restore server structure from a JSON backup. Attach the backup file."""
        if not ctx.message.attachments and not attachment:
            await ctx.send("❌ Please attach a `.json` backup file generated by `/setup server_backup`.")
            return

        att = attachment or ctx.message.attachments[0]
        if not att.filename.endswith('.json'):
            await ctx.send("❌ Only `.json` backup files are supported.")
            return

        if att.size > 5 * 1024 * 1024:  # 5MB limit
            await ctx.send("❌ Backup file is too large (max 5MB).")
            return

        content = await att.read()
        try:
            backup = json.loads(content)
        except json.JSONDecodeError:
            await ctx.send("❌ Invalid JSON format.")
            return

        # Safety confirmation
        roles_count = len(backup.get('roles', []))
        cats_count = len(backup.get('categories', []))
        text_count = len(backup.get('text_channels', []))
        voice_count = len(backup.get('voice_channels', []))

        confirm_embed = discord.Embed(
            title="⚠️ Confirm Server Restore",
            description=(
                f"This will attempt to recreate the following structure:\n\n"
                f"**{roles_count}** roles\n"
                f"**{cats_count}** categories\n"
                f"**{text_count}** text channels\n"
                f"**{voice_count}** voice channels\n\n"
                f"⚠️ **Existing channels/roles will NOT be deleted.** "
                f"New ones will be created based on the backup.\n\n"
                f"React with ✅ within 30 seconds to confirm."
            ),
            color=discord.Color.orange()
        )
        msg = await ctx.send(embed=confirm_embed)
        await msg.add_reaction("✅")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) == "✅" and reaction.message.id == msg.id

        try:
            await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await msg.edit(embed=discord.Embed(title="⏰ Restore Cancelled", description="Timed out.", color=discord.Color.red()))
            return

        await ctx.send("🔄 Starting restore process...")
        restored = {"roles": 0, "categories": 0, "text_channels": 0, "voice_channels": 0}

        # 1. Restore Roles
        existing_role_names = {r.name.lower() for r in ctx.guild.roles}
        for role_data in backup.get('roles', []):
            if role_data['name'].lower() in existing_role_names:
                continue
            try:
                await ctx.guild.create_role(
                    name=role_data['name'],
                    color=discord.Color(role_data.get('color', 0)),
                    permissions=discord.Permissions(role_data.get('permissions', 0)),
                    hoist=role_data.get('hoist', False),
                    mentionable=role_data.get('mentionable', False),
                    reason="Server restore from backup"
                )
                restored["roles"] += 1
            except Exception as e:
                self.logger.error(f"Failed to restore role {role_data['name']}: {e}")

        # 2. Restore Categories
        existing_cat_names = {c.name.lower() for c in ctx.guild.categories}
        cat_map = {}  # name -> category object
        for cat_data in backup.get('categories', []):
            if cat_data['name'].lower() in existing_cat_names:
                cat_map[cat_data['name']] = discord.utils.get(ctx.guild.categories, name=cat_data['name'])
                continue
            try:
                cat = await ctx.guild.create_category(name=cat_data['name'], reason="Server restore from backup")
                cat_map[cat_data['name']] = cat
                restored["categories"] += 1
            except Exception as e:
                self.logger.error(f"Failed to restore category {cat_data['name']}: {e}")

        # 3. Restore Text Channels
        existing_text_names = {c.name.lower() for c in ctx.guild.text_channels}
        for ch_data in backup.get('text_channels', []):
            if ch_data['name'].lower() in existing_text_names:
                continue
            try:
                category = cat_map.get(ch_data.get('category')) if ch_data.get('category') else None
                await ctx.guild.create_text_channel(
                    name=ch_data['name'],
                    topic=ch_data.get('topic'),
                    slowmode_delay=ch_data.get('slowmode_delay', 0),
                    nsfw=ch_data.get('nsfw', False),
                    category=category,
                    reason="Server restore from backup"
                )
                restored["text_channels"] += 1
            except Exception as e:
                self.logger.error(f"Failed to restore text channel {ch_data['name']}: {e}")

        # 4. Restore Voice Channels
        existing_voice_names = {c.name.lower() for c in ctx.guild.voice_channels}
        for ch_data in backup.get('voice_channels', []):
            if ch_data['name'].lower() in existing_voice_names:
                continue
            try:
                category = cat_map.get(ch_data.get('category')) if ch_data.get('category') else None
                await ctx.guild.create_voice_channel(
                    name=ch_data['name'],
                    bitrate=ch_data.get('bitrate', 64000),
                    user_limit=ch_data.get('user_limit', 0),
                    category=category,
                    reason="Server restore from backup"
                )
                restored["voice_channels"] += 1
            except Exception as e:
                self.logger.error(f"Failed to restore voice channel {ch_data['name']}: {e}")

        result_embed = discord.Embed(
            title="✅ Server Restore Complete",
            description=(
                f"**Roles created:** {restored['roles']}\n"
                f"**Categories created:** {restored['categories']}\n"
                f"**Text channels created:** {restored['text_channels']}\n"
                f"**Voice channels created:** {restored['voice_channels']}"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        result_embed.set_footer(text="Duplicates were skipped automatically.")
        await ctx.send(embed=result_embed)

    @setup.command(name="automod", description="Enable or disable AutoMod for this server.")
    @commands.has_permissions(administrator=True)
    async def setup_automod(self, ctx, enabled: bool):
        self.bot.config.set_config(ctx.guild.id, "automod.enabled", enabled)
        status = "activado" if enabled else "desactivado"
        await ctx.send(f"AutoMod **{status}**.")

    # ══════════════════════════════════════════════════════════════════════
    #  LISTENERS (welcome/goodbye — unchanged logic)
    # ══════════════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle member join with custom welcome message."""
        # WelcomeCards is the authoritative renderer when the web/modern
        # welcome configuration exists. This prevents both cogs sending a
        # welcome card for the same member.
        modern_config = await self.bot.db.fetch(
            "SELECT 1 FROM welcome_config WHERE guild_id = ?", member.guild.id
        )
        if modern_config:
            return
        config = self.bot.config.get(member.guild.id, 'welcome')
        if not config or not config.get('enabled', False):
            return
        channel_id = config.get('channel_id')
        if not channel_id:
            return
        channel = member.guild.get_channel(int(channel_id))
        if not channel:
            return

        member_count = len(member.guild.members)
        message = config.get('message', 'Welcome {mention} to **{server}**! You are member #{count}!')
        message = message.replace('{user}', member.display_name)
        message = message.replace('{mention}', member.mention)
        message = message.replace('{server}', member.guild.name)
        message = message.replace('{count}', str(member_count))

        use_embed = config.get('embed', True)
        if use_embed:
            try:
                bg_url = None
                premium = await self.bot.db.fetch("SELECT custom_background FROM premium_guilds WHERE guild_id = ?", member.guild.id)
                if premium and premium[0]:
                    bg_url = premium[0]
                else:
                    bg_url = "assets/welcome_background.jpg"
                from utils.images import create_welcome_card
                file = await create_welcome_card(
                    member, background_source=bg_url,
                    welcome_text=config.get('card_heading', 'BIENVENIDO'),
                    member_label=config.get('member_label', 'Miembro'),
                    custom_text=config.get('custom_text', ''),
                    layout=config.get('layout') or {},
                )
                from utils.webhooks import send_webhook
                await send_webhook(self.bot, channel, content=message, file=file)
            except Exception as e:
                self.logger.error(f"Error generating welcome card: {e}")
                try:
                    color_hex = config.get('color', '0x00ff00')
                    color = int(color_hex, 16)
                except Exception:
                    color = 0x00ff00
                embed = discord.Embed(title=f"Welcome to {member.guild.name}! 👋", description=message, color=color)
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                embed.set_footer(text=f"Member #{member_count}")
                embed.timestamp = discord.utils.utcnow()
                from utils.webhooks import send_webhook
                await send_webhook(self.bot, channel, embed=embed)
        else:
            from utils.webhooks import send_webhook
            await send_webhook(self.bot, channel, content=message)

        # Handle Welcome DM
        if config.get('dm_enabled', False):
            dm_message = config.get('dm_message', 'Welcome to **{server}**, {user}! We are glad to have you.')
            dm_message = dm_message.replace('{user}', member.display_name)
            dm_message = dm_message.replace('{mention}', member.mention)
            dm_message = dm_message.replace('{server}', member.guild.name)
            dm_message = dm_message.replace('{count}', str(member_count))
            try:
                from utils.abuse import guard as abuse_guard
                ag = abuse_guard(self.bot)
                if ag and not await ag.allow_outbound(
                    guild=member.guild,
                    actor_id=member.guild.owner_id,
                    dest_id=member.id,
                    text=dm_message,
                    kind="welcome_dm",
                ):
                    return
                await member.send(dm_message)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Handle member leave with custom goodbye message."""
        config = self.bot.config.get(member.guild.id, 'goodbye')
        if not config or not config.get('enabled', False):
            return
        channel_id = config.get('channel_id')
        if not channel_id:
            return
        channel = member.guild.get_channel(int(channel_id))
        if not channel:
            return

        member_count = len(member.guild.members)
        message = config.get('message', '{user} has left **{server}**. We now have {count} members.')
        message = message.replace('{user}', member.display_name)
        message = message.replace('{mention}', member.mention)
        message = message.replace('{server}', member.guild.name)
        message = message.replace('{count}', str(member_count))

        use_embed = config.get('embed', True)
        if use_embed:
            try:
                color_hex = config.get('color', '0xff0000')
                color = int(color_hex, 16)
            except Exception:
                color = 0xff0000
            embed = discord.Embed(title="Goodbye! 👋", description=message, color=color)
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f"Member #{member_count}")
            embed.timestamp = discord.utils.utcnow()
            from utils.webhooks import send_webhook
            await send_webhook(self.bot, channel, embed=embed)
        else:
            from utils.webhooks import send_webhook
            await send_webhook(self.bot, channel, content=message)


class AutoroleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Gamer", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="role_gamer")
    async def gamer_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle_role(interaction, "Gamer")

    @discord.ui.button(label="News", style=discord.ButtonStyle.secondary, emoji="📰", custom_id="role_news")
    async def news_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle_role(interaction, "News Pings")

    async def toggle_role(self, interaction, role_name):
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name)
            except Exception:
                await interaction.response.send_message(f"Role '{role_name}' not found.", ephemeral=True)
                return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"Removed role {role.mention}", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"Added role {role.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Management(bot))
