"""Accumulate HAND rows and fill leftover chunks 12–21."""
import json
from pathlib import Path
from _emit import build_chunk, mostly_template, LANGS

HAND = {}


def add(src, es, en, fr, de, pt, it, ja, ko, zh):
    HAND[src] = (es, en, fr, de, pt, it, ja, ko, zh)


def fill_remaining(start=12, end=21):
    missing_all = []
    for chunk_id in range(start, end + 1):
        srcs = json.loads(Path(f"/tmp/dabot_i18n_extract/chunk_{chunk_id:02d}.json").read_text(encoding="utf-8"))
        rows = []
        missing = []
        for src in srcs:
            if src in HAND:
                rows.append((src, *HAND[src]))
            elif mostly_template(src):
                rows.append((src,) + (src,) * 9)
            else:
                missing.append(src)
        if missing:
            missing_all.extend(missing)
            print(f"chunk {chunk_id}: still {len(missing)} missing")
            continue
        from _emit import emit
        emit(f"part_{chunk_id:02d}.json", rows)
    if missing_all:
        Path("/tmp/dabot_i18n_extract/still_missing.json").write_text(
            json.dumps(missing_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("STILL_MISSING", len(missing_all))
        return False
    return True
