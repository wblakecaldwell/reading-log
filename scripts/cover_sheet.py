#!/usr/bin/env python3
"""Contact sheet of cover images for a quick visual check (read-only).

Usage:
    cover_sheet.py                    # covers written today
    cover_sheet.py --since 2026-11-01 # covers written on or after a date
    cover_sheet.py --all              # every cover
    cover_sheet.py ID [ID ...]        # specific books

Writes _private/previews/cover-sheet.jpg: a labelled grid of thumbnails, each
tagged with its pixel size and MOCKUP? when add_book's mockup check fires.
Open it and look for wrong books, mockups, banners and foreign editions before
building the PDFs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_book import COVER_DIR, DATA, looks_like_mockup  # noqa: E402

OUT = DATA / "previews" / "cover-sheet.jpg"
TW, TH, LABEL, COLS = 180, 270, 44, 8


def pick(ids: list[str], since: dt.date | None, everything: bool) -> list[Path]:
    files = sorted(p for p in COVER_DIR.glob("*.*") if not p.name.startswith("."))
    if ids:
        return [p for p in files if p.stem in set(ids)]
    if everything:
        return files
    since = since or dt.date.today()
    return [p for p in files if dt.date.fromtimestamp(p.stat().st_mtime) >= since]


def sheet(files: list[Path], out: Path = OUT) -> Path:
    from PIL import Image, ImageDraw
    rows = max(1, (len(files) + COLS - 1) // COLS)
    canvas = Image.new("RGB", (COLS * TW, rows * (TH + LABEL)), "white")
    d = ImageDraw.Draw(canvas)
    for i, p in enumerate(files):
        with Image.open(p) as im:
            w, h = im.size
            flag = looks_like_mockup(im)
            thumb = im.convert("RGB")
            thumb.thumbnail((TW - 8, TH - 8))
        x, y = (i % COLS) * TW, (i // COLS) * (TH + LABEL)
        canvas.paste(thumb, (x + 4, y + 4))
        d.text((x + 4, y + TH), p.stem[:30], fill="black")
        d.text((x + 4, y + TH + 14), p.stem[30:60], fill="black")
        d.text((x + 4, y + TH + 28), f"{w}x{h}" + ("  MOCKUP?" if flag else ""),
               fill="red" if flag or h < 500 else "gray")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=85)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--since", type=dt.date.fromisoformat)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    files = pick(a.ids, a.since, a.all)
    if not files:
        print("no covers matched")
        return 0
    out = sheet(files)
    print(f"{out.relative_to(DATA.parent)}: {len(files)} covers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
