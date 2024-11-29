import discord
from discord.ext import commands, tasks
import random
import yt_dlp as ytdlp
import asyncio
import praw
import json
from threading import Thread
import requests
from googletrans import Translator
from dotenv import load_dotenv
import os
import time
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
async def on_ready():
    print(f'Conectado como {bot.user}')
    clear_used_data.start()  

@bot.command()
async def ping(ctx):
    await ctx.send('pong🏓')

@bot.command()
async def guessword(ctx):
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
        await ctx.send(f"¡Felicidades! Adivinaste la palabra: {''.join(guessed_word)}")
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


# Conectar al canal de voz y reproducir música
@bot.command()
async def play(ctx, *, query: str):
    """Busca y reproduce música en un canal de voz"""
    channel = ctx.author.voice.channel  # Obtener el canal de voz
    voice = await channel.connect()  # Conectar al canal de voz

    # Configurar las opciones de búsqueda y descarga
    ydl_opts = {
    'format': 'bestaudio/best',  # Selecciona la mejor calidad de audio
    'postprocessors': [{
        'key': 'FFmpegAudioConvertor',  # Usa FFmpeg para convertir el audio
        'preferredquality': '192',  # Calidad de audio (puedes ajustarla a tu preferencia)
    }],
    'postprocessor_args': ['-vn'],  # Sin video
    'prefer_ffmpeg': True,  # Prefiere FFmpeg si está disponible
    'extractaudio': True,  # Solo extrae el audio
    'audioquality': 1,  # Calidad de audio
    'outtmpl': 'downloads/%(id)s.%(ext)s',  # Ruta de salida
    'restrictfilenames': True,  # Nombres de archivo restrictivos
    }


    # Realizar la búsqueda con yt-dlp
    with ytdlp.YoutubeDL(ydl_opts) as ydl:
        # Buscar el primer resultado de la consulta
        info = ydl.extract_info(f"ytsearch:{query}", download=False)
        # Extraer la URL del primer video encontrado
        video_url = info['entries'][0]['url']
        title = info['entries'][0]['title']

    # Reproducir el audio en el canal de voz
    voice.play(discord.FFmpegPCMAudio(video_url))
    await ctx.send(f"Reproduciendo: {title}")

@bot.command()
async def stop(ctx):
    """Detiene la reproducción y desconecta el bot del canal de voz."""
    await ctx.voice_client.disconnect()
    await ctx.send("Desconectado del canal de voz.")


def run():
    bot.run(TOKEN)

if __name__ == "__main__":
    run()
