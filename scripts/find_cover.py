#!/usr/bin/env python3
"""Find flat, high-resolution cover candidates for one book (read-only lookups).

Usage:
    find_cover.py "Title" "Author" [--isbn ISBN ...] [--asin ASIN ...]
                  [--url PAGE_URL ...] [--out DIR]

Tries, in order, every source below and keeps every image it can download:
  1. Apple Books US ebook artwork (full size), skipping foreign editions
  2. Open Library covers for every English edition of the matching work
  3. Amazon for each --asin and each ISBN-10: the product page's "hiRes" image
     when the page is served, plus the ~500px public listing image
  4. Images and Amazon links found on each --url (author or publisher pages)

Each candidate is checked with add_book's rules: at least MIN_COVER_HEIGHT
tall, portrait or square, and not a 3D mockup. Passing candidates are saved to
--out (default: a temp dir) and printed as JSON, best first, so the caller can
look at them and pass the chosen file to add_book.py as cover_file. Mockups are
listed separately as a last resort. Nothing in _private/ is touched.
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_book import MIN_COVER_HEIGHT, _norm, looks_like_mockup  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15"}
OL_UA = {"User-Agent": "book-log/1.0"}
# Apple artwork file names that are non-English-market ISBNs (FR, DE, IT, ...).
FOREIGN_ISBN = re.compile(r"^(978[2-9]|9791[0-2])")


def isbn13_to_10(isbn: str) -> str | None:
    """ISBN-10 (= Amazon ASIN for print books) for a 978 ISBN-13, else None."""
    d = re.sub(r"\D", "", isbn)
    if len(d) == 10:
        return d
    if len(d) != 13 or not d.startswith("978"):
        return None
    core = d[3:12]
    check = (11 - sum((10 - i) * int(c) for i, c in enumerate(core)) % 11) % 11
    return core + ("X" if check == 10 else str(check))


def amazon_hires(html: str) -> list[str]:
    """Full-size image URLs from an Amazon product page, size suffix removed."""
    urls = re.findall(r'"hiRes":"(https://[^"]+)"', html)
    urls += re.findall(r'data-old-hires="(https://[^"]+)"', html)
    out = []
    for u in urls:
        u = re.sub(r"\._[^/]*_\.(jpg|png)$", r".\1", u)
        if u not in out:
            out.append(u)
    return out


def apple_art_full(url100: str) -> str:
    return re.sub(r"/\d+x\d+bb\.(jpg|png)$", r"/3000x3000bb.\1", url100)


def _get(session, url, **kw):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=30, **kw)
            if r.status_code == 429 or (r.status_code == 403 and attempt < 2):
                time.sleep(5 * (attempt + 1))
                continue
            return r
        except Exception:
            time.sleep(2)
    return None


def apple_candidates(s, title, author):
    r = _get(s, "https://itunes.apple.com/search",
             params={"term": f"{title} {author}", "media": "ebook", "country": "us", "limit": 15})
    try:
        results = r.json()["results"]
    except Exception:
        return []
    out = []
    last = _norm(author.split()[-1])
    for x in results:
        name = (x.get("trackName") or "").split("(")[0]
        art = x.get("artworkUrl100") or ""
        fname = art.rsplit("/", 2)[-2] if art.count("/") > 2 else ""
        if last not in _norm(x.get("artistName", "")) or FOREIGN_ISBN.match(fname):
            continue
        if difflib.SequenceMatcher(None, _norm(name), _norm(title)).ratio() < 0.8:
            continue
        out.append(("apple-ebook", apple_art_full(art)))
    return out


def openlibrary_candidates(s, title, author):
    r = _get(s, "https://openlibrary.org/search.json", headers=OL_UA,
             params={"title": title, "author": author.split()[-1], "limit": 3, "fields": "key,title"})
    try:
        docs = r.json()["docs"]
    except Exception:
        return [], []
    out, isbns = [], []
    for d in docs[:2]:
        if difflib.SequenceMatcher(None, _norm(d.get("title", "")), _norm(title)).ratio() < 0.8:
            continue
        er = _get(s, f"https://openlibrary.org{d['key']}/editions.json", headers=OL_UA,
                  params={"limit": 100})
        try:
            eds = er.json()["entries"]
        except Exception:
            continue
        for e in eds:
            langs = [lang["key"] for lang in e.get("languages", [])]
            if langs and "/languages/eng" not in langs:
                continue
            isbns += e.get("isbn_13", []) + e.get("isbn_10", [])
            for cid in e.get("covers", []):
                if cid > 0:
                    out.append(("openlibrary", f"https://covers.openlibrary.org/b/id/{cid}.jpg"))
    return out, isbns


def amazon_candidates(s, asins):
    out = []
    for a in asins:
        r = _get(s, f"https://www.amazon.com/dp/{a}", headers=UA)
        if r is not None and r.ok:
            out += [("amazon", u) for u in amazon_hires(r.text)[:2]]
        # Public listing image by ASIN (~500px tall); works even when the
        # product page itself is not served to scripts.
        out.append(("amazon-listing", f"https://m.media-amazon.com/images/P/{a}.01._SCLZZZZZZZ_.jpg"))
        time.sleep(1)
    return out


def page_candidates(s, urls):
    """Images and Amazon ASINs linked from author/publisher pages."""
    out, asins = [], []
    for page in urls:
        r = _get(s, page, headers=UA)
        if r is None or not r.ok:
            continue
        for src in re.findall(r'(?:src|href)="([^"]+\.(?:jpe?g|png|webp))"', r.text, re.I):
            out.append(("author-site", urljoin(page, src)))
        asins += re.findall(r"amazon\.com/(?:[^\"']*/)?dp/([A-Z0-9]{10})", r.text)
    return out, asins


def check(s, src, url, outdir, n):
    from PIL import Image
    r = _get(s, url, headers=UA)
    if r is None or not r.ok:
        return None
    try:
        img = Image.open(io.BytesIO(r.content))
        img.load()
    except Exception:
        return None
    w, h = img.size
    info = {"source": src, "url": url, "width": w, "height": h}
    if h < MIN_COVER_HEIGHT or h < w * 0.95:     # too small, or a banner/landscape image
        return None
    info["mockup"] = looks_like_mockup(img)
    ext = "png" if img.format == "PNG" else "jpg"
    path = outdir / f"cand_{n:02d}_{src}.{ext}"
    path.write_bytes(r.content)
    info["file"] = str(path)
    return info


def find(title, author, isbns=(), asins=(), urls=(), outdir=None):
    import requests
    outdir = Path(outdir or tempfile.mkdtemp(prefix="covers_"))
    outdir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    cands = apple_candidates(s, title, author)
    ol, ol_isbns = openlibrary_candidates(s, title, author)
    cands += ol
    site, site_asins = page_candidates(s, urls)
    all_asins = list(dict.fromkeys(
        list(asins) + site_asins + [a for a in map(isbn13_to_10, list(isbns) + ol_isbns) if a]))
    cands += amazon_candidates(s, all_asins[:8])
    cands += site
    seen, found = set(), []
    for src, url in cands:
        if url in seen:
            continue
        seen.add(url)
        info = check(s, src, url, outdir, len(found))
        if info:
            found.append(info)
    # Portrait print covers beat square audiobook art, then taller beats shorter.
    flat = sorted((f for f in found if not f["mockup"]),
                  key=lambda f: (f["height"] < f["width"] * 1.2, -f["height"]))
    mock = sorted((f for f in found if f["mockup"]), key=lambda f: -f["height"])
    return {"title": title, "author": author, "out_dir": str(outdir),
            "flat": flat, "mockups_last_resort": mock}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("title")
    ap.add_argument("author")
    ap.add_argument("--isbn", action="append", default=[])
    ap.add_argument("--asin", action="append", default=[])
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--out")
    a = ap.parse_args()
    print(json.dumps(find(a.title, a.author, a.isbn, a.asin, a.url, a.out), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
