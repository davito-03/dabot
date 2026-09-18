import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import random
import datetime

class Trivia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.Trivia')
        self.active_trivias = {}      # channel_id -> {question, answer, reward}
        self.last_trivia_runs = {}    # guild_id -> datetime
        self.auto_trivia_loop.start()

    def cog_unload(self):
        self.auto_trivia_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_tables()
        self.logger.info('Trivia Cog loaded and initialized.')

    async def ensure_tables(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS trivia_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS trivia_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                reward INTEGER DEFAULT 100,
                interval_minutes INTEGER DEFAULT 0
            )
        """)

    # App Command Group for Trivia
    trivia_group = app_commands.Group(
        name="trivia",
        description="Sistema de preguntas y respuestas (Trivia)."
    )

    @trivia_group.command(name="agregar", description="Añade una pregunta de trivia a la base de datos (Solo Admins).")
    @app_commands.describe(
        pregunta="La pregunta que se formulará.",
        respuesta="La respuesta exacta requerida (no distingue mayúsculas/minúsculas)."
    )
    @app_commands.default_permissions(administrator=True)
    async def trivia_add(self, interaction: discord.Interaction, pregunta: str, respuesta: str):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        await self.bot.db.execute(
            "INSERT INTO trivia_questions (question, answer) VALUES (?, ?)",
            pregunta.strip(), respuesta.strip()
        )
        await interaction.followup.send("✅ Pregunta de trivia añadida con éxito.", ephemeral=True)

    @trivia_group.command(name="eliminar", description="Elimina una pregunta de trivia por su ID (Solo Admins).")
    @app_commands.describe(id="ID de la pregunta a eliminar (puedes verlo usando /trivia listar).")
    @app_commands.default_permissions(administrator=True)
    async def trivia_delete(self, interaction: discord.Interaction, id: int):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        existing = await self.bot.db.fetch("SELECT 1 FROM trivia_questions WHERE id = ?", id)
        if not existing:
            await interaction.followup.send("❌ No se encontró ninguna pregunta con ese ID.", ephemeral=True)
            return

        await self.bot.db.execute("DELETE FROM trivia_questions WHERE id = ?", id)
        await interaction.followup.send(f"✅ Pregunta con ID {id} eliminada con éxito.", ephemeral=True)

    @trivia_group.command(name="listar", description="Muestra todas las preguntas de trivia configuradas (Solo Admins).")
    @app_commands.default_permissions(administrator=True)
    async def trivia_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        questions = await self.bot.db.fetch_all("SELECT id, question, answer FROM trivia_questions LIMIT 50")
        if not questions:
            await interaction.followup.send("❌ No hay preguntas en la base de datos.", ephemeral=True)
            return

        embed = discord.Embed(title="📝 Preguntas de Trivia", color=discord.Color.orange())
        desc = ""
        for q_id, q_text, a_text in questions:
            desc += f"**ID {q_id}:** {q_text} | *R: {a_text}*\n"
        embed.description = desc

        await interaction.followup.send(embed=embed, ephemeral=True)

    @trivia_group.command(name="configurar", description="Ajusta el canal y tiempo de las trivias automáticas (Solo Admins).")
    @app_commands.describe(
        channel="Canal donde se enviarán las preguntas automáticas.",
        premio="Cantidad de monedas que se otorgan al ganador.",
        intervalo_minutos="Intervalo en minutos de envío automático (0 para desactivar)."
    )
    @app_commands.default_permissions(administrator=True)
    async def trivia_config_setup(self, interaction: discord.Interaction, channel: discord.TextChannel, premio: int, intervalo_minutos: int = 0):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_tables()

        if premio <= 0:
            await interaction.followup.send("❌ El premio debe ser mayor a 0 monedas.", ephemeral=True)
            return
        if intervalo_minutos < 0:
            await interaction.followup.send("❌ El intervalo no puede ser negativo.", ephemeral=True)
            return

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO trivia_config (guild_id, channel_id, reward, interval_minutes) VALUES (?, ?, ?, ?)",
            interaction.guild.id, channel.id, premio, intervalo_minutos
        )

        status = f"Activado cada {intervalo_minutos} minutos" if intervalo_minutos > 0 else "Desactivado"
        await interaction.followup.send(
            f"✅ Configuración de trivia actualizada:\n"
            f"**Canal:** {channel.mention}\n"
            f"**Premio:** {premio} monedas\n"
            f"**Auto-envío:** {status}",
            ephemeral=True
        )

    @trivia_group.command(name="jugar", description="Lanza una pregunta de trivia al azar de forma manual.")
    async def trivia_play(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.ensure_tables()

        channel = interaction.channel
        if channel.id in self.active_trivias:
            await interaction.followup.send("❌ Ya hay una trivia activa en este canal esperando respuesta.", ephemeral=True)
            return

        # Fetch reward
        config = await self.bot.db.fetch("SELECT reward FROM trivia_config WHERE guild_id = ?", interaction.guild.id)
        reward = config[0] if config else 100

        # Fetch random question
        question_data = await self.bot.db.fetch("SELECT id, question, answer FROM trivia_questions ORDER BY RANDOM() LIMIT 1")
        if not question_data:
            await interaction.followup.send("❌ No hay preguntas de trivia registradas en la base de datos. Pide a un administrador que agregue algunas con `/trivia agregar`.")
            return

        q_id, question, answer = question_data

        # Save to active trivias
        self.active_trivias[channel.id] = {
            "question": question,
            "answer": answer,
            "reward": reward
        }

        embed = discord.Embed(
            title="📝 ¡Trivia Express!",
            description=(
                f"**Pregunta:**\n{question}\n\n"
                f"⚠️ *¡Escribe la respuesta correcta en el chat para ganar **{reward}** monedas!*"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="No distingues mayúsculas de minúsculas")
        await interaction.followup.send(embed=embed)

    async def post_auto_trivia(self, channel, reward):
        if channel.id in self.active_trivias:
            return

        question_data = await self.bot.db.fetch("SELECT id, question, answer FROM trivia_questions ORDER BY RANDOM() LIMIT 1")
        if not question_data:
            return

        q_id, question, answer = question_data
        self.active_trivias[channel.id] = {
            "question": question,
            "answer": answer,
            "reward": reward
        }

        embed = discord.Embed(
            title="📝 ¡Trivia Automática!",
            description=(
                f"**Pregunta:**\n{question}\n\n"
                f"⚠️ *¡Escribe la respuesta correcta en el chat para ganar **{reward}** monedas!*"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="Responde rápido en el chat")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        channel_id = message.channel.id
        if channel_id not in self.active_trivias:
            return

        active = self.active_trivias[channel_id]
        user_ans = message.content.strip().lower()
        correct_ans = active["answer"].strip().lower()

        if user_ans == correct_ans:
            # We have a winner! Remove active trivia first to avoid double rewards
            self.active_trivias.pop(channel_id, None)

            reward = active["reward"]
            eco_cog = self.bot.get_cog("Economy")
            if eco_cog:
                await eco_cog.update_balance(message.author.id, reward, "wallet", message.guild.id)

            embed = discord.Embed(
                title="🎉 ¡Respuesta Correcta!",
                description=(
                    f"¡Enhorabuena {message.author.mention}!\n"
                    f"La respuesta era: **{active['answer']}**\n\n"
                    f"🎁 Has ganado **{reward}** monedas para tu cartera."
                ),
                color=discord.Color.green()
            )
            await message.reply(embed=embed)

    # Background loop for auto posting trivias
    @tasks.loop(minutes=1)
    async def auto_trivia_loop(self):
        await self.bot.wait_until_ready()
        try:
            await self.ensure_tables()
            configs = await self.bot.db.fetch_all(
                "SELECT guild_id, channel_id, reward, interval_minutes FROM trivia_config WHERE interval_minutes > 0"
            )
            now = datetime.datetime.now()

            for guild_id, channel_id, reward, interval in configs:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue

                last_run = self.last_trivia_runs.get(guild_id)
                if last_run and (now - last_run).total_seconds() / 60 < interval:
                    continue

                self.last_trivia_runs[guild_id] = now
                await self.post_auto_trivia(channel, reward)

        except Exception as e:
            self.logger.error(f"Error en bucle auto_trivia_loop: {e}")

    @auto_trivia_loop.before_loop
    async def before_trivia_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Trivia(bot))
