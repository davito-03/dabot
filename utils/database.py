import aiosqlite
import asyncio
import logging
import os
from datetime import datetime, timezone

class Database:
    def __init__(self, db_name=None):
        self.db_name = db_name or os.environ.get("DATABASE_PATH", "dabot.db")
        self.logger = logging.getLogger('Dabot.Database')
        self._conn = None

    async def _get_conn(self):
        """Get or create the persistent database connection."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_name, timeout=30)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA busy_timeout=8000")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.execute("PRAGMA cache_size=-32000")
        return self._conn

    async def _reset_conn(self):
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def close(self):
        """Close the persistent database connection."""
        await self._reset_conn()

    async def setup(self):
        self.logger.info("Setting up database...")
        db = await self._get_conn()
        # Create tables here
        await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    bank INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    weekly_xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp TEXT
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER,
                    mute_role_id INTEGER,
                    welcome_channel_id INTEGER,
                    automod_enabled INTEGER DEFAULT 0
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS inventory (
                    user_id INTEGER,
                    item_name TEXT,
                    quantity INTEGER,
                    PRIMARY KEY (user_id, item_name)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS shop (
                    item_name TEXT PRIMARY KEY,
                    price INTEGER,
                    description TEXT
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS infractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    moderator_id INTEGER,
                    type TEXT,
                    reason TEXT,
                    timestamp TEXT,
                    status TEXT DEFAULT 'active',
                    staff_note TEXT
                )
            ''')
        for stmt in (
            "ALTER TABLE infractions ADD COLUMN staff_note TEXT",
            "ALTER TABLE infractions ADD COLUMN status TEXT DEFAULT 'active'",
        ):
            try:
                await db.execute(stmt)
            except Exception:
                pass
        await db.execute('''
                CREATE TABLE IF NOT EXISTS infraction_appeals (
                    infraction_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    appeal_reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    mod_response TEXT,
                    timestamp TEXT NOT NULL
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS verified_guilds (
                    guild_id INTEGER PRIMARY KEY,
                    note TEXT,
                    added_by INTEGER,
                    added_at TEXT
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS config_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER,
                    summary TEXT,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS bot_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    guild_id INTEGER,
                    guild_name TEXT,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    response TEXT,
                    message_id INTEGER,
                    channel_id INTEGER,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by INTEGER
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS owner_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    actor_id INTEGER,
                    target_id INTEGER,
                    guild_id INTEGER,
                    detail TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
            # Add more tables as needed for other features
        await db.execute('''
                CREATE TABLE IF NOT EXISTS blacklist (
                    user_id INTEGER PRIMARY KEY,
                    reason TEXT,
                    timestamp TEXT
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_blacklist (
                    guild_id INTEGER PRIMARY KEY,
                    reason TEXT,
                    timestamp TEXT,
                    banned_by INTEGER
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    message TEXT,
                    expires_at TEXT,
                    created_at TEXT
                )
            ''')
            
            # Phase 1: Rewards & Engagement
        await db.execute('''
                CREATE TABLE IF NOT EXISTS level_roles (
                    guild_id INTEGER,
                    level INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, level)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    description TEXT,
                    emoji TEXT,
                    requirement_type TEXT,
                    requirement_value INTEGER
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id INTEGER,
                    guild_id INTEGER,
                    achievement_id INTEGER,
                    earned_at TEXT,
                    PRIMARY KEY (user_id, guild_id, achievement_id)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS user_lastfm (
                    user_id INTEGER PRIMARY KEY,
                    lastfm_username TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Phase 2: Moderation
        await db.execute('''
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    moderator_id INTEGER,
                    note TEXT,
                    timestamp TEXT
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS tempbans (
                    user_id INTEGER,
                    guild_id INTEGER,
                    expires_at TEXT,
                    reason TEXT,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')
            
            # Phase 3: Economy
        await db.execute('''
                CREATE TABLE IF NOT EXISTS role_shop (
                    guild_id INTEGER,
                    role_id INTEGER,
                    price INTEGER,
                    duration_days INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, role_id)
                )
            ''')
            
            # Phase 4: Utilities
        await db.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    message TEXT,
                    scheduled_time TEXT,
                    created_by INTEGER,
                    created_at TEXT
                )
            ''')
            
            # Phase 5: Automation
        await db.execute('''
                CREATE TABLE IF NOT EXISTS auto_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    trigger TEXT,
                    response TEXT,
                    created_by INTEGER
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS auto_reactions (
                    guild_id INTEGER,
                    channel_id INTEGER,
                    emoji TEXT,
                    PRIMARY KEY (guild_id, channel_id)
                )
            ''')
            
            # Reputation System
        await db.execute('''
                CREATE TABLE IF NOT EXISTS reputation (
                    user_id INTEGER,
                    guild_id INTEGER,
                    given_by INTEGER,
                    timestamp TEXT,
                    PRIMARY KEY (user_id, guild_id, given_by)
                )
            ''')
            
            # Game Statistics
        await db.execute('''
                CREATE TABLE IF NOT EXISTS game_stats (
                    user_id INTEGER,
                    guild_id INTEGER,
                    game_type TEXT,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    draws INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id, game_type)
                )
            ''')
            
            # Giveaways
        await db.execute('''
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    message_id INTEGER,
                    prize TEXT,
                    winners_count INTEGER,
                    end_time TEXT,
                    host_id INTEGER,
                    requirements TEXT,
                    participants TEXT,
                    ended BOOLEAN DEFAULT 0
                )
            ''')
            
            # Message count tracking for achievements
        await db.execute('''
                CREATE TABLE IF NOT EXISTS message_count (
                    user_id INTEGER,
                    guild_id INTEGER,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

            # DX Tracking System
        await db.execute('''
                CREATE TABLE IF NOT EXISTS tracking (
                    user_id INTEGER PRIMARY KEY,
                    started_at TEXT
                )
            ''')
            
            # --- NEW FEATURES (Suggestions Implementation) ---

             # Custom Commands (Premium)
        await db.execute('''
                CREATE TABLE IF NOT EXISTS custom_commands (
                    guild_id INTEGER,
                    trigger TEXT,
                    response TEXT,
                    type TEXT DEFAULT 'text',
                    created_by INTEGER,
                    PRIMARY KEY (guild_id, trigger)
                )
            ''')
            
            # Starboard
        await db.execute('''
                CREATE TABLE IF NOT EXISTS starboard_messages (
                    original_message_id INTEGER PRIMARY KEY,
                    starboard_message_id INTEGER,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    starboard_channel_id INTEGER
                )
            ''')
            
            # Social Profiles
        await db.execute('''
                CREATE TABLE IF NOT EXISTS social_profiles (
                    user_id INTEGER PRIMARY KEY,
                    bio TEXT,
                    twitter TEXT,
                    instagram TEXT,
                    github TEXT,
                    youtube TEXT,
                    twitch TEXT,
                    website TEXT
                )
            ''')
            
            # Premium Guilds (for custom images)
        await db.execute('''
                CREATE TABLE IF NOT EXISTS premium_guilds (
                    guild_id INTEGER PRIMARY KEY,
                    activated_at TEXT,
                    expires_at TEXT,
                    custom_background TEXT,
                    custom_bot_name TEXT,
                    custom_bot_avatar TEXT
                )
            ''')
        
        # Migration for new columns (if table existed)
        try:
            await db.execute("ALTER TABLE premium_guilds ADD COLUMN custom_bot_name TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE premium_guilds ADD COLUMN custom_bot_avatar TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE premium_guilds ADD COLUMN plan TEXT DEFAULT 'monthly'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE premium_users ADD COLUMN plan TEXT DEFAULT 'monthly'")
        except Exception:
            pass

            # Stats Channels
        await db.execute('''
                CREATE TABLE IF NOT EXISTS stats_channels (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER,
                    type TEXT,
                    format TEXT,
                    timezone TEXT
                )
            ''')
        try:
            await db.execute("ALTER TABLE stats_channels ADD COLUMN timezone TEXT")
        except Exception:
            pass
            
            # Per-Server Leveling
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_levels (
                    user_id INTEGER,
                    guild_id INTEGER,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    weekly_xp INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_economy (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    balance INTEGER DEFAULT 0,
                    bank INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_shop (
                    guild_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    description TEXT,
                    PRIMARY KEY (guild_id, item_name)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_inventory (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id, item_name)
                )
            ''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_guild_economy_bal ON guild_economy(guild_id, balance DESC)")
            
            # Guess Game Stats (for percentile calculation)
        await db.execute('''
                CREATE TABLE IF NOT EXISTS birthdays (
                    user_id INTEGER PRIMARY KEY,
                    day INTEGER,
                    month INTEGER,
                    year INTEGER
                )
            ''')
            
            # --- AI FEATURES ---
        await db.execute('''
                CREATE TABLE IF NOT EXISTS user_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    memory_text TEXT,
                    timestamp TEXT
                )
            ''')
        
        # Migration for user_memories (add guild_id)
        try:
            await db.execute("ALTER TABLE user_memories ADD COLUMN guild_id INTEGER")
        except Exception:
            pass

        await db.execute('''
                CREATE TABLE IF NOT EXISTS ai_settings (
                    guild_id INTEGER PRIMARY KEY,
                    personality_prompt TEXT,
                    moderation_channel_id INTEGER,
                    tts_enabled BOOLEAN DEFAULT 0,
                    toxicity_threshold REAL DEFAULT 0.8
                )
            ''')

            
        await db.execute('''
                CREATE TABLE IF NOT EXISTS guess_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    attempts INTEGER,
                    timestamp TEXT
                )
            ''')

        # --- PERFORMANCE OPTIMIZATIONS (Indexes) ---
        # Indexes for frequently joined/filtered columns
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_warnings_user_guild ON warnings(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_infractions_user_guild ON infractions(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_memories_user_guild ON user_memories(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_achievements_user_guild ON user_achievements(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_ranking_xp ON users(xp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_guild_ranking_xp ON guild_levels(guild_id, xp DESC)"
        ]
        
        for idx in indexes:
            await db.execute(idx)

        # --- NEW FEATURE TABLES ---
        await db.execute('''
                CREATE TABLE IF NOT EXISTS user_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS quarantine_config (
                    guild_id INTEGER PRIMARY KEY,
                    role_id INTEGER NOT NULL,
                    min_age_days INTEGER NOT NULL DEFAULT 7
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS emoji_usage (
                    guild_id INTEGER,
                    emoji TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, emoji)
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS message_activity (
                    guild_id INTEGER,
                    user_id INTEGER,
                    date TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, date)
                )
            ''')

        # --- ANTI-RAID ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antiraid_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                join_threshold INTEGER DEFAULT 10,
                window_seconds INTEGER DEFAULT 10,
                alert_channel_id INTEGER,
                lockdown_minutes INTEGER DEFAULT 5
            )
        ''')

        # --- SERVER DISCOVERY & BUMP (DISBOARD STYLE) ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS server_discovery (
                guild_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                icon TEXT,
                invite_url TEXT,
                invite_channel_id INTEGER,
                tags TEXT DEFAULT '',
                category TEXT DEFAULT 'General',
                member_count INTEGER DEFAULT 0,
                bump_count INTEGER DEFAULT 0,
                last_bump_at TEXT,
                last_bump_user_id INTEGER,
                is_public INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_server_discovery_bump ON server_discovery (is_public, last_bump_at DESC)')

        # --- VERIFICATION SYSTEM ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS verification_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                verification_channel_id INTEGER NOT NULL,
                unverified_role_id INTEGER NOT NULL,
                verified_role_id INTEGER NOT NULL,
                verification_type TEXT DEFAULT 'emoji'
            )
        ''')
        from utils.alt_intel import ensure_schema_async
        await ensure_schema_async(self)
        from utils import verify_log
        await db.execute(verify_log.SCHEMA)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ve_guild ON verification_events(guild_id, id DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ve_user ON verification_events(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ve_guild_user ON verification_events(guild_id, user_id, id DESC)")

        # --- ACTIVE TEMP ROLES ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS active_temp_roles (
                guild_id INTEGER,
                user_id INTEGER,
                role_id INTEGER,
                expires_at TEXT,
                PRIMARY KEY (guild_id, user_id, role_id)
            )
        ''')

        # --- WELCOME SYSTEM ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS welcome_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                channel_id INTEGER,
                background_url TEXT,
                message_text TEXT DEFAULT '¡Bienvenido {member} a nuestro servidor!',
                card_heading TEXT DEFAULT 'BIENVENIDO',
                member_label TEXT DEFAULT 'Miembro',
                custom_text TEXT DEFAULT '',
                layout_json TEXT DEFAULT '{}'
            )
        ''')
        for sql in (
            "ALTER TABLE welcome_config ADD COLUMN card_heading TEXT DEFAULT 'BIENVENIDO'",
            "ALTER TABLE welcome_config ADD COLUMN member_label TEXT DEFAULT 'Miembro'",
            "ALTER TABLE welcome_config ADD COLUMN custom_text TEXT DEFAULT ''",
            "ALTER TABLE welcome_config ADD COLUMN layout_json TEXT DEFAULT '{}'",
        ):
            try:
                await db.execute(sql)
            except Exception:
                pass

        # --- TRIVIA SYSTEM ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS trivia_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS trivia_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                reward INTEGER DEFAULT 100,
                interval_minutes INTEGER DEFAULT 0
            )
        ''')

        # --- COLOR SYSTEM ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS color_config (
                guild_id INTEGER PRIMARY KEY,
                price INTEGER DEFAULT 500,
                duration_days INTEGER DEFAULT 30
            )
        ''')

        # --- STREAM ALERTS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS stream_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                platform TEXT DEFAULT 'twitch',
                username TEXT,
                last_notified TEXT,
                UNIQUE(guild_id, platform, username)
            )
        ''')

        # --- RSS FEEDS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                url TEXT,
                last_entry_id TEXT,
                UNIQUE(guild_id, url)
            )
        ''')

        # --- GITHUB CONFIG ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS github_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                repo TEXT,
                last_event_id TEXT,
                UNIQUE(guild_id, repo)
            )
        ''')

        # --- SERVER STRUCTURE BACKUPS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS server_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                backup_data TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')

        # --- INVITE TRACKER ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS invite_tracker (
                guild_id INTEGER,
                inviter_id INTEGER,
                invited_id INTEGER,
                invite_code TEXT,
                timestamp TEXT,
                PRIMARY KEY (guild_id, invited_id)
            )
        ''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_invite_tracker_inviter ON invite_tracker(guild_id, inviter_id)")

        await db.execute('''
            CREATE TABLE IF NOT EXISTS bot_runtime (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                latency_ms INTEGER DEFAULT 0,
                guilds INTEGER DEFAULT 0,
                users INTEGER DEFAULT 0,
                commands INTEGER DEFAULT 0,
                started_at TEXT,
                updated_at TEXT,
                version TEXT,
                user_id TEXT,
                username TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor_id INTEGER,
                target_id INTEGER,
                channel_id INTEGER,
                summary TEXT,
                extra TEXT,
                timestamp TEXT NOT NULL
            )
        ''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_guild_id ON audit_events(guild_id, id DESC)")
        try:
            await db.execute("ALTER TABLE server_backups ADD COLUMN status TEXT DEFAULT 'ready'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE server_backups ADD COLUMN kind TEXT DEFAULT 'structure'")
        except Exception:
            pass

        # --- PREMIUM USERS ---
        await db.execute('''
                CREATE TABLE IF NOT EXISTS premium_users (
                user_id INTEGER PRIMARY KEY,
                tier TEXT DEFAULT 'premium',
                activated_at TEXT,
                expires_at TEXT
                )
            ''')

        # Global announcements: one source message can be mirrored to every guild.
        await db.execute('''
                CREATE TABLE IF NOT EXISTS announcement_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    updated_by INTEGER,
                    updated_at TEXT NOT NULL
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS announcement_messages (
                    source_message_id TEXT PRIMARY KEY,
                    source_guild_id INTEGER,
                    source_channel_id INTEGER,
                    content TEXT,
                    embeds TEXT,
                    attachments TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
        await db.execute('''
                CREATE TABLE IF NOT EXISTS announcement_deliveries (
                    source_message_id TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    message_id INTEGER,
                    status TEXT NOT NULL,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_message_id, guild_id)
                )
            ''')

        # Voice Stats
        await db.execute('''
            CREATE TABLE IF NOT EXISTS voice_time (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                weekly_seconds INTEGER DEFAULT 0,
                total_seconds INTEGER DEFAULT 0,
                last_channel_name TEXT,
                last_active TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # --- FORUMS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS forum_resolutions (
                thread_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                resolved_by INTEGER NOT NULL,
                resolved_at TEXT NOT NULL
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS forum_config (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                auto_close_days INTEGER DEFAULT 7,
                PRIMARY KEY (guild_id, channel_id)
            )
        ''')

        # --- POLLS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS polls (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL,  -- JSON array
                votes TEXT NOT NULL DEFAULT '{}',  -- JSON: {"option_index": [user_id, ...]}
                author_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                closed INTEGER DEFAULT 0
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER,
                guild_id INTEGER,
                message TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                delivered INTEGER DEFAULT 0
            )
        ''')
        try:
            await db.execute("ALTER TABLE reminders ADD COLUMN delivered INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE reminders ADD COLUMN remind_at TEXT")
        except Exception:
            pass


        # --- TICKETS EXTRAS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ticket_snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                usage_count INTEGER DEFAULT 0,
                UNIQUE(guild_id, name)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ticket_ratings (
                ticket_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                rated_at TEXT NOT NULL
            )
        ''')

        # --- ANTINUKE ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                max_channel_deletes INTEGER DEFAULT 3,
                max_role_deletes INTEGER DEFAULT 3,
                max_bans INTEGER DEFAULT 5,
                max_kicks INTEGER DEFAULT 5,
                window_seconds INTEGER DEFAULT 10,
                action TEXT DEFAULT 'strip_roles',
                log_channel_id INTEGER,
                whitelist TEXT DEFAULT '[]'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                action_type TEXT NOT NULL,
                count INTEGER NOT NULL,
                action_taken TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS system_schedule (
                key TEXT PRIMARY KEY,
                last_run TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS privacy_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                data_snapshot TEXT,
                requested_at TEXT NOT NULL,
                processed_at TEXT,
                processed_by INTEGER,
                encrypted_ip_backup TEXT,
                admin_notes TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS privacy_security_fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                encrypted_ip_fingerprint TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                legal_basis TEXT DEFAULT 'Art. 6.1.f RGPD - Prevención de abusos y multicuentas'
            )
        ''')

        await db.commit()
        self.logger.info("Database setup complete.")

    _TRANSIENT = (
        "disk i/o error", "database is locked", "database is busy",
        "no active connection", "unable to open", "cannot start a transaction",
    )

    def _is_transient(self, err) -> bool:
        msg = str(err).lower()
        return any(token in msg for token in self._TRANSIENT)

    async def execute(self, query, *args):
        last_err = None
        for attempt in range(3):
            try:
                db = await self._get_conn()
                cursor = await db.execute(query, args)
                last_id = cursor.lastrowid
                await db.commit()
                return last_id
            except Exception as e:
                last_err = e
                if not self._is_transient(e) or attempt == 2:
                    raise
                self.logger.warning("db execute retry %s: %s", attempt + 1, e)
                await self._reset_conn()
                await asyncio.sleep(0.05 * (attempt + 1))
        raise last_err

    async def fetch(self, query, *args):
        last_err = None
        for attempt in range(3):
            try:
                db = await self._get_conn()
                async with db.execute(query, args) as cursor:
                    return await cursor.fetchone()
            except Exception as e:
                last_err = e
                if not self._is_transient(e) or attempt == 2:
                    raise
                self.logger.warning("db fetch retry %s: %s", attempt + 1, e)
                await self._reset_conn()
                await asyncio.sleep(0.05 * (attempt + 1))
        raise last_err

    async def fetch_all(self, query, *args):
        last_err = None
        for attempt in range(3):
            try:
                db = await self._get_conn()
                async with db.execute(query, args) as cursor:
                    return await cursor.fetchall()
            except Exception as e:
                last_err = e
                if not self._is_transient(e) or attempt == 2:
                    raise
                self.logger.warning("db fetch_all retry %s: %s", attempt + 1, e)
                await self._reset_conn()
                await asyncio.sleep(0.05 * (attempt + 1))
        raise last_err

    async def is_user_premium(self, user_id: int) -> bool:
        """User-level premium is retired. Keep the method so old calls don't crash."""
        return False

    async def is_guild_premium(self, guild, bot) -> bool:
        guild_id = guild if isinstance(guild, int) else getattr(guild, "id", None)
        if guild_id is None:
            return False
        guild_obj = bot.get_guild(int(guild_id)) if isinstance(guild, int) else guild
        super_owner_id = int(os.getenv("SUPER_OWNER_ID") or "0")
        if bot and getattr(bot, "super_owner_id", 0):
            super_owner_id = int(bot.super_owner_id)

        row = await self.fetch(
            "SELECT expires_at, plan FROM premium_guilds WHERE guild_id = ?",
            int(guild_id),
        )
        plan = None
        exp = None
        if row:
            exp = row[0] if not hasattr(row, "keys") else row["expires_at"]
            try:
                plan = row[1] if not hasattr(row, "keys") else row["plan"]
            except Exception:
                plan = None
        if str(plan or "").lower() in ("disabled", "off", "none", "revoked"):
            return False
        from utils.premium import is_active
        if row and is_active(exp, plan):
            return True
        if guild_obj and getattr(guild_obj, "owner_id", None) == super_owner_id:
            return True
        return False

    async def get_user_lastfm(self, user_id: int) -> str | None:
        row = await self.fetch_one("SELECT lastfm_username FROM user_lastfm WHERE user_id = ?", user_id)
        if row:
            return row['lastfm_username'] if isinstance(row, dict) else row[0]
        return None

    async def set_user_lastfm(self, user_id: int, username: str):
        now = datetime.now(timezone.utc).isoformat()
        await self.execute(
            """INSERT INTO user_lastfm (user_id, lastfm_username, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   lastfm_username = excluded.lastfm_username,
                   updated_at = excluded.updated_at""",
            user_id, username, now
        )

    async def delete_user_lastfm(self, user_id: int):
        await self.execute("DELETE FROM user_lastfm WHERE user_id = ?", user_id)

