"""SQLite cache of guild channels and the last N messages per text channel.

The Discord bot writes this from gateway events. The dashboard reads it so the
admin live console does not hammer the Discord REST API.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

KEEP_MESSAGES = 10
TEXT_TYPES = (0, 5)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS cached_guilds (
        guild_id INTEGER PRIMARY KEY,
        name TEXT,
        icon TEXT,
        member_count INTEGER,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS cached_channels (
        channel_id INTEGER PRIMARY KEY,
        guild_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        type INTEGER NOT NULL,
        position INTEGER DEFAULT 0,
        parent_id INTEGER,
        category TEXT,
        updated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cached_channels_guild ON cached_channels(guild_id, type, position)",
    """CREATE TABLE IF NOT EXISTS cached_messages (
        message_id INTEGER PRIMARY KEY,
        channel_id INTEGER NOT NULL,
        guild_id INTEGER,
        author_id INTEGER,
        author_name TEXT,
        author_avatar TEXT,
        author_bot INTEGER DEFAULT 0,
        content TEXT,
        attachments_json TEXT,
        timestamp TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cached_messages_ch ON cached_messages(channel_id, message_id DESC)",
    """CREATE TABLE IF NOT EXISTS live_watch (
        channel_id INTEGER PRIMARY KEY,
        guild_id INTEGER,
        user_id INTEGER,
        watched_at TEXT
    )""",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema_sync(conn) -> None:
    cur = conn.cursor()
    for sql in SCHEMA:
        cur.execute(sql)
    try:
        conn.commit()
    except Exception:
        pass


def upsert_guild_sync(conn, guild_id, name, icon=None, member_count=0) -> None:
    conn.execute(
        """INSERT INTO cached_guilds (guild_id, name, icon, member_count, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(guild_id) DO UPDATE SET
             name=excluded.name, icon=excluded.icon,
             member_count=excluded.member_count, updated_at=excluded.updated_at""",
        (int(guild_id), name or "Servidor", icon, int(member_count or 0), now_iso()),
    )


def upsert_channel_sync(conn, channel_id, guild_id, name, ctype, position=0, parent_id=None, category=None) -> None:
    conn.execute(
        """INSERT INTO cached_channels
           (channel_id, guild_id, name, type, position, parent_id, category, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(channel_id) DO UPDATE SET
             guild_id=excluded.guild_id, name=excluded.name, type=excluded.type,
             position=excluded.position, parent_id=excluded.parent_id,
             category=excluded.category, updated_at=excluded.updated_at""",
        (
            int(channel_id), int(guild_id), name or "canal", int(ctype),
            int(position or 0), int(parent_id) if parent_id else None,
            category, now_iso(),
        ),
    )


def delete_channel_sync(conn, channel_id) -> None:
    cid = int(channel_id)
    conn.execute("DELETE FROM cached_channels WHERE channel_id = ?", (cid,))
    conn.execute("DELETE FROM cached_messages WHERE channel_id = ?", (cid,))
    conn.execute("DELETE FROM live_watch WHERE channel_id = ?", (cid,))


def prune_guild_channels_sync(conn, guild_id, keep_ids: list[int]) -> None:
    gid = int(guild_id)
    if not keep_ids:
        conn.execute("DELETE FROM cached_channels WHERE guild_id = ?", (gid,))
        return
    placeholders = ",".join("?" * len(keep_ids))
    conn.execute(
        f"DELETE FROM cached_channels WHERE guild_id = ? AND channel_id NOT IN ({placeholders})",
        (gid, *[int(x) for x in keep_ids]),
    )


def upsert_message_sync(
    conn, *, message_id, channel_id, guild_id, author_id, author_name,
    author_avatar=None, author_bot=False, content="", attachments=None, timestamp=None,
) -> None:
    conn.execute(
        """INSERT INTO cached_messages
           (message_id, channel_id, guild_id, author_id, author_name, author_avatar,
            author_bot, content, attachments_json, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(message_id) DO UPDATE SET
             content=excluded.content, attachments_json=excluded.attachments_json,
             author_name=excluded.author_name, author_avatar=excluded.author_avatar""",
        (
            int(message_id), int(channel_id), int(guild_id) if guild_id else None,
            int(author_id) if author_id else None, author_name or "Usuario",
            author_avatar, 1 if author_bot else 0, content or "",
            json.dumps(attachments or [], ensure_ascii=False),
            timestamp or now_iso(),
        ),
    )
    conn.execute(
        """DELETE FROM cached_messages
           WHERE channel_id = ?
             AND message_id IN (
               SELECT message_id FROM (
                 SELECT message_id FROM cached_messages
                 WHERE channel_id = ?
                 ORDER BY message_id DESC
                 LIMIT -1 OFFSET ?
               )
             )""",
        (int(channel_id), int(channel_id), KEEP_MESSAGES),
    )


def delete_message_sync(conn, message_id) -> None:
    conn.execute("DELETE FROM cached_messages WHERE message_id = ?", (int(message_id),))


def set_watch_sync(conn, channel_id, guild_id=None, user_id=None) -> None:
    conn.execute(
        """INSERT INTO live_watch (channel_id, guild_id, user_id, watched_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(channel_id) DO UPDATE SET
             guild_id=excluded.guild_id, user_id=excluded.user_id, watched_at=excluded.watched_at""",
        (int(channel_id), int(guild_id) if guild_id else None, int(user_id) if user_id else None, now_iso()),
    )


def list_channels_sync(conn, guild_id: int) -> list[dict]:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    cur.execute(
        """SELECT channel_id, guild_id, name, type, position, parent_id, category
           FROM cached_channels
           WHERE guild_id = ? AND type IN (0, 5)
           ORDER BY category COLLATE NOCASE, position, name COLLATE NOCASE""",
        (int(guild_id),),
    )
    out = []
    for r in cur.fetchall():
        if hasattr(r, "keys"):
            cid, gid, name, ctype, pos, parent, cat = (
                r["channel_id"], r["guild_id"], r["name"], r["type"],
                r["position"], r["parent_id"], r["category"],
            )
        else:
            cid, gid, name, ctype, pos, parent, cat = r
        out.append({
            "id": str(cid),
            "name": name or "canal",
            "type": int(ctype),
            "position": int(pos or 0),
            "parent_id": str(parent) if parent else None,
            "category": cat,
        })
    return out


def list_messages_sync(conn, channel_id: int, after: str | int | None = None) -> list[dict]:
    ensure_schema_sync(conn)
    cur = conn.cursor()
    after_id = int(after) if after and str(after).isdigit() else 0
    if after_id:
        cur.execute(
            """SELECT message_id, channel_id, guild_id, author_id, author_name, author_avatar,
                      author_bot, content, attachments_json, timestamp
               FROM cached_messages
               WHERE channel_id = ? AND message_id > ?
               ORDER BY message_id ASC""",
            (int(channel_id), after_id),
        )
    else:
        cur.execute(
            """SELECT message_id, channel_id, guild_id, author_id, author_name, author_avatar,
                      author_bot, content, attachments_json, timestamp
               FROM cached_messages
               WHERE channel_id = ?
               ORDER BY message_id DESC
               LIMIT ?""",
            (int(channel_id), KEEP_MESSAGES),
        )
    rows = cur.fetchall()
    if not after_id:
        rows = list(reversed(rows))
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            mid, cid, gid, aid, aname, aav, abot, content, atts, ts = (
                r["message_id"], r["channel_id"], r["guild_id"], r["author_id"],
                r["author_name"], r["author_avatar"], r["author_bot"],
                r["content"], r["attachments_json"], r["timestamp"],
            )
        else:
            mid, cid, gid, aid, aname, aav, abot, content, atts, ts = r
        try:
            attachments = json.loads(atts or "[]")
        except Exception:
            attachments = []
        if not isinstance(attachments, list):
            attachments = []
        out.append({
            "id": str(mid),
            "content": content or "",
            "timestamp": ts,
            "author": {
                "id": str(aid or ""),
                "username": aname or "Usuario",
                "bot": bool(abot),
                "avatar": aav,
            },
            "attachments": attachments,
            "reply_to": None,
        })
    return out


def message_count_sync(conn, channel_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cached_messages WHERE channel_id = ?", (int(channel_id),))
    row = cur.fetchone()
    return int(row[0] if row else 0)
