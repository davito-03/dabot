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
async def adivina_palabra(ctx):
    palabras = cargar_palabras()
    await ctx.send("¿Cuál es la dificultad que prefieres? (fácil, medio, difícil)")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    msg = await bot.wait_for('message', check=check)
    dificultad = msg.content.lower()

    if dificultad in palabras:
        palabra = random.choice(palabras[dificultad])
    else:
        await ctx.send("Dificultad no válida. Usando 'medio'.")
        palabra = random.choice(palabras["medio"])

    guessed_word = ['_'] * len(palabra)
    attempts = 6  

    await ctx.send(f"¡Adivina la palabra! Tienes {attempts} intentos. La palabra tiene {len(palabra)} letras.")

    while attempts > 0 and '_' in guessed_word:
        await ctx.send(f"Palabra: {''.join(guessed_word)}")
        msg = await bot.wait_for('message', check=check)
        guess = msg.content.lower()

        if guess in palabra:
            for i, letter in enumerate(palabra):
                if letter == guess:
                    guessed_word[i] = guess
            await ctx.send(f"¡Bien! {guess} está en la palabra.")
        else:
            attempts -= 1
            await ctx.send(f"Incorrecto, te quedan {attempts} intentos.")

        if '_' not in guessed_word:
            await ctx.send(f"¡Felicidades! Adivinaste la palabra: {''.join(guessed_word)}")
            break

    if attempts == 0:
        await ctx.send(f"Se te acabaron los intentos. La palabra era: {palabra}")


@bot.command()
async def cita(ctx):
    try:
        response = requests.get("https://zenquotes.io/api/random")
        
        if response.status_code != 200:
            await ctx.send(f"Hubo un error al obtener la cita. Código de estado: {response.status_code}")
            return

        quote_data = response.json()

        if not quote_data or len(quote_data) == 0:
            await ctx.send("No se pudo obtener una cita válida.")
            return

        quote = quote_data[0].get('q', '')
        author = quote_data[0].get('a', '')

        if not quote or not author:
            await ctx.send("Cita o autor no válidos recibidos.")
            return

        # Evitar que se repita la cita
        while quote in used_quotes:
            response = requests.get("https://zenquotes.io/api/random")
            quote_data = response.json()
            if not quote_data or len(quote_data) == 0:
                await ctx.send("No se pudo obtener una cita válida.")
                return
            quote = quote_data[0].get('q', '')
            author = quote_data[0].get('a', '')

        used_quotes.append(quote)

        quote_text = f"**{quote}**\nPor: {author}"

        translator = Translator()
        translated_quote = translator.translate(quote_text, src='en', dest='es').text

        await ctx.send(f"Aquí tienes una cita:\n\n{translated_quote}")

    except Exception as e:
        await ctx.send(f"Hubo un error al obtener la cita. Detalles: {e}")
        print(f"Error: {e}")

@bot.command()
async def chiste_todos(ctx):
    try:
        response = requests.get("https://v2.jokeapi.dev/joke/Miscellaneous?lang=en")
        joke_data = response.json()

        if response.status_code != 200:
            await ctx.send(f"Hubo un error con la API de chistes. Código de estado: {response.status_code}")
            return

        if joke_data.get('error'):
            await ctx.send(f"Error en los datos recibidos de la API: {joke_data['error']}")
            return

        if joke_data['type'] == 'single':
            joke = joke_data['joke']
        elif joke_data['type'] == 'twopart':
            joke = f"{joke_data['setup']} - {joke_data['delivery']}"

        while joke in used_jokes:
            response = requests.get("https://v2.jokeapi.dev/joke/Miscellaneous?lang=en")
            joke_data = response.json()
            if joke_data['type'] == 'single':
                joke = joke_data['joke']
            elif joke_data['type'] == 'twopart':
                joke = f"{joke_data['setup']} - {joke_data['delivery']}"

        used_jokes.append(joke)

        translator = Translator()
        translated_joke = translator.translate(joke, src='auto', dest='es').text

        await ctx.send(f"Aquí tienes un chiste:\n\n{translated_joke}")

    except Exception as e:
        await ctx.send(f"Hubo un error al obtener el chiste. Detalles: {e}")
        print(f"Error: {e}")

@bot.command()
async def chiste(ctx):
    try:
        response = requests.get("https://v2.jokeapi.dev/joke/Any?safe-mode")

        if response.status_code != 200:
            await ctx.send(f"Hubo un error con la API de chistes. Código de estado: {response.status_code}")
            return

        joke_data = response.json()

        if joke_data.get('error'):
            await ctx.send(f"Error en los datos recibidos de la API: {joke_data['error']}")
            return

        if joke_data['type'] == 'single':
            joke = joke_data['joke']
        elif joke_data['type'] == 'twopart':
            joke = f"{joke_data['setup']} - {joke_data['delivery']}"
        else:
            await ctx.send("No se pudo obtener un chiste válido.")
            return

        while joke in used_jokes:
            response = requests.get("https://v2.jokeapi.dev/joke/Any?safe-mode")
            joke_data = response.json()
            if joke_data['type'] == 'single':
                joke = joke_data['joke']
            elif joke_data['type'] == 'twopart':
                joke = f"{joke_data['setup']} - {joke_data['delivery']}"
            if not joke_data.get('error') and joke:
                break

        used_jokes.append(joke)

        translator = Translator()
        translated_joke = translator.translate(joke, src='auto', dest='es').text

        await ctx.send(f"Aquí tienes un chiste:\n\n{translated_joke}")

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
