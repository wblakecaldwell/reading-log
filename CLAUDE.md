# The Job

Maintain an incremental, persistent book-tracking system from attached photos of handwritten pages in a physical reading log. Everything specific to the physical log (its layout, cover-box size, paper, printer) is defined once in **Book Log Profile** below.

Each run processes a partial batch of new or overlapping log photos and maintains five artifacts:
1. Date-stamped copies of processed log photos in `_private/log-photos/`
2. High-resolution cover art in `_private/cover-art/`
3. A single, sorted YAML database at `_private/books.yaml`
4. A complete, alphabetically sorted digital catalog at `_private/book-log.pdf`
5. A 1:1 printable cover cutout sheet in `_private/to-print/covers-YYYY-MM-DD.pdf` containing only covers that still need to be printed and pasted

---

# Book Log Profile

The only section to edit when using this system with a different physical log. The rest of this file refers to these values instead of hard-coding them.

| Setting | Value |
|---|---|
| Physical log | *"Reading Log, 1500 Books"* by Andrea Winterborn |
| Page layout | 10 entries per page (2 columns × 5 rows). Each entry: a cover box on the left, then `Book #`, `Title`, `Author`, `Date`, `Length`, and a 5-star rating |
| Cover box (`W × H`) | `3.3 × 4.31 cm` (`1.3 × 1.7 in`) |
| Paper | US Letter (`21.59 × 27.94 cm`, `lp` media `Letter`) |
| Printer-safe margin | `1.25 cm` on every side |
| Printer queue | `<PRINTER_QUEUE_NAME>` (any color printer; list queues with `lpstat -p`) |

The cover box is also set as `BOX_W` / `BOX_H` in `scripts/build_cutouts.py`, and the paper and margin as `PAGE_W` / `PAGE_H` / `MARGIN`. Keep them in sync with this table.

---

# Why

The reader tracks the books they read in a physical reading log. They want to print color book covers sized exactly to fit the cover box on each page, cut them out cleanly with minimal straight cuts on a paper cutter, and glue them in place, while also keeping a clean digital PDF catalog of every book they have read.

---

# Workspace Layout

All personal data lives under `_private/`, which is gitignored, so the repository holds only code. Every data path in this file (`books.yaml`, `cover-art/`, `log-photos/`, `book-log.pdf`, `to-print/`) is relative to `_private/`.

```text
.
├── CLAUDE.md
├── pyproject.toml                 # Pinned Python dependencies
├── .gitignore                     # Ignores _private/, .venv/, caches
├── scripts/
│   ├── archive_photos.py          # Date-stamps & deduplicates into _private/log-photos/
│   ├── find_books.py              # Fuzzy lookup against _private/books.yaml
│   ├── add_book.py                # Sole writer to _private/books.yaml & _private/cover-art/
│   ├── build_catalog.py           # Compiles _private/book-log.pdf from books.yaml
│   └── build_cutouts.py           # Compiles _private/to-print/covers-YYYY-MM-DD.pdf
├── tests/
│   └── test_scripts.py            # Unit tests (no personal data)
└── _private/                      # Personal data, never committed (created on first run)
    ├── books.yaml                 # Single sorted source-of-truth database
    ├── book-log.pdf               # Complete digital catalog (all books)
    ├── cover-art/                 # High-res cover images
    ├── log-photos/                # Date-stamped archive of processed photos
    └── to-print/                  # Dated printable cutout PDFs
```

**Pre-flight check:** The scripts create `_private/` and its subfolders on first run. Before writing, check whether `_private/books.yaml` already exists: if it does, treat it as the source of truth; if `_private/` is missing on a log that has been processed before (photos show books you would expect on disk), stop and ask the user where their data went instead of starting a fresh database.

---

# Workflow

## Phase 1: Extract, Verify, and Resolve (Conditional Gate)

1. **Inspect the attached photos:** Use the layout described in **Book Log Profile** and extract every handwritten entry (`Photo #`, `Row #`, `Raw Title`, `Raw Author`, `Cover Pasted?`).
   - An entry has sufficient info to identify a book if it has a title and author.
   - An entry is physically complete (`Cover Pasted? = Yes`) if a printed book cover is already glued into its cover box.
2. **Check disk first (via script):** Run `scripts/find_books.py` (if `books.yaml` exists and is non-empty) to check whether extracted entries already exist in `books.yaml`. Never read the entire `books.yaml` file into context directly. If a book already exists on disk, reuse its canonical record without querying external APIs.
3. **Verify new entries via read-only lookup:** For entries not yet on disk, run read-only lookups (Google Books API, Open Library API, or web search) to resolve the book and gather canonical metadata (`title`, `author`, `year_released`, `isbn`, `pages`, `description`, and high-res cover image URL).
   - **Confirmed match:** Raw title and author unambiguously resolve to a single published work—even with spelling errors, missing subtitles, or author initials. Adopt the canonical title and author going forward.
   - **Needs review:** No confident match exists, multiple plausible books fit the handwriting, title or author is missing/unreadable, or `Cover Pasted?` is unclear.
4. **Conditional Gate:**
   - **If ANY entry is `NEEDS REVIEW`:** Output a Markdown table of only the flagged rows (`Photo # | Row # | Raw Title | Raw Author | Cover Pasted? | Best Guess & Question`), then **STOP**. Do not archive photos, download images, modify `books.yaml`, or generate PDFs until the user resolves the flagged entries.
   - **If ALL entries are confirmed:** Proceed directly to Phase 2 without pausing. Include a compact `Raw → Canonical` list in your final summary for any spelling or title corrections applied.

## Phase 2: Execute via Persistent Scripts

Do not perform photo archival, filename sanitization, sorting, YAML edits, or PDF layout ad-hoc. Maintain reusable Python scripts inside `scripts/` (managed via `uv` or a local `.venv` with pinned dependencies in `pyproject.toml`).

- **First run (when `scripts/` does not exist):** Write `archive_photos.py`, `find_books.py`, `add_book.py`, `build_catalog.py`, and `build_cutouts.py`, plus unit tests covering filename sanitization, publisher-alphabetical sorting, atomic YAML persistence, photo deduplication/date-stamping, and cutout bounding-box/spacing math. Render sample pages of both generated PDFs to PNG via `pdftoppm` and visually inspect them to verify layout, alignment, and page breaks before finishing.
- **Subsequent runs:** Execute the existing scripts. Do not rewrite or alter them unless fixing a verified bug or implementing an explicit change requested by the user.
- Archive the processed batch photos via `scripts/archive_photos.py`, then add/update books via `scripts/add_book.py`, rebuild `book-log.pdf` via `scripts/build_catalog.py`, and generate any needed cutout sheet via `scripts/build_cutouts.py`.

## Phase 3: Deliver Preview & Print on Confirmation

- If a new `to-print/covers-YYYY-MM-DD.pdf` was generated, send it to the user via `SendUserFile` (when available over Remote Control) so they can visually inspect the covers on their phone.
- **Do not print automatically.** Ask the user if they want you to send the sheet to the printer named in **Book Log Profile**.
- Once the user replies to print (e.g., `"print it"`), run:
  ```bash
  lp -d "<PRINTER_QUEUE_NAME>" \
     -o media=Letter \
     -o print-scaling=none \
     -o sides=one-sided \
     _private/to-print/covers-YYYY-MM-DD.pdf
  ```

---

# Rules

## 1. Incremental State & Persistence (`books.yaml`)
- **Disk is the source of truth:** Attached photos are always a partial update, never the complete reading log.
- **Append-only (never delete):** Never remove a book from `books.yaml`, `cover-art/`, `log-photos/`, or `book-log.pdf` because it is absent from the current batch of photos.
- **Never read or edit `books.yaml` directly:** All lookups go through `scripts/find_books.py`; all writes go through `scripts/add_book.py` (and status flips through `scripts/build_cutouts.py`).
- **Atomic, sorted writes:** Every write to `books.yaml` must sort the list by publisher-alphabetical title (case-insensitive, ignoring leading `A `, `An `, `The `, with `author` as tiebreaker), serialize to `books.yaml.tmp`, verify the temp file parses back cleanly, and swap it into place with `os.replace()`.
- **Deduplicate before creating:** Match by ISBN or canonical title + author. If a book already exists on disk, do not create a duplicate entry, overwrite its metadata, or re-download its cover image.
- **Three-state `cover_status` tracking:**
  - `needed` — Book has no pasted cover and has not yet been placed on a cutout PDF.
  - `printed` — Cover has been included in a `to-print/` PDF.
  - `pasted` — Log photo shows the printed cover glued into the book.
- **Monotonic transitions only:**
  - New entry with pasted cover → `pasted`
  - New entry without pasted cover → `needed`
  - Existing entry reappearing in a new photo with a pasted cover → upgrade to `pasted` (never automatically downgrade `printed` or `pasted`).
  - After `build_cutouts.py` generates a cutout PDF, flip only the included books from `needed` → `printed`.

## 2. `books.yaml` Schema
Maintain a single top-level YAML list. Store the clean 2–4 sentence official short description (~40–80 words, HTML tags and marketing blurbs stripped) using a folded block scalar (`>`):

```yaml
- id: weir_andy-project_hail_mary
  title: Project Hail Mary
  author: Andy Weir
  year_released: 2021
  isbn: "9780593135204"
  pages: 496
  cover_image: cover-art/weir_andy-project_hail_mary.jpg
  cover_status: needed
  description: >
    Ryland Grace is the sole survivor on a desperate, last-chance mission—and if
    he fails, humanity and the earth itself will perish. Except that right now,
    he doesn't know that. He can't even remember his own name, let alone the
    nature of his assignment or how to complete it.
```

## 3. Cover Art Rules (`cover-art/`)
- Download the official, authorized color cover image from the publisher/author. Prefer the original US hardcover or primary edition; avoid movie/TV tie-in covers unless no other edition exists.
- Target high resolution (`>= 1500px` tall preferred; minimum `500px` tall so a print at the cover-box height stays sharp at 300 DPI). Never upscale low-res thumbnails to fake resolution.
- **Filename & `id` format:**
  `<author_last>_<author_first>-<book_title>.<ext>` (with `id` omitting `.<ext>`)
  - Use the first author only if there are multiple authors.
  - Convert to lowercase ASCII alphanumeric (`a-z`, `0-9`); replace any run of non-alphanumeric characters with a single underscore (`_`), and strip leading/trailing underscores from each segment (keep digits intact so titles like `1984` or `Catch-22` stay legible).
- Never re-download a cover if the target file already exists on disk.

## 4. Log Photo Archival (`log-photos/`)
- Copy every processed input photo from the current batch (e.g., from `~/.claude/uploads/` or any passed local file path) into `log-photos/` using `scripts/archive_photos.py`.
- **Filename format:** `YYYY-MM-DD_01.<ext>`, `YYYY-MM-DD_02.<ext>`, etc., using the local run date and preserving the original lowercase extension.
- **No overwrites or exact duplicates:** If files with today's date already exist in `log-photos/`, continue numbering after the highest existing index. Before copying, compare SHA-256 hashes against existing files in `log-photos/` and skip any exact duplicate.

## 5. Digital Catalog PDF Specification (`book-log.pdf`)
Rebuild `book-log.pdf` from **ALL** entries in `books.yaml` whenever a run adds or updates a book.

- **Sorting:** Follow the publisher-alphabetical order in `books.yaml` (case-insensitive, ignoring leading `A `, `An `, `The `).
- **Rendering engine:** HTML + CSS via **WeasyPrint** (or **Typst**). Do not use raw ReportLab or LaTeX for the catalog layout.
- **Page setup:** US Letter (`8.5in × 11in`), portrait, `0.75in` margins on all sides. Clean sans-serif stack (Inter, Helvetica Neue, or system sans-serif), `10pt` body, `1.45` line-height, `#1a1a1a` text. Centered page numbers in the bottom margin (`8.5pt`, `#666666`).
- **Entry layout (two-column card):**
  - Strict page-break protection (`break-inside: avoid;` or `block(breakable: false)`) so an entry never splits across pages.
  - Flexbox/grid row, `0.25in` column gap, `0.25in` vertical padding, `1px solid #e0e0e0` bottom border (omitted on final entry).
  - **Left column (cover):** Fixed `1.3in` width (`flex-shrink: 0`), auto height preserving aspect ratio (`max-height: 2.1in`), `3px` border-radius, `1px solid #d0d0d0` border. Fallback if missing: `1.3in × 1.95in` `#f0f0f0` box with centered title.
  - **Right column (stacked top to bottom):**
    1. **Title:** `15pt`, bold (`700`), `#000000`, `2pt` bottom margin.
    2. **Author:** `11pt`, medium (`500`), `#4a4a4a`, `8pt` bottom margin.
    3. **Short description:** `10pt`, regular (`400`), `#222222`, `10pt` bottom margin.
    4. **Metadata footer:** Single line, `8.5pt`, `#666666`, middot-separated:
       `{Pages} pages · ISBN {ISBN-13} · Published {Year}`
       *(Omit missing fields cleanly; never print "N/A" or trailing middots.)*

## 6. Printable Cover Cutout PDF Specification (`to-print/covers-YYYY-MM-DD.pdf`)
Generate a cutout PDF **only** if one or more books currently have `cover_status: needed`. Never overwrite an existing same-day file—append `-2`, `-3`, etc. if multiple runs occur on the same date.

- **Exact physical sizing (1:1 scale):** Use the profile's paper size with exact physical coordinates (`1 cm = 28.3465 pt`) and at least the profile's printer-safe margin on all four sides.
- **Per-cover dimensions:** Fit every cover strictly within the profile's cover box (`W × H`) without distorting aspect ratio: height must equal `H` and/or width must equal `W`.
- **Cut-minimizing column packing:**
  - Group **width-constrained** covers (`width == W`, `height <= H`) upright in shared `W`-wide columns so both left and right edges align vertically for straight paper-cutter cuts.
  - Rotate **height-constrained** covers (`height == H`, `width < W`) by `90 degrees` so their `H` edge runs horizontally, and group them in shared `H`-wide columns so their left and right edges also align vertically.
  - Maintain at least `1.0 cm` spacing between adjacent covers (both horizontally and vertically).
- **Cut aids & calibration:**
  - Draw a faint `0.5pt solid #cccccc` border tightly around each cover so white/light-colored covers have visible cut edges.
  - Draw a thin, labeled `5.0 cm` calibration bar in the bottom margin of each page so print scale can be verified with a ruler.

---

# Done

A run is complete only when all of the following hold:
- Every processed input photo from the current batch has been archived into `log-photos/` with a `YYYY-MM-DD_NN.<ext>` filename (or skipped cleanly if an identical hash already exists).
- Every confirmed book from the attached photos (plus all previously stored books) has its high-resolution cover image in `cover-art/` and a valid entry in the sorted `books.yaml` containing `id`, `title`, `author`, `year_released`, `isbn`, `pages`, `cover_image`, `cover_status`, and `description`.
- `book-log.pdf` is rebuilt from all entries in `books.yaml`, sorted alphabetically by title, with zero split cards or broken images.
- If any books had `cover_status: needed`, a dated cutout PDF exists in `to-print/` with exact cover-box (`W × H`) scaling, at least `1.0 cm` spacing, aligned columns, and a `5.0 cm` calibration bar—those entries have been updated to `cover_status: printed`, and the PDF has been sent to the user via `SendUserFile` (when available).
- On the first run (or after script edits), unit tests pass and rendered PNG previews of both PDFs have been visually verified.
- Your final message includes:
  1. Count of photos archived, and count of books added, already known, and status-upgraded.
  2. Any `Raw → Canonical` spelling/title corrections applied automatically.
  3. Confirmation of the cutout PDF sent (or its local path), a prompt asking whether to print it from the Mac via `lp` at 1:1 scale (or print manually in macOS Preview at **Scale: 100%**), and a reminder to check the `5.0 cm` calibration bar with a ruler on the first print.
  