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
# Keyword opcodes from resource 0x77: "to" is 0, "handle" is 1, "get" is 173.
# A trailing space leaves bit 5 clear. "get" is a two-byte index.
_TO_HANDLE = bytes((0x80, 0x81))
_TO_GET = bytes((0x80, 0x90, 0xAD))


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


def _kind(source: str) -> str:
    parts = source.lstrip().split()
    if len(parts) >= 3 and parts[0].lower() == "to" and parts[1].lower() in ("handle", "get"):
        return parts[2].strip("(),")
    return (parts[0] if parts else "")[:40]


def _page_name(book: Book, offset: int) -> str:
    for page in book.pages:
        if page.offset <= offset < page.offset + len(page.blob):
            return page.name
    return "scripts"


def _compressed(data: bytes, words, taken: set[int]) -> list[Handler]:
    """Handlers whose names are keywords, not plain text. System books store them this way."""
    found = []
    for pattern in (_TO_HANDLE, _TO_GET):
        start = 0
        while True:
            origin = data.find(pattern, start)
            if origin < 0:
                break
            start = origin + 1
            if origin in taken:
                continue
            try:
                source = _body(decompress(data, words, origin=origin, span=8000, max_out=8000))
            except Exception:
                continue
            low = source.lstrip().lower()
            if not (low.startswith("to handle ") or low.startswith("to get ")):
                continue
            taken.add(origin)
            goto = _GOTO.search(source)
            found.append(Handler(
                name=_kind(source),
                source=source,
                offset=origin,
                goto=goto.group(1) if goto else "",
                book=goto.group(2) or "" if goto else "",
            ))
    found.sort(key=lambda h: h.offset)
    return found


def open_book(path: str | Path) -> Opened:
    path = Path(path)
    book = load(path)
    data = path.read_bytes()
    words = keywords()
    opened = Opened(book, data)
    taken: set[int] = set()
    for page in book.pages:
        found = []
        for match in _HANDLE.finditer(page.blob):
            origin = page.offset + match.start()
            span = max(1, len(page.blob) - match.start())
            source = _body(decompress(data, words, origin=origin, span=span, max_out=8000))
            taken.add(origin)
            goto = _GOTO.search(source)
            found.append(Handler(
                name=match.group().split()[-1].decode("latin-1"),
                source=source,
                offset=origin,
                goto=goto.group(1) if goto else "",
                book=goto.group(2) or "" if goto else "",
            ))
        if found:
            opened.handlers[page.name] = found
    for handler in _compressed(data, words, taken):
        name = _page_name(book, handler.offset)
        bucket = opened.handlers.setdefault(name, [])
        if any(have.source == handler.source for have in bucket):
            continue
        bucket.append(handler)
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


def _followed(engine) -> str:
    script = engine.followed
    if script is None:
        return "no buttonClick"
    return f"{script['name']} {script['offset']:#x}"


def click(opened: Opened) -> list[str]:
    """Run the first page's buttonClick, then the page it landed on.

    Each line is: from page, the handler that ran and its offset, landed page.
    """
    from .engine import Engine

    if not opened.book.pages:
        return []
    engine = Engine(opened.book)
    engine.load_scripts(opened.handlers)
    start = engine.page.name
    try:
        landed = engine.button_click()
    except (KeyError, IndexError):
        return [f"{start} {_followed(engine)} -> -"]
    lines = [f"{start} {_followed(engine)} -> {landed.name}"]
    if landed.name == start:
        return lines
    try:
        back = engine.button_click()
    except (KeyError, IndexError):
        return lines
    lines.append(f"{landed.name} {_followed(engine)} -> {back.name}")
    return lines


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
    if "scripts" in opened.handlers:
        lines.append(f"scripts {len(opened.handlers['scripts'])}")
    if page:
        got = opened.book.page(page)
        extra = opened.page_handlers(page)
        if got is None and not extra:
            lines.append(f"no page {page}")
            return "\n".join(lines)
        lines.append(f"page {page if got is None else got.name}")
        if got is not None:
            for field in got.fields[:6]:
                lines.append(f"  text {field.text.replace(chr(10), ' ')[:120]}")
        for handler in extra:
            lines.append(f"--- {handler.name} {handler.offset:#x}")
            if got is None:
                lines.append(handler.source.split("\n", 1)[0])
            else:
                lines.append(handler.source)
        return "\n".join(lines)
    lines.append("map")
    for page in book.pages:
        lines.append(f"  {page.name}  -> {_forward(opened, page.name) or '-'}")
    lines.append("click")
    lines.extend("  " + row for row in click(opened))
    lines.append("trace")
    lines.extend("  " + row for row in trace(opened))
    return "\n".join(lines)
