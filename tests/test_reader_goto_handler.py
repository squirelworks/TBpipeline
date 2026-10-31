"""A compressed buttonClick with go to page "P2" lands on P2.

Handlers the expander cannot read are reported, not skipped.
The book is built here with keyword opcodes from res_77.bin. The
scripts are original. No binary, no CPU.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.openbook import keywords, open_book, report
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB


def word(text: str, space: bool = True) -> bytes:
    index = keywords().index(text)
    flag = 0x00 if space else 0x20
    if index < 16:
        return bytes((0x80 | flag | index,))
    return bytes((0x90 | flag | (index >> 8), index & 0xFF))


CRLF_2 = b"\xe2"
CRLF = b"\xe0"
# to handle buttonClick / go to page "P2" / end
GOTO_P2 = (word("to") + word("handle") + b"buttonClick" + CRLF_2
           + word("go") + word("to") + word("page") + b'"P2"' + CRLF + word("end", space=False) + b"\x00")
# to handle buttonClick / <a long copy from far before the file> / end
UNREAD = (word("to") + word("handle") + b"buttonClick" + CRLF_2
          + b"\xd0\xff\xff" + CRLF + word("end", space=False) + b"\x00")


def page(name: str, script: bytes) -> bytes:
    return MARK + b"\x00" * 4 + name.encode("ascii") + b"\x00" + script


def book() -> tuple[bytes, int]:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    head = bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12
    p1 = page("P1", GOTO_P2)
    p2 = page("P2", UNREAD)
    return head + p1 + p2, len(head) + len(p1) + p2.index(UNREAD)


class GotoHandler(unittest.TestCase):
    def test_compressed_goto_lands_and_unread_is_reported(self):
        data, unread_at = book()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "goto.tbk"
            path.write_bytes(data)
            opened = open_book(path)
            text = report(opened)

        self.assertIn('go to page "P2"', opened.handlers["P1"][0].source)
        lines = text.splitlines()
        self.assertEqual(lines[lines.index("click") + 1].split()[-1], "P2")
        at = lines.index("unread")
        self.assertEqual(lines[at + 1], f"  P2 buttonClick {unread_at:#x} 4 bytes copied from outside the book")
        self.assertEqual(lines[at + 2], "click")


if __name__ == "__main__":
    unittest.main()
