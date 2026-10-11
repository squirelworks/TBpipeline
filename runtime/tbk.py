"""ToolBook II 8.1 course-book loader.

On disk a lesson is not a PE. It is a Click2learn shell: a 0xC00-byte
stub, then the book at ZZZTBKBOOKLOC (file 0xC00, magic 0x22222222).
Pages are the only 80 65 00 05 00 02 02 records. Widgets are nested
14 00 00 chunks inside the page. Field text is a Text\\0\\0 property.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MARK = bytes.fromhex("80650005000202")
BOOK_MAGIC = 0x22222222
STUB = 0xC00
PROP_HEAD = bytes.fromhex("14000001")


def cstr(buf: bytes, off: int, n: int) -> str:
    out = []
    for i in range(n):
        if off + i >= len(buf):
            break
        c = buf[off + i]
        if c == 0 or c < 32 or c > 126:
            break
        out.append(chr(c))
    return "".join(out)


@dataclass
class FieldText:
    offset: int
    text: str


@dataclass
class Page:
    name: str
    offset: int
    blob: bytes
    fields: list[FieldText] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    quoted_jumps: list[str] = field(default_factory=list)


@dataclass
class Book:
    path: Path
    pages: list[Page]
    book_offset: int

    def page(self, name: str) -> Page | None:
        for p in self.pages:
            if p.name == name:
                return p
        return None


def book_offset(data: bytes) -> int:
    if len(data) >= STUB + 4 and struct.unpack_from("<I", data, STUB)[0] == BOOK_MAGIC:
        return STUB
    i = data.find(struct.pack("<I", BOOK_MAGIC))
    return i if i >= 0 else 0


def field_texts(blob: bytes) -> list[FieldText]:
    out = []
    start = 0
    while True:
        i = blob.find(b"Text\x00\x00", start)
        if i < 0:
            break
        start = i + 6
        if i + 16 > len(blob):
            continue
        length = int.from_bytes(blob[i + 14:i + 16], "little")
        if length < 8 or i + 16 + length > len(blob):
            continue
        raw = blob[i + 16:i + 16 + length]
        if raw[0] not in (0x0D, 0x0A):
            continue
        text = raw.replace(b"\r", b"").decode("latin-1").strip()
        if text:
            out.append(FieldText(i, text))
    return out


def paragraphs(blob: bytes) -> list[str]:
    """Lesson sentences that are not in the Text\\0\\0 property shape.

    Most course pages store the visible line as a plain run, not as the
    field property the first reader required. Keep runs that look like
    prose. Drop handler headers and property names.
    """
    out = []
    cur: list[str] = []
    for c in blob:
        if c in (9, 10, 13) or 32 <= c < 127:
            cur.append(chr(c))
        else:
            s = "".join(cur).strip()
            cur = []
            if len(s) < 40 or " " not in s:
                continue
            if s.lower().startswith("to handle"):
                continue
            s = " ".join(s.split())
            if s not in out:
                out.append(s)
    return out
    jumps = []
    start = 0
    while True:
        i = blob.find(b'("P', start)
        if i < 0:
            i = blob.find(b"(P", start)
        if i < 0:
            break
        j = i + 1
        if blob[j:j + 1] == b'"':
            j += 1
        k = j
        while k < len(blob) and 32 < blob[k] < 127 and chr(blob[k]).isalnum():
            k += 1
        name = blob[j:k].decode("ascii", "ignore")
        if name.startswith("P") and name not in jumps:
            jumps.append(name)
        start = k + 1
    return jumps


def quoted_jumps(blob: bytes) -> list[str]:
    jumps = []
    start = 0
    while True:
        i = blob.find(b'("P', start)
        if i < 0:
            i = blob.find(b"(P", start)
        if i < 0:
            break
        j = i + 1
        if blob[j:j + 1] == b'"':
            j += 1
        k = j
        while k < len(blob) and 32 < blob[k] < 127 and chr(blob[k]).isalnum():
            k += 1
        name = blob[j:k].decode("ascii", "ignore")
        if name.startswith("P") and name not in jumps:
            jumps.append(name)
        start = k + 1
    return jumps


def load(path: str | Path) -> Book:
    path = Path(path)
    data = path.read_bytes()
    origin = book_offset(data)
    hits = []
    start = 0
    while True:
        i = data.find(MARK, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    pages = []
    for n, off in enumerate(hits):
        nxt = hits[n + 1] if n + 1 < len(hits) else len(data)
        name = cstr(data, off + 11, 32)
        if not name.startswith("P"):
            continue
        blob = data[off:nxt]
        pages.append(Page(
            name, off, blob,
            field_texts(blob),
            paragraphs(blob),
            quoted_jumps(blob),
        ))
    return Book(path, pages, origin)
