"""Shapes we can draw but cannot place yet.

A polygon on disk is a 14 00 00 record with +0x0c = 04 00. Fill color
is the dword at +4. Point count is the word at +0x1a. x,y twip pairs
start at +0x22. Screen is twips / 15. One PNG per page that has any.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from ..tbk import Book

SIG = bytes.fromhex("140000")


def word(rec, off):
    return int.from_bytes(rec[off:off + 2], "little")


def polygons(blob: bytes):
    hits = []
    start = 0
    while True:
        i = blob.find(SIG, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    shapes = []
    for n, at in enumerate(hits):
        if blob[at + 3] != 0:
            continue
        end = hits[n + 1] if n + 1 < len(hits) else len(blob)
        rec = blob[at:end]
        if len(rec) < 0x24 or rec[0x0C:0x0E] != b"\x04\x00":
            continue
        count = word(rec, 0x1A)
        if not 3 <= count <= 400 or 0x22 + 4 * count > len(rec):
            continue
        points = []
        ok = True
        for i in range(count):
            x = word(rec, 0x22 + 4 * i)
            y = word(rec, 0x24 + 4 * i)
            if not (0 <= x <= 60000 and 0 <= y <= 60000):
                ok = False
                break
            points.append((x / 15.0, y / 15.0))
        if not ok:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
            continue
        shapes.append((points, tuple(rec[5:8])))
    return shapes


def draw(shapes, dest: Path):
    xs = [p[0] for pts, _ in shapes for p in pts]
    ys = [p[1] for pts, _ in shapes for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    scale, pad = 2, 16
    width = int((maxx - minx) * scale) + pad * 2
    height = int((maxy - miny) * scale) + pad * 2
    image = Image.new("RGB", (max(width, 1), max(height, 1)), (255, 255, 255))
    pen = ImageDraw.Draw(image)
    for points, color in shapes:
        xy = [(pad + (p[0] - minx) * scale, pad + (p[1] - miny) * scale) for p in points]
        pen.polygon(xy, outline=color, fill=color)
    image.save(dest)


def write(book: Book, out: Path) -> dict:
    folder = out / "render"
    folder.mkdir(exist_ok=True)
    manifest = {}
    for page in book.pages:
        shapes = polygons(page.blob)
        if not shapes:
            continue
        name = f"{page.name}.png"
        draw(shapes, folder / name)
        manifest[page.name] = [f"render/{name}"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
