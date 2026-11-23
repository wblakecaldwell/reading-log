#!/usr/bin/env python3
"""Make small, view-only copies of PDFs for sending to a phone.

Usage:
    make_preview.py FILE.pdf [FILE.pdf ...] [--max-mb 18]

Full-resolution PDFs (the catalog, cutout sheets) can be far over the 20 MB
limit for sending files to a phone. Each input is rendered to JPEG pages with
pdftoppm and reassembled into _private/previews/<name>-preview.pdf, lowering
resolution until it fits under --max-mb. Previews are for looking only: always
print from the original file. A PDF already under the limit is reported as
"no preview needed" and nothing is written.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW_DIR = ROOT / "_private" / "previews"
DPIS = (110, 80, 60, 45)


def render(pdf: Path, dpi: int, out: Path) -> int:
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-jpeg", "-jpegopt", "quality=75",
                        str(pdf), f"{tmp}/p"], check=True)
        pages = sorted(Path(tmp).glob("p-*.jpg"), key=lambda p: int(p.stem.split("-")[-1]))
        ims = [Image.open(p).convert("RGB") for p in pages]
        ims[0].save(out, save_all=True, append_images=ims[1:], resolution=dpi)
    return out.stat().st_size


def preview(pdf: Path, max_mb: float = 18, outdir: Path = PREVIEW_DIR) -> Path | None:
    limit = max_mb * 1024 * 1024
    if pdf.stat().st_size <= limit:
        return None
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{pdf.stem}-preview.pdf"
    for dpi in DPIS:
        if render(pdf, dpi, out) <= limit:
            return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--max-mb", type=float, default=18)
    a = ap.parse_args()
    for pdf in a.pdfs:
        out = preview(pdf, a.max_mb)
        if out is None:
            print(f"{pdf}: {pdf.stat().st_size / 2**20:.1f} MB, no preview needed")
        else:
            print(f"{pdf}: preview {out.relative_to(ROOT)} ({out.stat().st_size / 2**20:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
