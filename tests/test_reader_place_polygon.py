"""A kind-04 polygon is on the page in render.html, at its record's twips / 15.

The book is built here: one page, one polygon record. No binary, no CPU.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

TWIPS = [(1500, 1500), (3000, 1500), (3000, 3000)]


def polygon_record(points, rgb) -> bytes:
    rec = bytearray(0x22)
    rec[0:3] = b"\x14\x00\x00"
    rec[5:8] = bytes(rgb)
    rec[0x0C:0x0E] = b"\x04\x00"
    xs, ys = [x for x, _ in points], [y for _, y in points]
    rec[0x12:0x1A] = struct.pack("<4H", min(xs), min(ys), max(xs), max(ys))
    rec[0x1A:0x1C] = struct.pack("<H", len(points))
    for x, y in points:
        rec += struct.pack("<HH", x, y)
    return bytes(rec)


def book_with_polygon() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    page = MARK + b"\x00" * 4 + b"P1\x00" + polygon_record(TWIPS, (0x20, 0x40, 0x80))
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + page


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class PlacePolygon(unittest.TestCase):
    def test_polygon_is_on_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = tmp / "poly.tbk"
            book.write_bytes(book_with_polygon())
            out = tmp / "db"
            lines, _ = run(str(book), out, dbgrender=True)
            html = (out / "render.html").read_text()

            page = payload(html)["pages"][0]
            self.assertEqual(page["id"], "P1")
            self.assertEqual(page["shapes"], [{
                "points": [[x / 15, y / 15] for x, y in TWIPS],
                "fill": "#204080",
                "bounds": [100, 100, 200, 200],
            }])
            self.assertIn('createElementNS(ns, "polygon")', html)
            self.assertIn("  placed 1 polygons on 1 pages, at record twips / 15", lines)


if __name__ == "__main__":
    unittest.main()
