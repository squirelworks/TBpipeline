"""runtime/tbk.py loads the original fixture book. No --b."""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime import tbk
from tbpipeline_bf.runtime.openbook import open_book
from tests.fixtures import book


class FixtureBook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = book.write(Path(self.tmp.name) / "fixture.tbk")
        self.data = self.path.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def test_shell(self):
        self.assertIn(b"ZZZTBKBOOKLOC", self.data[:tbk.STUB])
        self.assertEqual(struct.unpack_from("<I", self.data, 0xC00)[0], 0x22222222)
        self.assertLess(len(self.data) - tbk.STUB, 512, "the book past the stub is a few hundred bytes")

    def test_tbk_loads_one_page(self):
        loaded = tbk.load(self.path)
        self.assertEqual(loaded.book_offset, 0xC00)
        self.assertEqual([p.name for p in loaded.pages], ["P1"])
        self.assertEqual([f.text for f in loaded.pages[0].fields], ["Fixture page one."])

    def test_one_quoted_page_id(self):
        opened = open_book(self.path)
        handlers = opened.page_handlers("P1")
        self.assertEqual([h.name for h in handlers], ["buttonClick"])
        self.assertEqual(handlers[0].goto, "P1")

    def test_build_is_stable(self):
        self.assertEqual(book.build(), self.data)


if __name__ == "__main__":
    unittest.main()
