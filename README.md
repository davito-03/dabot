<p align="center">
  <img src="https://davito.es/media/dabot.png" width="140" alt="Dabot">
</p>

<h1 align="center">Dabot</h1>

<p align="center">
  Bot de Discord + panel FastAPI <strong>en producción</strong>.<br>
  Lo diseño, lo programo y lo opero en un VPS. Este repo es esa copia, sin secretos.
</p>

<p align="center">
  <a href="https://dabot.davito.es">dabot.davito.es</a>
  ·
  <a href="https://davito.es/proyectos/dabot">ficha</a>
  ·
  <a href="docs/ARCHITECTURE.md">arquitectura</a>
  ·
  <a href="docs/MODULES.md">módulos</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
  <img alt="discord.py" src="https://img.shields.io/badge/discord.py-2-5865F2?logo=discord&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.x-009688?logo=fastapi&logoColor=white">
  <img alt="SQLite WAL" src="https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white">
</p>

Estado público (sin auth): [`GET /api/status`](https://dabot.davito.es/api/status) y [`GET /healthz`](https://dabot.davito.es/healthz).

## Qué es

Un producto, no un bot de tres comandos. El mismo código cubre:

1. Un proceso Discord (`main.py` + `cogs/`) con slash commands, eventos y jobs.
2. Un panel web (`dashboard_server.py` + `webapp/`) en [dabot.davito.es](https://dabot.davito.es) donde el staff entra con Discord OAuth2 **PKCE S256** y configura el guild.

En el VPS ahora mismo: **68 cogs cargados**, **~45k líneas de Python**, **~100 tablas** en un SQLite WAL compartido entre bot y API, **9 idiomas**.

## Qué no es (a propósito)

| Se podría pensar | Lo que hay de verdad |
| --- | --- |
| Bot de música | `music` no está en el árbol. `tts.py` existe y **no se carga**. `yt-dlp` queda en `requirements.txt` de esa época. |
| YAML por servidor | La config viva es JSON en `guild_configs`. `configs/default.yaml` es plantilla/import. |
| Postgres + Redis + cola | Un SQLite WAL. Sin broker. |
| Panel de adorno | FastAPI con OAuth, CSRF, CSP, HSTS, tickets, backups, consola live. Sigue siendo un fichero denso (~6k líneas); `/healthz` y `/api/status` ya viven en `webapp/routers/`. |
| LLM que escribe el disco | Las tools públicas buscan/dibujan/consultan. `read_file` / `list_dir` solo owner, allow-list (`utils/llm_fs.py`). No hay write ni restart. |

## Arquitectura

```
Discord Gateway
      │
      ▼
  main.py  ── cogs/ (68) ──┐
      │                    │
      │   dabot.db (WAL)   │
      │         ▲          │
      │         │          │
dashboard_server.py ◄──────┘
      │
      ▼
dabot.davito.es   nginx → 127.0.0.1:8090
```

Diagrama y arranque: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Compose levanta **dos servicios** del mismo Dockerfile:

| Servicio | Comando | Health |
| --- | --- | --- |
| `dabot-bot` | `python main.py` | fichero `/tmp/bot_alive` (< 60 s) |
| `dabot-api` | `uvicorn dashboard_server:app` | `GET /healthz` |

El contenedor arranca como root solo para `chown` y pasa a **uid 1000** con `gosu` (`docker-entrypoint.sh`). El puerto de la API solo escucha en localhost.

## Stack

Python 3.11 · discord.py 2 · FastAPI · uvicorn · aiosqlite / sqlite3 · aiohttp · Pillow · Docker Compose · nginx (TLS fuera de este repo).

Intents en el portal: **Server Members**, **Message Content**, **Presence**, más moderation / voice / invites / webhooks / AutoMod.

## Módulos

Lista completa y honesta: **[docs/MODULES.md](docs/MODULES.md)**. Agrupados:

- **Moderación y seguridad** — `/mod`, AutoMod propio + nativo, anti-raid, anti-nuke, hijack, cuarentena, logs, verificación web (IP/device), privacidad GDPR.
- **Tickets y staff** — panel, transcripts HTML, CSAT, snippets, mesa de staff.
- **Progreso** — XP texto/voz, tarjetas, logros, reputación, bienvenidas.
- **IA** — pool Gemini / Groq / Cohere / OpenAI / OpenRouter / HF / Cloudflare, moderación de texto, traductor.
- **Economía y juegos** — por guild, casino, minijuegos.
- **Voz y social** — join-to-create, Last.fm, streams, perfiles.
- **Servidor** — backups ZIP, plantillas, roles, comandos custom, RSS, starboard, giveaways, foros, anuncios, webhooks, GitHub hooks.

`main.py` parchea `Context.send` e `InteractionResponse.send_message` para traducir embeds sin que cada cog sepa de i18n (`langs/*.json`: es, en, fr, de, it, pt, ja, ko, zh).

## Panel (dabot.davito.es)

Páginas: `/` `/dashboard` `/servers` `/niveles` `/normas` `/verify` `/premium` `/cuenta` `/comunidad` `/help` más legal (`/privacy` `/terms` `/cookies`).

La API autenticada cubre config del guild, infracciones y apelaciones, tickets (reply/close/transcript), leaderboard, economía, backups/restore, plantillas, anti-raid/anti-nuke, miembros, alts, verificación, consola live de mensajes, anuncios y GDPR. Webhooks: Stripe, Sellix, Discord entitlements.

Login: OAuth2 + PKCE S256, state en SQLite, cookie de sesión, CSRF en `POST/PUT/PATCH/DELETE /api/*`.

## Árbol (lo que publica este repo)

```
main.py                 bot, intents, i18n, carga de cogs, crash-loop guard
dashboard_server.py     FastAPI (aún monolítico) + include de routers
webapp/routers/         healthz, /api/status
cogs/                   69 ficheros; 68 se cargan, tts se salta
utils/                  SQLite, config JSON, i18n, IA, privacidad, alts
templates/ static/      HTML/CSS/JS del panel
langs/                  traducciones bot
tests/                  pytest (env, payload de status, allow-list LLM, helpers)
docs/                   arquitectura y mapa de módulos
Dockerfile              python:3.11-slim + gosu uid 1000
docker-compose.yml      bot + api, bind mounts, healthchecks
```

No va a git: `.env`, `data/`, `logs/`, `*.db`, YAML por guild, sesiones.

## Arranque

```bash
cp .env.example .env   # DISCORD_TOKEN, SUPER_OWNER_ID, OAuth, …
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pytest
docker compose up -d --build
```

Sin Docker: `python main.py` y `uvicorn dashboard_server:app --host 127.0.0.1 --port 8090`.

Obligatorios: `DISCORD_TOKEN`, `SUPER_OWNER_ID`. La API también exige `DISCORD_CLIENT_ID` y `DISCORD_CLIENT_SECRET`. Si faltan, el proceso **sale**. El resto (claves de IA, Stripe, Last.fm) es opcional y está listado vacío en `.env.example`.

## Tests

```bash
pip install pytest ruff
pytest
ruff check .
```

CI local: `.github/workflows/ci.yml` (ruff + pytest). Hace falta un PAT con scope `workflow` para subirlo a Actions.

## Relacionado

[nexo-bot](https://github.com/davito-03/nexo-bot) · [telegram-drive](https://github.com/davito-03/telegram-drive) · [davito.es](https://davito.es)
