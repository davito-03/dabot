"""Shared settings for Dabot's global announcement relay."""
from __future__ import annotations

import os


SOURCE_GUILD_ID = int(os.environ.get("ANNOUNCEMENT_SOURCE_GUILD_ID", "1413959468365905962"))
SOURCE_CHANNEL_ID = int(os.environ.get("ANNOUNCEMENT_SOURCE_CHANNEL_ID", "1541073840468398100"))


def is_source(guild_id: int | None, channel_id: int | None) -> bool:
    return int(guild_id or 0) == SOURCE_GUILD_ID and int(channel_id or 0) == SOURCE_CHANNEL_ID


def default_channel_name(name: str | None) -> bool:
    return (name or "").strip().casefold() == "general"
