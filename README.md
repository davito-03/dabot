# Dabot

Bot de Discord multipropósito y panel web en [dabot.davito.es](https://dabot.davito.es).

Esta copia es la que corre en producción. El repo `dabot-v2` es un archivo de 2025 con otra arquitectura; no lo uses como base.

## Qué hace

Moderación, automod, tickets, niveles (texto y voz), economía, IA (pool de proveedores), música, bienvenidas, logs, backups del servidor, giveaways, starboard, verificación y un dashboard FastAPI con OAuth de Discord.

El sitio público (`templates/` + `static/` + `dashboard_server.py`) vive en el mismo código que el bot (`main.py` + `cogs/`).

## Arranque

```bash
cp .env.example .env
# rellena DISCORD_TOKEN, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
docker compose up -d --build
```

Sin Docker: `python main.py` (bot) y `uvicorn dashboard_server:app --host 127.0.0.1 --port 8090` (panel).

Intents en el portal de Discord: Server Members, Message Content, Presence si usas estados.

## Secretos

Nada de tokens va en el repo. Usa `.env`. Las configs por servidor (`configs/<guild_id>.yaml`) y las bases SQLite tampoco se publican; `configs/default.yaml` es la plantilla.

## Stack

Python 3.11, discord.py 2, FastAPI, SQLite, Docker.
