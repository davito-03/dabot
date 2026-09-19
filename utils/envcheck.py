"""Fail fast if required secrets are missing. No hardcoded owner IDs."""
from __future__ import annotations

import os
import sys


REQUIRED = ("DISCORD_TOKEN", "SUPER_OWNER_ID")
OPTIONAL_WARN = ("SESSION_SECRET", "PRIVACY_SECRET_PEPPER")


def require_runtime_env(role: str = "bot") -> None:
    missing = [k for k in REQUIRED if not str(os.getenv(k, "")).strip()]
    if missing:
        sys.stderr.write(
            f"dabot {role}: missing required env: {', '.join(missing)}\n"
        )
        raise SystemExit(2)
    try:
        owner = int(os.environ["SUPER_OWNER_ID"])
    except (KeyError, ValueError):
        sys.stderr.write("dabot: SUPER_OWNER_ID must be a Discord snowflake integer\n")
        raise SystemExit(2)
    if owner <= 0:
        sys.stderr.write("dabot: SUPER_OWNER_ID must be > 0\n")
        raise SystemExit(2)
    if role == "api":
        for k in ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"):
            if not str(os.getenv(k, "")).strip():
                sys.stderr.write(f"dabot api: missing {k}\n")
                raise SystemExit(2)
    if not (os.getenv("PRIVACY_SECRET_PEPPER") or os.getenv("SESSION_SECRET")):
        sys.stderr.write(
            "dabot warning: set PRIVACY_SECRET_PEPPER or SESSION_SECRET "
            "(no built-in pepper)\n"
        )
