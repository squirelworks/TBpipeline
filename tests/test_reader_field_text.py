"""Field text is listed on the page, and the page says its position is unknown.

The book is built here: one page, one Text property. No binary, no CPU.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

SENTENCE = "Fixture field text."
UNKNOWN = "Text position unknown: the field record's coordinates are not decoded, so this text is listed, not placed."


def text_property(text: str) -> bytes:
    raw = b"\r\n" + text.encode("latin-1")
    return b"Text\x00\x00" + b"\x00" * 8 + struct.pack("<H", len(raw)) + raw + b"\x00"


def book_with_field() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    page = MARK + b"\x00" * 4 + b"P1\x00" + text_property(SENTENCE)
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + page


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class FieldText(unittest.TestCase):
    def test_text_is_listed_and_position_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = tmp / "field.tbk"
            book.write_bytes(book_with_field())
            out = tmp / "db"
            run(str(book), out, dbgrender=True)
            html = (out / "render.html").read_text()

            page = payload(html)["pages"][0]
            self.assertEqual(page["text"], [SENTENCE])
            self.assertIn("textAt", page)
            self.assertIsNone(page["textAt"])
            self.assertIn(UNKNOWN, html)


if __name__ == "__main__":
    unittest.main()
