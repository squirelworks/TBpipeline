#!/usr/bin/env python3
"""Pipeline host: startup, file open, file process, file render.

The Unicorn RTM host dies on an unresolved far call before it issues a
DOS open. This host is the four stages that call never reaches. Startup
is the SoftICE load order. Open, process, and render use the book format
already decoded in runtime.tbk. It does not execute OpenScript and it
does not pretend to be USER or GDI.
"""

import os
import sys
from pathlib import Path

from .runtime.tbk import BOOK_MAGIC, load
from .runtime.play import render
from .nehost.loadseq import ORDER, FILES

OUT = Path(__file__).resolve().parent
UNPACKED = os.environ.get("TBK_UNPACKED", str(OUT.parent / "bin"))


def startup():
    rows = []
    for kind, name in ORDER:
        filename = FILES.get(name)
        path = os.path.join(UNPACKED, filename) if filename else ""
        present = bool(path) and os.path.isfile(path)
        rows.append((kind, name, "yes" if present else "absent"))
    return rows


def process(book):
    pages = []
    for page in book.pages:
        text = [f.text for f in page.fields]
        for para in page.paragraphs:
            if para not in text:
                text.append(para)
        pages.append({
            "id": page.name,
            "offset": page.offset,
            "fields": len(page.fields),
            "jumps": page.quoted_jumps[:8],
            "text": text[:4],
            "bmps": page.blob.count(b"BM"),
        })
    return pages


def main():
    book_path = sys.argv[1] if len(sys.argv) > 1 else "/workspace/artifacts/courses/9e954d01.tbk"
    lines = ["stage 1 startup"]
    rows = startup()
    present = [name for _, name, flag in rows if flag == "yes"]
    absent = [name for _, name, flag in rows if flag == "absent"]
    lines.append(f"  modules on disk {len(present)}: {', '.join(present)}")
    lines.append(f"  windows modules absent {len(absent)}: {', '.join(absent[:8])}")

    lines.append("stage 2 file open")
    book = load(book_path)
    data = Path(book_path).read_bytes()
    magic = int.from_bytes(data[book.book_offset:book.book_offset + 4], "little")
    lines.append(f"  {book_path}")
    lines.append(f"  size {len(data)} book at {book.book_offset:#x} magic {magic:#x} ok {magic == BOOK_MAGIC}")
    lines.append(f"  pages {len(book.pages)}")

    lines.append("stage 3 file process")
    pages = process(book)
    shown = [p for p in pages if p["text"]][:3]
    for page in shown:
        lines.append(f"  {page['id']} @{page['offset']:#x} fields {page['fields']} bmps {page['bmps']} jumps {page['jumps']}")
        if page["text"]:
            lines.append(f"    {page['text'][0][:90]}")

    lines.append("stage 4 file render")
    html_path = OUT / "render.html"
    html_path.write_text(render(book), encoding="utf-8")
    lines.append(f"  wrote {html_path} ({html_path.stat().st_size} bytes, {len(book.pages)} pages)")

    trace = OUT / "TRACE.txt"
    trace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
