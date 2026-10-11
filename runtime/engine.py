"""In-memory book the old TB80RTM object 0 / page P0 model was walking.

Not a port of the NE image. Pages, a current page, and notify handlers
are enough to drive the Navy CAI books once OpenScript is interpreted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tbk import Book, Page


@dataclass
class Notify:
    name: str
    args: tuple


@dataclass
class Engine:
    book: Book
    index: int = 0
    log: list[Notify] = field(default_factory=list)

    @property
    def page(self) -> Page | None:
        if not self.book.pages:
            return None
        return self.book.pages[self.index]

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

    def button_click(self, target: str) -> Page:
        self.log.append(Notify("buttonClick", (target,)))
        return self.go(target)
