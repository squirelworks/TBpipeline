"""--theme default and --theme modern each write a page with --dbgrender.

Checks a marker string in each page, not a screenshot. The book is
built here. No binary, no CPU.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB


def one_page_book() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + MARK + b"\x00" * 4 + b"P1\x00"


class Themes(unittest.TestCase):
    def render(self, theme: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "one.tbk"
            book.write_bytes(one_page_book())
            out = Path(tmp) / "db"
            lines, _ = run(str(book), out, dbgrender=True, theme=theme)
            self.assertIn(f"  theme {theme}", lines)
            return (out / "render.html").read_text()

    def test_each_theme_writes_its_marker(self):
        for theme in ("default", "modern"):
            with self.subTest(theme=theme):
                page = self.render(theme)
                self.assertIn(f'<body data-theme="{theme}">', page)
                self.assertNotIn('data-theme="default"' if theme == "modern" else 'data-theme="modern"', page)

    def test_unknown_theme_is_marked_default(self):
        self.assertIn('<body data-theme="default">', self.render("nope"))


if __name__ == "__main__":
    unittest.main()
