import discord
from discord.ext import commands
from discord import app_commands

class RolePanelSelect(discord.ui.Select):
    """
    Used only during creation to show the preview or if we were using stateful views.
    But for the persistent handling, we rely on the listener.
    """
    def __init__(self, roles: list[discord.Role], max_values: int, placeholder: str = "Select roles..."):
        options = []
        for role in roles[:25]:
            options.append(discord.SelectOption(
                label=role.name,
                value=str(role.id),
                description=f"ID: {role.id}"
            ))
        
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=min(max_values, len(options)),
            options=options,
            custom_id="autoreact:role_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        # We handle this in the listener for persistence, 
        # but if the view is active in memory (just created), this might trigger.
        # So we can just defer or let the listener handle it? 
        # Discord.py usually calls the callback IF the view is attached.
        # If we rely on the listener, we shouldn't fail here.
        # Let's just pass, assuming the listener will catch it globally?
        # WARNING: If a View is attached + Listener exists, BOTH might trigger?
        # Discord.py dispatches to Component Callback first. 
        # If callback handles it, it might stop? No, listeners usually run too.
        # To be safe, let's implement the logic here too OR just not attach this callback 
        # effectively by not doing anything, BUT we need to respond to avoid "Interaction Failed".
        # Actually, best approach: Don't use a callback here. 
        # BUT discord.ui.Select requires a callback if used in a View.
        # We will make this callback call the same logic as the listener if we can,
        # OR we just make sure we DON'T respond twice.
        pass

class RolePanelView(discord.ui.View):
    def __init__(self, roles: list[discord.Role] = None, max_values: int = 1):
        super().__init__(timeout=None)
        if roles:
            self.add_item(RolePanelSelect(roles, max_values))

# --- Setup Views/Modals ---

class PanelSetupModal(discord.ui.Modal, title="Panel Configuration"):
    description = discord.ui.TextInput(
        label="Panel Description",
        style=discord.TextStyle.paragraph,
        placeholder="Choose your roles below...",
        required=True,
        max_length=2000
    )
    
    max_roles = discord.ui.TextInput(
        label="Max Roles Selectable",
        style=discord.TextStyle.short,
        placeholder="1",
        default="1",
        required=True,
        min_length=1,
        max_length=2
    )

    def __init__(self, bot, view_parent):
        super().__init__()
        self.bot = bot
        self.view_parent = view_parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.max_roles.value)
            if limit < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Max roles must be a positive integer.", ephemeral=True)
            return
        
        self.view_parent.panel_description = self.description.value
        self.view_parent.max_values = limit
        await interaction.response.send_message("✅ Configuration saved! Now select the roles to include using the dropdown below.", ephemeral=True)


class AdminRoleSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Search/Select roles to add...",
            min_values=1,
            max_values=25,
            select_type=discord.ComponentType.role_select
        )

    async def callback(self, interaction: discord.Interaction):
        # Filter roles
        valid_roles = []
        invalid_roles = []
        
        for role in self.values:
            if role.permissions.administrator or role.permissions.manage_guild:
                invalid_roles.append(role.name)
            elif role.position >= interaction.guild.me.top_role.position:
                invalid_roles.append(f"{role.name} (Too high)")
            elif role.is_bot_managed():
                invalid_roles.append(f"{role.name} (Bot managed)")
            else:
                valid_roles.append(role)
        
        view: SetupView = self.view
        
        for r in valid_roles:
            if r.id not in [existing.id for existing in view.selected_roles]:
                 if len(view.selected_roles) >= 25:
                     await interaction.response.send_message("❌ Maximum of 25 roles per panel reached.", ephemeral=True)
                     return
                 view.selected_roles.append(r)

        messages = []
        if valid_roles:
            messages.append(f"✅ Added {len(valid_roles)} roles.")
        if invalid_roles:
            messages.append(f"❌ Ignored {len(invalid_roles)} unsafe/invalid roles: {', '.join(invalid_roles)}")
            
        await interaction.response.send_message("\n".join(messages), ephemeral=True)

class SetupView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot
        self.panel_description = "React to get roles!"
        self.max_values = 1
        self.selected_roles = []
        
        self.add_item(AdminRoleSelect())

    @discord.ui.button(label="Edit Description & Limit", style=discord.ButtonStyle.primary, row=2)
    async def edit_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PanelSetupModal(self.bot, self))

    @discord.ui.button(label="Create Panel", style=discord.ButtonStyle.success, row=2)
    async def create_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_roles:
            await interaction.response.send_message("❌ You must select at least one role first!", ephemeral=True)
            return

        # Ensure max_values is accurate to count
        if self.max_values > len(self.selected_roles):
             self.max_values = len(self.selected_roles)

        embed = discord.Embed(
            title="Roles",
            description=self.panel_description,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Select up to {self.max_values} roles")

        final_view = RolePanelView(self.selected_roles, self.max_values)
        
        await interaction.channel.send(embed=embed, view=final_view)
        await interaction.response.send_message("✅ Panel created successfully!", ephemeral=True)

class AutoReact(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def create_role_panel(self, interaction: discord.Interaction):
        view = SetupView(self.bot)
        await interaction.response.send_message(
            "**Role Panel Setup**\n1. Click 'Edit Description' to set text and limits.\n2. Use the dropdown to search and Select roles.\n3. Click 'Create Panel' when done.\n\n*Note: Administrator roles are blocked.*", 
            view=view, 
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        
        custom_id = interaction.data.get('custom_id')
        if custom_id != "autoreact:role_select":
            return
        
        # Check if already responded (if View callback handled it)
        if interaction.response.is_done():
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            selected_values = interaction.data.get('values', [])
            selected_role_ids = set(map(int, selected_values))
            
            all_option_ids = set()
            
            # Find the component options from the message
            for action_row in interaction.message.components:
                for component in action_row.children:
                    if component.custom_id == "autoreact:role_select":
                        for option in component.options:
                            try:
                                all_option_ids.add(int(option.value))
                            except ValueError:
                                pass
                                
            user = interaction.user
            added = []
            removed = []
            errors = []
            
            to_add = []
            to_remove = []

            for role_id in all_option_ids:
                role = interaction.guild.get_role(role_id)
                if not role:
                    continue
                
                # Security Check
                if role.permissions.administrator or role.permissions.manage_guild:
                    errors.append(f"Skipped unsafe role: {role.name}")
                    continue

                if role_id in selected_role_ids:
                    if role not in user.roles:
                        to_add.append(role)
                else:
                    if role in user.roles:
                        to_remove.append(role)
            
            if to_add:
                try:
                    await user.add_roles(*to_add, reason="AutoReact Panel")
                    added.extend([r.name for r in to_add])
                except discord.Forbidden:
                    errors.append("Permission Denied (Heirarchy?)")
                except Exception as e:
                    errors.append(str(e))
                    
            if to_remove:
                try:
                    await user.remove_roles(*to_remove, reason="AutoReact Panel")
                    removed.extend([r.name for r in to_remove])
                except discord.Forbidden:
                    errors.append("Permission Denied (Heirarchy?)")
                except Exception as e:
                    errors.append(str(e))

            response_parts = []
            if added:
                response_parts.append(f"✅ Added: {', '.join(added)}")
            if removed:
                response_parts.append(f"🗑️ Removed: {', '.join(removed)}")
            if errors:
                response_parts.append(f"⚠️ Errors: {', '.join(errors)}")
            
            if not response_parts:
                response_parts.append("ℹ️ No changes made.")
                
            await interaction.followup.send("\n".join(response_parts), ephemeral=True)

        except Exception as e:
            try:
                await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
            except:
                pass

async def setup(bot):
    await bot.add_cog(AutoReact(bot))
