from webapp.status_payload import assemble_status, heartbeat_online


class _Row(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


def test_assemble_prefers_live_ping():
    row = _Row(
        latency_ms=90,
        guilds=2,
        users=10,
        commands=0,
        started_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        version="3.1.0",
        username="Dabot",
    )
    live = {"ok": True, "latency_ms": 40, "guilds": 18, "users": 950}
    payload = assemble_status(row, live, heartbeat=True, now_iso="now")
    assert payload["online"] is True
    assert payload["latency_ms"] == 40
    assert payload["guilds"] == 18
    assert payload["source"] == "live"
    assert payload["checked_at"] == "now"


def test_heartbeat_without_live_still_online():
    payload = assemble_status(None, {"ok": False}, heartbeat=True, now_iso="now")
    assert payload["online"] is True
    assert payload["source"] == "heartbeat"


def test_stale_heartbeat():
    assert heartbeat_online(None) is False
    assert heartbeat_online("not-a-date") is False
