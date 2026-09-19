<p align="center">
  <img src="https://davito.es/media/dabot.png" width="140" alt="Dabot">
</p>

<h1 align="center">Dabot</h1>

<p align="center">
  Bot de Discord + panel FastAPI en producción.<br>
  <a href="https://dabot.davito.es">dabot.davito.es</a>
  ·
  <a href="https://davito.es/proyectos/dabot">ficha</a>
</p>

## Qué es

Un bot multipropósito **y** un dashboard con OAuth2 de Discord (PKCE). Lo opero yo en un VPS: no es un tutorial.

## Qué no es

- No carga música ni TTS (`music` no está; `tts` se salta).
- La config viva **no** es YAML por guild: es JSON en SQLite (`guild_configs`). `configs/default.yaml` es plantilla/import.
- No hay broker de colas ni Postgres. Un SQLite WAL compartido entre bot y API.
- El panel es un FastAPI aún denso; `/healthz` vive en `webapp/routers/health.py`.

## Arquitectura

```
Discord Gateway → main.py (cogs/) ⇄ dabot.db (WAL) ⇄ dashboard_server.py → dabot.davito.es
```

Compose: `bot` (`python main.py`) y `api` (`uvicorn`, `127.0.0.1:8090`). Health: `/tmp/bot_alive` y `GET /healthz`.

## Stack

Python 3.11, discord.py 2, FastAPI, aiosqlite/sqlite3, Docker.

## Arranque

```bash
cp .env.example .env   # DISCORD_TOKEN, SUPER_OWNER_ID, OAuth client, …
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pytest
docker compose up -d --build
```

Sin Docker: `python main.py` y `uvicorn dashboard_server:app --host 127.0.0.1 --port 8090`.

Intents en el portal: **Server Members**, **Message Content**, Presence.

## Tests

```bash
pip install pytest ruff
pytest
ruff check .
```

CI: `.github/workflows/ci.yml`.

## Secretos

Nada en git. Sin `DISCORD_TOKEN` / `SUPER_OWNER_ID` el proceso **sale**. `data/`, `logs/`, configs por guild y `*.db` fuera del repo.

## Relacionado

[nexo-bot](https://github.com/davito-03/nexo-bot) · [telegram-drive](https://github.com/davito-03/telegram-drive) · [davito.es](https://davito.es)
