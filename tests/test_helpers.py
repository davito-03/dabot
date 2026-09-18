"""Lightweight helpers tests (no Discord)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.abuse import extract_urls
from utils import antilinks as AL
from cogs.moderation import neutralize_links, _normalize_guild_name, _reason_fingerprint, _NEW_GUILD_DAYS


def test_urls():
    assert extract_urls("hola https://evil.test/x y") == ["https://evil.test/x"]
    text, found = neutralize_links("click https://a.test/y now")
    assert found and "`https://a.test/y`" in text
    assert neutralize_links("sin enlaces")[1] is False


def test_names():
    assert _normalize_guild_name("The Official Foo!!") == _normalize_guild_name("official foo")
    assert _NEW_GUILD_DAYS == 14
    assert _reason_fingerprint("Hola  mundo") == _reason_fingerprint("hola mundo")


def test_antilinks():
    cfg = {
        "enabled": True,
        "block_all": False,
        "default_action": "delete",
        "whitelist": ["youtube.com"],
        "blocked": [{"domain": "grabify.link", "action": "ban"}, {"domain": "bit.ly", "action": "delete"}],
        "tracking": {"enabled": True, "action": "warn", "allow_referral": True, "referral_domains": ["amazon.es"]},
    }
    assert AL.inspect_url("https://grabify.link/abc", cfg)["action"] == "ban"
    assert AL.inspect_url("https://bit.ly/x", cfg)["action"] == "delete"
    assert AL.inspect_url("https://youtube.com/watch?v=1", cfg) is None
    cfg_all = dict(cfg, block_all=True)
    assert AL.inspect_url("https://random.example/a", cfg_all)["reason"] == "not_whitelisted"
    assert AL.inspect_url("https://www.youtube.com/watch?v=1", cfg_all) is None
    track = AL.inspect_url("https://youtube.com/watch?v=1&utm_source=x&fbclid=1", cfg, premium=True)
    assert track and track["reason"] == "tracking"
    assert AL.inspect_url("https://amazon.es/dp/1?tag=shop-21", cfg, premium=True) is None
    mixed = AL.inspect_url("https://amazon.es/dp/1?tag=shop-21&utm_source=x", cfg, premium=True)
    assert mixed and mixed["reason"] == "tracking"
    assert AL.inspect_url("https://cdn.discordapp.com/x.png", cfg_all) is None
    hit = AL.inspect_text("mira https://GRABIFY.link/zz porfa", cfg)
    assert hit["action"] == "ban"


if __name__ == "__main__":
    test_urls()
    test_names()
    test_antilinks()
    print("ok")
