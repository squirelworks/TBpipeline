"""An original fixture book, built in code.

Nothing here is copied from a lesson. It is the smallest file that has
the shape documentation/book.md describes: a 0xC00-byte stub that names
ZZZTBKBOOKLOC, magic 0x22222222 at 0xC00, and one page record whose
handler names a page in quotes.

  python3 -m tests.fixtures.book out.tbk
"""

import struct
import sys
from pathlib import Path

LOCATOR = b"ZZZTBKBOOKLOC"
MAGIC = 0x22222222
STUB = 0xC00
PAGE_MARK = bytes.fromhex("80650005000202")

PAGE = "P1"
TEXT = "Fixture page one."
SCRIPT = 'to handle buttonClick\r\n  go to page "P1"\r\nend\r\n'


def _stub() -> bytes:
    head = b"MZ" + bytes(0x3E) + LOCATOR + b"\x00" + struct.pack("<I", STUB)
    return head + bytes(STUB - len(head))


def _text(text: str) -> bytes:
    raw = ("\r\n" + text).encode("latin-1")
    return b"Text\x00\x00" + bytes(8) + struct.pack("<H", len(raw)) + raw


def _page(name: str, text: str, script: str) -> bytes:
    head = PAGE_MARK + bytes(4) + name.encode("ascii") + b"\x00"
    return head + bytes(4) + _text(text) + bytes(4) + script.encode("latin-1") + bytes(4)


def build() -> bytes:
    return _stub() + struct.pack("<I", MAGIC) + bytes(12) + _page(PAGE, TEXT, SCRIPT)


def write(path) -> Path:
    path = Path(path)
    path.write_bytes(build())
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 -m tests.fixtures.book out.tbk", file=sys.stderr)
        sys.exit(2)
    print(write(sys.argv[1]))
