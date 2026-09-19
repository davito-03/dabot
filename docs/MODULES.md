# Módulos de Dabot

Inventario del árbol en el VPS. **68 cogs cargados**. `tts.py` está en disco y se salta. No hay cog `music`.

Cada fila es un fichero en `cogs/`.

## Moderación y seguridad

| Cog | Qué hace |
| --- | --- |
| `moderation.py` | Grupo `/mod`: kick, ban, timeout, warns, purge, apelaciones, CSV. |
| `automod.py` | Spam, flood, invites, unicode, `/antilinks`. |
| `discord_automod.py` | Puente con las reglas nativas de Discord. |
| `antiraid.py` | Lockdown por flood de joins. |
| `antinuke.py` | Límites y whitelist contra acciones masivas. |
| `hijack_guard.py` | Detección de secuestro de canales/webhooks. |
| `quarantine.py` | Aislamiento de miembros. |
| `logging.py` | Canales de log (mensajes, voz, miembros, mod, …). |
| `verification.py` | Captcha / emoji / math; la web aporta IP y device. |
| `privacy.py` | Exportar / borrar datos (GDPR). |

Utilidades: `utils/alt_intel.py`, `utils/proxy_detect.py`, `utils/privacy_crypto.py`, `utils/antilinks.py`, `utils/abuse.py`, `utils/hijack.py`.

## Tickets y staff

| Cog | Qué hace |
| --- | --- |
| `tickets.py` | Panel, categorías, mensajes en SQLite, transcripts HTML. |
| `ticket_extras.py` | CSAT y snippets. |
| `staffdesk.py` | Mesa de staff. |

Transcripts también en el panel: `/tickets/{id}/transcript`.

## Progreso y comunidad

| Cog | Qué hace |
| --- | --- |
| `leveling.py` | XP de texto (cooldown 60 s) y loop de voz, tarjetas Pillow, roles por nivel. |
| `achievements.py` | Logros. |
| `reputation.py` | Reputación. |
| `stats.py` | Contadores / canales de stats. |
| `voice_stats.py` | Tiempo en voz. |
| `welcome_cards.py` | Tarjetas de bienvenida. |
| `onboarding.py` | Onboarding. |
| `birthdays.py` | Cumpleaños. |
| `bump.py` | Bump / recordatorio. |
| `suggestions.py` | Sugerencias del guild. |
| `bot_feedback.py` | Feedback al bot. |
| `digest.py` / `recap.py` | Resúmenes. |

## IA

| Cog | Qué hace |
| --- | --- |
| `chatbot.py` | Compañero con pool de proveedores y tools. |
| `ai_moderation.py` | Moderación de texto con modelo. |
| `ai_tools.py` | Herramientas de IA auxiliares. |
| `games_ia.py` | Minijuegos con modelo. |
| `translator.py` | Traducción. |

Cliente y recambio: `utils/gemini_client.py`. Allow-list de ficheros: `utils/llm_fs.py`.

## Economía y juegos

| Cog | Qué hace |
| --- | --- |
| `economy.py` | Economía **por servidor**. |
| `casino.py` | Casino. |
| `games.py` / `games_extra.py` | Minijuegos. |
| `trivia.py` | Trivia. |
| `fun.py` / `interactions.py` | Fun / interacciones. |

## Voz y social

| Cog | Qué hace |
| --- | --- |
| `voice.py` | Join-to-create (canales temporales). |
| `lastfm.py` | Last.fm (scrobbles / now playing, también en `/cuenta`). |
| `streams.py` | Alertas de stream. |
| `social.py` | Perfiles (bio, redes). |
| `chat.py` | Utilidades de chat. |
| `afk.py` | AFK. |
| `starboard.py` | Starboard. |
| `forums.py` | Foros. |
| `polls.py` | Encuestas. |
| `giveaways.py` | Sorteos. |
| `rss.py` | Feeds RSS. |

## Gestión del servidor

| Cog | Qué hace |
| --- | --- |
| `server_backup.py` | Backup / restore (también desde el panel). |
| `server_templates.py` | Plantillas de roles/canales. |
| `management.py` | Gestión general. |
| `roles.py` / `role_shop.py` / `colors.py` | Roles, tienda, colores. |
| `embed_builder.py` | Constructor de embeds. |
| `custom_commands.py` | Comandos custom. |
| `autoresponse.py` / `autoreact.py` | Autorespuestas / autoreacciones. |
| `announcements.py` | Anuncios (origen + fan-out). |
| `scheduler.py` | Mensajes programados. |
| `webhooks_mgr.py` | Webhooks. |
| `github_hooks.py` | Hooks de GitHub. |
| `admin.py` | Admin / owner. |
| `utility.py` | Utilidades. |
| `user_install.py` | Comandos instalables a nivel usuario. |
| `live_cache.py` | Caché live para el panel. |
| `notes_private.py` | Notas privadas. |

## No se carga

| Fichero | Estado |
| --- | --- |
| `tts.py` | En el árbol. `skip = {"tts", "music"}` en `main.py`. |
| `music` | No existe en el árbol. |

## Utils de plataforma (no son cogs)

`database.py` (aiosqlite WAL), `config.py` (JSON por guild), `envcheck.py` (fail-fast), `i18n.py`, `helpers.py`, `permissions.py`, `premium.py`, `health.py`, `webhooks.py`, `lastfm.py`, `images.py`, `verify_log.py`, `bot_suggestions.py`, `announcements.py`, `ai_repair.py`, `server_templates.py`, `template_posts.py`.

## Panel — páginas

`templates/`: `index`, `dashboard`, `servers`, `niveles`, `normas`, `verify`, `premium`, `cuenta`, `comunidad`, `help`, `privacy`, `terms`, `cookies`.
