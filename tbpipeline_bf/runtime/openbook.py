"""Open a ToolBook file and read the handlers.

The 16-bit host never reaches the book. This path does. A handler is
expanded against the whole file, so a back-reference can use an earlier page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .expand import decompress, load_keywords
from .tbk import Book, load

_GOTO = re.compile(
    r'go\s+to\s+page\s+"([^"]+)"(?:\s+of\s+book\s+"([^"]+)")?',
    re.IGNORECASE,
)
_HANDLE = re.compile(rb"(?i)to handle [A-Za-z][A-Za-z0-9_]*")


@dataclass
class Handler:
    name: str
    source: str
    offset: int
    goto: str = ""
    book: str = ""


@dataclass
class Opened:
    book: Book
    data: bytes
    handlers: dict[str, list[Handler]] = field(default_factory=dict)

    def page_handlers(self, name: str) -> list[Handler]:
        return self.handlers.get(name, [])


def keywords():
    return load_keywords(Path(__file__).resolve().parent / "compat" / "res_77.bin")


def _body(source: str) -> str:
    lines = []
    for raw in source.replace("\r", "").split("\n"):
        line = raw.rstrip()
        if lines and line.strip().lower() in ("end", "end handler"):
            lines.append(line.strip())
            break
        lines.append(line)
    return "\n".join(lines).strip()


def open_book(path: str | Path) -> Opened:
    path = Path(path)
    book = load(path)
    data = path.read_bytes()
    words = keywords()
    opened = Opened(book, data)
    for page in book.pages:
        found = []
        for match in _HANDLE.finditer(page.blob):
            origin = page.offset + match.start()
            span = max(1, len(page.blob) - match.start())
            source = _body(decompress(data, words, origin=origin, span=span, max_out=8000))
            name = match.group().split()[-1].decode("latin-1")
            goto = _GOTO.search(source)
            found.append(Handler(
                name=name,
                source=source,
                offset=origin,
                goto=goto.group(1) if goto else "",
                book=goto.group(2) or "" if goto else "",
            ))
        if found:
            opened.handlers[page.name] = found
    return opened


def _forward(opened: Opened, name: str) -> str:
    """The jump that stays in this book and does not return to the first page."""
    clicks = [h for h in opened.page_handlers(name) if h.goto]
    if not clicks:
        return ""
    own = opened.book.path.name.lower()
    local = [h for h in clicks if not h.book or h.book.lower() == own]
    first = opened.book.pages[0].name if opened.book.pages else ""
    onward = [h for h in local if h.goto not in (first, name)]
    pick = onward[0] if onward else (local[0] if local else clicks[0])
    return pick.goto


def trace(opened: Opened, start: str | None = None, limit: int = 12) -> list[str]:
    """Follow the forward buttonClick from each page."""
    names = [p.name for p in opened.book.pages]
    if not names:
        return []
    here = start or names[0]
    lines = []
    seen = set()
    for _ in range(limit):
        if here in seen:
            lines.append(f"{here}  (already visited)")
            break
        seen.add(here)
        page = opened.book.page(here)
        if page is None:
            lines.append(f"{here}  (not in this book)")
            break
        jump = _forward(opened, here)
        text = ""
        if page.fields:
            text = page.fields[0].text.replace("\n", " ")[:80]
        lines.append(f"{here}  -> {jump or '-'}  {text}".rstrip())
        if not jump or jump == here:
            break
        here = jump
    return lines


def report(opened: Opened, page: str | None = None) -> str:
    book = opened.book
    lines = [
        f"opened {book.path.name}",
        f"pages {len(book.pages)}",
        f"handlers {sum(len(v) for v in opened.handlers.values())}",
    ]
    if page:
        got = opened.book.page(page)
        if got is None:
            lines.append(f"no page {page}")
            return "\n".join(lines)
        lines.append(f"page {got.name}")
        for field in got.fields[:6]:
            lines.append(f"  text {field.text.replace(chr(10), ' ')[:120]}")
        for handler in opened.page_handlers(page):
            lines.append(f"--- {handler.name} {handler.offset:#x}")
            lines.append(handler.source)
        return "\n".join(lines)
    lines.append("map")
    for page in book.pages:
        lines.append(f"  {page.name}  -> {_forward(opened, page.name) or '-'}")
    lines.append("trace")
    lines.extend("  " + row for row in trace(opened))
    return "\n".join(lines)
