import sqlite3
import json
import os
import time
import copy
import threading

DEFAULT_CONFIG = {
    "lang": "es-ES",
    "prefix": "!",
    "authorizations": {
        "EVERYONE": 0
    },
    "moderation": {
        "mute_role_id": "",
        "appeals_channel": "",
        "appeal_managers": [],
        "antispam": {
            "enabled": False,
            "max_level_bypass": 90
        },
        "escalate": {
            "enabled": False,
            "warns_timeout": 3,
            "timeout_minutes": 30,
            "warns_kick": 5,
            "window_hours": 24
        }
    },
    "leveling": {
        "enabled": False,
        "text_xp": {
            "min": 15,
            "max": 25
        },
        "voice_xp": {
            "min": 10,
            "max": 20
        },
        "ignored_channels": [],
        "ignored_roles": [],
        "leaderboard_channel": "",
        "level_up_channel": "",
        "remove_xp_on_leave": False,
        "card_custom_text": "",
        "card_layout": {}
    },
    "logs": {
        "messages": "",
        "voice": "",
        "members": "",
        "joins": "",
        "moderation": "",
        "alts": "",
        "hijack": "",
        "tickets": "",
        "server": "",
        "verification": ""
    },
    "messages": {
        "warn": "You have been warned in **{server}** for: {reason}",
        "kick": "You have been kicked from **{server}**. Reason: {reason}",
        "ban": "You have been banned from **{server}**. Reason: {reason}",
        "tempban": "You have been temporarily banned from **{server}** for {duration}. Reason: {reason}",
        "unban": "You have been unbanned from **{server}**.",
        "timeout": "You have been timed out in **{server}** for {duration}. Reason: {reason}",
        "unwarn": "Se ha eliminado una sanción tuya en **{server}**. Motivo original: {reason}"
    },
    "chatbot": {
        "enabled": False,
        "channel_ids": [],
        "personality_prompt": "",
        "toxicity_threshold": 0.8
    },
    "economy": {
        "enabled": True,
        "currency_symbol": "🦞"
    },
    "tickets": {
        "category_name": "Tickets",
        "transcript_channel_id": "",
        "staff_roles": ["Staff", "Moderator", "Support"],
        "categories": [
            {"id": "support", "label": "Soporte", "emoji": "📩", "description": "Ayuda general", "category": "Tickets · Soporte"},
            {"id": "report", "label": "Reporte", "emoji": "🚨", "description": "Reportar a un usuario", "category": "Tickets · Reportes"},
            {"id": "idea", "label": "Sugerencia", "emoji": "💡", "description": "Proponer una idea", "category": "Tickets · Sugerencias"},
            {"id": "other", "label": "Otro", "emoji": "💬", "description": "Cualquier otra consulta", "category": "Tickets · General"},
        ],
    },
    "welcome": {
        "enabled": False,
        "channel_id": "",
        "message": "¡Bienvenido {mention} a **{server}**! Eres el miembro #{count} 🦞",
        "card_heading": "BIENVENIDO",
        "member_label": "Miembro",
        "custom_text": "",
        "layout": {},
        "embed": True,
        "color": "0x00ff88",
        "dm_enabled": False,
        "dm_message": "¡Bienvenido a **{server}**, {user}! Configura Dabot en https://dabot.davito.es"
    },
    "goodbye": {
        "enabled": False,
        "channel_id": "",
        "message": "{user} ha salido de **{server}**. Quedan {count} miembros.",
        "embed": True,
        "color": "0xff0050"
    },
    "automod": {
        "enabled": False,
        "block_invites": True,
        "auto_warn": False,
        "mention_limit": 5,
        "spam_threshold": 3,
        "banned_words": [],
        "hijack": True,
        "hijack_timeout": True,
        "links": {
            "enabled": False,
            "block_all": False,
            "ignore_staff": True,
            "default_action": "delete",
            "timeout_minutes": 10,
            "whitelist": [],
            "blocked": [],
            "tracking": {
                "enabled": False,
                "action": "delete",
                "allow_referral": True,
                "referral_domains": [],
                "params": [],
            },
        },
    },
    "starboard": {
        "enabled": False,
        "channel_id": "",
        "limit": 3
    },
    "suggestions": {
        "channel": "",
        "auto_approve_threshold": 10
    },
    "achievements": {
        "enabled": False,
        "channel_id": "",
        "disabled_ids": []
    },
    "commands": {
        "ban": 90,
        "kick": 50,
        "warn": 50,
        "clear": 90
    }
}

class ConfigManager:
    """Guild config backed by SQLite.

    A new connection on every ``get()`` (called from ``get_prefix`` on every
    Discord message) was producing ``disk I/O error`` and silently falling back
    to DEFAULT_CONFIG — which has ``chatbot.enabled = False``. The dashboard
    could save the toggle and the bot would still swear the IA was off.
    """

    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.environ.get("DATABASE_PATH", "dabot.db")
        self._lock = threading.Lock()
        self._conn = None
        self._cache = {}
        self._ttl = 1.5
        self._init_db()

    def _connect(self):
        if self._conn is not None:
            try:
                self._conn.execute("SELECT 1")
                return self._conn
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        self._conn = conn
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._connect()
            conn.execute('''
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id INTEGER PRIMARY KEY,
                    config_json TEXT NOT NULL
                )
            ''')
            conn.commit()

    def _deep_merge(self, default, custom):
        """Recursively merges a custom dict into default to preserve missing structure."""
        if not isinstance(custom, dict):
            return custom
        merged = copy.deepcopy(default)
        for k, v in custom.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = self._deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged

    def _cached(self, guild_id):
        hit = self._cache.get(int(guild_id))
        if not hit:
            return None
        ts, data = hit
        if (time.monotonic() - ts) > self._ttl:
            return None
        return data

    def load_config(self, guild_id, *, force=False):
        """Loads configuration for a specific guild from the database, creating default entry if missing."""
        guild_id = int(guild_id)
        if not force:
            cached = self._cached(guild_id)
            if cached is not None:
                return cached

        last_err = None
        with self._lock:
            if not force:
                cached = self._cached(guild_id)
                if cached is not None:
                    return cached
            for _ in range(3):
                try:
                    conn = self._connect()
                    cursor = conn.cursor()
                    cursor.execute("SELECT config_json FROM guild_configs WHERE guild_id = ?", (guild_id,))
                    row = cursor.fetchone()
                    if row:
                        data = self._deep_merge(DEFAULT_CONFIG, json.loads(row[0] or "{}"))
                    else:
                        data = copy.deepcopy(DEFAULT_CONFIG)
                        cursor.execute(
                            "INSERT OR IGNORE INTO guild_configs (guild_id, config_json) VALUES (?, ?)",
                            (guild_id, json.dumps(DEFAULT_CONFIG)),
                        )
                        conn.commit()
                    self._cache[guild_id] = (time.monotonic(), data)
                    return data
                except Exception as e:
                    last_err = e
                    try:
                        if self._conn:
                            self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    time.sleep(0.05)

        stale = self._cache.get(guild_id)
        if stale:
            return stale[1]
        print(f"Error reading config from db for {guild_id}: {last_err}")
        return copy.deepcopy(DEFAULT_CONFIG)

    def get(self, guild_id, key=None):
        """
        Retrieves a config value.
        If key is None, returns the whole config dict.
        Supports dotted access for nested keys e.g. "moderation.antispam.enabled"
        """
        data = self.load_config(guild_id)
        if key is None:
            return data

        keys = key.split('.')
        value = data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return None

    def set_config(self, guild_id, key, value):
        """
        Updates a config value in the database.
        Supports dotted access for nested keys e.g. "logs.messages".
        If value is None, deletes the key from the dictionary.
        """
        guild_id = int(guild_id)
        data = copy.deepcopy(self.load_config(guild_id, force=True))

        keys = key.split('.')
        current = data

        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]

        if value is None:
            current.pop(keys[-1], None)
        else:
            current[keys[-1]] = value

        return self.save_full_config(guild_id, data)

    def save_full_config(self, guild_id, data):
        """Saves a complete dictionary config to the database."""
        guild_id = int(guild_id)
        last_err = None
        with self._lock:
            for _ in range(3):
                try:
                    conn = self._connect()
                    conn.execute(
                        "INSERT INTO guild_configs (guild_id, config_json) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET config_json = excluded.config_json",
                        (guild_id, json.dumps(data)),
                    )
                    conn.commit()
                    self._cache[guild_id] = (time.monotonic(), copy.deepcopy(data))
                    return True
                except Exception as e:
                    last_err = e
                    try:
                        if self._conn:
                            self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    time.sleep(0.05)
        print(f"Error saving full config to db for {guild_id}: {last_err}")
        return False

    def reload(self, guild_id):
        """Force reads a guild's config from database."""
        self._cache.pop(int(guild_id), None)
        return self.load_config(guild_id, force=True)

    def invalidate(self, guild_id=None):
        if guild_id is None:
            self._cache.clear()
        else:
            self._cache.pop(int(guild_id), None)
