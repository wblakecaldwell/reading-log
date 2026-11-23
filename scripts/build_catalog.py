#!/usr/bin/env python3
"""Compile _private/book-log.pdf (every book in books.yaml) with WeasyPrint.

Four books per page: each card is sized to fit a quarter of the page, and a
page break follows every fourth card, so pages never hold three or five.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_book import BOOKS_YAML, DATA, load_books, sort_key  # noqa: E402

PER_PAGE = 4
# Homebrew's pango/gobject live here; dyld only reads this at process start.
MAC_LIB_DIRS = "/opt/homebrew/lib:/usr/local/lib"

CSS = """
@page { size: 8.5in 11in; margin: 0.75in;
  @bottom-center { content: counter(page); font-size: 8.5pt; color: #666666;
    font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif; } }
body { font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 10pt; line-height: 1.45; color: #1a1a1a; margin: 0; }
.entry { display: flex; gap: 0.25in; padding: 0.12in 0; border-bottom: 1px solid #e0e0e0;
  height: 2.2in; box-sizing: border-box; overflow: hidden;
  break-inside: avoid; page-break-inside: avoid; }
.entry:nth-child(PER_PAGEn) { break-after: page; border-bottom: none; }
.entry:last-child { border-bottom: none; }
.cover { width: 1.3in; flex-shrink: 0; }
.cover img { width: 1.3in; height: auto; max-height: 1.95in; object-fit: contain;
  border-radius: 3px; border: 1px solid #d0d0d0; display: block; }
.fallback { width: 1.3in; height: 1.95in; background: #f0f0f0; border-radius: 3px;
  border: 1px solid #d0d0d0; display: flex; align-items: center; justify-content: center;
  text-align: center; font-size: 9pt; color: #666; padding: 0.1in; box-sizing: border-box; }
.info { flex: 1; min-width: 0; }
.title { font-size: 15pt; font-weight: 700; color: #000000; margin: 0 0 2pt 0; line-height: 1.2; }
.author { font-size: 11pt; font-weight: 500; color: #4a4a4a; margin: 0 0 8pt 0; }
.desc { font-size: 10pt; font-weight: 400; color: #222222; margin: 0 0 10pt 0; }
.meta { font-size: 8.5pt; color: #666666; margin: 0; }
""".replace("PER_PAGE", str(PER_PAGE))


def meta_line(b: dict) -> str:
    parts = []
    if b.get("pages"):
        parts.append(f"{b['pages']} pages")
    elif b.get("audio_length"):
        parts.append(f"Audiobook, {b['audio_length']}")
    if b.get("isbn"):
        parts.append(f"ISBN {b['isbn']}")
    if b.get("year_released"):
        parts.append(f"Published {b['year_released']}")
    return " · ".join(parts)


def entry_html(b: dict, root: Path) -> str:
    e = html.escape
    cover = root / (b.get("cover_image") or "")
    if b.get("cover_image") and cover.is_file():
        img = f'<img src="{cover.resolve().as_uri()}" alt="">'
    else:
        img = f'<div class="fallback">{e(b["title"])}</div>'
    meta = meta_line(b)
    return (f'<div class="entry"><div class="cover">{img}</div><div class="info">'
            f'<p class="title">{e(b["title"])}</p><p class="author">{e(b["author"])}</p>'
            + (f'<p class="desc">{e(b["description"].strip())}</p>' if b.get("description") else "")
            + (f'<p class="meta">{e(meta)}</p>' if meta else "") + "</div></div>")


def build_html(books: list[dict], root: Path = DATA) -> str:
    body = "\n".join(entry_html(b, root) for b in sorted(books, key=sort_key))
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def _import_weasyprint():
    """Import WeasyPrint, re-running this script with Homebrew's library path
    on macOS if its native libraries can't be found."""
    try:
        from weasyprint import HTML
        return HTML
    except OSError:
        if sys.platform != "darwin" or os.environ.get("BOOKLOG_REEXEC"):
            raise
        env = dict(os.environ, BOOKLOG_REEXEC="1",
                   DYLD_FALLBACK_LIBRARY_PATH=":".join(
                       x for x in [os.environ.get("DYLD_FALLBACK_LIBRARY_PATH"), MAC_LIB_DIRS] if x))
        os.execve(sys.executable, [sys.executable, *sys.argv], env)


def main() -> int:
    HTML = _import_weasyprint()
    books = load_books(BOOKS_YAML)
    out = DATA / "book-log.pdf"
    tmp = out.with_suffix(".pdf.tmp")
    HTML(string=build_html(books), base_url=str(DATA)).write_pdf(tmp)
    tmp.replace(out)
    print(f"book-log.pdf: {len(books)} books")
    return 0


if __name__ == "__main__":
    sys.exit(main())
