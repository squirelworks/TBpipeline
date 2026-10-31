"""A Windows BMP inside a page is drawn on that page, not only copied out.

The book is built here: one page holding a 1-by-1 BMP. No binary, no CPU.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

UNKNOWN = "Picture position unknown: Windows bitmaps from this page are drawn in book order, not placed."


def one_pixel_bmp() -> bytes:
    pixels = b"\x00\x00\xff\x00"
    info = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    size = 14 + len(info) + len(pixels)
    return b"BM" + struct.pack("<IHHI", size, 0, 0, 14 + len(info)) + info + pixels


def book_with_bmp() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    page = MARK + b"\x00" * 4 + b"P1\x00" + one_pixel_bmp()
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + page


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class BmpOnPage(unittest.TestCase):
    def test_bmp_is_drawn_on_its_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = tmp / "bmp.tbk"
            book.write_bytes(book_with_bmp())
            out = tmp / "db"
            run(str(book), out, dbgrender=True)
            html = (out / "render.html").read_text()

            page = payload(html)["pages"][0]
            self.assertEqual(page["pictures"], ["resources/P1_001.bmp"])
            self.assertEqual((out / "resources" / "P1_001.bmp").read_bytes(), one_pixel_bmp())
            self.assertIn('img.className = "picture"', html)
            self.assertIn(UNKNOWN, html)


if __name__ == "__main__":
    unittest.main()
