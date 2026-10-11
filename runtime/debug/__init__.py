"""Debug route for the book reader.

Stage 2a opens and processes the book. Stage 2b writes render.html.
Stage 2c says the debug files are there. Off unless stage 2 failed
to open the book, or the caller passed debug=True.
"""

from pathlib import Path

from .play import render
from ..tbk import BOOK_MAGIC, load


def run(book_path, out, debug=False, stage2_failed=True):
    out = Path(out)
    out.mkdir(exist_ok=True)
    lines = []
    run_reader = debug or stage2_failed

    if run_reader:
        why = "--debug" if debug and not stage2_failed else "stage 2 did not open the book"
        block = ["stage 2a open and process", f"  on ({why})", f"  {book_path}"]
        book = load(book_path)
        data = Path(book_path).read_bytes()
        magic = int.from_bytes(data[book.book_offset:book.book_offset + 4], "little")
        block.append(
            f"  book at {book.book_offset:#x} magic {magic:#x} ok {magic == BOOK_MAGIC} pages {len(book.pages)}"
        )
        shown = 0
        for page in book.pages:
            text = [f.text for f in page.fields] + [
                p for p in page.paragraphs if p not in [f.text for f in page.fields]
            ]
            if not text:
                continue
            block.append(f"  {page.name} @{page.offset:#x} {text[0][:80]}")
            shown += 1
            if shown == 3:
                break
        (out / "02a_process.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
        lines.extend(block)

        html_path = out / "render.html"
        html_path.write_text(render(book), encoding="utf-8")
        block = ["stage 2b render", f"  wrote {html_path} ({html_path.stat().st_size} bytes)"]
        (out / "02b_render.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
        lines.extend(block)
    else:
        block = ["stage 2a open and process", "  off (stage 2 opened the book; pass --debug to force)"]
        (out / "02a_process.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
        lines.extend(block)
        block = ["stage 2b render", "  off"]
        (out / "02b_render.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
        lines.extend(block)

    files = sorted(p.name for p in out.iterdir() if p.is_file())
    prompt = f"Debug information is available in {out}"
    block = ["stage 2c", f"  {prompt}", f"  {', '.join(files)}"]
    (out / "02c.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
    lines.extend(block)
    return lines, prompt
