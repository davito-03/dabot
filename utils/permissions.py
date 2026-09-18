import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import json
import os

def check_custom_staff_permission(guild_id, member, required_perm, channel):
    """
    Checks if a member has a custom staff permission in a specific channel/category or globally.
    required_perm is one of: 'ban', 'kick', 'warn', 'timeout', 'resolve_appeals', 'manage_config', 'admin'
    """
    if not guild_id or not member:
        return False
        
    # Keep bot-side custom permissions on the same database used by the
    # dashboard/compose deployment. The previous hard-coded path could make
    # the bot read a stale /app/dabot.db instead of /app/data/dabot.db.
    db_path = os.environ.get("DATABASE_PATH", "dabot.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT role_id, permissions, scope_type, scoped_channels FROM staff_permissions WHERE guild_id = ?", (guild_id,))
        rows = cursor.fetchall()
        
        user_role_ids = [role.id for role in getattr(member, "roles", [])]
        
        for row in rows:
            role_id = row["role_id"]
            if role_id in user_role_ids:
                try:
                    perms = json.loads(row["permissions"])
                    scope_type = row["scope_type"]
                    scoped_chans = json.loads(row["scoped_channels"]) if row["scoped_channels"] else []
                except Exception:
                    continue
                    
                # If they have the specific perm or admin
                if required_perm in perms or "admin" in perms:
                    if scope_type == "global":
                        return True
                    elif scope_type == "channels":
                        if str(channel.id) in scoped_chans or channel.id in scoped_chans:
                            return True
                    elif scope_type == "categories":
                        category_id = getattr(channel, "category_id", None)
                        if category_id and (str(category_id) in scoped_chans or category_id in scoped_chans):
                            return True
        return False
    except Exception as e:
        print(f"Error checking custom staff permissions: {e}")
        return False
    finally:
        conn.close()

def map_discord_perms_to_custom(perms_dict):
    """Maps discord permissions keyword arguments to a custom permission string."""
    if perms_dict.get("administrator"):
        return "admin"
    if perms_dict.get("ban_members"):
        return "ban"
    if perms_dict.get("kick_members"):
        return "kick"
    if perms_dict.get("moderate_members"):
        return "timeout"
    if perms_dict.get("manage_guild") or perms_dict.get("manage_channels") or perms_dict.get("manage_roles"):
        return "manage_config"
    return None

def patch_permissions(super_owner_id):
    """
    Monkey-patches discord.ext.commands.has_permissions and related checks
    to always return True for the super_owner_id or if they have custom staff roles.
    """
    # 1. Patch discord.ext.commands.has_permissions
    original_has_permissions = commands.has_permissions

    def new_has_permissions(**perms):
        original_predicate = original_has_permissions(**perms).predicate

        async def extended_predicate(ctx):
            if super_owner_id and ctx.author.id == super_owner_id:
                return True
            
            # Check native permissions
            try:
                if await original_predicate(ctx):
                    return True
            except Exception:
                pass
                
            # Check database custom staff roles
            custom_perm = map_discord_perms_to_custom(perms)
            if custom_perm and ctx.guild:
                if check_custom_staff_permission(ctx.guild.id, ctx.author, custom_perm, ctx.channel):
                    return True
            
            raise commands.MissingPermissions(perms.keys())
        
        return commands.check(extended_predicate)

    commands.has_permissions = new_has_permissions

    # 2. Patch discord.ext.commands.has_guild_permissions
    original_has_guild_permissions = commands.has_guild_permissions

    def new_has_guild_permissions(**perms):
        original_predicate = original_has_guild_permissions(**perms).predicate

        async def extended_predicate(ctx):
            if super_owner_id and ctx.author.id == super_owner_id:
                return True
            
            try:
                if await original_predicate(ctx):
                    return True
            except Exception:
                pass
                
            custom_perm = map_discord_perms_to_custom(perms)
            if custom_perm and ctx.guild:
                if check_custom_staff_permission(ctx.guild.id, ctx.author, custom_perm, ctx.channel):
                    return True

            raise commands.MissingPermissions(perms.keys())

        return commands.check(extended_predicate)

    commands.has_guild_permissions = new_has_guild_permissions

    # 3. Patch discord.app_commands.checks.has_permissions (Slash Commands)
    original_app_has_permissions = app_commands.checks.has_permissions

    def new_app_has_permissions(**perms):
        original_decorator = original_app_has_permissions(**perms)
        
        def decorator(func):
            async def extended_predicate(interaction: discord.Interaction) -> bool:
                if super_owner_id and interaction.user.id == super_owner_id:
                    return True
                
                # Check native permissions
                permissions = interaction.permissions
                missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]
                if not missing:
                    return True
                
                # Check database custom staff roles
                custom_perm = map_discord_perms_to_custom(perms)
                if custom_perm and interaction.guild:
                    if check_custom_staff_permission(interaction.guild_id, interaction.user, custom_perm, interaction.channel):
                        return True

                raise app_commands.MissingPermissions(missing or perms.keys())

            return app_commands.check(extended_predicate)(func)

        return decorator

    app_commands.checks.has_permissions = new_app_has_permissions

    print(f"Permissions patched for Super Owner and custom database staff roles.")
