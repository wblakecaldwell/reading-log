#!/usr/bin/env python3
"""Look up a book's page count, or its listening length if it is audio-only.

Usage:
    find_pages.py "Title" "Author" [--isbn ISBN]
    find_pages.py --missing          # every book in books.yaml without pages
                                     # or audio_length; prints add_book --fill JSON

Sources, in order (first English-language hit wins):
  1. Open Library: the edition with this ISBN, then the median page count of
     the work's English editions
  2. Apple Books US ebook page: its "numberOfPages" (publisher print length),
     only when the listing's language is English and the author matches
  3. Apple Books audiobook page: its duration, reported as audio_length like
     "6 hr 30 min" when no page count was found

Check the result before storing it:
  - Apple's page counts are sometimes far too low (a full-length novel listed
    at a fraction of its print length). One under 200 is flagged "check":
    confirm it with a second source.
  - audio_length alone is right only for audio-only books (no print edition).
    If a print edition exists, find its page count (publisher or retailer
    listing via web search) instead; the output says so in "next".

Google Books is not used: its keyless quota is shared and usually exhausted.
Read-only; prints JSON.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_book import _norm, load_books  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"}
OL_UA = {"User-Agent": "book-log/1.0"}


def _get(s, url, **kw):
    for attempt in range(3):
        try:
            r = s.get(url, timeout=30, **kw)
            if r.status_code in (403, 429) and attempt < 2:
                time.sleep(8 * (attempt + 1))
                continue
            return r
        except Exception:
            time.sleep(3)
    return None


def _json(r):
    try:
        return r.json()
    except Exception:
        return {}


def _title_ok(found: str, title: str) -> bool:
    found = re.split(r"[:(]", found)[0]
    return difflib.SequenceMatcher(None, _norm(found), _norm(title.split(":")[0])).ratio() >= 0.85


def _author_ok(found: str, author: str) -> bool:
    return _norm(author.split()[-1]) in _norm(found)


def iso_duration(d: str) -> str | None:
    """'PT6H30M15S' -> '6 hr 30 min'."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:[\d.]+S)?", d or "")
    if not m or not (m.group(1) or m.group(2)):
        return None
    h, mins = int(m.group(1) or 0), int(m.group(2) or 0)
    return " ".join(p for p in [f"{h} hr" if h else "", f"{mins} min" if mins else ""] if p)


def page_count(html: str) -> int | None:
    """English-language numberOfPages from an Apple Books page, else None."""
    loc = re.search(r'primaryLocale\\?":\\?"([a-z]{2})', html)
    if loc and loc.group(1) != "en":
        return None
    m = re.search(r'"numberOfPages":(\d+)', html) or re.search(r'pageCount\\?":(\d+)', html)
    n = int(m.group(1)) if m else 0
    return n if 20 <= n <= 3000 else None


def openlibrary(s, title, author, isbn):
    if isbn:
        r = _get(s, f"https://openlibrary.org/isbn/{isbn}.json", headers=OL_UA)
        n = _json(r).get("number_of_pages") if r is not None and r.ok else None
        if n:
            return n, "openlibrary-isbn"
    r = _get(s, "https://openlibrary.org/search.json", headers=OL_UA,
             params={"title": title, "author": author.split()[-1], "limit": 3, "fields": "key,title"})
    for d in _json(r).get("docs", [])[:2]:
        if not _title_ok(d.get("title", ""), title):
            continue
        eds = _json(_get(s, f"https://openlibrary.org{d['key']}/editions.json", headers=OL_UA,
                         params={"limit": 100})).get("entries", [])
        counts = [e["number_of_pages"] for e in eds if e.get("number_of_pages")
                  and (not e.get("languages") or {"key": "/languages/eng"} in e["languages"])
                  and 20 <= e["number_of_pages"] <= 3000]
        if counts:
            return int(statistics.median(counts)), "openlibrary-editions"
    return None, None


def apple(s, title, author, media):
    r = _get(s, "https://itunes.apple.com/search",
             params={"term": f"{title} {author}", "media": media, "country": "us", "limit": 10})
    for x in _json(r).get("results", []):
        name = x.get("trackName") or x.get("collectionName") or ""
        if not (_title_ok(name, title) and _author_ok(x.get("artistName", ""), author)):
            continue
        url = (x.get("trackViewUrl") or x.get("collectionViewUrl") or "").split("?")[0]
        page = _get(s, url, headers=UA)
        if page is None or not page.ok:
            continue
        if media == "ebook":
            n = page_count(page.text)
            if n:
                return n
        else:
            m = re.search(r'"duration":"(PT[^"]+)"', page.text)
            if m and iso_duration(m.group(1)):
                return iso_duration(m.group(1))
        time.sleep(1)
    return None


def lookup(title, author, isbn=None, session=None):
    import requests
    s = session or requests.Session()
    pages, src = openlibrary(s, title, author, isbn)
    if not pages:
        pages = apple(s, title, author, "ebook")
        src = "apple-ebook" if pages else None
    out = {"title": title, "author": author, "pages": pages, "source": src}
    if pages and src == "apple-ebook" and pages < 200:
        out["check"] = "Apple page count under 200; confirm with a second source"
    if not pages:
        length = apple(s, title, author, "audiobook")
        if length:
            out.update(audio_length=length, source="apple-audiobook")
        out["next"] = ("no page count found: if a print edition exists, look up its page "
                       "count; use audio_length only for audio-only books")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("title", nargs="?")
    ap.add_argument("author", nargs="?")
    ap.add_argument("--isbn")
    ap.add_argument("--missing", action="store_true")
    a = ap.parse_args()
    if a.missing:
        import requests
        s = requests.Session()
        fills = []
        for b in load_books():
            if b.get("pages") or b.get("audio_length"):
                continue
            r = lookup(b["title"], b["author"], b.get("isbn"), s)
            fill = {"id": b["id"], "_source": r["source"]}
            if r.get("pages"):
                fill["pages"] = r["pages"]
            if r.get("audio_length"):
                fill["audio_length"] = r["audio_length"]
            fills.append(fill)
            print(f"{b['id']}: {fill}", file=sys.stderr)
            time.sleep(2)
        print(json.dumps(fills, indent=1))
        return 0
    if not (a.title and a.author):
        ap.error("give a title and author, or --missing")
    print(json.dumps(lookup(a.title, a.author, a.isbn), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
