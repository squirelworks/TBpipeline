"""next and back follow the page's handler when it has one, and the page list when not.

The book is built here: P1 has an original "to handle next", P3 an
original "to handle previous", P2 has neither. No binary, no CPU.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.engine import Engine
from tbpipeline_bf.runtime.openbook import open_book
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB


def page(name: str, script: str = "") -> bytes:
    return MARK + b"\x00" * 4 + name.encode("ascii") + b"\x00" + script.encode("ascii") + b"\x00"


def handler(verb: str, dest: str) -> str:
    return f'to handle {verb}\r\n  go to page "{dest}"\r\nend\r\n'


def book() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    head = bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12
    return head + page("P1", handler("next", "P3")) + page("P2") + page("P3", handler("previous", "P1"))


def payload(html: str) -> dict:
    line = next(l for l in html.splitlines() if l.startswith("const book = "))
    return json.loads(line[len("const book = "):].rstrip(";"))


class NextBack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "moves.tbk"
        self.path.write_bytes(book())
        opened = open_book(self.path)
        self.engine = Engine(opened.book)
        self.engine.load_scripts(opened.handlers)

    def tearDown(self):
        self.tmp.cleanup()

    def test_handler_wins(self):
        self.assertEqual(self.engine.go("P1").name, "P1")
        self.assertEqual(self.engine.next().name, "P3")
        self.assertEqual(self.engine.back().name, "P1")

    def test_page_list_without_handler(self):
        self.engine.go("P2")
        self.assertEqual(self.engine.next().name, "P3")
        self.engine.go("P2")
        self.assertEqual(self.engine.back().name, "P1")

    def test_reader_carries_the_handler(self):
        out = Path(self.tmp.name) / "db"
        run(str(self.path), out, dbgrender=True)
        pages = {p["id"]: p for p in payload((out / "render.html").read_text())["pages"]}
        self.assertEqual(pages["P1"]["moves"], {"next": [{"op": "goto", "page": "P3"}]})
        self.assertEqual(pages["P2"]["moves"], {})
        self.assertEqual(pages["P3"]["moves"], {"back": [{"op": "goto", "page": "P1"}]})


if __name__ == "__main__":
    unittest.main()
