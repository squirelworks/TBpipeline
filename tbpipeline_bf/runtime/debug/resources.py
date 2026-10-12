"""Resources the book holds that the reader cannot place.

A Windows BMP in the file starts with BM, a sane size, and a sane
offbits. Each one is copied out. If it sits inside a page, it is named
for that page. The rest are book-level.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..tbk import Book


def bitmaps(data: bytes):
    hits = []
    start = 0
    while True:
        i = data.find(b"BM", start)
        if i < 0:
            break
        start = i + 1
        if i + 14 > len(data):
            continue
        size = int.from_bytes(data[i + 2:i + 6], "little")
        off = int.from_bytes(data[i + 10:i + 14], "little")
        if not (14 < off < size < 2_000_000 and i + size <= len(data)):
            continue
        hits.append((i, size))
    return hits


def write(book: Book, data: bytes, out: Path) -> dict:
    folder = out / "resources"
    folder.mkdir(exist_ok=True)
    pages = sorted(book.pages, key=lambda p: p.offset)
    manifest = {"book": [], "pages": {}}
    for n, (at, size) in enumerate(bitmaps(data), 1):
        owner = None
        for page in pages:
            if page.offset <= at < page.offset + len(page.blob):
                owner = page.name
                break
        name = f"{owner or 'book'}_{n:03d}.bmp"
        (folder / name).write_bytes(data[at:at + size])
        rel = f"resources/{name}"
        if owner:
            manifest["pages"].setdefault(owner, []).append(rel)
        else:
            manifest["book"].append(rel)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
