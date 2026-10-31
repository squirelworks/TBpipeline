"""Write a page the way the reader did: text, then the buttons that jump.

The book stays a TBK. This writes one HTML file that holds the pages
already split out of it, and moves on buttonClick / next / back.

--theme default is the Windows 95 window. --theme modern is the dark reader.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from ..engine import Engine, compile_handler
from ..tbk import Book
from .shapes import polygons

THEMES = {
    "default": """
  body { margin: 0; background: #008080; color: #000; font: 13px/1.4 Tahoma, "MS Sans Serif", sans-serif; }
  .window { max-width: 760px; margin: 24px auto; background: #c0c0c0; border: 2px solid; border-color: #fff #404040 #404040 #fff; box-shadow: 1px 1px 0 #000; }
  header { background: #000080; color: #fff; padding: 3px 4px; display: flex; align-items: center; gap: 8px; }
  header b { font-weight: 700; padding-left: 4px; }
  header select { font: 13px Tahoma, "MS Sans Serif", sans-serif; min-width: 120px; background: #fff; color: #000; border: 2px solid; border-color: #404040 #fff #fff #404040; }
  #count { margin-left: auto; padding-right: 6px; }
  main { background: #fff; color: #000; min-height: 420px; margin: 4px; padding: 12px 14px; border: 2px solid; border-color: #404040 #fff #fff #404040; }
  p { margin: 0 0 10px; }
  .empty { color: #404040; font-style: italic; }
  .jumps { margin-top: 14px; display: flex; flex-wrap: wrap; gap: 6px; }
  button { font: 13px Tahoma, "MS Sans Serif", sans-serif; padding: 4px 12px; background: #c0c0c0; color: #000; border: 2px solid; border-color: #fff #404040 #404040 #fff; cursor: pointer; }
  button:active { border-color: #404040 #fff #fff #404040; }
  footer { display: flex; justify-content: space-between; padding: 4px 6px 6px; }
""",
    "modern": """
  body { margin: 0; background: #10141a; color: #e7edf4; font: 16px/1.5 system-ui, sans-serif; }
  .window { max-width: 760px; margin: 24px auto; }
  header { position: sticky; top: 0; display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: #172033; border-bottom: 1px solid #2a3548; }
  header b { font-weight: 600; }
  header select { font: 14px system-ui, sans-serif; padding: 6px 8px; min-width: 140px; background: #10141a; color: inherit; border: 1px solid #3a4760; border-radius: 6px; }
  #count { margin-left: auto; color: #9aabbf; font-size: 13px; }
  main { background: #f7f4ee; color: #1c1c1c; min-height: 420px; padding: 28px 32px 20px; border-radius: 8px; }
  p { margin: 0 0 12px; }
  .empty { color: #777; font-style: italic; }
  .jumps { margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; }
  button { font: 14px system-ui, sans-serif; padding: 6px 12px; border: 1px solid #2a3548; border-radius: 6px; background: #fff; cursor: pointer; }
  button:hover { background: #e7eef8; }
  footer { display: flex; justify-content: space-between; color: #9aabbf; font-size: 13px; padding: 8px 0 24px; }
""",
}


def theme_css(name):
    return THEMES.get(name, THEMES["default"])


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


def document(title, payload, theme, script, extra=""):
    css = theme_css(theme)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{css}
  .extra {{ max-width: 760px; margin: 8px auto 24px; text-align: center; }}
  .extra button {{ font: 13px Tahoma, "MS Sans Serif", sans-serif; padding: 4px 12px; }}
  main {{ position: relative; }}
  svg.placed {{ position: absolute; left: 0; top: 0; overflow: visible; pointer-events: none; }}
  #files {{ margin-top: 10px; }}
  #files img {{ max-width: 100%; background: #fff; border: 1px solid #404040; }}
  #files p {{ color: inherit; }}
</style>
</head>
<body>
<div class="window">
<header><b id="title"></b><select id="pages"></select><span id="count"></span></header>
<main id="stage"></main>
<footer>
  <span>
    <button id="back" type="button">Back</button>
    <button id="next" type="button">Next</button>
  </span>
  <span id="pid"></span>
</footer>
</div>
<div class="extra">
  <button id="show" type="button">Show rendered files for this page</button>
  <button id="resources" type="button">Resources extracted</button>
  <div id="files"></div>
</div>
<script>
const book = {payload};
{script}
</script>
</body>
</html>
"""


OLD_SCRIPT = """
let i = 0;
const stage = document.getElementById("stage");
const menu = document.getElementById("pages");
document.getElementById("title").textContent = book.title;
for (const page of book.pages) {
  const opt = document.createElement("option");
  opt.value = page.id;
  opt.textContent = page.id;
  menu.appendChild(opt);
}
function show(n) {
  i = Math.max(0, Math.min(book.pages.length - 1, n));
  const page = book.pages[i];
  document.getElementById("count").textContent = (i + 1) + " / " + book.pages.length;
  document.getElementById("pid").textContent = page.id;
  menu.value = page.id;
  stage.replaceChildren();
  if (!page.text.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "This page has no lesson text in the book.";
    stage.appendChild(p);
  }
  for (const line of page.text) {
    const p = document.createElement("p");
    p.textContent = line;
    stage.appendChild(p);
  }
  if (page.jumps.length) {
    const box = document.createElement("div");
    box.className = "jumps";
    for (const id of page.jumps) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = id;
      b.addEventListener("click", () => go(id));
      box.appendChild(b);
    }
    stage.appendChild(box);
  }
}
function go(id) {
  const n = book.pages.findIndex(p => p.id === id);
  if (n >= 0) show(n);
}
document.getElementById("next").addEventListener("click", () => show(i + 1));
document.getElementById("back").addEventListener("click", () => show(i - 1));
menu.addEventListener("change", () => go(menu.value));
show(0);
"""


NEW_SCRIPT = """
const engine = { index: 0, log: [], vars: {} };
const stage = document.getElementById("stage");
const menu = document.getElementById("pages");
document.getElementById("title").textContent = book.title;
for (const page of book.pages) {
  const opt = document.createElement("option");
  opt.value = page.id;
  opt.textContent = page.id;
  menu.appendChild(opt);
}
function show() {
  const page = book.pages[engine.index];
  document.getElementById("count").textContent = (engine.index + 1) + " / " + book.pages.length;
  document.getElementById("pid").textContent = page.id;
  menu.value = page.id;
  stage.replaceChildren();
  if (!page.text.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "This page has no lesson text in the book.";
    stage.appendChild(p);
  }
  for (const line of page.text) {
    const p = document.createElement("p");
    p.textContent = line;
    stage.appendChild(p);
  }
  if (page.text.length && !page.textAt) {
    const p = document.createElement("p");
    p.className = "empty unplaced";
    p.textContent = "Text position unknown: the field record's coordinates are not decoded, so this text is listed, not placed.";
    stage.appendChild(p);
  }
  if (page.shapes && page.shapes.length) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "placed");
    let w = 1, h = 1;
    for (const shape of page.shapes) {
      for (const [x, y] of shape.points) { w = Math.max(w, x); h = Math.max(h, y); }
    }
    svg.setAttribute("width", Math.ceil(w));
    svg.setAttribute("height", Math.ceil(h));
    for (const shape of page.shapes) {
      const poly = document.createElementNS(ns, "polygon");
      poly.setAttribute("points", shape.points.map(p => p[0] + "," + p[1]).join(" "));
      poly.setAttribute("fill", shape.fill);
      svg.appendChild(poly);
    }
    stage.appendChild(svg);
  }
  if (page.handlers && page.handlers.length) {
    const box = document.createElement("div");
    box.className = "jumps";
    page.handlers.forEach((handler, n) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = handler.label;
      b.addEventListener("click", () => buttonClick(n));
      box.appendChild(b);
    });
    stage.appendChild(box);
  } else if (page.jumps.length) {
    const box = document.createElement("div");
    box.className = "jumps";
    for (const id of page.jumps) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = id;
      b.addEventListener("click", () => go(id));
      box.appendChild(b);
    }
    stage.appendChild(box);
  }
}
function enter(name) {
  engine.log.push(["enterPage", name]);
  show();
}
function go(id) {
  const n = book.pages.findIndex(p => p.id === id);
  if (n < 0) return;
  engine.index = n;
  enter(id);
}
function next() {
  if (engine.index + 1 < book.pages.length) go(book.pages[engine.index + 1].id);
}
function back() {
  if (engine.index > 0) go(book.pages[engine.index - 1].id);
}
function runSteps(steps) {
  let dest = "";
  let other = "";
  for (const step of steps) {
    if (step.op === "set") {
      engine.vars[step.name] = step.from === "book" ? (book.file || "") : book.pages[engine.index].id;
    } else if (step.op === "goto") {
      dest = step.page || engine.vars[step.pageVar] || "";
      other = step.book || (step.bookVar ? (engine.vars[step.bookVar] || "") : "");
    }
  }
  const own = (book.file || "").toLowerCase();
  if (other && own && other.toLowerCase() !== own) return;
  if (dest) go(dest);
}
function buttonClick(n) {
  const page = book.pages[engine.index];
  const handler = page.handlers && page.handlers[n];
  engine.log.push(["buttonClick", handler ? handler.label : n]);
  if (handler) runSteps(handler.steps);
}
document.getElementById("next").addEventListener("click", next);
document.getElementById("back").addEventListener("click", back);
menu.addEventListener("change", () => go(menu.value));
if (book.pages.length) enter(book.pages[0].id);
document.getElementById("show").addEventListener("click", () => {
  const box = document.getElementById("files");
  const page = book.pages[engine.index];
  const files = (book.files && book.files[page.id]) || [];
  box.replaceChildren();
  if (!files.length) {
    const p = document.createElement("p");
    p.textContent = page.id + " has nothing rendered yet.";
    box.appendChild(p);
    return;
  }
  for (const src of files) {
    const img = document.createElement("img");
    img.src = src;
    img.alt = src;
    box.appendChild(img);
  }
});
document.getElementById("resources").addEventListener("click", () => {
  const box = document.getElementById("files");
  const page = book.pages[engine.index];
  const res = book.resources || { book: [], pages: {} };
  const files = (res.pages && res.pages[page.id]) || [];
  const bookFiles = res.book || [];
  box.replaceChildren();
  const head = document.createElement("p");
  head.textContent = page.id + ": " + files.length + " on this page, " + bookFiles.length + " book-level.";
  box.appendChild(head);
  for (const src of files.concat(bookFiles)) {
    const img = document.createElement("img");
    img.src = src;
    img.alt = src;
    box.appendChild(img);
  }
  if (!files.length && !bookFiles.length) {
    const p = document.createElement("p");
    p.textContent = "Nothing extracted.";
    box.appendChild(p);
  }
});
"""


def render_old(book: Book, theme="default") -> str:
    payload = json.dumps({"title": book.path.stem, "pages": page_text(book)})
    return document(html.escape(book.path.stem), payload, theme, OLD_SCRIPT)


def write(book: Book, dest: str | Path, theme="default") -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_old(book, theme), encoding="utf-8")
    return dest


def _clicks(handlers) -> list[dict]:
    clicks = []
    for handler in handlers or []:
        if handler.name.lower() != "buttonclick":
            continue
        steps = compile_handler(handler.source)
        label = next((s.get("page") for s in steps if s.get("page")), "")
        if not label:
            label = next((s.get("pageVar") for s in steps if s.get("pageVar")), "buttonClick")
        clicks.append({"label": label, "steps": steps})
    return clicks


def placed(blob: bytes) -> list[dict]:
    """Kind-04 polygons at the twips the record names, divided by 15."""
    return [
        {"points": [[x, y] for x, y in points], "fill": "#%02x%02x%02x" % color}
        for points, color in polygons(blob)
    ]


def walked(book: Book, handlers: dict | None = None) -> list[dict]:
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
            "handlers": _clicks((handlers or {}).get(page.name)),
            "shapes": placed(page.blob),
            "textAt": None,
        })
        try:
            engine.next()
        except IndexError:
            break
    return pages


def render_new(book: Book, theme="default", files=None, resources=None, handlers=None) -> str:
    payload = json.dumps({
        "title": book.path.stem,
        "file": Path(book.path).name,
        "pages": walked(book, handlers),
        "files": files or {},
        "resources": resources or {"book": [], "pages": {}},
    })
    return document(html.escape(book.path.stem), payload, theme, NEW_SCRIPT)
