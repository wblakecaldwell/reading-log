#!/usr/bin/env python3
"""Copy processed log photos into _private/log-photos/ as YYYY-MM-DD_NN.<ext>.

Usage: archive_photos.py PHOTO [PHOTO ...] [--date YYYY-MM-DD]

Skips exact duplicates (SHA-256 against everything already in log-photos/),
never overwrites, and continues numbering after today's highest index.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "_private" / "log-photos"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive(photos: list[Path], dest: Path = DEST, date: str | None = None) -> dict:
    date = date or dt.date.today().isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    known = {sha256(p) for p in dest.iterdir() if p.is_file()}
    pat = re.compile(rf"^{re.escape(date)}_(\d+)\.")
    idx = max((int(m.group(1)) for p in dest.iterdir() if (m := pat.match(p.name))), default=0)
    copied, skipped = [], []
    for src in photos:
        digest = sha256(src)
        if digest in known:
            skipped.append(str(src))
            continue
        idx += 1
        ext = (src.suffix.lower().lstrip(".") or "jpg")
        target = dest / f"{date}_{idx:02d}.{ext}"
        while target.exists():  # paranoia: never overwrite
            idx += 1
            target = dest / f"{date}_{idx:02d}.{ext}"
        shutil.copy2(src, target)
        known.add(digest)
        copied.append(target.name)
    return {"copied": copied, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("photos", nargs="+", type=Path)
    ap.add_argument("--date")
    ap.add_argument("--dest", type=Path, default=DEST)
    a = ap.parse_args()
    res = archive(a.photos, a.dest, a.date)
    for n in res["copied"]:
        print("archived:", n)
    for n in res["skipped"]:
        print("duplicate, skipped:", n)
    print(f"{len(res['copied'])} archived, {len(res['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
