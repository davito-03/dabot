"""Shared FastAPI dependencies extracted from dashboard_server.py."""
from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get("DATABASE_PATH", "dabot.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()
