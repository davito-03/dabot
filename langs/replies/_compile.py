#!/usr/bin/env python3
"""Merge langs/replies/part_*.json into validated catalogs."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LANGS = ("es", "en", "fr", "de", "pt", "it", "ja", "ko", "zh")


def main():
    catalog = {}
    parts = sorted(ROOT.glob("part_*.json"))
    if not parts:
        print("no part_*.json files", file=sys.stderr)
        return 1
    for path in parts:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{path} is not an object")
        catalog.update(data)
        print(f"loaded {path.name}: {len(data)}")
    missing_lang = 0
    for src, row in catalog.items():
        if not isinstance(row, dict):
            raise SystemExit(f"bad row for {src[:60]!r}")
        for lang in LANGS:
            if lang not in row or not isinstance(row[lang], str) or not row[lang]:
                row[lang] = row.get("en") or src
                missing_lang += 1
    out = ROOT / "catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} sources={len(catalog)} filled_missing={missing_lang}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
