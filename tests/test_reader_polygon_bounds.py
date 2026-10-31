"""A kind-04 polygon is placed by the bounds its record names at +0x12.

left, top, right, bottom are four twip words. The fixture writes bounds
that differ from the points' own box, so the test sees which one the
reader used. No binary, no CPU.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.debug.shapes import bounds
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

POINTS = [(1500, 1500), (3000, 1500), (3000, 3000)]
BOUNDS = (1200, 1350, 3300, 3450)


def polygon_record() -> bytes:
    rec = bytearray(0x22)
    rec[0:3] = b"\x14\x00\x00"
    rec[5:8] = b"\x10\x20\x30"
    rec[0x0C:0x0E] = b"\x04\x00"
    rec[0x12:0x1A] = struct.pack("<4H", *BOUNDS)
    rec[0x1A:0x1C] = struct.pack("<H", len(POINTS))
    for x, y in POINTS:
        rec += struct.pack("<HH", x, y)
    return bytes(rec)


def book() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    page = MARK + b"\x00" * 4 + b"P1\x00" + polygon_record()
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + page


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class PolygonBounds(unittest.TestCase):
    def test_bounds_are_the_words_at_0x12(self):
        self.assertEqual(bounds(polygon_record()), BOUNDS)

    def test_reader_places_by_record_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bounds.tbk"
            path.write_bytes(book())
            out = Path(tmp) / "db"
            run(str(path), out, dbgrender=True)
            html = (out / "render.html").read_text()

        shape = payload(html)["pages"][0]["shapes"][0]
        self.assertEqual(shape["bounds"], [v / 15 for v in BOUNDS])
        self.assertIn("const [left, top, right, bottom] = shape.bounds;", html)
        self.assertIn('svg.style.left = left + "px";', html)


if __name__ == "__main__":
    unittest.main()
