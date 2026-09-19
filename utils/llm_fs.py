"""Owner-only LLM filesystem: read/list inside an allow-list. Never write."""
from __future__ import annotations

from pathlib import Path

ALLOWED_DIRS = ("cogs", "utils", "webapp", "docs", "templates", "static", "tests")
ALLOWED_FILES = frozenset(
    {
        "README.md",
        "ARCHITECTURE.md",
        "pyproject.toml",
        "requirements.txt",
        "main.py",
        "dashboard_server.py",
        "docker-compose.yml",
        "Dockerfile",
        ".env.example",
    }
)
BLOCKED_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        "credentials.json",
        "token.json",
        "rclone.conf",
        "cookies.txt",
    }
)
BLOCKED_SUFFIXES = (".session", ".db", ".db-wal", ".db-shm", ".key", ".pem", ".crt")
BLOCKED_PARTS = frozenset({"data", "logs", ".git", "configs"})


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_readable(raw: str, root: Path | None = None) -> tuple[Path | None, str]:
    """Return (path, error). path is None when access is denied."""
    root = (root or project_root()).resolve()
    if not raw or not str(raw).strip():
        return None, "empty path"
    try:
        candidate = Path(raw)
        target = candidate.resolve() if candidate.is_absolute() else (root / raw).resolve()
        target.relative_to(root)
    except (ValueError, OSError, TypeError):
        return None, "path outside project"
    rel = target.relative_to(root)
    if any(part in BLOCKED_PARTS for part in rel.parts):
        return None, "blocked directory"
    if target.name in BLOCKED_NAMES or target.name.startswith(".env"):
        return None, "blocked file"
    if target.suffix.lower() in BLOCKED_SUFFIXES:
        return None, "blocked suffix"
    if target.name in ALLOWED_FILES and len(rel.parts) == 1:
        return target, ""
    if rel.parts and rel.parts[0] in ALLOWED_DIRS:
        return target, ""
    return None, "not in allow-list"


def read_text(raw: str, root: Path | None = None, limit: int = 1900) -> str:
    path, err = resolve_readable(raw, root)
    if err:
        return f"ACCESS DENIED: {err}"
    if not path.exists() or not path.is_file():
        return "File not found."
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Tool Execution Error: {exc}"
    return f"File Content ({path.name}):\n```\n{text[:limit]}\n```"


def list_names(raw: str, root: Path | None = None) -> str:
    root = (root or project_root()).resolve()
    requested = (raw or ".").strip() or "."
    if requested in {".", "./"}:
        names = sorted(
            [name for name in ALLOWED_DIRS if (root / name).exists()]
            + [name for name in ALLOWED_FILES if (root / name).exists()]
        )
        return f"Files in .: {', '.join(names)}"
    path, err = resolve_readable(requested, root)
    if err:
        return f"ACCESS DENIED: {err}"
    if not path.exists() or not path.is_dir():
        return "Directory not found."
    try:
        names = sorted(p.name for p in path.iterdir() if p.name not in BLOCKED_NAMES)
    except OSError as exc:
        return f"Tool Execution Error: {exc}"
    return f"Files in {requested}: {', '.join(names)}"
