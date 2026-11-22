# reading-log

Turn photos of a handwritten reading journal into a tidy digital catalog, plus print-ready book covers cut to fit the journal's cover boxes.

You keep a physical reading log. You snap photos of its pages. [Claude Code](https://claude.com/claude-code) reads the handwriting, looks up each book, and this repo's scripts do the rest:

- **`books.yaml`**: one sorted database of every book (title, author, year, ISBN, pages, short description, cover status)
- **`cover-art/`**: a high-resolution cover image for each book
- **`book-log.pdf`**: an alphabetical catalog of everything you've read, one card per book
- **`to-print/covers-YYYY-MM-DD.pdf`**: a 1:1-scale sheet of the covers you still need to paste in, packed into straight columns so a paper cutter can trim them in a few cuts, with a 5 cm calibration bar
- **`log-photos/`**: a dated, de-duplicated archive of the page photos you processed

All of that is personal data, so it lives in `_private/`, which is gitignored. The repository itself is only code.

## How it works

`CLAUDE.md` is the playbook. When you open Claude Code in this folder and hand it new log photos, it:

1. Reads every handwritten entry and checks it against books already in `_private/books.yaml`.
2. Looks up new books (Open Library, Google Books, or the web) to get the official title, author, ISBN, page count, description and cover. If an entry is unreadable or ambiguous, it stops and asks you before changing anything.
3. Runs the scripts in `scripts/` to archive the photos, add the books, rebuild the catalog PDF, and generate a cutout sheet for covers that still need printing.
4. Asks before printing anything.

Each run is incremental: photos can overlap or skip pages, and nothing already on disk is deleted or duplicated.

## Setup (macOS)

```bash
brew install uv pango poppler   # uv for Python, pango for WeasyPrint, poppler for PDF previews
git clone https://github.com/<you>/reading-log.git
cd reading-log
uv sync                         # creates .venv with pinned dependencies
uv run pytest                   # optional: run the unit tests
```

Then open Claude Code in the folder, attach your log photos, and say something like "process these."

## Adapting it to your journal

Open `CLAUDE.md` and edit the **Book Log Profile** table near the top:

| Setting | What to put there |
|---|---|
| Physical log | The journal you use |
| Page layout | How entries are arranged and which fields each one has |
| Cover box (`W × H`) | The size of the cover box on each page, in cm |
| Paper | Your printer paper (US Letter by default) |
| Printer-safe margin | How close to the edge your printer can print |
| Printer queue | Your printer's name (`lpstat -p` lists them) |

The cover box, paper size and margin are also constants at the top of `scripts/build_cutouts.py` (`BOX_W`, `BOX_H`, `PAGE_W`, `PAGE_H`, `MARGIN`). Keep the two in sync.

## Printing tips

Print the cutout sheet at **100% scale** (no "fit to page"), then measure the 5 cm calibration bar with a ruler on the first print. The `lp` command in `CLAUDE.md` already disables scaling.

## Scripts

| Script | What it does |
|---|---|
| `scripts/archive_photos.py` | Copies page photos into `_private/log-photos/` as `YYYY-MM-DD_NN.ext`, skipping exact duplicates |
| `scripts/find_books.py` | Fuzzy-searches `books.yaml` by title and author |
| `scripts/add_book.py` | The only writer to `books.yaml` and `cover-art/`: de-duplicates, downloads covers, sorts, and writes atomically |
| `scripts/build_catalog.py` | Builds `book-log.pdf` with WeasyPrint |
| `scripts/build_cutouts.py` | Builds the 1:1 cover cutout sheet with ReportLab and marks those covers as printed |

## License

[MIT](LICENSE)
