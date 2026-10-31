"""Shapes we can draw but cannot place yet.

A polygon on disk is a 14 00 00 record with +0x0c = 04 00. Fill color
is the dword at +4. Bounds are four words at +0x12: left, top, right,
bottom, in twips. Point count is the word at +0x1a. x,y twip pairs
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


def bounds(rec: bytes) -> tuple[int, int, int, int]:
    """left, top, right, bottom in twips, as a kind-04 record names them."""
    return tuple(word(rec, off) for off in (0x12, 0x14, 0x16, 0x18))


def polygons(blob: bytes):
    return [(points, color) for _rec, points, color in polygon_records(blob)]


def polygon_records(blob: bytes):
    """(record, screen points, fill) for each kind-04 polygon in a page."""
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
        shapes.append((rec, points, tuple(rec[5:8])))
    return shapes


def curves(blob: bytes):
    """Long runs of twip pairs that are not kind-04 polygons.

    P420's flame is one: 53 pairs at record +0x38, screen span about
    150. A run is kept when it is long and tight on screen.
    """
    found = []
    start = 0
    while start + 8 < len(blob):
        run = []
        at = start
        while at + 4 <= len(blob):
            x = word(blob, at)
            y = word(blob, at + 2)
            if not (3000 <= x <= 12000 and 3000 <= y <= 12000):
                break
            run.append((x / 15.0, y / 15.0))
            at += 4
        if len(run) >= 20:
            xs = [p[0] for p in run]
            ys = [p[1] for p in run]
            if max(xs) - min(xs) < 250 and max(ys) - min(ys) < 250:
                found.append(run)
            start = at + 4
        else:
            start += 1
    return found


def draw(shapes, lines, dest: Path):
    xs = [p[0] for pts, _ in shapes for p in pts] + [p[0] for run in lines for p in run]
    ys = [p[1] for pts, _ in shapes for p in pts] + [p[1] for run in lines for p in run]
    if not xs:
        return
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
    for run in lines:
        xy = [(pad + (p[0] - minx) * scale, pad + (p[1] - miny) * scale) for p in run]
        pen.line(xy, fill=(220, 90, 0), width=2)
    image.save(dest)


def write(book: Book, out: Path) -> dict:
    folder = out / "render"
    folder.mkdir(exist_ok=True)
    manifest = {}
    for page in book.pages:
        files = []
        shapes = polygons(page.blob)
        if shapes:
            name = f"{page.name}.png"
            draw(shapes, [], folder / name)
            files.append(f"render/{name}")
        for n, run in enumerate(curves(page.blob), 1):
            name = f"{page.name}_curve_{n}.png"
            draw([], [run], folder / name)
            files.append(f"render/{name}")
        if files:
            manifest[page.name] = files
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
