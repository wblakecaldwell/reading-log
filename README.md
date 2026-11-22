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
git clone https://github.com/wblakecaldwell/reading-log.git
cd reading-log
uv sync                         # creates .venv with pinned dependencies
uv run pytest                   # optional: run the unit tests
```

Then open Claude Code in the folder, attach your log photos, and say something like "process these."

## Suggested workflow: snap pages from your phone

The reading log sits next to your reading chair, not your desk. With Claude Code's [Remote Control](https://code.claude.com/docs/en/remote-control) mode you can run everything from your phone while the scripts, your data and your printer stay on your Mac.

1. **On your Mac (once per sitting):** in this folder, run `claude remote-control` (or `claude --remote-control` for an interactive session, or type `/remote-control` in one that's already running). Leave the Mac awake and the `claude` process running. Remote Control needs a claude.ai sign-in on a Pro, Max, Team or Enterprise plan; API keys don't work.
2. **On your phone:** scan the QR code the terminal shows (press space if it isn't visible), or open the Claude app, tap **Code**, and pick the session. Then take photos of the log pages you've filled in since last time. Shoot them flat, in good light, with the whole page in frame. Overlapping pages you've already sent are fine.
3. **Send them** with a short message such as "process these." Claude reads the handwriting, looks up the books, and asks you about anything it can't read or isn't sure of. Answer from your phone.
4. **Check the cutout sheet.** If any covers still need printing, Claude sends the new `covers-YYYY-MM-DD.pdf` to your phone so you can look it over.
5. **Reply "print it"** and your Mac sends the sheet to your printer at 100% scale. Cut the covers out, glue them into the log, and the next photos you send will mark them as pasted.

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
