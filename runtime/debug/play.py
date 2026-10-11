"""Write a page the way the reader did: text, then the buttons that jump.

The book stays a TBK. This writes one HTML file that holds the pages
already split out of it, and moves on buttonClick / next / back.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from ..engine import Engine
from ..tbk import Book


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


def render_old(book: Book) -> str:
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
  header {{ background: #1e4d8c; padding: 10px 16px; display: flex; align-items: center; gap: 16px; }}
  header b {{ font-family: system-ui, sans-serif; }}
  header select {{ font: 14px system-ui, sans-serif; padding: 4px 8px; min-width: 120px; }}
  #count {{ margin-left: auto; }}
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
<header><b id="title"></b><select id="pages"></select><span id="count"></span></header>
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
const menu = document.getElementById("pages");
document.getElementById("title").textContent = book.title;
for (const page of book.pages) {{
  const opt = document.createElement("option");
  opt.value = page.id;
  opt.textContent = page.id;
  menu.appendChild(opt);
}}
function show(n) {{
  i = Math.max(0, Math.min(book.pages.length - 1, n));
  const page = book.pages[i];
  document.getElementById("count").textContent = (i + 1) + " / " + book.pages.length;
  document.getElementById("pid").textContent = page.id;
  menu.value = page.id;
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
menu.addEventListener("change", () => go(menu.value));
show(0);
</script>
</body>
</html>
"""


def write(book: Book, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_old(book), encoding="utf-8")
    return dest


render = render_old


def walked(book: Book) -> list[dict]:
    """Pages in the order engine.py walks them. Works for a .tbk or a .sbk."""
    engine = Engine(book)
    pages = []
    while True:
        page = engine.page
        if page is None:
            break
        prose = [f.text for f in page.fields]
        for para in page.paragraphs:
            if para not in prose:
                prose.append(para)
        pages.append({
            "id": page.name,
            "text": prose[:12],
            "jumps": page.quoted_jumps[:16],
        })
        try:
            engine.next()
        except IndexError:
            break
    return pages


def render_new(book: Book) -> str:
    payload = json.dumps({
        "title": book.path.stem,
        "pages": walked(book),
    })
    title = html.escape(book.path.stem)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; background: #10141a; color: #e7edf4; font: 16px/1.5 system-ui, sans-serif; }}
  header {{ position: sticky; top: 0; display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: #172033; border-bottom: 1px solid #2a3548; }}
  header b {{ font-weight: 600; }}
  header select {{ font: 14px system-ui, sans-serif; padding: 6px 8px; min-width: 140px; background: #10141a; color: inherit; border: 1px solid #3a4760; border-radius: 6px; }}
  #count {{ margin-left: auto; color: #9aabbf; font-size: 13px; }}
  main {{ max-width: 760px; margin: 24px auto; background: #f7f4ee; color: #1c1c1c; min-height: 420px; padding: 28px 32px 20px; border-radius: 8px; }}
  p {{ margin: 0 0 12px; }}
  .empty {{ color: #777; font-style: italic; }}
  .jumps {{ margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; }}
  button {{ font: 14px system-ui, sans-serif; padding: 6px 12px; border: 1px solid #2a3548; border-radius: 6px; background: #fff; cursor: pointer; }}
  button:hover {{ background: #e7eef8; }}
  footer {{ max-width: 760px; margin: 0 auto 24px; display: flex; justify-content: space-between; color: #9aabbf; font-size: 13px; }}
</style>
</head>
<body>
<header><b id="title"></b><select id="pages"></select><span id="count"></span></header>
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
const engine = {{ index: 0, log: [] }};
const stage = document.getElementById("stage");
const menu = document.getElementById("pages");
document.getElementById("title").textContent = book.title;
for (const page of book.pages) {{
  const opt = document.createElement("option");
  opt.value = page.id;
  opt.textContent = page.id;
  menu.appendChild(opt);
}}
function show() {{
  const page = book.pages[engine.index];
  document.getElementById("count").textContent = (engine.index + 1) + " / " + book.pages.length;
  document.getElementById("pid").textContent = page.id;
  menu.value = page.id;
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
      b.addEventListener("click", () => buttonClick(id));
      box.appendChild(b);
    }}
    stage.appendChild(box);
  }}
}}
function enter(name) {{
  engine.log.push(["enterPage", name]);
  show();
}}
function go(id) {{
  const n = book.pages.findIndex(p => p.id === id);
  if (n < 0) return;
  engine.index = n;
  enter(id);
}}
function next() {{
  if (engine.index + 1 < book.pages.length) go(book.pages[engine.index + 1].id);
}}
function back() {{
  if (engine.index > 0) go(book.pages[engine.index - 1].id);
}}
function buttonClick(id) {{
  engine.log.push(["buttonClick", id]);
  go(id);
}}
document.getElementById("next").addEventListener("click", next);
document.getElementById("back").addEventListener("click", back);
menu.addEventListener("change", () => go(menu.value));
if (book.pages.length) enter(book.pages[0].id);
</script>
</body>
</html>
"""
