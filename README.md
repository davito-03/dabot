<p align="center">
  <img src="https://davito.es/media/dabot.png" width="140" alt="Dabot">
</p>

<h1 align="center">Dabot</h1>

<p align="center">
  <strong>Bot de Discord + dashboard</strong> que diseño, programo y dejo corriendo yo.<br>
  <a href="https://dabot.davito.es">dabot.davito.es</a>
  ·
  <a href="https://davito.es/proyectos">portfolio</a>
  ·
  <a href="https://github.com/davito-03">@davito-03</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
  <img alt="discord.py" src="https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-dashboard-009688?logo=fastapi&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-yellow">
</p>

Esta es la copia de **producción**. `dabot-v2` es un archivo de 2025 con otra arquitectura; no lo uses como base.

Ficha larga (módulos, panel, OAuth, IA): [davito.es/proyectos/dabot](https://davito.es/proyectos/dabot) · diagrama interno: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Qué hay aquí

| Capa | Qué hace |
| --- | --- |
| Bot (`main.py`, `cogs/`) | Moderación, automod, tickets, niveles (texto y voz), economía, IA, música, bienvenidas, logs, backups, giveaways, starboard, verificación |
| Web (`dashboard_server.py`, `templates/`, `static/`) | Panel público en [dabot.davito.es](https://dabot.davito.es) con OAuth de Discord, i18n, staff y cuenta de usuario |
| Datos | SQLite + `configs/default.yaml` como plantilla. Las configs por guild y las bases no se publican |

Lo hice para usarlo de verdad, no como demo: Docker, healthchecks, rotación de logs y un pool de proveedores de IA.

## Arranque

```bash
cp .env.example .env
# DISCORD_TOKEN, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
docker compose up -d --build
```

Sin Docker: `python main.py` y `uvicorn dashboard_server:app --host 127.0.0.1 --port 8090`.

Intents en el portal: **Server Members**, **Message Content**. Presence si usas estados.

## Secretos

Nada de tokens en el repo. `.env` local. `configs/<guild_id>.yaml` y `*.db` fuera de git.

## Relacionado

- Portfolio: [davito.es/proyectos](https://davito.es/proyectos)
- Hub: [davito.es](https://davito.es)
- Nexo (TypeScript): [nexo-bot](https://github.com/davito-03/nexo-bot)
