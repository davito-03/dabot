# Arquitectura de Dabot

Dos procesos, un SQLite WAL.

```mermaid
flowchart LR
  Discord --> Bot[main.py + cogs]
  Bot <--> DB[(dabot.db WAL)]
  API[dashboard_server.py] <--> DB
  API --> Site[dabot.davito.es]
```

- Config **viva**: JSON en `guild_configs`. YAML es plantilla/legado.
- `tts` no se carga. `music` no está en el árbol.
- Liveness API: `webapp/routers/health.py` (`GET /healthz`).
- Estado del bot para la home: `GET /api/status` (heartbeat + ping Discord).
- Compose: `bot` + `api`. El contenedor no corre como root (gosu → uid 1000).
