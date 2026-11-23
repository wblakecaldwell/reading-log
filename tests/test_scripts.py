import hashlib
from pathlib import Path

import pytest
import yaml

import add_book
import archive_photos
import build_catalog
import build_cutouts as bc


# ------------------------------------------------------------- filenames ---
@pytest.mark.parametrize("title,author,expected", [
    ("A Tale of Two Cities", "Charles Dickens", "dickens_charles-a_tale_of_two_cities"),
    ("The Time Machine", "H. G. Wells", "wells_h_g-the_time_machine"),
    ("Alice's Adventures in Wonderland", "Lewis Carroll", "carroll_lewis-alice_s_adventures_in_wonderland"),
    ("Pride & Prejudice", "Jane Austen", "austen_jane-pride_prejudice"),
    ("Catch-22", "Joseph Heller", "heller_joseph-catch_22"),
    ("1984", "George Orwell", "orwell_george-1984"),
    ("Le Père Goriot", "Honoré de Balzac", "balzac_honore_de-le_pere_goriot"),
    ("The Communist Manifesto", "Karl Marx & Friedrich Engels", "marx_karl-the_communist_manifesto"),
    ("Frankenstein: or, The Modern Prometheus", "Mary Shelley", "shelley_mary-frankenstein_or_the_modern_prometheus"),
])
def test_make_id(title, author, expected):
    assert add_book.make_id(title, author) == expected


def test_slug_strips_edges_and_collapses_runs():
    assert add_book.slug("  --Hello,   World!!  ") == "hello_world"


# --------------------------------------------------------------- sorting ---
def test_publisher_sort_ignores_articles_and_case():
    books = [{"title": t, "author": a} for t, a in [
        ("The Time Machine", "H. G. Wells"), ("a Christmas Carol", "Charles Dickens"),
        ("An Apple", "X"), ("Beowulf", "Anonymous"), ("Emma", "Jane Austen"),
        ("Dracula", "Bram Stoker"), ("Bound", "B Author"), ("Bound", "A Author")]]
    titles = [(b["title"], b["author"]) for b in sorted(books, key=add_book.sort_key)]
    assert titles == [("An Apple", "X"), ("Beowulf", "Anonymous"), ("Bound", "A Author"),
                      ("Bound", "B Author"), ("a Christmas Carol", "Charles Dickens"),
                      ("Dracula", "Bram Stoker"), ("Emma", "Jane Austen"),
                      ("The Time Machine", "H. G. Wells")]


# ----------------------------------------------------------- persistence ---
def _rec(title, author, isbn=None, pasted=False):
    return dict(title=title, author=author, year_released=2020, isbn=isbn, pages=100,
                description="One. Two.", pasted=pasted)


def test_atomic_sorted_write_and_roundtrip(tmp_path):
    db = tmp_path / "books.yaml"
    add_book.add_books([_rec("Zeta", "A B", "9780000000001"), _rec("The Alpha", "C D")],
                       db, download=None)
    data = yaml.safe_load(db.read_text())
    assert [b["title"] for b in data] == ["The Alpha", "Zeta"]
    assert data[1]["isbn"] == "9780000000001" and isinstance(data[1]["isbn"], str)
    assert list(data[0]) == add_book.FIELDS
    assert not (tmp_path / "books.yaml.tmp").exists()
    assert "description: >" in db.read_text()


def test_dedup_and_monotonic_status(tmp_path):
    db = tmp_path / "books.yaml"
    add_book.add_books([_rec("Emma", "Jane Austen")], db, download=None)
    s = add_book.add_books([_rec("Emma", "Jane Austen")], db, download=None)
    assert s["known"] and not s["added"]
    s = add_book.add_books([_rec("emma", "Jane Austen", pasted=True)], db, download=None)
    assert s["upgraded"]
    data = yaml.safe_load(db.read_text())
    assert len(data) == 1 and data[0]["cover_status"] == "pasted"
    # a later sighting without a cover never downgrades
    add_book.add_books([_rec("Emma", "Jane Austen")], db, download=None)
    assert yaml.safe_load(db.read_text())[0]["cover_status"] == "pasted"


def test_upgrade_status_never_downgrades():
    assert add_book.upgrade_status("printed", "needed") == "printed"
    assert add_book.upgrade_status("printed", "pasted") == "pasted"
    assert add_book.upgrade_status("pasted", "needed") == "pasted"


def test_failed_verification_keeps_original(tmp_path, monkeypatch):
    db = tmp_path / "books.yaml"
    add_book.add_books([_rec("Keep", "Me Here")], db, download=None)
    before = db.read_text()
    monkeypatch.setattr(add_book.yaml, "safe_load", lambda *_: [])
    with pytest.raises(RuntimeError):
        add_book.save_books([{"id": "x", "title": "X", "author": "Y"}], db)
    assert db.read_text() == before


# ---------------------------------------------------------------- photos ---
def test_archive_dedup_and_numbering(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    a, b, c = src / "IMG_1.JPEG", src / "IMG_2.jpeg", src / "IMG_3.png"
    a.write_bytes(b"a"); b.write_bytes(b"b"); c.write_bytes(b"c")
    dest = tmp_path / "log-photos"
    r1 = archive_photos.archive([a, b], dest, "2026-11-22")
    assert r1["copied"] == ["2026-11-22_01.jpeg", "2026-11-22_02.jpeg"]
    r2 = archive_photos.archive([b, c, a], dest, "2026-11-22")
    assert r2["copied"] == ["2026-11-22_03.png"] and len(r2["skipped"]) == 2
    assert hashlib.sha256((dest / "2026-11-22_03.png").read_bytes()).hexdigest() == \
        hashlib.sha256(b"c").hexdigest()


# --------------------------------------------------------------- catalog ---
def test_meta_line_omits_missing():
    assert build_catalog.meta_line({"pages": 300, "isbn": None, "year_released": 2020}) == \
        "300 pages · Published 2020"
    assert build_catalog.meta_line({}) == ""


# --------------------------------------------------------------- cutouts ---
def test_fit_preserves_aspect_and_hits_one_edge():
    w, h, wc = bc.fit(1000, 1500)       # 2:3 cover is height-constrained (4.31 tall)
    assert abs(h - bc.BOX_H) < 1e-9 and w < bc.BOX_W and not wc
    assert abs(w / h - 1000 / 1500) < 1e-9
    w, h, wc = bc.fit(1000, 1000)       # square is width-constrained
    assert abs(w - bc.BOX_W) < 1e-9 and h <= bc.BOX_H and wc


def _overlap_gap(a, b):
    dx = max(b.x - (a.x + a.w), a.x - (b.x + b.w))
    dy = max(b.y - (a.y + a.h), a.y - (b.y + b.h))
    return max(dx, dy)


def test_layout_spacing_margins_and_columns():
    items = [(f"b{i}", "x.jpg", 1000, 1500 if i % 3 else 1000) for i in range(40)]
    placed = bc.layout(items)
    assert len(placed) == 40
    for p in placed:
        assert p.x >= bc.MARGIN - 1e-9 and p.x + p.w <= bc.PAGE_W - bc.MARGIN + 1e-9
        assert p.y >= bc.MARGIN + bc.BOTTOM_RESERVE - 1e-9
        assert p.y + p.h <= bc.PAGE_H - bc.MARGIN + 1e-9
        assert p.w <= max(bc.BOX_W, bc.BOX_H) + 1e-9
        assert (abs(p.w - bc.BOX_W) < 1e-9 and not p.rotated) or \
               (abs(p.w - bc.BOX_H) < 1e-9 and p.rotated)
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            if a.page == b.page:
                assert _overlap_gap(a, b) >= bc.GAP - 1e-9
    # every cover in a column shares the same left and right edge
    cols = {}
    for p in placed:
        cols.setdefault((p.page, round(p.x, 6)), set()).add(round(p.x + p.w, 6))
    assert all(len(rights) == 1 for rights in cols.values())


def test_next_path_never_overwrites(tmp_path):
    (tmp_path / "covers-2026-11-22.pdf").write_text("x")
    (tmp_path / "covers-2026-11-22-2.pdf").write_text("x")
    assert bc.next_path("2026-11-22", tmp_path).name == "covers-2026-11-22-3.pdf"


# --------------------------------------------------------- mockup check ---
def test_mockup_detection():
    from PIL import Image, ImageDraw
    flat = Image.new("RGB", (400, 600), (30, 60, 120))           # artwork to every edge
    pale = Image.new("RGB", (400, 600), (250, 250, 250))         # pale cover, dark art inside
    ImageDraw.Draw(pale).rectangle((0, 300, 400, 600), fill=(120, 20, 20))
    mock = Image.new("RGB", (472, 600), (255, 255, 255))         # angled book on white page
    ImageDraw.Draw(mock).polygon([(60, 40), (420, 20), (420, 580), (60, 560)], fill=(90, 20, 40))
    assert not add_book.looks_like_mockup(flat)
    assert not add_book.looks_like_mockup(pale)
    assert add_book.looks_like_mockup(mock)


def test_mockup_refused_unless_allowed(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw
    mock = Image.new("RGB", (472, 600), (255, 255, 255))
    ImageDraw.Draw(mock).polygon([(60, 40), (420, 20), (420, 580), (60, 560)], fill=(90, 20, 40))
    src = tmp_path / "mock.png"
    mock.save(src)
    monkeypatch.setattr(add_book, "COVER_DIR", tmp_path / "covers")
    rec = {"title": "T", "author": "A B", "cover_file": str(src)}
    with pytest.raises(ValueError, match="mockup"):
        add_book.fetch_cover(rec, "b_a-t")
    assert add_book.fetch_cover({**rec, "allow_mockup": True}, "b_a-t") == "cover-art/b_a-t.png"


# ----------------------------------------------------------- find_cover ---
def test_find_cover_helpers():
    import find_cover
    assert find_cover.isbn13_to_10("9780306406157") == "0306406152"
    assert find_cover.isbn13_to_10("9798000000000") is None          # 979 has no ISBN-10
    html = '"hiRes":"https://m.media-amazon.com/images/I/AbCd123._SL1500_.jpg" data-old-hires="https://m.media-amazon.com/images/I/AbCd123._SL1500_.jpg"'
    assert find_cover.amazon_hires(html) == ["https://m.media-amazon.com/images/I/AbCd123.jpg"]
    assert find_cover.apple_art_full("https://x/a/9781.jpg/100x100bb.jpg") == "https://x/a/9781.jpg/3000x3000bb.jpg"


# ---------------------------------------------------------- make_preview ---
def test_make_preview_skips_small_and_shrinks_large(tmp_path):
    import make_preview
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "big.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(100, 700, "hello")
    c.save()
    assert make_preview.preview(pdf, max_mb=10, outdir=tmp_path / "p") is None
    out = make_preview.preview(pdf, max_mb=pdf.stat().st_size / 2**20 / 2, outdir=tmp_path / "p")
    assert out == tmp_path / "p" / "big-preview.pdf" and out.exists()


# ----------------------------------------------------------- corrections ---
def _flat_cover(path, size=(400, 600)):
    from PIL import Image
    Image.new("RGB", size, (30, 60, 120)).save(path)
    return path


def test_replace_cover_and_remove_book(tmp_path, monkeypatch):
    monkeypatch.setattr(add_book, "COVER_DIR", tmp_path / "covers")
    db = tmp_path / "books.yaml"
    add_book.add_books([_rec("Emma", "Jane Austen"), _rec("Dracula", "Bram Stoker")], db, download=None)
    new = _flat_cover(tmp_path / "new.png")
    assert add_book.replace_cover("austen_jane-emma", str(new), path=db) == "cover-art/austen_jane-emma.png"
    assert (tmp_path / "covers" / "austen_jane-emma.png").exists()
    with pytest.raises(ValueError):           # still enforces the minimum height
        add_book.replace_cover("austen_jane-emma", str(_flat_cover(tmp_path / "s.png", (100, 150))), path=db)
    add_book.remove_book("austen_jane-emma", path=db)
    ids = [b["id"] for b in yaml.safe_load(db.read_text())]
    assert ids == ["stoker_bram-dracula"]
    assert not list((tmp_path / "covers").glob("austen_jane-emma.*"))
    with pytest.raises(KeyError):
        add_book.remove_book("nope", path=db)


def test_cutouts_redo_flips_only_that_sheets_books(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(bc, "DATA", tmp_path)
    monkeypatch.setattr(bc, "BOOKS_YAML", tmp_path / "books.yaml")
    (tmp_path / "to-print").mkdir()
    books = [{"id": "a", "title": "A", "author": "X", "cover_status": "printed"},
             {"id": "b", "title": "B", "author": "X", "cover_status": "printed"},
             {"id": "c", "title": "C", "author": "X", "cover_status": "pasted"}]
    add_book.save_books(books, tmp_path / "books.yaml")
    sheet = tmp_path / "to-print" / "covers-2026-01-01.pdf"
    sheet.write_bytes(b"%PDF")
    sheet.with_suffix(".json").write_text(json.dumps(["a", "c"]))
    books, path = bc.undo_sheet(add_book.load_books(tmp_path / "books.yaml"), Path("covers-2026-01-01.pdf"))
    status = {b["id"]: b["cover_status"] for b in books}
    assert status == {"a": "needed", "b": "printed", "c": "pasted"}   # pasted never downgraded
    assert path == sheet and not sheet.exists() and not sheet.with_suffix(".json").exists()


# ----------------------------------------------------------- cover_sheet ---
def test_cover_sheet_grid(tmp_path):
    import cover_sheet
    files = [_flat_cover(tmp_path / f"b{i}.png") for i in range(3)]
    out = cover_sheet.sheet(files, tmp_path / "sheet.jpg")
    from PIL import Image
    with Image.open(out) as im:
        assert im.size == (cover_sheet.COLS * cover_sheet.TW, cover_sheet.TH + cover_sheet.LABEL)