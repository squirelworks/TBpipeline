"""Compressed pictures stay unplaced, and every page says so.

The book is built here: one page, no pictures. No binary, no CPU.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

SENTENCE = (
    "Compressed ToolBook pictures are not drawn: the decoder is TB80BMP ordinal 3, "
    "and the host probe stops at its first import, KERNEL.36. Only Windows bitmaps are shown."
)


def one_page_book() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    page = MARK + b"\x00" * 4 + b"P1\x00"
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + page


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class CompressedPictures(unittest.TestCase):
    def test_page_says_compressed_pictures_are_not_drawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = tmp / "one.tbk"
            book.write_bytes(one_page_book())
            out = tmp / "db"
            run(str(book), out, dbgrender=True)
            html = (out / "render.html").read_text()

            self.assertEqual(payload(html)["compressed"], SENTENCE)
            self.assertIn('<p id="status"', html)
            self.assertIn('getElementById("status").textContent = book.compressed', html)


if __name__ == "__main__":
    unittest.main()
