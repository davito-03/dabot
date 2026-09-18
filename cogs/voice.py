import logging
import discord
from discord.ext import commands
from discord import ui
import asyncio

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS voice_hubs (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                category_id INTEGER
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS temp_channels (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER,
                owner_id INTEGER
            )
        """)
        self.logger.info("Voice Cog loaded and tables checked.")

    @commands.command(name="setup_voicehub")
    @commands.has_permissions(administrator=True)
    async def setup_voicehub(self, ctx, channel: discord.VoiceChannel = None):
        """Sets the voice channel that triggers the creation of temporary channels."""
        if getattr(ctx, "interaction", None) and not ctx.interaction.response.is_done():
            await ctx.defer()
        try:
            if not channel:
                category = await ctx.guild.create_category("Voice Hub")
                channel = await ctx.guild.create_voice_channel("➕ Create Channel", category=category)
            else:
                category = channel.category

            await self.bot.db.execute(
                "INSERT OR REPLACE INTO voice_hubs (guild_id, channel_id, category_id) VALUES (?, ?, ?)",
                ctx.guild.id, channel.id, category.id if category else None
            )
            await ctx.send(f"✅ Voice Hub setup complete! Join {channel.mention} to test.")
        except Exception as e:
            await ctx.send(f"❌ No pude crear el Voice Hub. Revisa mis permisos. ({e})")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # Handle Join to Create
        if after.channel:
            hub = await self.bot.db.fetch("SELECT channel_id, category_id FROM voice_hubs WHERE guild_id = ?", member.guild.id)
            if hub and after.channel.id == hub[0]:
                category = member.guild.get_channel(hub[1]) if hub[1] else after.channel.category
                
                # Create Voice Channel
                overwrites = {
                    member.guild.default_role: discord.PermissionOverwrite(connect=True),
                    member: discord.PermissionOverwrite(connect=True, move_members=True, manage_channels=True)
                }
                
                # Try to clean name
                name = f"{member.display_name}'s Channel"
                
                try:
                    voice_channel = await member.guild.create_voice_channel(name, category=category, overwrites=overwrites)
                    
                    # Move member
                    await member.move_to(voice_channel)
                    
                    # Save to DB
                    await self.bot.db.execute("INSERT INTO temp_channels (channel_id, guild_id, owner_id) VALUES (?, ?, ?)", voice_channel.id, member.guild.id, member.id)

                    # Send control panel automatically
                    try:
                        embed = discord.Embed(
                            title="🎛️ Panel de Control de Voz",
                            description=(
                                f"¡Bienvenido a tu sala de voz temporal, **{member.display_name}**!\n\n"
                                "Usa los botones de abajo para gestionar tu canal sin escribir comandos:\n"
                                "• 🔒 **Bloquear/Desbloquear**: Controla quién entra\n"
                                "• 👻 **Ocultar/Mostrar**: Haz la sala invisible\n"
                                "• 👥 **Límite**: Ajusta el cupo de personas\n"
                                "• ✏️ **Renombrar**: Cambia el nombre de tu sala"
                            ),
                            color=discord.Color.from_rgb(0, 255, 136)
                        )
                        embed.set_footer(text=f"Propietario: {member.display_name} • Se eliminará al quedar vacía")
                        view = VoiceControlPanel(self.bot, member.id, voice_channel.id)
                        await voice_channel.send(embed=embed, view=view)
                    except Exception as e:
                        self.logger.debug(f"Could not send control panel to voice channel chat: {e}")

                except Exception as e:
                    self.logger.error(f"Failed to create voice channel: {e}")

        # Handle Leave / Cleanup
        if before.channel:
            # Check if it was a temp channel
            temp = await self.bot.db.fetch("SELECT owner_id FROM temp_channels WHERE channel_id = ?", before.channel.id)
            if temp:
                if len(before.channel.members) == 0:
                    # Delete channel
                    try:
                        await before.channel.delete()
                    except:
                        pass
                    await self.bot.db.execute("DELETE FROM temp_channels WHERE channel_id = ?", before.channel.id)

    async def check_voice_owner(self, ctx):
        if not ctx.author.voice:
            await ctx.send("❌ You are not in a voice channel.")
            return False
            
        data = await self.bot.db.fetch("SELECT owner_id FROM temp_channels WHERE channel_id = ?", ctx.author.voice.channel.id)
        if not data:
            await ctx.send("❌ This is not a temporary channel.")
            return False
            
        if data[0] != ctx.author.id and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ You don't own this channel.")
            return False
            
        return True

    # Group commands to save slash command slots
    @commands.hybrid_group(name="vc", description="🔊 Manage your temporary voice channel.")
    async def vc(self, ctx):
        if ctx.invoked_subcommand is None:
             embed = discord.Embed(
                 title="🔊 Voice Channel Commands",
                 description=(
                     "`/vc lock` — Lock your channel\n"
                     "`/vc unlock` — Unlock your channel\n"
                     "`/vc hide` — Make channel invisible\n"
                     "`/vc reveal` — Make channel visible\n"
                     "`/vc rename <name>` — Rename channel\n"
                     "`/vc limit <n>` — Set user limit\n"
                     "`/vc bitrate <kbps>` — Set audio quality\n"
                     "`/vc permit <user>` — Allow a user in\n"
                     "`/vc reject <user>` — Kick/ban a user\n"
                     "`/vc transfer <user>` — Transfer ownership\n"
                     "`/vc claim` — Claim if owner left\n"
                     "`/vc info` — Channel info panel\n"
                     "`/vc panel` — Interactive control panel"
                 ),
                 color=discord.Color.from_rgb(88, 101, 242)
             )
             await ctx.send(embed=embed)

    @vc.command(name="hub", description="Setup the Join-to-Create voice system.")
    @commands.has_permissions(administrator=True)
    async def vc_hub(self, ctx, channel: discord.VoiceChannel = None):
        await self.setup_voicehub(ctx, channel)

    @vc.command(name="lock", description="Lock your temporary voice channel.")
    async def vc_lock(self, ctx):
        if not await self.check_voice_owner(ctx): return
        
        channel = ctx.author.voice.channel
        await channel.set_permissions(ctx.guild.default_role, connect=False)
        await ctx.send(f"🔒 {channel.mention} is now locked.")

    @vc.command(name="unlock", description="Unlock your temporary voice channel.")
    async def vc_unlock(self, ctx):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await channel.set_permissions(ctx.guild.default_role, connect=True)
        await ctx.send(f"🔓 {channel.mention} is now unlocked.")

    @vc.command(name="hide", description="Hide your temporary voice channel.")
    async def vc_hide(self, ctx):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await channel.set_permissions(ctx.guild.default_role, view_channel=False)
        await ctx.send(f"👻 {channel.mention} is now hidden.")

    @vc.command(name="reveal", description="Reveal your temporary voice channel.")
    async def vc_reveal(self, ctx):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await channel.set_permissions(ctx.guild.default_role, view_channel=True)
        await ctx.send(f"👁️ {channel.mention} is now visible.")

    @vc.command(name="rename", description="Rename your temporary voice channel.")
    async def vc_rename(self, ctx, *, name: str):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await channel.edit(name=name)
        await ctx.send(f"✏️ Channel renamed to **{name}**.")

    @vc.command(name="limit", description="Set a user limit for your channel.")
    async def vc_limit(self, ctx, limit: int):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await channel.edit(user_limit=limit)
        await ctx.send(f"👥 User limit set to **{limit}**.")

    @vc.command(name="bitrate", description="Set the audio quality (bitrate) of your channel.")
    async def vc_bitrate(self, ctx, kbps: int):
        """Set audio bitrate in kbps (8-384)."""
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        # Clamp to valid range
        max_bitrate = int(ctx.guild.bitrate_limit / 1000)
        kbps = max(8, min(kbps, max_bitrate))
        await channel.edit(bitrate=kbps * 1000)
        
        quality = "🔴 Low" if kbps < 64 else ("🟡 Normal" if kbps < 128 else ("🟢 High" if kbps < 256 else "💎 Studio"))
        await ctx.send(f"🎧 Bitrate set to **{kbps} kbps** ({quality})")

    @vc.command(name="permit", description="Permit a user to join your locked channel.")
    async def vc_permit(self, ctx, member: discord.Member):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await channel.set_permissions(member, connect=True)
        await ctx.send(f"✅ {member.mention} has been permitted to join.")

    @vc.command(name="reject", description="Kick/Ban a user from your channel.")
    async def vc_reject(self, ctx, member: discord.Member):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        
        # Kick if inside
        if member in channel.members:
            await member.move_to(None)
            
        await channel.set_permissions(member, connect=False)
        await ctx.send(f"🚫 {member.mention} has been rejected from the channel.")
        
    @vc.command(name="transfer", description="Transfer ownership of your channel.")
    async def vc_transfer(self, ctx, member: discord.Member):
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        await self.bot.db.execute("UPDATE temp_channels SET owner_id = ? WHERE channel_id = ?", member.id, channel.id)
        await ctx.send(f"👑 Ownership transferred to {member.mention}!")

    @vc.command(name="claim", description="Claim ownership of the channel if the owner left.")
    async def vc_claim(self, ctx):
        if not ctx.author.voice:
             await ctx.send("❌ You are not in a voice channel.")
             return
             
        channel = ctx.author.voice.channel
        data = await self.bot.db.fetch("SELECT owner_id FROM temp_channels WHERE channel_id = ?", channel.id)
        
        if not data:
            await ctx.send("❌ This is not a temporary channel.")
            return
            
        current_owner_id = data[0]
        # Check if owner is present
        owner_present = any(m.id == current_owner_id for m in channel.members)
        
        if owner_present and not ctx.author.guild_permissions.administrator:
            await ctx.send(f"❌ The owner is still here.")
            return
            
        await self.bot.db.execute("UPDATE temp_channels SET owner_id = ? WHERE channel_id = ?", ctx.author.id, channel.id)
        await ctx.send(f"👑 You are now the owner of {channel.mention}!")

    @vc.command(name="info", description="Show detailed info about your temporary voice channel.")
    async def vc_info(self, ctx):
        """Display a comprehensive info panel for the current temporary voice channel."""
        if not ctx.author.voice:
            await ctx.send("❌ You are not in a voice channel.")
            return

        channel = ctx.author.voice.channel
        data = await self.bot.db.fetch("SELECT owner_id FROM temp_channels WHERE channel_id = ?", channel.id)

        if not data:
            await ctx.send("❌ This is not a temporary channel.")
            return

        owner_id = data[0]
        owner = ctx.guild.get_member(owner_id)
        owner_name = owner.display_name if owner else f"Unknown ({owner_id})"

        # Determine channel status
        default_perms = channel.overwrites_for(ctx.guild.default_role)
        is_locked = default_perms.connect is False
        is_hidden = default_perms.view_channel is False
        
        status_parts = []
        if is_locked:
            status_parts.append("🔒 Locked")
        else:
            status_parts.append("🔓 Open")
        if is_hidden:
            status_parts.append("👻 Hidden")
        else:
            status_parts.append("👁️ Visible")

        bitrate_kbps = channel.bitrate // 1000
        user_limit = channel.user_limit or "∞"

        embed = discord.Embed(
            title=f"🔊 {channel.name}",
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.add_field(name="👑 Owner", value=owner_name, inline=True)
        embed.add_field(name="👥 Members", value=f"{len(channel.members)}/{user_limit}", inline=True)
        embed.add_field(name="🎧 Bitrate", value=f"{bitrate_kbps} kbps", inline=True)
        embed.add_field(name="📡 Status", value=" • ".join(status_parts), inline=False)
        
        member_list = ", ".join([m.display_name for m in channel.members[:15]])
        if len(channel.members) > 15:
            member_list += f" ... (+{len(channel.members) - 15} more)"
        embed.add_field(name="🧑‍🤝‍🧑 In Channel", value=member_list or "Empty", inline=False)
        embed.set_footer(text="Use /vc panel for interactive controls")
        await ctx.send(embed=embed)

    @vc.command(name="panel", description="Send an interactive control panel for your channel.")
    async def vc_panel(self, ctx):
        """Send a panel with interactive buttons to manage your temporary voice channel."""
        if not await self.check_voice_owner(ctx): return

        channel = ctx.author.voice.channel
        embed = discord.Embed(
            title="🎛️ Voice Channel Control Panel",
            description=f"Control panel for **{channel.name}**\nUse the buttons below to manage your channel.",
            color=discord.Color.from_rgb(88, 101, 242)
        )
        embed.set_footer(text=f"Owner: {ctx.author.display_name}")

        view = VoiceControlPanel(self.bot, ctx.author.id, channel.id)
        await ctx.send(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════════════
#  Interactive Voice Control Panel (Buttons)
# ══════════════════════════════════════════════════════════════════════

class VoiceControlPanel(discord.ui.View):
    def __init__(self, bot, owner_id, channel_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.owner_id = owner_id
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the channel owner can use these controls.", ephemeral=True)
            return False
        return True

    def _get_channel(self, interaction):
        return interaction.guild.get_channel(self.channel_id)

    @discord.ui.button(label="Lock", style=discord.ButtonStyle.danger, emoji="🔒", row=0)
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self._get_channel(interaction)
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return
        default_perms = channel.overwrites_for(interaction.guild.default_role)
        if default_perms.connect is False:
            # Unlock
            await channel.set_permissions(interaction.guild.default_role, connect=True)
            button.label = "Lock"
            button.style = discord.ButtonStyle.danger
            button.emoji = "🔒"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("🔓 Channel unlocked!", ephemeral=True)
        else:
            # Lock
            await channel.set_permissions(interaction.guild.default_role, connect=False)
            button.label = "Unlock"
            button.style = discord.ButtonStyle.success
            button.emoji = "🔓"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("🔒 Channel locked!", ephemeral=True)

    @discord.ui.button(label="Hide", style=discord.ButtonStyle.secondary, emoji="👻", row=0)
    async def hide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self._get_channel(interaction)
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return
        default_perms = channel.overwrites_for(interaction.guild.default_role)
        if default_perms.view_channel is False:
            await channel.set_permissions(interaction.guild.default_role, view_channel=True)
            button.label = "Hide"
            button.emoji = "👻"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("👁️ Channel revealed!", ephemeral=True)
        else:
            await channel.set_permissions(interaction.guild.default_role, view_channel=False)
            button.label = "Reveal"
            button.emoji = "👁️"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("👻 Channel hidden!", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RenameModal(self.bot, self.channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Limit", style=discord.ButtonStyle.primary, emoji="👥", row=1)
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = LimitModal(self.bot, self.channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Bitrate", style=discord.ButtonStyle.primary, emoji="🎧", row=1)
    async def bitrate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BitrateModal(self.bot, self.channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Channel", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self._get_channel(interaction)
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ Deleting channel...", ephemeral=True)
        await self.bot.db.execute("DELETE FROM temp_channels WHERE channel_id = ?", channel.id)
        await channel.delete(reason=f"Deleted by owner via control panel")


class RenameModal(discord.ui.Modal, title="✏️ Rename Channel"):
    new_name = discord.ui.TextInput(
        label="New Channel Name",
        placeholder="e.g. Gaming Lounge",
        max_length=100,
        required=True
    )

    def __init__(self, bot, channel_id):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.edit(name=str(self.new_name))
            await interaction.response.send_message(f"✏️ Channel renamed to **{self.new_name}**!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)


class LimitModal(discord.ui.Modal, title="👥 Set User Limit"):
    user_limit = discord.ui.TextInput(
        label="Max Users (0 = unlimited)",
        placeholder="e.g. 5",
        max_length=3,
        required=True
    )

    def __init__(self, bot, channel_id):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return
        try:
            limit = int(str(self.user_limit))
            limit = max(0, min(limit, 99))
            await channel.edit(user_limit=limit)
            display = str(limit) if limit > 0 else "Unlimited"
            await interaction.response.send_message(f"👥 User limit set to **{display}**!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)


class BitrateModal(discord.ui.Modal, title="🎧 Set Bitrate"):
    bitrate_value = discord.ui.TextInput(
        label="Bitrate in kbps (8-384)",
        placeholder="e.g. 128",
        max_length=3,
        required=True
    )

    def __init__(self, bot, channel_id):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return
        try:
            kbps = int(str(self.bitrate_value))
            max_bitrate = int(interaction.guild.bitrate_limit / 1000)
            kbps = max(8, min(kbps, max_bitrate))
            await channel.edit(bitrate=kbps * 1000)
            quality = "🔴 Low" if kbps < 64 else ("🟡 Normal" if kbps < 128 else ("🟢 High" if kbps < 256 else "💎 Studio"))
            await interaction.response.send_message(f"🎧 Bitrate set to **{kbps} kbps** ({quality})", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Voice(bot))
