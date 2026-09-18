import discord
from discord.ext import commands
import random
import re
import datetime

class CustomCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        try:
            await self.bot.db.execute("ALTER TABLE custom_commands ADD COLUMN usage_count INTEGER DEFAULT 0")
        except Exception:
            pass

    async def _render_template(self, template: str, message: discord.Message) -> str:
        try:
            prefix = await self.bot.get_prefix(message)
            if isinstance(prefix, list):
                prefix = prefix[0]
        except:
            prefix = "!"
            
        content = message.content[len(prefix):]
        parts = content.split(' ', 1)
        trigger = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        now = datetime.datetime.now()

        usage_count = 0
        try:
            row = await self.bot.db.fetch("SELECT usage_count FROM custom_commands WHERE guild_id = ? AND trigger = ?", message.guild.id, trigger)
            if row and row[0] is not None:
                usage_count = row[0]
        except Exception:
            pass

        replacements = {
            "{user}": message.author.mention,
            "{user.mention}": message.author.mention,
            "{user.name}": message.author.display_name,
            "{user.id}": str(message.author.id),
            "{user.tag}": str(message.author),
            "{user.avatar}": str(message.author.display_avatar.url) if message.author.display_avatar else "",
            "{server}": message.guild.name,
            "{server.name}": message.guild.name,
            "{server.id}": str(message.guild.id),
            "{server.members}": str(message.guild.member_count),
            "{server.icon}": str(message.guild.icon.url) if message.guild.icon else "",
            "{channel}": message.channel.mention,
            "{channel.mention}": message.channel.mention,
            "{channel.name}": message.channel.name,
            "{channel.id}": str(message.channel.id),
            "{args}": args,
            "{date}": now.strftime("%d/%m/%Y"),
            "{time}": now.strftime("%H:%M"),
        }

        result = template
        for k, v in replacements.items():
            result = result.replace(k, v)

        def random_match(m):
            opts = m.group(1).split('|')
            return random.choice(opts)
        result = re.sub(r'\{random:(.*?)\}', random_match, result)

        count_matches = list(re.finditer(r'\{count:(.*?)\}', result))
        for m in count_matches:
            t = m.group(1)
            if t == trigger:
                val = str(usage_count)
            else:
                try:
                    row = await self.bot.db.fetch("SELECT usage_count FROM custom_commands WHERE guild_id = ? AND trigger = ?", message.guild.id, t)
                    val = str(row[0]) if (row and row[0] is not None) else "0"
                except Exception:
                    val = "0"
            result = result.replace(m.group(0), val)
            
        return result

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        try:
            prefix = await self.bot.get_prefix(message)
            if isinstance(prefix, list):
                prefix = prefix[0]
        except:
            prefix = "!"
        if not message.content.startswith(prefix):
            return
        content = message.content[len(prefix):]
        parts = content.split()
        if not parts:
            return
        trigger = parts[0]
        if self.bot.get_command(trigger):
            return
            
        cmd_data = await self.bot.db.fetch(
            "SELECT response, type FROM custom_commands WHERE guild_id = ? AND trigger = ?",
            message.guild.id, trigger
        )
        if cmd_data:
            response, type_ = cmd_data
            
            rendered_response = await self._render_template(response, message)
            
            if type_ == 'embed':
                embed = discord.Embed(description=rendered_response, color=discord.Color.blue())
                await message.channel.send(embed=embed)
            else:
                await message.channel.send(rendered_response)
                
            try:
                await self.bot.db.execute("UPDATE custom_commands SET usage_count = COALESCE(usage_count, 0) + 1 WHERE guild_id = ? AND trigger = ?", message.guild.id, trigger)
            except Exception:
                pass

    @commands.group(name="customcmd", aliases=["cc"], description="Manage custom commands.", invoke_without_command=True)
    async def customcmd(self, ctx):
        await ctx.send_help(ctx.command)

    @customcmd.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def cc_add(self, ctx, trigger: str, *, response: str):
        if not await self.bot.db.is_guild_premium(ctx.guild, self.bot):
            from utils.premium import deny_text
            from utils.helpers import guild_lang
            await ctx.send(deny_text(guild_lang(self.bot, ctx.guild.id)))
            return
        exists = await self.bot.db.fetch("SELECT 1 FROM custom_commands WHERE guild_id = ? AND trigger = ?", ctx.guild.id, trigger)
        if exists:
            await ctx.send(f"❌ Command `{trigger}` already exists.")
            return
        await self.bot.db.execute(
            "INSERT INTO custom_commands (guild_id, trigger, response, created_by) VALUES (?, ?, ?, ?)",
            ctx.guild.id, trigger, response, ctx.author.id
        )
        await ctx.send(f"✅ Added command `{trigger}`.")

    @customcmd.command(name="edit")
    @commands.has_permissions(manage_guild=True)
    async def cc_edit(self, ctx, trigger: str, *, response: str):
        exists = await self.bot.db.fetch("SELECT 1 FROM custom_commands WHERE guild_id = ? AND trigger = ?", ctx.guild.id, trigger)
        if not exists:
            await ctx.send(f"❌ Command `{trigger}` not found.")
            return
        await self.bot.db.execute("UPDATE custom_commands SET response = ? WHERE guild_id = ? AND trigger = ?", response, ctx.guild.id, trigger)
        await ctx.send(f"✅ Updated command `{trigger}`.")

    @customcmd.command(name="remove", aliases=["del", "delete"])
    @commands.has_permissions(manage_guild=True)
    async def cc_remove(self, ctx, trigger: str):
        exists = await self.bot.db.fetch("SELECT 1 FROM custom_commands WHERE guild_id = ? AND trigger = ?", ctx.guild.id, trigger)
        if not exists:
            await ctx.send(f"❌ Command `{trigger}` not found.")
            return
        await self.bot.db.execute("DELETE FROM custom_commands WHERE guild_id = ? AND trigger = ?", ctx.guild.id, trigger)
        await ctx.send(f"✅ Deleted command `{trigger}`.")

    @customcmd.command(name="list")
    async def cc_list(self, ctx):
        cmds = await self.bot.db.fetch_all("SELECT trigger FROM custom_commands WHERE guild_id = ?", ctx.guild.id)
        if not cmds:
            await ctx.send("No custom commands found.")
            return
        trigger_list = ", ".join([f"`{c[0]}`" for c in cmds])
        embed = discord.Embed(title="Custom Commands", description=trigger_list, color=discord.Color.blue())
        await ctx.send(embed=embed)

    @customcmd.command(name="variables", aliases=["vars"])
    async def cc_variables(self, ctx):
        embed = discord.Embed(title="Custom Command Variables", description="You can use these variables in your custom commands:", color=discord.Color.blue())
        embed.add_field(name="User", value="`{user}` - Mention user\n`{user.name}` - Display name\n`{user.id}` - User ID\n`{user.tag}` - Username#0000\n`{user.avatar}` - Avatar URL", inline=False)
        embed.add_field(name="Server", value="`{server}` - Server name\n`{server.id}` - Server ID\n`{server.members}` - Member count\n`{server.icon}` - Server icon URL", inline=False)
        embed.add_field(name="Channel", value="`{channel}` - Mention channel\n`{channel.name}` - Channel name\n`{channel.id}` - Channel ID", inline=False)
        embed.add_field(name="Misc", value="`{args}` - Command arguments\n`{date}` - Current date (DD/MM/YYYY)\n`{time}` - Current time (HH:MM)", inline=False)
        embed.add_field(name="Functions", value="`{random:opt1|opt2}` - Pick a random option\n`{count:trigger}` - Number of times a command was used", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
