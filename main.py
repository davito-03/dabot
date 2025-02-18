import discord
from discord.ext import commands, tasks
import random
import requests
from googletrans import Translator
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix='dabot ', intents=intents)

# Se limpia la lista de chistes y citas usados cada 30 minutos
used_jokes = []  
used_quotes = []  

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
    await ctx.send('pong')

@bot.command()
async def adivina_palabra(ctx):
    await ctx.send("¿Cuál es la dificultad que prefieres? (fácil, medio, difícil)")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    msg = await bot.wait_for('message', check=check)
    dificultad = msg.content.lower()

    # Mapeo de dificultades a rangos de longitud
    dificultad_map = {
        'fácil': (3, 5),
        'medio': (6, 8),
        'difícil': (9, 12)
    }

    min_len, max_len = dificultad_map.get(dificultad, (6, 8))  # Valor predeterminado: medio

    response = requests.get(f"https://random-word-api.herokuapp.com/word?number=1")
    word = response.json()[0]

    while not (min_len <= len(word) <= max_len):
        response = requests.get(f"https://random-word-api.herokuapp.com/word?number=1")
        word = response.json()[0]

    palabra_traducida = word
    guessed_word = ['_'] * len(palabra_traducida)
    attempts = 6

    await ctx.send(f"¡Adivina la palabra! Tienes {attempts} intentos. La palabra tiene {len(palabra_traducida)} letras.")

    while attempts > 0 and '_' in guessed_word:
        await ctx.send(f"Palabra: {''.join(guessed_word)}")
        msg = await bot.wait_for('message', check=check)
        guess = msg.content.lower()

        if guess in palabra_traducida:
            for i, letter in enumerate(palabra_traducida):
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
        await ctx.send(f"Se te acabaron los intentos. La palabra era: {palabra_traducida}")

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

        joke = joke_data['joke'] if joke_data['type'] == 'single' else f"{joke_data['setup']} - {joke_data['delivery']}"

        while joke in used_jokes:
            response = requests.get("https://v2.jokeapi.dev/joke/Miscellaneous?lang=en")
            joke_data = response.json()
            joke = joke_data['joke'] if joke_data['type'] == 'single' else f"{joke_data['setup']} - {joke_data['delivery']}"

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
        joke_data = response.json()

        if response.status_code != 200:
            await ctx.send(f"Hubo un error con la API de chistes. Código de estado: {response.status_code}")
            return

        if joke_data.get('error'):
            await ctx.send(f"Error en los datos recibidos de la API: {joke_data['error']}")
            return

        joke = joke_data['joke'] if joke_data['type'] == 'single' else f"{joke_data['setup']} - {joke_data['delivery']}"

        while joke in used_jokes:
            response = requests.get("https://v2.jokeapi.dev/joke/Any?safe-mode")
            joke_data = response.json()
            joke = joke_data['joke'] if joke_data['type'] == 'single' else f"{joke_data['setup']} - {joke_data['delivery']}"

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
            
bot.run(TOKEN)
