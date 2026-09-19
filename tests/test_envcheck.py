import os

import pytest

from utils.envcheck import require_runtime_env


def test_require_runtime_env_ok(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("SUPER_OWNER_ID", "123")
    require_runtime_env("bot")


def test_require_runtime_env_missing(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setenv("SUPER_OWNER_ID", "123")
    with pytest.raises(SystemExit):
        require_runtime_env("bot")


def test_api_needs_oauth_client(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("SUPER_OWNER_ID", "123")
    monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
    monkeypatch.delenv("DISCORD_CLIENT_SECRET", raising=False)
    with pytest.raises(SystemExit):
        require_runtime_env("api")
