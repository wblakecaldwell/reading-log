#!/usr/bin/env python3
"""Compile _private/to-print/covers-YYYY-MM-DD.pdf for every book with cover_status: needed.

Exact 1:1 physical layout on US Letter with ReportLab. Each cover is fitted
inside a 3.3 x 4.31 cm box (aspect preserved). Width-constrained covers stand
upright in 3.3 cm columns; height-constrained covers are rotated 90 degrees and
stacked in 4.31 cm columns, so every column's left/right edges line up for
straight paper-cutter cuts. >= 1.0 cm between covers, >= 1.25 cm outer margin,
and a labelled 5.0 cm calibration bar in each page's bottom margin.

After writing the PDF, the included books flip needed -> printed, and a
manifest (covers-YYYY-MM-DD.json next to the PDF) records which books it holds.

Usage:
    build_cutouts.py [--date YYYY-MM-DD]       # build a sheet for every `needed` book
    build_cutouts.py --dry-run                  # report the layout; writes nothing
    build_cutouts.py --redo to-print/covers-YYYY-MM-DD.pdf
        # The sheet has NOT been printed yet and needs rebuilding (e.g. a cover
        # was replaced or a book corrected): flips that sheet's books back to
        # needed, removes the sheet and its manifest, then builds a fresh sheet
        # under the same name. Never use it on a sheet that has been printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_book import BOOKS_YAML, DATA, load_books, save_books, sort_key  # noqa: E402

CM = 28.3465                # points per cm
PAGE_W, PAGE_H = 21.59, 27.94
MARGIN = 1.25               # outer margin, all sides
BOTTOM_RESERVE = 1.25       # extra band above the bottom margin for the calibration bar
BOX_W, BOX_H = 3.3, 4.31
GAP = 1.0
EPS = 1e-9


@dataclass
class Placed:
    book_id: str
    image: str
    x: float          # cm, lower-left of the placed (possibly rotated) rectangle
    y: float
    w: float          # cm, placed width/height on the page
    h: float
    rotated: bool
    page: int


def fit(img_w: float, img_h: float) -> tuple[float, float, bool]:
    """Fit into BOX_W x BOX_H. Returns (w, h, width_constrained)."""
    scale = min(BOX_W / img_w, BOX_H / img_h)
    w, h = img_w * scale, img_h * scale
    width_constrained = abs(w - BOX_W) < 1e-6 and h <= BOX_H + 1e-6
    return w, h, width_constrained


def layout(items: list[tuple[str, str, float, float]]) -> list[Placed]:
    """items: (book_id, image_path, px_w, px_h). Pure geometry, no drawing."""
    upright, rotated = [], []
    for bid, img, pw, ph in items:
        w, h, wc = fit(pw, ph)
        if wc:
            upright.append((bid, img, BOX_W, h, False))
        else:  # height == 4.31: rotate so the 4.31 edge runs horizontally
            rotated.append((bid, img, BOX_H, w, True))
    top = PAGE_H - MARGIN
    bottom = MARGIN + BOTTOM_RESERVE
    right = PAGE_W - MARGIN
    placed: list[Placed] = []
    page, x = 0, MARGIN
    for group, col_w in ((upright, BOX_W), (rotated, BOX_H)):
        queue = list(group)
        while queue:
            if x + col_w > right + EPS:      # no room for another column
                page, x = page + 1, MARGIN
            y = top
            while queue and y - queue[0][3] >= bottom - EPS:
                bid, img, w, h, rot = queue.pop(0)
                placed.append(Placed(bid, img, x, y - h, w, h, rot, page))
                y -= h + GAP
            x += col_w + GAP
    return placed


def draw(placed: list[Placed], out: Path) -> None:
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(out), pagesize=(PAGE_W * CM, PAGE_H * CM))
    pages = max((p.page for p in placed), default=-1) + 1
    for pg in range(pages):
        for p in (q for q in placed if q.page == pg):
            img = ImageReader(str(DATA / p.image))
            x, y, w, h = p.x * CM, p.y * CM, p.w * CM, p.h * CM
            if p.rotated:
                c.saveState()
                c.translate(x + w, y)
                c.rotate(90)          # image's own width runs up the page
                c.drawImage(img, 0, 0, width=h, height=w)
                c.restoreState()
            else:
                c.drawImage(img, x, y, width=w, height=h)
            c.setStrokeColor(HexColor("#cccccc"))
            c.setLineWidth(0.5)
            c.rect(x, y, w, h, stroke=1, fill=0)
        # calibration bar in the bottom margin band
        bx, by = MARGIN * CM, (MARGIN + 0.35) * CM
        c.setStrokeColor(black)
        c.setLineWidth(0.75)
        c.line(bx, by, bx + 5.0 * CM, by)
        for t in range(6):
            tick = 0.25 * CM if t in (0, 5) else 0.15 * CM
            c.line(bx + t * CM, by, bx + t * CM, by + tick)
        c.setFont("Helvetica", 7)
        c.drawString(bx + 5.0 * CM + 0.25 * CM, by - 2,
                     "5.0 cm calibration bar: measure with a ruler; print at 100% / no scaling")
        c.drawRightString((PAGE_W - MARGIN) * CM, by - 2, f"page {pg + 1} of {pages}")
        c.showPage()
    c.save()


def next_path(date: str, outdir: Path) -> Path:
    p = outdir / f"covers-{date}.pdf"
    n = 2
    while p.exists():
        p = outdir / f"covers-{date}-{n}.pdf"
        n += 1
    return p


def undo_sheet(books: list[dict], sheet: Path) -> tuple[list[dict], Path]:
    """Flip an unprinted sheet's books printed -> needed and delete the sheet."""
    sheet = DATA / "to-print" / sheet.name        # sheets only ever live in to-print/
    manifest = sheet.with_suffix(".json")
    if not manifest.exists():
        raise SystemExit(f"no manifest {manifest.name}; cannot tell which books {sheet.name} holds")
    ids = set(json.loads(manifest.read_text()))
    n = 0
    for b in books:
        if b["id"] in ids and b.get("cover_status") == "printed":
            b["cover_status"] = "needed"
            n += 1
    save_books(books, BOOKS_YAML)
    sheet.unlink(missing_ok=True)
    manifest.unlink()
    print(f"redo: {n} books from {sheet.name} set back to needed")
    return load_books(BOOKS_YAML), sheet


def main() -> int:
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--redo", type=Path, help="unprinted sheet to rebuild")
    a = ap.parse_args()
    books = load_books(BOOKS_YAML)
    redo_path = None
    if a.redo:
        books, redo_path = undo_sheet(books, a.redo)
    needed = [b for b in sorted(books, key=sort_key)
              if b.get("cover_status") == "needed" and b.get("cover_image")
              and (DATA / b["cover_image"]).is_file()]
    if not needed:
        print("No covers needed; no cutout PDF generated.")
        return 0
    items = []
    for b in needed:
        with Image.open(DATA / b["cover_image"]) as im:
            items.append((b["id"], b["cover_image"], im.width, im.height))
    placed = layout(items)
    outdir = DATA / "to-print"
    outdir.mkdir(parents=True, exist_ok=True)
    pages = max(p.page for p in placed) + 1
    if a.dry_run:
        print(f"dry run: {len(placed)} covers would fit on {pages} page(s); nothing written")
        return 0
    out = redo_path or next_path(a.date, outdir)
    draw(placed, out)
    out.with_suffix(".json").write_text(json.dumps(sorted(p.book_id for p in placed), indent=1))
    print(f"{out.relative_to(DATA.parent)}: {len(placed)} covers on {pages} page(s)")
    done = {p.book_id for p in placed}
    for b in books:
        if b["id"] in done and b.get("cover_status") == "needed":
            b["cover_status"] = "printed"
    save_books(books, BOOKS_YAML)
    print(f"{len(done)} books flipped needed -> printed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
