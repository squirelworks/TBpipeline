"""In-memory book the old TB80RTM object 0 / page P0 model was walking.

Not a port of the NE image. Pages, a current page, and notify handlers
are enough to drive the Navy CAI books once OpenScript is interpreted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .tbk import Book, Page

_ASSIGN = re.compile(r"^(\w+)\s*=\s*name\s+of\s+this\s+(book|page)\s*$", re.IGNORECASE)
_GOTO = re.compile(
    r'go\s+to\s+page\s+(?:"([^"]+)"|\(\s*(\w+)\s*\))'
    r'(?:\s+of\s+book\s*(?:\(\s*(\w+)\s*\)|"([^"]+)"))?',
    re.IGNORECASE,
)


def compile_handler(source: str) -> list[dict]:
    """The navigation subset of one handler. Anything else is ignored."""
    steps = []
    for raw in source.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        low = line.lower()
        if low.startswith("to handle") or low.startswith("to get"):
            continue
        if low == "end" or low.startswith("end "):
            break
        if low.startswith("system "):
            continue
        assigned = _ASSIGN.match(line)
        if assigned:
            steps.append({"op": "set", "name": assigned.group(1), "from": assigned.group(2).lower()})
            continue
        goto = _GOTO.search(line)
        if not goto:
            continue
        step = {"op": "goto"}
        if goto.group(1):
            step["page"] = goto.group(1)
        else:
            step["pageVar"] = goto.group(2)
        if goto.group(4):
            step["book"] = goto.group(4)
        elif goto.group(3):
            step["bookVar"] = goto.group(3)
        steps.append(step)
    return steps


def run_steps(steps: list[dict], variables: dict, book_name: str, page_name: str):
    """Run compiled steps. Returns (page, book) for the last goto, or (None, None)."""
    dest = None
    other = None
    for step in steps:
        if step["op"] == "set":
            variables[step["name"]] = book_name if step["from"] == "book" else page_name
            continue
        if step["op"] != "goto":
            continue
        dest = step.get("page") or variables.get(step.get("pageVar") or "", "")
        if step.get("book"):
            other = step["book"]
        elif step.get("bookVar"):
            other = variables.get(step["bookVar"], "")
        else:
            other = ""
    return dest or None, other or None


@dataclass
class Notify:
    name: str
    args: tuple


@dataclass
class Engine:
    book: Book
    index: int = 0
    log: list[Notify] = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    scripts: dict = field(default_factory=dict)

    @property
    def page(self) -> Page | None:
        if not self.book.pages:
            return None
        return self.book.pages[self.index]

    def load_scripts(self, handlers: dict) -> None:
        """buttonClick handlers, compiled, keyed by page name."""
        self.scripts = {}
        for name, found in handlers.items():
            clicks = []
            for handler in found:
                if handler.name.lower() != "buttonclick":
                    continue
                steps = compile_handler(handler.source)
                literal = next((s.get("page") for s in steps if s.get("op") == "goto" and s.get("page")), "")
                clicks.append({"name": handler.name, "steps": steps, "literal": literal})
            if clicks:
                self.scripts[name] = clicks

    def go(self, name: str) -> Page:
        for i, page in enumerate(self.book.pages):
            if page.name == name:
                self.index = i
                self.log.append(Notify("enterPage", (name,)))
                return page
        raise KeyError(name)

    def next(self) -> Page:
        if self.index + 1 >= len(self.book.pages):
            raise IndexError("last page")
        self.index += 1
        page = self.book.pages[self.index]
        self.log.append(Notify("enterPage", (page.name,)))
        return page

    def back(self) -> Page:
        if self.index == 0:
            raise IndexError("first page")
        self.index -= 1
        page = self.book.pages[self.index]
        self.log.append(Notify("enterPage", (page.name,)))
        return page

    def button_click(self, target: str | None = None) -> Page:
        """Run this page's buttonClick. A quoted id is only the fallback."""
        page = self.page
        if page is None:
            raise IndexError("no page")
        self.log.append(Notify("buttonClick", (page.name, target or "")))
        scripts = self.scripts.get(page.name) or []
        chosen = None
        if target:
            for script in scripts:
                if script.get("literal") == target:
                    chosen = script
                    break
        if chosen is None and scripts and not target:
            chosen = scripts[0]
        if chosen is not None:
            dest, other = run_steps(chosen["steps"], self.variables, Path(self.book.path).name, page.name)
            own = Path(self.book.path).name.lower()
            if other and Path(other).name.lower() != own:
                self.log.append(Notify("otherBook", (other, dest or "")))
                return page
            if dest:
                try:
                    return self.go(dest)
                except KeyError:
                    self.log.append(Notify("missing", (dest,)))
                    return page
        if target:
            return self.go(target)
        return page
