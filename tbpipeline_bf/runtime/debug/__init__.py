"""Debug route for the book reader.

Stage 2a opens and processes the book. Stage 2b writes render.html.
Stage 2c says the debug files are there. Off unless the caller passed
--dbgrender.
"""

from pathlib import Path

from .play import render_new, render_old
from .resources import write as write_resources
from .shapes import write as write_shapes
from ..openbook import open_book
from ..tbk import BOOK_MAGIC

PROBE_LOGS = ("bmp_bitmap.txt", "dll_probe.txt", "scaffold.txt")


def run(book_path, out, dbgrender=False, theme="default", render="new"):
    out = Path(out)
    out.mkdir(exist_ok=True)
    lines = []
    if not dbgrender:
        lines.append("stage 2a not reached (pass --dbgrender)")
        return lines, ""

    block = ["stage 2a open and process", "  on (--dbgrender)", f"  {book_path}"]
    opened = open_book(book_path)
    book = opened.book
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

    manifest = write_shapes(book, out)
    resources = write_resources(book, data, out)
    html_path = out / "render.html"
    html_path.write_text(render_new(book, theme, manifest, resources, opened.handlers), encoding="utf-8")
    wrote = [f"  wrote {html_path} ({html_path.stat().st_size} bytes) engine"]
    wrote.append(f"  render/ {len(manifest)} pages with a drawing")
    wrote.append(f"  resources/ {len(resources['book'])} book, {sum(len(v) for v in resources['pages'].values())} in pages")
    if render == "old":
        old_path = out / "render-old.html"
        old_path.write_text(render_old(book, theme), encoding="utf-8")
        wrote.append(f"  wrote {old_path} ({old_path.stat().st_size} bytes) render-old")
    block = ["stage 2b render", f"  theme {theme}", *wrote]
    (out / "02b_render.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
    lines.extend(block)

    probe = Path(__file__).resolve().parents[2] / "nehost"
    copied = []
    for name in PROBE_LOGS:
        src = probe / name
        if src.is_file():
            (out / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            copied.append(name)
    if copied:
        lines.append("  probes " + ", ".join(copied))

    files = sorted(p.name for p in out.iterdir() if p.is_file())
    drawn = sorted(p.stem for p in (out / "render").glob("*.png")) if (out / "render").is_dir() else []
    prompt = f"Debug information is available in {out}"
    block = [
        "stage 2c",
        f"  {prompt}",
        f"  {', '.join(files)}",
        f"  render/ {len(drawn)} PNG files, drawn and not placed",
    ]
    (out / "02c.txt").write_text("\n".join(block) + "\n", encoding="utf-8")
    lines.extend(block)
    return lines, prompt
