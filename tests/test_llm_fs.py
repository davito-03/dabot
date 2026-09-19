from pathlib import Path

from utils.llm_fs import list_names, read_text, resolve_readable


def test_allow_cogs_and_block_env(tmp_path: Path):
    (tmp_path / "cogs").mkdir()
    (tmp_path / "cogs" / "chatbot.py").write_text("ok\n", encoding="utf-8")
    (tmp_path / ".env").write_text("DISCORD_TOKEN=secret\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "dabot.db").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("# dabot\n", encoding="utf-8")

    path, err = resolve_readable("cogs/chatbot.py", tmp_path)
    assert err == "" and path is not None
    path, err = resolve_readable(".env", tmp_path)
    assert path is None and "blocked" in err
    path, err = resolve_readable("data/dabot.db", tmp_path)
    assert path is None
    path, err = resolve_readable("../etc/passwd", tmp_path)
    assert path is None
    assert "ACCESS DENIED" in read_text(".env", tmp_path)
    assert "ok" in read_text("cogs/chatbot.py", tmp_path)
    listing = list_names(".", tmp_path)
    assert "cogs" in listing and ".env" not in listing
