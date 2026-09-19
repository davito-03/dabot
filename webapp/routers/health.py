"""Public liveness. Isolated so dashboard_server.py is not the only entry."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from webapp.deps import get_db

router = APIRouter()


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
