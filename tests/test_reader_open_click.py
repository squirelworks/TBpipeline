"""--open reports the handler it followed and the page it landed on.

The book is built here: P1 and P2, each with an original buttonClick
that names the other page. No binary, no CPU.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.openbook import open_book, report
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB


def page(name: str, script: str) -> bytes:
    return MARK + b"\x00" * 4 + name.encode("ascii") + b"\x00" + script.encode("ascii") + b"\x00"


def handler(dest: str) -> str:
    return f'to handle buttonClick\r\n  go to page "{dest}"\r\nend\r\n'


def two_page_book() -> tuple[bytes, dict]:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    head = bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12
    p1 = page("P1", handler("P2"))
    p2 = page("P2", handler("P1"))
    offsets = {
        "P1": len(head) + p1.index(b"to handle"),
        "P2": len(head) + len(p1) + p2.index(b"to handle"),
    }
    return head + p1 + p2, offsets


class OpenClick(unittest.TestCase):
    def test_click_names_handler_and_landing(self):
        data, offsets = two_page_book()
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "two.tbk"
            book.write_bytes(data)
            text = report(open_book(book))

        lines = text.splitlines()
        at = lines.index("click")
        self.assertEqual(lines[at + 1:at + 3], [
            f"  P1 buttonClick {offsets['P1']:#x} -> P2",
            f"  P2 buttonClick {offsets['P2']:#x} -> P1",
        ])


if __name__ == "__main__":
    unittest.main()
