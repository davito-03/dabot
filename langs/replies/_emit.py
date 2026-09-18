#!/usr/bin/env python3
"""Write a replies part file from 9-tuples: src, es, en, fr, de, pt, it, ja, ko, zh."""
import json
import sys
from pathlib import Path

LANGS = ("es", "en", "fr", "de", "pt", "it", "ja", "ko", "zh")
ROOT = Path(__file__).resolve().parent


def emit(name, rows):
    out = {}
    for row in rows:
        if len(row) != 10:
            raise SystemExit(f"bad row len {len(row)}: {row[0][:60]!r}")
        src = row[0]
        out[src] = dict(zip(LANGS, row[1:]))
    path = ROOT / name
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.name} {len(out)}")
    return len(out)


def mostly_template(s: str) -> bool:
    import re
    stripped = re.sub(r"\{[^}]+\}", "", s)
    stripped = re.sub(r"`[^`]+`", "", stripped)
    stripped = re.sub(r"<[#@t:][^>]+>", "", stripped)
    letters = re.findall(r"[A-Za-zÀ-ÿ一-龥가-힣ぁ-んァ-ン]", stripped)
    return len("".join(letters)) < 12


def build_chunk(chunk_id: int, hand_rows):
    srcs = json.loads(Path(f"/tmp/dabot_i18n_extract/chunk_{chunk_id:02d}.json").read_text(encoding="utf-8"))
    hand = {row[0]: row[1:] for row in hand_rows}
    rows = []
    missing = []
    for src in srcs:
        if src in hand:
            rows.append((src, *hand[src]))
        elif mostly_template(src):
            rows.append((src,) + (src,) * 9)
        else:
            missing.append(src)
    if missing:
        print("MISSING", len(missing))
        for item in missing:
            print(" -", item[:120].replace("\n", " / "))
        raise SystemExit(f"chunk {chunk_id}: {len(missing)} untranslated")
    return emit(f"part_{chunk_id:02d}.json", rows)
