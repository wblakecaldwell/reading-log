#!/usr/bin/env python3
"""Privacy guard for commits: keeps personal reading-log data out of git.

Run by .githooks/pre-commit (staged files and added lines) and
.githooks/commit-msg (the message). Enable once per clone:

    git config core.hooksPath .githooks

Blocked files: anything under _private/, CLAUDE.local.md, PDFs and images,
YAML/JSON data outside tests/, .env files, keys, .DS_Store.

Blocked text (case-insensitive, whole words):
  - every title and author in _private/books.yaml (multi-word or 8+ letters),
    every ISBN (13- and 10-digit) and every listening length there, read on
    this machine at commit time so the values themselves are never committed
  - every line of _private/blocked-terms.txt (names and anything else private)
  - this Mac's computer name and printer names, read from the system
  - email addresses, home-folder paths, and common API key/token formats

Allowed: the copyright line in LICENSE and the repo's clone URL in README.md.
The terms themselves are never printed in full, only the file and line.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True).stdout.strip() or ".")
PRIVATE = ROOT / "_private"

BLOCKED_PATH = [
    (re.compile(r"(^|/)_private/"), "personal data folder"),
    (re.compile(r"(^|/)CLAUDE\.local\.md$"), "private Claude notes"),
    (re.compile(r"\.(pdf|png|jpe?g|heic|heif|gif|webp|tiff?|bmp)$", re.I), "PDF or image"),
    (re.compile(r"(^|/)books\.ya?ml$", re.I), "book database"),
    (re.compile(r"^(?!tests/).*\.(ya?ml|json)$", re.I), "data file outside tests/"),
    (re.compile(r"(^|/)\.env(\..*)?$"), "environment file"),
    (re.compile(r"\.(pem|key|p12)$", re.I), "key file"),
    (re.compile(r"(^|/)\.DS_Store$"), "Finder metadata"),
]
PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "email address"),
    (re.compile(r"/Users/[^/\s]+|/home/[^/\s]+|C:\\Users\\", re.I), "home-folder path"),
    (re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
]
# (file, regex) pairs whose matching lines may contain the owner's name.
ALLOW = [
    ("LICENSE", re.compile(r"^Copyright \(c\)")),
    ("README.md", re.compile(r"github\.com/[\w-]+/reading-log(\.git)?")),
    (".githooks/guard.py", re.compile(r"re\.compile\(")),   # the guard's own patterns
]


def _cmd(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def isbn10(isbn13: str) -> str:
    core = isbn13[3:12]
    check = (11 - sum((10 - i) * int(c) for i, c in enumerate(core)) % 11) % 11
    return core + ("X" if check == 10 else str(check))


def private_terms() -> list[str]:
    terms: set[str] = set()
    db = PRIVATE / "books.yaml"
    if db.exists():
        for m in re.finditer(r"^\s*(?:- )?(title|author):\s*(.+)$", db.read_text(errors="replace"), re.M):
            v = m.group(2).strip().strip("'\"")
            if " " in v or len(v) >= 8:
                terms.add(v)
        for m in re.finditer(r"^\s*isbn:\s*['\"]?(\d{9,13}X?)", db.read_text(errors="replace"), re.M):
            terms.add(m.group(1))
            if len(m.group(1)) == 13 and m.group(1).startswith("978"):
                terms.add(isbn10(m.group(1)))
        for m in re.finditer(r"^\s*audio_length:\s*['\"]?([^'\"\n]+)", db.read_text(errors="replace"), re.M):
            v = m.group(1).strip()
            terms.add(v)
            hm = re.fullmatch(r"(?:(\d+) hr)?\s*(?:(\d+) min)?", v)
            if hm and (hm.group(1) or hm.group(2)):            # ISO form, e.g. PT5H20M
                terms.add("PT" + (f"{hm.group(1)}H" if hm.group(1) else "") + (f"{hm.group(2)}M" if hm.group(2) else ""))
    extra = PRIVATE / "blocked-terms.txt"
    if extra.exists():
        terms |= {ln.strip() for ln in extra.read_text().splitlines()
                  if ln.strip() and not ln.startswith("#")}
    for name in (_cmd("scutil", "--get", "ComputerName"), _cmd("scutil", "--get", "LocalHostName")):
        if name.strip():
            terms.add(name.strip())
    for m in re.finditer(r"^printer (\S+)", _cmd("lpstat", "-p"), re.M):
        terms.add(m.group(1))
        terms.add(m.group(1).split("_")[0])       # brand, e.g. the first word of the queue
    return sorted(t for t in terms if len(t) >= 3)


def term_regex(terms: list[str]) -> re.Pattern | None:
    if not terms:
        return None
    parts = []
    for t in terms:
        words = [re.escape(w) for w in re.split(r"[\s_-]+", t) if w]
        parts.append(r"(?<![A-Za-z0-9])" + r"[\s_-]+".join(words) + r"(?![A-Za-z0-9])")
    return re.compile("|".join(parts), re.I)


def scan_text(label: str, lines: list[tuple[int, str]], terms_re) -> list[str]:
    problems = []
    for n, line in lines:
        if any(label == f and rx.search(line) for f, rx in ALLOW):
            continue
        if terms_re and (m := terms_re.search(line)):
            hidden = m.group(0)[:2] + "…"
            problems.append(f"{label}:{n}: private term ({hidden})")
        for rx, what in PATTERNS:
            if rx.search(line):
                problems.append(f"{label}:{n}: {what}")
    return problems


def staged() -> list[str]:
    problems = []
    names = _cmd("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR").split("\n")
    for f in filter(None, names):
        for rx, what in BLOCKED_PATH:
            if rx.search(f):
                problems.append(f"{f}: {what} must not be committed")
                break
    terms_re = term_regex(private_terms())
    diff = _cmd("git", "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR")
    current, lineno, added = None, 0, {}
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and current:
            lineno = int(re.search(r"\+(\d+)", line).group(1))
        elif current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append((lineno, line[1:]))
            lineno += 1
    for f, lines in added.items():
        problems += scan_text(f, lines, terms_re)
    return problems


def message(path: str) -> list[str]:
    text = Path(path).read_text(errors="replace")
    lines = [(i + 1, ln) for i, ln in enumerate(text.splitlines()) if not ln.startswith("#")]
    return scan_text("commit message", lines, term_regex(private_terms()))


def main(argv: list[str]) -> int:
    problems = message(argv[2]) if len(argv) > 2 and argv[1] == "msg" else staged()
    if problems:
        print("Commit blocked by the privacy guard (.githooks/guard.py):", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        print("Remove the personal data; do not bypass with --no-verify.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
