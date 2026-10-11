"""Write a page the way the reader did: text, then the buttons that jump.

The book stays a TBK. This writes one HTML file that holds the pages
already split out of it, and moves on buttonClick / next / back.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .tbk import Book


def page_text(book: Book) -> list[dict]:
    pages = []
    for page in book.pages:
        prose = [f.text for f in page.fields]
        for para in page.paragraphs:
            if para not in prose:
                prose.append(para)
        pages.append({
            "id": page.name,
            "text": prose[:12],
            "jumps": page.quoted_jumps[:16],
        })
    return pages


def render(book: Book) -> str:
    payload = json.dumps({
        "title": book.path.stem,
        "pages": page_text(book),
    })
    title = html.escape(book.path.stem)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ margin: 0; background: #1c2430; color: #e8eef6; font: 16px/1.45 Georgia, serif; }}
  header {{ background: #1e4d8c; padding: 10px 16px; display: flex; justify-content: space-between; }}
  header b {{ font-family: system-ui, sans-serif; }}
  main {{ max-width: 760px; margin: 24px auto; background: #f4f1e8; color: #1b1b1b; min-height: 420px; padding: 28px 32px 20px; }}
  p {{ margin: 0 0 12px; }}
  .empty {{ color: #666; font-style: italic; }}
  .jumps {{ margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; }}
  button {{ font: 14px system-ui, sans-serif; padding: 6px 12px; border: 1px solid #1e4d8c; background: #fff; cursor: pointer; }}
  button:hover {{ background: #e4eef8; }}
  footer {{ max-width: 760px; margin: 0 auto 24px; display: flex; justify-content: space-between; color: #c5d0dc; font: 13px system-ui, sans-serif; }}
</style>
</head>
<body>
<header><b id="title"></b><span id="count"></span></header>
<main id="stage"></main>
<footer>
  <span>
    <button id="back" type="button">Back</button>
    <button id="next" type="button">Next</button>
  </span>
  <span id="pid"></span>
</footer>
<script>
const book = {payload};
let i = 0;
const stage = document.getElementById("stage");
document.getElementById("title").textContent = book.title;
function show(n) {{
  i = Math.max(0, Math.min(book.pages.length - 1, n));
  const page = book.pages[i];
  document.getElementById("count").textContent = (i + 1) + " / " + book.pages.length;
  document.getElementById("pid").textContent = page.id;
  stage.replaceChildren();
  if (!page.text.length) {{
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "This page has no lesson text in the book.";
    stage.appendChild(p);
  }}
  for (const line of page.text) {{
    const p = document.createElement("p");
    p.textContent = line;
    stage.appendChild(p);
  }}
  if (page.jumps.length) {{
    const box = document.createElement("div");
    box.className = "jumps";
    for (const id of page.jumps) {{
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = id;
      b.addEventListener("click", () => go(id));
      box.appendChild(b);
    }}
    stage.appendChild(box);
  }}
}}
function go(id) {{
  const n = book.pages.findIndex(p => p.id === id);
  if (n >= 0) show(n);
}}
document.getElementById("next").addEventListener("click", () => show(i + 1));
document.getElementById("back").addEventListener("click", () => show(i - 1));
show(0);
</script>
</body>
</html>
"""


def write(book: Book, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(book), encoding="utf-8")
    return dest
