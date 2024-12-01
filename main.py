import discord
from discord.ext import commands, tasks
import random
import asyncio
import praw
import json
from threading import Thread
import requests
from googletrans import Translator
from dotenv import load_dotenv
import os
import time
from datetime import datetime, timedelta
import sympy as sp

def cargar_palabras():
    with open("palabras.json", "r", encoding="utf-8") as file:
        return json.load(file)

def traducir_palabra(palabra):
    url = 'https://libretranslate.de/translate'
    params = {
        'q': palabra,
        'source': 'en',
        'target': 'es'
    }
    response = requests.post(url, data=params)
    return response.json()['translatedText']

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')


WARNINGS_FILE = "warnings.json"
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix='dabot ', intents=intents)

last_message_time = {}
used_jokes = []  
used_quotes = []  

reddit = praw.Reddit(
    client_id=os.getenv('REDDIT_CLIENT_ID'),
    client_secret=os.getenv('REDDIT_SECRET'),
    user_agent=os.getenv('REDDIT_USER_AGENT')
)

@tasks.loop(minutes=30)
async def clear_used_data():
    global used_jokes, used_quotes
    used_jokes.clear()
    used_quotes.clear()
    print("Chistes y citas almacenadas limpiadas.")

@bot.event
async def on_message(message):
    # Evitar que el bot responda a sí mismo
    if message.author == bot.user:
        return

    # Lista de palabras clave para saludar
    saludos = ['hola', 'hi', 'holi', 'ola', '🌊', 'qué tal', 'hello', 'buenas', 'saludos']

    # Verificar si alguna palabra clave está en el mensaje
    if any(saludo in message.content.lower() for saludo in saludos):
        await message.channel.send(f"¡Hola {message.author.mention}! ¿Cómo estás?")

    # Esto es necesario para que los comandos sigan funcionando
    await bot.process_commands(message)

# Función para cargar las advertencias desde el archivo
def load_warnings():
    try:
        with open(WARNINGS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Función para guardar las advertencias en el archivo
def save_warnings(warnings_data):
    with open(WARNINGS_FILE, "w") as f:
        json.dump(warnings_data, f, indent=4)

# Inicializar advertencias
warnings = load_warnings()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Detectar más de 12 letras consecutivas en mayúsculas
    if any(len(word) > 12 and word.isupper() for word in message.content.split()):
        try:
            await message.delete()

            user_id = str(message.author.id)
            user_name = str(message.author.name)
            if user_id not in warnings:
                warnings[user_id] = {"name": user_name, "count": 1}
            else:
                warnings[user_id]["count"] += 1

            count = warnings[user_id]["count"]
            save_warnings(warnings)

            # Mensaje directo
            try:
                await message.author.send(
                    f"Hola, {message.author.name}. Tu mensaje en **{message.guild.name}** fue eliminado porque contenía más de 12 letras consecutivas en mayúsculas. "
                    f"Esta es tu advertencia número {count}. Por favor, evita usar mayúsculas excesivas."
                )
            except discord.Forbidden:
                await message.channel.send(
                    f"{message.author.mention}, no pude enviarte un mensaje directo. Revisa tu configuración de privacidad. Esta es tu advertencia número {count}."
                )

            # Sanciones progresivas
            if count == 5:
                timeout_until = datetime.utcnow() + timedelta(hours=1)
                await message.author.timeout(timeout_until, reason="Exceso de advertencias (5). Timeout de 1 hora.")
                await message.channel.send(f"{message.author.mention} ha recibido un timeout de 1 hora por acumular 5 advertencias.")

            elif count == 10:
                timeout_until = datetime.utcnow() + timedelta(days=1)
                await message.author.timeout(timeout_until, reason="Exceso de advertencias (10). Timeout de 1 día.")
                await message.channel.send(f"{message.author.mention} ha recibido un timeout de 1 día por acumular 10 advertencias.")

            elif count == 15:
                await message.guild.ban(message.author, reason="Exceso de advertencias (15). Usuario baneado.")
                await message.channel.send(f"{message.author.mention} ha sido baneado del servidor por acumular 15 advertencias.")
                
        except discord.Forbidden:
            await message.channel.send(
                "No tengo permisos para borrar mensajes o aplicar sanciones en este canal."
            )

    # Procesar otros comandos
    await bot.process_commands(message)

@bot.event
async def on_message(message):
    # Evitar que el bot se responda a sí mismo
    if message.author == bot.user:
        return

    # Detectar más de 12 letras consecutivas en mayúsculas
    if any(len(word) > 12 and word.isupper() for word in message.content.split()):
        try:
            await message.delete()
            # Intentar enviar un mensaje directo al usuario
            try:
                await message.author.send(
                    f"Hola, {message.author.name}. Tu mensaje en **{message.guild.name}** fue eliminado porque contenía más de 12 letras consecutivas en mayúsculas. Por favor, evita usar mayúsculas de forma excesiva."
                )
            except discord.Forbidden:
                # Si no es posible enviar un mensaje directo, notificar en el servidor
                await message.channel.send(
                    f"{message.author.mention}, no pude enviarte un mensaje directo. Por favor, revisa tu configuración de privacidad."
                )
        except discord.Forbidden:
            await message.channel.send(
                "No tengo permisos para borrar mensajes en este canal, pero por favor, evita usar mayúsculas excesivas."
            )

    # Procesar otros comandos
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f'Conectado como {bot.user}')
    clear_used_data.start()  

@bot.command()
async def ping(ctx):
    await ctx.send('pong🏓')

@bot.command()
@commands.has_permissions(ban_members=True)
async def banear(ctx, user_id: int, *, reason=None):
    try:
        # Buscar al usuario por su ID
        user = await bot.fetch_user(user_id)

        # Obtener el miembro en el servidor
        member = ctx.guild.get_member(user_id)
        
        # Si no es un miembro del servidor, enviar un mensaje
        if member is None:
            await ctx.send(f"No se encontró un miembro con el ID {user_id} en este servidor.")
            return

        # Si se encuentra el miembro, proceder al baneo
        await member.ban(reason=reason)

        # Informar al canal
        await ctx.send(f"El usuario {user.name} ha sido baneado correctamente.")

        # Enviar un mensaje directo al usuario baneado
        try:
            await user.send(f"Has sido baneado del servidor {ctx.guild.name}. Razón: {reason if reason else 'No se proporcionó una razón.'}")
        except discord.errors.Forbidden:
            pass  # En caso de que no se pueda enviar mensaje directo al usuario

    except discord.NotFound:
        await ctx.send(f"No se pudo encontrar el usuario con el ID {user_id}.")
    except discord.Forbidden:
        await ctx.send("No tengo permisos para banear a este usuario.")
    except discord.HTTPException as e:
        await ctx.send(f"Ocurrió un error al intentar banear: {e}")


@bot.command()
async def ahorcado(ctx):
    await ctx.send("¿Cuál es la dificultad que prefieres? (fácil, medio, difícil)")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    msg = await bot.wait_for('message', check=check)
    dificultad = msg.content.lower()

    if dificultad not in ["fácil", "medio", "difícil"]:
        await ctx.send("Dificultad no válida. Por defecto se usará 'medio'.")
        dificultad = "medio"

    # Cargar palabras desde el archivo JSON
    try:
        with open("palabras.json", "r") as f:
            palabras_data = json.load(f)
            palabras = palabras_data.get(dificultad, [])
    except FileNotFoundError:
        await ctx.send("El archivo de palabras no se encontró. Por favor, asegúrate de que 'palabras.json' está presente.")
        return

    if not palabras:
        await ctx.send(f"No hay palabras disponibles para la dificultad '{dificultad}'.")
        return

    # Elegir una palabra aleatoria
    palabra_secreta = random.choice(palabras).lower()
    guessed_word = ['_'] * len(palabra_secreta)
    letras_adivinadas = set()

    # Determinar intentos según dificultad
    intentos = {"fácil": 12, "medio": 9, "difícil": 6}[dificultad]

    await ctx.send(f"¡Adivina la palabra! Tienes {intentos} intentos. La palabra tiene {len(palabra_secreta)} letras.")

    while intentos > 0 and '_' in guessed_word:
        await ctx.send(f"Palabra: {' '.join(guessed_word)}\nIntentos restantes: {intentos}")
        msg = await bot.wait_for('message', check=check)
        guess = msg.content.lower()

        # Validación de la entrada
        if len(guess) != 1 or not guess.isalpha():
            await ctx.send("Por favor, ingresa solo una letra válida.")
            continue

        if guess in letras_adivinadas:
            await ctx.send(f"Ya intentaste la letra '{guess}'. Prueba con otra.")
            continue

        letras_adivinadas.add(guess)

        if guess in palabra_secreta:
            for i, letter in enumerate(palabra_secreta):
                if letter == guess:
                    guessed_word[i] = guess
            await ctx.send(f"¡Bien hecho! '{guess}' está en la palabra.")
        else:
            intentos -= 1
            await ctx.send(f"¡Fallaste! La letra '{guess}' no está en la palabra.")

    if '_' not in guessed_word:
        await ctx.send(f"¡Felicidades! Adivinaste la palabra: {''.join(guessed_word)}. Si quieres volvere a jugar pon de nuevo el comando.")
    else:
        await ctx.send(f"Se acabaron los intentos. La palabra era: {palabra_secreta}.")


@bot.command()
async def cita(ctx):
    try:
        # Cargar citas desde el archivo JSON
        with open('citas.json', 'r', encoding='utf-8') as f:
            citas_data = json.load(f)

        # Si ya se han mostrado todas las citas, reiniciamos la lista de citas usadas
        if len(used_quotes) >= len(citas_data):
            used_quotes.clear()

        # Elegir una cita aleatoria que no se haya mostrado antes
        available_quotes = [cita for cita in citas_data if cita['quote'] not in used_quotes]
        
        if not available_quotes:
            await ctx.send("No hay citas disponibles.")
            return
        
        random_quote = random.choice(available_quotes)
        quote = random_quote['quote']
        author = random_quote['author']

        # Evitar que se repita la cita
        used_quotes.append(quote)

        quote_text = f"**{quote}**\nPor: {author}"


        await ctx.send(f"Aquí tienes una cita:\n\n{quote_text}")

    except Exception as e:
        await ctx.send(f"Hubo un error al obtener la cita. Detalles: {e}")
        print(f"Error: {e}")

# Comando para enviar un chiste
@bot.command()
async def chiste(ctx):
    try:
        # Cargar los chistes desde el archivo JSON
        with open('chistes.json', 'r', encoding='utf-8') as file:
            chistes_data = json.load(file)

        # Verificar si el archivo JSON tiene chistes
        if not chistes_data:
            await ctx.send("No hay chistes disponibles.")
            return

        # Escoger un chiste aleatorio
        chiste_data = random.choice(chistes_data)
        joke = chiste_data.get('joke', '')
        delivery = chiste_data.get('delivery', '')

        # Verificar si el chiste tiene contenido
        if not joke:
            await ctx.send("No se pudo obtener un chiste válido.")
            return

        # Asegurarse de que el chiste no se repita
        while joke in used_jokes:
            chiste_data = random.choice(chistes_data)
            joke = chiste_data.get('joke', '')
            delivery = chiste_data.get('delivery', '')

        # Añadir el chiste a la lista de usados
        used_jokes.append(joke)

        # Componer el chiste completo
        if delivery:
            full_joke = f"{joke} - {delivery}"
        else:
            full_joke = joke

        # Enviar el chiste tal cual está
        await ctx.send(f"Aquí tienes un chiste:\n\n{full_joke}")

    except Exception as e:
        await ctx.send(f"Hubo un error al obtener el chiste. Detalles: {e}")
        print(f"Error: {e}")

@bot.command()
async def meme(ctx, subreddit_name="memes"):
    try:
        subreddit = reddit.subreddit(subreddit_name)
        post = subreddit.random()

        if not post:
            await ctx.send(f"No encontré ningún meme en el subreddit **{subreddit_name}**. Revisa si existe o prueba con otro.")
            return

        if not post.over_18:
            if post.is_video:
                await ctx.send(f"**{post.title}**\n{post.url}")
            elif post.url.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                embed = discord.Embed(title=post.title, url=post.url)
                embed.set_image(url=post.url)
                embed.set_footer(text=f"👍 {post.score} | 💬 {post.num_comments} comentarios")
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"**{post.title}**\n{post.url}")
        else:
            await ctx.send("El meme seleccionado era NSFW, no puedo mostrarlo aquí. ¡Prueba de nuevo!")

    except Exception as e:
        await ctx.send(f"No pude obtener un meme de **{subreddit_name}**. Intenta más tarde o prueba con otro subreddit.")
        print(e)

@bot.command()
async def guessnum(ctx):
    num = random.randint(1, 100)
    await ctx.send("Adivina un número entre 1 y 100")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    while True:
        msg = await bot.wait_for('message', check=check)
        try:
            guess = int(msg.content)
            if guess < num:
                await ctx.send("Intenta algo más alto.")
            elif guess > num:
                await ctx.send("Intenta algo más bajo.")
            else:
                await ctx.send(f"¡Correcto! El número era {num}. ¡Bien hecho!")
                break
        except ValueError:
            await ctx.send("Por favor, ingresa un número válido.")

@bot.command()
async def gato(ctx):
    response = requests.get("https://api.thecatapi.com/v1/images/search")
    data = response.json()
    await ctx.send(data[0]["url"])

@bot.command()
async def perro(ctx):
    response = requests.get("https://dog.ceo/api/breeds/image/random")
    data = response.json()
    await ctx.send(data["message"])

@bot.command()
async def ppt(ctx, choice: str):
    choices = ["piedra", "papel", "tijera"]
    if choice.lower() not in choices:
        await ctx.send("Por favor, elige entre piedra, papel o tijera.")
        return
    
    bot_choice = random.choice(choices)
    result = ""
    
    if choice.lower() == bot_choice:
        result = "Es un empate."
    elif (choice.lower() == "piedra" and bot_choice == "tijera") or \
         (choice.lower() == "papel" and bot_choice == "piedra") or \
         (choice.lower() == "tijera" and bot_choice == "papel"):
        result = "¡Ganaste!"
    else:
        result = "¡Perdiste!"

    await ctx.send(f"Tu elección: {choice}\nElección del bot: {bot_choice}\n{result}")

@bot.command()
async def ayuda(ctx):
    embed = discord.Embed(title="Comandos Disponibles", description="Aquí tienes una lista de los comandos que puedes usar con este bot:", color=0x00ff00)
    
    embed.add_field(name="`ping`", value="Responde con 'pong 🏓'. Ideal para probar si el bot está funcionando.", inline=False)
    embed.add_field(name="`ahorcado`", value="Inicia un juego de ahorcado. Puedes elegir entre diferentes niveles de dificultad.", inline=False)
    embed.add_field(name="`cita`", value="Muestra una cita motivacional o reflexiva aleatoria.", inline=False)
    embed.add_field(name="`chiste`", value="Cuenta un chiste aleatorio para alegrarte el día.", inline=False)
    embed.add_field(name="`meme [subreddit]`", value="Muestra un meme aleatorio del subreddit especificado (por defecto, 'memes').", inline=False)
    embed.add_field(name="`guessnum`", value="Adivina un número entre 1 y 100. El bot te guía si estás cerca.", inline=False)
    embed.add_field(name="`gato`", value="Envía una imagen aleatoria de un gato.", inline=False)
    embed.add_field(name="`perro`", value="Envía una imagen aleatoria de un perro.", inline=False)
    embed.add_field(name="`ppt [piedra/papel/tijera]`", value="Juega piedra, papel o tijera contra el bot.", inline=False)
    
    await ctx.send(embed=embed)

def run():
    bot.run(TOKEN)

if __name__ == "__main__":
    run()
