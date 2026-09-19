"""Public liveness. Isolated so dashboard_server.py is not the only entry."""
from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

router = APIRouter()
DB_PATH = os.environ.get("DATABASE_PATH", "dabot.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@router.get("/healthz")
@router.get("/api/healthz")
async def healthcheck(db: sqlite3.Connection = Depends(get_db)):
    try:
        db.execute("SELECT 1")
        db_status = "connected"
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": f"error: {e}"},
        )
    return {"status": "healthy", "service": "dabot-api", "database": db_status}
