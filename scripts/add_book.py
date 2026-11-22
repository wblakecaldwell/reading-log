#!/usr/bin/env python3
"""Sole writer to books.yaml and cover-art/.

Usage:
    add_book.py BOOKS.json         # one object or a list of objects
    add_book.py -                  # read JSON from stdin

Each input object: title, author, year_released, isbn, pages, description,
cover_url (or cover_file), pasted (bool). Existing books (same ISBN, or same
canonical title + author) are never duplicated or overwritten; a `pasted: true`
sighting only upgrades cover_status to `pasted`.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "_private"          # all personal reading-log data (gitignored)
BOOKS_YAML = DATA / "books.yaml"
COVER_DIR = DATA / "cover-art"
STATUS_RANK = {"needed": 0, "printed": 1, "pasted": 2}
FIELDS = ["id", "title", "author", "year_released", "isbn", "pages",
          "cover_image", "cover_status", "description"]
MIN_COVER_HEIGHT = 500


# ---------------------------------------------------------------- naming ---
def slug(text: str) -> str:
    """Lowercase ASCII alphanumerics; runs of anything else become one '_'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def split_author(author: str) -> tuple[str, str]:
    """First listed author -> (last, first). Handles 'A & B', 'A, B', 'A and B'."""
    first_author = re.split(r"\s*(?:&|,| and )\s*", author.strip())[0]
    parts = first_author.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def make_id(title: str, author: str) -> str:
    last, first = split_author(author)
    author_seg = "_".join(s for s in (slug(last), slug(first)) if s)
    return f"{author_seg}-{slug(title)}"


# --------------------------------------------------------------- sorting ---
_ARTICLE = re.compile(r"^(a|an|the)\s+", re.I)


def sort_key(book: dict) -> tuple[str, str]:
    """Publisher-alphabetical: case-insensitive, ignore leading A/An/The."""
    title = _ARTICLE.sub("", (book.get("title") or "").strip()).casefold()
    return title, (book.get("author") or "").casefold()


# ----------------------------------------------------------- persistence ---
class _Folded(str):
    pass


def _folded_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=">")


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(_Folded, _folded_repr)


def load_books(path: Path = BOOKS_YAML) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or []


def save_books(books: list[dict], path: Path = BOOKS_YAML) -> None:
    """Sort, write to .tmp, verify it parses back identically, os.replace()."""
    ordered = sorted(books, key=sort_key)
    out = []
    for b in ordered:
        rec = {k: b.get(k) for k in FIELDS}
        if rec["isbn"] is not None:
            rec["isbn"] = str(rec["isbn"])
        if rec["description"]:
            rec["description"] = _Folded(" ".join(str(rec["description"]).split()))
        out.append(rec)
    text = yaml.dump(out, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=80, default_flow_style=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    reparsed = yaml.safe_load(tmp.read_text(encoding="utf-8")) or []
    if [r["id"] for r in reparsed] != [r["id"] for r in out] or len(reparsed) != len(out):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("books.yaml.tmp failed round-trip verification")
    os.replace(tmp, path)


# ----------------------------------------------------------------- dedup ---
def _norm(s: str) -> str:
    return slug(_ARTICLE.sub("", s or ""))


def find_existing(books: list[dict], rec: dict) -> dict | None:
    isbn = str(rec.get("isbn") or "").strip()
    for b in books:
        if isbn and str(b.get("isbn") or "") == isbn:
            return b
    for b in books:
        if b.get("id") == rec.get("id"):
            return b
        if _norm(b["title"]) == _norm(rec["title"]) and \
                split_author(b["author"])[0].lower() == split_author(rec["author"])[0].lower():
            return b
    return None


def upgrade_status(current: str, new: str) -> str:
    """Monotonic: never downgrade needed < printed < pasted."""
    return new if STATUS_RANK[new] > STATUS_RANK[current] else current


# ----------------------------------------------------------------- cover ---
def fetch_cover(rec: dict, book_id: str) -> str:
    """Download (or copy) the cover once; returns its repo-relative path."""
    from PIL import Image

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    for existing in COVER_DIR.glob(book_id + ".*"):
        return f"cover-art/{existing.name}"
    if rec.get("cover_file"):
        data = Path(rec["cover_file"]).read_bytes()
    else:
        import requests
        r = requests.get(rec["cover_url"], timeout=60,
                         headers={"User-Agent": "book-log/1.0"})
        r.raise_for_status()
        data = r.content
    img = Image.open(io.BytesIO(data))
    if img.height < MIN_COVER_HEIGHT:
        raise ValueError(f"{book_id}: cover only {img.height}px tall (< {MIN_COVER_HEIGHT})")
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(img.format, "jpg")
    if ext == "webp":
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=95)
        data, ext = buf.getvalue(), "jpg"
    dest = COVER_DIR / f"{book_id}.{ext}"
    dest.write_bytes(data)
    return f"cover-art/{dest.name}"


# ------------------------------------------------------------------ main ---
def add_books(items: list[dict], path: Path = BOOKS_YAML, download=fetch_cover) -> dict:
    books = load_books(path)
    stats = {"added": [], "known": [], "upgraded": []}
    for item in items:
        rec = dict(item)
        rec["id"] = make_id(rec["title"], rec["author"])
        status = "pasted" if rec.get("pasted") else "needed"
        existing = find_existing(books, rec)
        if existing:
            new = upgrade_status(existing.get("cover_status", "needed"), status)
            if new != existing.get("cover_status"):
                existing["cover_status"] = new
                stats["upgraded"].append(existing["id"])
            else:
                stats["known"].append(existing["id"])
            continue
        rec["cover_image"] = download(rec, rec["id"]) if download else None
        rec["cover_status"] = status
        books.append({k: rec.get(k) for k in FIELDS})
        stats["added"].append(rec["id"])
    save_books(books, path)
    return stats


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    raw = sys.stdin.read() if argv[1] == "-" else Path(argv[1]).read_text(encoding="utf-8")
    items = json.loads(raw)
    if isinstance(items, dict):
        items = [items]
    stats = add_books(items)
    print(json.dumps({k: len(v) for k, v in stats.items()}))
    for k, v in stats.items():
        for i in v:
            print(f"{k}: {i}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
