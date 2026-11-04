"""A class 0x11 arc is on the page in render.html, at its record's twips / 15.

The layout is opentoolbook8 SETTLED.md "Arc": bounds at +0x0F from the id,
stroke at +0x17, two stored pairs at +0x25 and +0x29, center at +0x2D,
radii at +0x31 and +0x33. The stored pairs map onto the bounds ellipse.
The synthetic book holds P1140 object 80 of Logic Families. With
TBK_BOOK2 set, P430's arcs are read from the book itself.
"""

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.debug import play
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB, load

BOUNDS = (5010, 3675, 5550, 4230)


def arc_record(at: int, object_id: int, bounds, rgb) -> bytes:
    """End word, class 0x11, then 60 bytes from the id. at is its blob offset."""
    rec = bytearray(4 + 60)
    rec[0:4] = struct.pack("<HH", at + 64 + 0x10, 0x11)
    body = 4
    rec[body:body + 2] = struct.pack("<H", object_id)
    rec[body + 0x0F:body + 0x17] = struct.pack("<4h", *bounds)
    rec[body + 0x17:body + 0x1A] = bytes(rgb)
    rec[body + 0x25:body + 0x35] = struct.pack("<8h", 1866, 5065, 1815, 4620, 1815, 4845, 270, 225)
    return bytes(rec)


def book_with_arc() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    head = MARK + b"\x00" * 4 + b"P1\x00"
    page = head + arc_record(len(head), 80, BOUNDS, (0x20, 0x40, 0x80))
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + page


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class PlaceArc(unittest.TestCase):
    def test_arc_is_on_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = tmp / "arc.tbk"
            book.write_bytes(book_with_arc())
            out = tmp / "db"
            lines, _ = run(str(book), out, dbgrender=True)
            html = (out / "render.html").read_text()

            page = payload(html)["pages"][0]
            self.assertEqual(page["id"], "P1")
            # (5331, 4224) and (5280, 3675) are the TBKX export Vertices of
            # P1140 object 80, as SETTLED.md "Arc" names them.
            self.assertEqual(page["arcs"], [{
                "id": 80,
                "bounds": [v / 15 for v in BOUNDS],
                "start": [5331 / 15, 4224 / 15],
                "end": [5280 / 15, 3675 / 15],
                "stroke": "#204080",
                "large": False,
            }])
            self.assertIn('createElementNS(ns, "path")', html)
            self.assertIn("  placed 1 arcs on 1 pages, at record twips / 15", lines)


class PlaceP430Arcs(unittest.TestCase):
    def test_p430_arcs_sit_at_their_record_twips(self):
        path = os.environ.get("TBK_BOOK2")
        if not path:
            raise unittest.SkipTest("TBK_BOOK2 is not set")
        page = load(path).page("P430")
        arcs = play.placed_arcs(page.blob)
        self.assertEqual([a["id"] for a in arcs], [8, 86, 102, 118, 134, 150, 166, 183])
        # opentoolbook8's arc reader gives object 8 bounds (2040, 3189, 2347, 3477)
        # and page_vertices (2222, 3474), (2219, 3192): a 160 degree notch.
        first = arcs[0]
        self.assertEqual(first["bounds"], [v / 15 for v in (2040, 3189, 2347, 3477)])
        self.assertEqual(first["start"], [2222 / 15, 3474 / 15])
        self.assertEqual(first["end"], [2219 / 15, 3192 / 15])
        self.assertFalse(first["large"])
        self.assertEqual(arcs[-1]["bounds"], [v / 15 for v in (6165, 5769, 6472, 6057)])

    def test_every_arc_in_the_book_is_read(self):
        path = os.environ.get("TBK_BOOK2")
        if not path:
            raise unittest.SkipTest("TBK_BOOK2 is not set")
        # SETTLED.md "Arc": 62 arcs on 9e954d01.tbk.
        self.assertEqual(sum(len(play.placed_arcs(p.blob)) for p in load(path).pages), 62)


if __name__ == "__main__":
    unittest.main()
