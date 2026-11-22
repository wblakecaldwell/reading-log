#!/usr/bin/env python3
"""Fuzzy lookup against books.yaml (read-only).

Usage:
    find_books.py "Title" ["Author"]        # one query
    find_books.py --json QUERIES.json       # list of {"title":..,"author":..}

Prints JSON: for each query, the best matches (score >= 0.6) with id, title,
author, isbn, cover_status.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_book import BOOKS_YAML, _norm, load_books, split_author  # noqa: E402


def score(book: dict, title: str, author: str | None) -> float:
    t = difflib.SequenceMatcher(None, _norm(book["title"]), _norm(title)).ratio()
    if not author:
        return t
    a = difflib.SequenceMatcher(None, split_author(book["author"])[0].lower(),
                                split_author(author)[0].lower()).ratio()
    return 0.75 * t + 0.25 * a


def find(books, title, author=None, threshold=0.6, limit=3):
    scored = sorted(((score(b, title, author), b) for b in books), key=lambda x: -x[0])
    return [dict(score=round(s, 3), **{k: b.get(k) for k in
                 ("id", "title", "author", "isbn", "cover_status")})
            for s, b in scored[:limit] if s >= threshold]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("title", nargs="?")
    ap.add_argument("author", nargs="?")
    ap.add_argument("--json")
    ap.add_argument("--db", default=str(BOOKS_YAML))
    args = ap.parse_args()
    books = load_books(Path(args.db))
    queries = json.loads(Path(args.json).read_text()) if args.json else \
        [{"title": args.title, "author": args.author}]
    out = [dict(query=q, matches=find(books, q["title"], q.get("author"))) for q in queries]
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
