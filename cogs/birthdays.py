import logging
import discord
from discord.ext import commands, tasks
import datetime
import yaml
import os

class Birthdays(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info('Birthdays Cog loaded.')

    @commands.hybrid_group(name="birthday", description="Manage birthdays.")
    async def birthday(self, ctx):
        if ctx.invoked_subcommand is None:
            # Show user's birthday if no subcommand
            await self.show_birthday(ctx, ctx.author)

    @birthday.command(name="set")
    async def set_birthday(self, ctx, day: int, month: int, year: int = None):
        """
        Set your birthday. Year is optional.
        """
        try:
            # Validate date
            test_year = year if year else 2000 # Leap year safe
            datetime.date(test_year, month, day)
        except ValueError:
            await ctx.send("❌ Invalid date.")
            return

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO birthdays (user_id, day, month, year) VALUES (?, ?, ?, ?)",
            ctx.author.id, day, month, year
        )
        
        await ctx.send(f"✅ Birthday set to **{day}/{month}**" + (f"/{year}" if year else "") + ".")

    @birthday.command(name="remove")
    async def remove_birthday(self, ctx):
        """
        Remove your birthday.
        """
        await self.bot.db.execute("DELETE FROM birthdays WHERE user_id = ?", ctx.author.id)
        await ctx.send("✅ Birthday removed.")

    @birthday.command(name="show")
    async def show_birthday_cmd(self, ctx, user: discord.Member = None):
        """
        Show a user's birthday.
        """
        user = user or ctx.author
        await self.show_birthday(ctx, user)

    async def show_birthday(self, ctx, user):
        data = await self.bot.db.fetch("SELECT day, month, year FROM birthdays WHERE user_id = ?", user.id)
        
        if not data:
            await ctx.send(f"{user.display_name} hasn't set their birthday.")
            return
            
        day, month, year = data
        msg = f"🎂 **{user.display_name}'s Birthday:** {day}/{month}"
        if year:
            msg += f"/{year}"
            
            # Calculate age (rough)
            today = datetime.date.today()
            age = today.year - year - ((today.month, today.day) < (month, day))
            msg += f" ({age} years old)"
            
        await ctx.send(msg)

    @birthday.command(name="upcoming")
    async def upcoming(self, ctx):
        """
        Show upcoming birthdays in this server.
        """
        birthdays = await self.bot.db.fetch_all("SELECT user_id, day, month FROM birthdays ORDER BY month, day")
        
        if not birthdays:
            await ctx.send("No birthdays set.")
            return

        today = datetime.date.today()
        upcoming_list = []
        
        for uid, day, month in birthdays:
            member = ctx.guild.get_member(uid)
            if not member: 
                continue # Skip if user not in server
            
            bday_date = datetime.date(today.year, month, day)
            if bday_date < today:
                bday_date = datetime.date(today.year + 1, month, day)
            
            days_until = (bday_date - today).days
            if 0 <= days_until <= 30: # Show next 30 days
                upcoming_list.append((days_until, member, f"{day}/{month}"))

        upcoming_list.sort(key=lambda x: x[0])
        
        if not upcoming_list:
            await ctx.send("No upcoming birthdays in the next 30 days.")
            return

        embed = discord.Embed(title="🎂 Upcoming Birthdays", color=discord.Color.brand_red())
        lines = []
        for days, member, date_str in upcoming_list:
            if days == 0:
                when = "**TODAY!**"
            elif days == 1:
                when = "Tomorrow"
            else:
                when = f"in {days} days"
            lines.append(f"{member.mention} - {date_str} ({when})")
            
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @birthday.command(name="channel", description="Canal para anuncios de cumpleaños.")
    @commands.has_permissions(administrator=True)
    async def set_birthday_channel(self, ctx, channel: discord.TextChannel):
        """
        Set the channel for birthday announcements.
        """
        self.bot.config.set_config(ctx.guild.id, "birthdays.channel_id", channel.id)
        await ctx.send(f"✅ Birthday announcements will be sent to {channel.mention}")

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc))
    async def check_birthdays(self):
        """Check for birthdays daily at midnight UTC."""
        today = datetime.date.today() # UTC date from system? Wait, loop runs UTC, but we need to serve local time? 
        # For simplicity, we use the bot's system date which seems to be the assumed standard here.
        
        # Actually, let's just match day/month
        matches = await self.bot.db.fetch_all("SELECT user_id, year FROM birthdays WHERE day = ? AND month = ?", today.day, today.month)
        
        if not matches:
            return

        for user_id, year in matches:
            # We need to find which guilds this user is in, AND which of those have birthday channels enabled
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if not member:
                    continue
                    
                config = self.bot.config.get(guild.id, 'birthdays')
                if not config or not config.get('channel_id'):
                    continue
                
                channel = guild.get_channel(config.get('channel_id'))
                if not channel:
                    continue
                    
                age_str = ""
                if year:
                    age = today.year - year
                    age_str = f" ({age}th)"
                
                # Use i18n logic if possible, or hardcoded for now as user just asked for "felicite" (congratulate)
                # Let's try to be fancy and use language if available
                lang = self.bot.config.get(guild.id, 'language') or 'en'
                msg = self.bot.i18n.get("birthdays.happy_birthday", lang, mention=member.mention, age=age_str)
                    
                try:
                    await channel.send(msg)
                except:
                    pass

    @check_birthdays.before_loop
    async def before_check_birthdays(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Birthdays(bot))
