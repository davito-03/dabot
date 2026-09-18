import discord
from discord.ext import commands
from discord import app_commands
import datetime
import logging


class PrivateNotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot')

    async def ensure_table(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS user_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

    note_group = app_commands.Group(name="note", description="Manage your private notes.")

    @note_group.command(name="add", description="Add a personal note (only you can see it).")
    @app_commands.describe(text="The note content")
    async def note_add(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        # Check limit
        count_row = await self.bot.db.fetch(
            "SELECT COUNT(*) FROM user_notes WHERE user_id = ?", interaction.user.id
        )
        count = count_row[0] if count_row else 0

        # Check premium (20 free, 100 premium)
        premium = interaction.guild and await self.bot.db.is_guild_premium(interaction.guild, self.bot)
        limit = 100 if premium else 20

        if count >= limit:
            await interaction.followup.send(
                f"❌ You've reached the limit of **{limit}** notes. Delete some first.",
                ephemeral=True
            )
            return

        now = datetime.datetime.now().isoformat()
        await self.bot.db.execute(
            "INSERT INTO user_notes (user_id, text, created_at) VALUES (?, ?, ?)",
            interaction.user.id, text, now
        )
        await interaction.followup.send(f"✅ Note saved! You have {count + 1}/{limit} notes.", ephemeral=True)

    @note_group.command(name="list", description="View all your private notes.")
    async def note_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        notes = await self.bot.db.fetch_all(
            "SELECT id, text, created_at FROM user_notes WHERE user_id = ? ORDER BY id DESC",
            interaction.user.id
        )

        if not notes:
            await interaction.followup.send("📝 You have no notes yet. Use `/note add` to create one.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📝 Your Notes ({len(notes)})",
            color=discord.Color.blurple()
        )
        for note_id, text, created_at in notes[:20]:
            date = created_at.split("T")[0]
            embed.add_field(name=f"Note #{note_id} — {date}", value=text[:256], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @note_group.command(name="delete", description="Delete one of your notes by ID.")
    @app_commands.describe(note_id="The ID of the note to delete (get it from /note list)")
    async def note_delete(self, interaction: discord.Interaction, note_id: int):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        row = await self.bot.db.fetch(
            "SELECT id FROM user_notes WHERE id = ? AND user_id = ?",
            note_id, interaction.user.id
        )
        if not row:
            await interaction.followup.send(f"❌ Note #{note_id} not found.", ephemeral=True)
            return

        await self.bot.db.execute("DELETE FROM user_notes WHERE id = ?", note_id)
        await interaction.followup.send(f"✅ Deleted note #{note_id}.", ephemeral=True)

    @note_group.command(name="clear", description="Delete ALL your notes.")
    async def note_clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        view = discord.ui.View(timeout=30)

        async def confirm_callback(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                return
            await self.bot.db.execute("DELETE FROM user_notes WHERE user_id = ?", interaction.user.id)
            await btn_interaction.response.edit_message(content="✅ All notes deleted.", embed=None, view=None)

        async def cancel_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)

        confirm_btn = discord.ui.Button(label="Delete All", style=discord.ButtonStyle.danger)
        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        confirm_btn.callback = confirm_callback
        cancel_btn.callback = cancel_callback
        view.add_item(confirm_btn)
        view.add_item(cancel_btn)

        await interaction.followup.send("⚠️ Are you sure you want to delete **all** your notes?", view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PrivateNotes(bot))
