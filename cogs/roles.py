import discord
from discord.ext import commands
from discord import app_commands


def _parse_emoji(raw: str | None):
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return raw


class AutoroleButton(discord.ui.Button):
    def __init__(self, role: discord.Role, label: str, emoji: str | None = None):
        kwargs = {
            "style": discord.ButtonStyle.secondary,
            "label": (label or role.name)[:80],
            "custom_id": f"rr_{role.id}",
        }
        parsed = _parse_emoji(emoji)
        if parsed:
            kwargs["emoji"] = parsed
        super().__init__(**kwargs)


def build_autorole_view(title: str, description: str, options: list) -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(title=title[:256], description=description[:4000], color=0xE23D28)
    embed.set_footer(text="Pulsa de nuevo para quitar el rol · Dabot")
    view = discord.ui.View(timeout=None)
    for name, role, emoji in options[:25]:
        if not role:
            continue
        view.add_item(AutoroleButton(role, name, emoji))
        mention = role.mention if hasattr(role, "mention") else str(role)
        embed.add_field(name=f"{emoji or '•'} {name}", value=mention, inline=True)
    return embed, view


class RoleDropdownSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], placeholder: str = "Elige tus roles...", max_values: int = 1):
        super().__init__(
            placeholder=placeholder[:100],
            min_values=0,
            max_values=min(max(1, max_values), len(options)),
            options=options[:25],
            custom_id="dabot:roleselect",
        )


def build_dropdown_view(title: str, description: str, options: list[discord.SelectOption], placeholder: str, max_values: int) -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(title=title[:256], description=description[:4000], color=0x3498DB)
    embed.set_footer(text="Despliega el menú para obtener o quitar roles · Dabot")
    view = discord.ui.View(timeout=None)
    view.add_item(RoleDropdownSelect(options, placeholder=placeholder, max_values=max_values))
    return embed, view


async def handle_role_selection(interaction: discord.Interaction, selected_values: list[str]):
    guild = interaction.guild
    member = interaction.user
    if not isinstance(member, discord.Member) or not guild:
        return

    # Extract all role options from the message select component
    menu_role_ids = set()
    if interaction.message and interaction.message.components:
        for action_row in interaction.message.components:
            for comp in getattr(action_row, "children", []):
                if getattr(comp, "custom_id", "").startswith("dabot:roleselect") and hasattr(comp, "options"):
                    for opt in comp.options:
                        try:
                            menu_role_ids.add(int(opt.value))
                        except Exception:
                            pass

    selected_ids = {int(v) for v in selected_values if v.isdigit()}
    if not menu_role_ids:
        menu_role_ids = selected_ids

    bot_top_role = guild.me.top_role

    to_add = []
    to_remove = []
    skipped = []

    for r_id in menu_role_ids:
        role = guild.get_role(r_id)
        if not role:
            continue
        if role >= bot_top_role or role.managed or role.permissions.administrator:
            skipped.append(role.name)
            continue

        if r_id in selected_ids:
            if role not in member.roles:
                to_add.append(role)
        else:
            if role in member.roles:
                to_remove.append(role)

    try:
        if to_add:
            await member.add_roles(*to_add, reason="Selección interactiva de roles en dropdown Dabot")
        if to_remove:
            await member.remove_roles(*to_remove, reason="Selección interactiva de roles en dropdown Dabot")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Error de permisos: No puedo gestionar algunos roles debido a la jerarquía.", ephemeral=True)
        return

    lines = ["**Roles actualizados:**"]
    if to_add:
        lines.append("➕ **Añadidos:** " + ", ".join(r.mention for r in to_add))
    if to_remove:
        lines.append("➖ **Retirados:** " + ", ".join(r.mention for r in to_remove))
    if skipped:
        lines.append(f"⚠️ *(Sin permisos para gestionar: {', '.join(skipped)})*")
    if not to_add and not to_remove and not skipped:
        lines.append("No hubo cambios en tus roles.")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    roles_group = app_commands.Group(name="roles", description="Autorole and reaction-role panels.")

    @roles_group.command(name="reactpanel", description="Crea un panel de roles con reacciones.")
    @app_commands.default_permissions(manage_roles=True)
    async def roles_reactpanel(self, interaction: discord.Interaction):
        cog = self.bot.get_cog("AutoReact")
        if not cog:
            await interaction.response.send_message("❌ Módulo autoreact no cargado.", ephemeral=True)
            return
        await cog.create_role_panel(interaction)

    @roles_group.command(name="panel", description="Post an embed panel with roles, emojis and option names in one command.")
    @app_commands.describe(
        titulo="Título del embed",
        descripcion="Texto del panel",
        opcion1_nombre="Nombre de la opción 1",
        opcion1_rol="Rol de la opción 1",
        opcion1_emoji="Emoji de la opción 1",
        opcion2_nombre="Nombre de la opción 2",
        opcion2_rol="Rol de la opción 2",
        opcion2_emoji="Emoji de la opción 2",
        opcion3_nombre="Nombre de la opción 3",
        opcion3_rol="Rol de la opción 3",
        opcion3_emoji="Emoji de la opción 3",
        opcion4_nombre="Nombre de la opción 4",
        opcion4_rol="Rol de la opción 4",
        opcion4_emoji="Emoji de la opción 4",
        opcion5_nombre="Nombre de la opción 5",
        opcion5_rol="Rol de la opción 5",
        opcion5_emoji="Emoji de la opción 5",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def roles_panel(
        self,
        interaction: discord.Interaction,
        titulo: str,
        descripcion: str,
        opcion1_nombre: str,
        opcion1_rol: discord.Role,
        opcion1_emoji: str,
        opcion2_nombre: str | None = None,
        opcion2_rol: discord.Role | None = None,
        opcion2_emoji: str | None = None,
        opcion3_nombre: str | None = None,
        opcion3_rol: discord.Role | None = None,
        opcion3_emoji: str | None = None,
        opcion4_nombre: str | None = None,
        opcion4_rol: discord.Role | None = None,
        opcion4_emoji: str | None = None,
        opcion5_nombre: str | None = None,
        opcion5_rol: discord.Role | None = None,
        opcion5_emoji: str | None = None,
    ):
        triples = [
            (opcion1_nombre, opcion1_rol, opcion1_emoji),
            (opcion2_nombre, opcion2_rol, opcion2_emoji),
            (opcion3_nombre, opcion3_rol, opcion3_emoji),
            (opcion4_nombre, opcion4_rol, opcion4_emoji),
            (opcion5_nombre, opcion5_rol, opcion5_emoji),
        ]
        options = []
        for name, role, emoji in triples:
            if not role:
                continue
            if role.permissions.administrator or role.managed:
                continue
            options.append((name or role.name, role, emoji))
        if not options:
            await interaction.response.send_message("❌ Añade al menos un rol válido (sin admin).", ephemeral=True)
            return
        embed, view = build_autorole_view(titulo, descripcion, options)
        await interaction.response.send_message("✅ Panel publicado. Se puede borrar el mensaje si no lo quieres.", ephemeral=True)
        await interaction.channel.send(embed=embed, view=view)

    async def _create_dropdown_panel(
        self,
        interaction: discord.Interaction,
        titulo: str,
        descripcion: str,
        placeholder: str,
        max_selecciones: int,
        roles: list[discord.Role]
    ):
        valid_roles = []
        bot_top = interaction.guild.me.top_role
        for r in roles:
            if not r:
                continue
            if r.permissions.administrator or r.managed:
                continue
            if r >= bot_top:
                continue
            if r not in valid_roles:
                valid_roles.append(r)

        if not valid_roles:
            await interaction.response.send_message(
                "❌ No has proporcionado roles válidos que Dabot pueda asignar (revisa que estén por debajo del rol del bot y no tengan permisos de Administrador).",
                ephemeral=True
            )
            return

        select_options = []
        for r in valid_roles[:25]:
            select_options.append(discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description=f"Rol con {len(r.members)} miembros"[:100]
            ))

        embed, view = build_dropdown_view(
            titulo=titulo,
            description=descripcion,
            options=select_options,
            placeholder=placeholder,
            max_values=min(max_selecciones, len(select_options))
        )

        await interaction.response.send_message("✅ Menú desplegable de roles publicado con éxito.", ephemeral=True)
        await interaction.channel.send(embed=embed, view=view)

    @roles_group.command(name="dropdown", description="Crea un menú desplegable (Select Menu) interactivo para seleccionar roles.")
    @app_commands.describe(
        titulo="Título del panel",
        descripcion="Descripción explicativa para los usuarios",
        placeholder="Texto del menú desplegable antes de abrirlo",
        max_selecciones="Cantidad máxima de roles que se pueden seleccionar a la vez",
        rol1="Primer rol seleccionable",
        rol2="Segundo rol seleccionable",
        rol3="Tercer rol seleccionable",
        rol4="Cuarto rol seleccionable",
        rol5="Quinto rol seleccionable",
        rol6="Sexto rol seleccionable",
        rol7="Séptimo rol seleccionable",
        rol8="Octavo rol seleccionable",
        rol9="Noveno rol seleccionable",
        rol10="Décimo rol seleccionable"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def roles_dropdown(
        self,
        interaction: discord.Interaction,
        titulo: str = "🎭 Menú de Roles",
        descripcion: str = "Selecciona tus roles en el menú desplegable inferior:",
        placeholder: str = "Elige tus roles aquí...",
        max_selecciones: int = 1,
        rol1: discord.Role = None,
        rol2: discord.Role = None,
        rol3: discord.Role = None,
        rol4: discord.Role = None,
        rol5: discord.Role = None,
        rol6: discord.Role = None,
        rol7: discord.Role = None,
        rol8: discord.Role = None,
        rol9: discord.Role = None,
        rol10: discord.Role = None,
    ):
        roles_list = [r for r in [rol1, rol2, rol3, rol4, rol5, rol6, rol7, rol8, rol9, rol10] if r]
        if not roles_list:
            await interaction.response.send_message("❌ Debes especificar al menos un rol en `rol1`.", ephemeral=True)
            return
        await self._create_dropdown_panel(interaction, titulo, descripcion, placeholder, max_selecciones, roles_list)

    @app_commands.command(name="rolemenu", description="Crea un panel interactivo con menú desplegable (Select Menu) para elegir roles.")
    @app_commands.describe(
        titulo="Título del panel",
        descripcion="Descripción explicativa para los usuarios",
        placeholder="Texto del menú desplegable antes de abrirlo",
        max_selecciones="Cantidad máxima de roles que se pueden seleccionar a la vez",
        rol1="Primer rol seleccionable",
        rol2="Segundo rol seleccionable",
        rol3="Tercer rol seleccionable",
        rol4="Cuarto rol seleccionable",
        rol5="Quinto rol seleccionable",
        rol6="Sexto rol seleccionable",
        rol7="Séptimo rol seleccionable",
        rol8="Octavo rol seleccionable",
        rol9="Noveno rol seleccionable",
        rol10="Décimo rol seleccionable"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def rolemenu_top(
        self,
        interaction: discord.Interaction,
        titulo: str = "🎭 Menú de Roles",
        descripcion: str = "Selecciona tus roles en el menú desplegable inferior:",
        placeholder: str = "Elige tus roles aquí...",
        max_selecciones: int = 1,
        rol1: discord.Role = None,
        rol2: discord.Role = None,
        rol3: discord.Role = None,
        rol4: discord.Role = None,
        rol5: discord.Role = None,
        rol6: discord.Role = None,
        rol7: discord.Role = None,
        rol8: discord.Role = None,
        rol9: discord.Role = None,
        rol10: discord.Role = None,
    ):
        roles_list = [r for r in [rol1, rol2, rol3, rol4, rol5, rol6, rol7, rol8, rol9, rol10] if r]
        if not roles_list:
            await interaction.response.send_message("❌ Debes especificar al menos un rol en `rol1`.", ephemeral=True)
            return
        await self._create_dropdown_panel(interaction, titulo, descripcion, placeholder, max_selecciones, roles_list)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get('custom_id', '')

        # Handle Role Dropdown Select Menu
        if custom_id.startswith('dabot:roleselect'):
            values = interaction.data.get('values', [])
            await handle_role_selection(interaction, values)
            return

        if not (custom_id.startswith('rr_') or custom_id.startswith('dabot:role:')):
            return

        # Handle Role Button
        try:
            role_id = int(custom_id.split(':')[-1] if custom_id.startswith('dabot:role:') else custom_id.split('_')[1])
            role = interaction.guild.get_role(role_id)

            if not role:
                await interaction.response.send_message("❌ Role not found. It might have been deleted.", ephemeral=True)
                return

            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(f"❌ Removed {role.mention}", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"✅ Added {role.mention}", ephemeral=True)

        except discord.Forbidden:
             await interaction.response.send_message("❌ I do not have permission to manage this role. Please check my role hierarchy.", ephemeral=True)
        except Exception as e:
             await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @commands.group(name="rr", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def rr(self, ctx):
        await ctx.send("Usage: `/rr add <message_link> <role> [label] [emoji]`")

    @rr.command(name="add")
    @commands.has_permissions(administrator=True)
    async def rr_add(self, ctx, message_link: str, role: discord.Role, label: str = None, emoji: str = None):
        """Add a reaction role button to a message."""
        try:
            parts = message_link.split('/')
            message_id = int(parts[-1])
            channel_id = int(parts[-2])
            channel = ctx.guild.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
        except:
            await ctx.send("❌ Invalid message link.")
            return

        view = discord.ui.View.from_message(message)

        if len(view.children) >= 25:
             await ctx.send("❌ This message has too many buttons.")
             return

        label = label or role.name
        custom_id = f"rr_{role.id}"

        button = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=label,
            custom_id=custom_id,
            emoji=emoji
        )

        view.add_item(button)

        await message.edit(view=view)
        await ctx.send(f"✅ Added button for {role.mention} to the message.")

    @rr.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def rr_remove(self, ctx, message_link: str, role: discord.Role):
        """Remove a reaction role button from a message."""
        try:
            parts = message_link.split('/')
            message_id = int(parts[-1])
            channel_id = int(parts[-2])
            channel = ctx.guild.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
        except:
            await ctx.send("❌ Invalid message link.")
            return

        view = discord.ui.View.from_message(message)
        target_id = f"rr_{role.id}"

        found = False
        new_children = []
        for child in view.children:
            if hasattr(child, "custom_id") and child.custom_id == target_id:
                found = True
                continue
            new_children.append(child)

        if not found:
             await ctx.send("❌ Button for that role not found on the message.")
             return

        new_view = discord.ui.View()
        for child in new_children:
            new_view.add_item(child)

        await message.edit(view=new_view)
        await ctx.send(f"✅ Removed button for {role.name}.")


async def setup(bot):
    await bot.add_cog(Roles(bot))
