"""Run many ToolBook books through neww and record where each one stops (#227).

    python3 -m tbpipeline_neww.sweep --bin TBK_BIN --out results.jsonl BOOK...

Each book runs in its own process, with a time limit, so one that hangs or crashes does not
take the others with it. The walk is the same for every book: the first page, then up to
--pages steps to the next page, each followed by a wait and a mouse move so the book's
timers run. A step is Go > Next (the menu item's WM_COMMAND), Ctrl+Right (ToolBook's next
page key) or a click on text that reads like a Next button; a way that leaves the screen
unchanged gives way to the next, and the walk ends when none moves it. The walk letters
(m, k, t; upper case when the screen changed) and the screens count say how far it got.

A result line holds the stop, the calls, how many distinct screens were seen, the MessageBox
texts, the spec-row defaults, and the stop's cause: the "MODULE.ordinal Name" it names when
there is one. Books, screens and logs stay out of the repository: point --out outside it.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

FIRST = "wait 8000; move 320,240"
NEXT = "key ctrl+right; wait 4000; move {x},240"
CALL = re.compile(r"\b([A-Z][A-Z0-9_]+[.!]\d*\s*[A-Za-z_][A-Za-z0-9_]*)")


def cause_of(stop):
    """What a stop line names: 'GDI.351 ExtTextOut', a 'map mode' stop, a fault, or the line."""
    if not stop:
        return ""
    if stop.startswith("idle:"):
        return "idle"
    if stop.startswith("dos exit"):
        return "exit"
    m = CALL.search(stop)
    if m:
        return re.sub(r"\s+", " ", m.group(1))
    return re.sub(r"0x[0-9a-fA-F]+", "N", stop)[:80]


def titles(wine):
    """The captions of the visible top-level windows: the runtime's main window names the
    book it has open, or says (Untitled) when it opened none."""
    from tbpipeline_neww.user_wnd import WS_VISIBLE, wm
    m = wm(wine)
    out = []
    for h in m.children.get(m.desktop, []):
        w = m.get(h)
        if w is not None and w.style & WS_VISIBLE and w.text:
            out.append(w.text if isinstance(w.text, str) else w.text.decode("cp1252", "replace"))
    return out


def opened(result):
    """A pass: idle with no MessageBox and no spec-row defaults, and a main window that is not
    the runtime's empty "(Untitled)" one."""
    return (result.get("cause") == "idle" and not result.get("messagebox_count")
            and not result.get("default_count")
            and not any("(Untitled)" in t for t in result.get("titles") or []))


WM_COMMAND, MF_GRAYED, MF_DISABLED = 0x111, 0x1, 0x2


def next_command(wine):
    """(hwnd, id) of the Next item on the Go menu of a visible top-level window, enabled; or
    None. ToolBook's runtime menus have it (Go > Next); a book that hides its menu bar has
    none. Choosing it ends in WM_COMMAND with that id (a menu click's last message), which
    is what the walk posts: neww has no menu-bar tracking yet (WM_NCHITTEST stops)."""
    from tbpipeline_neww.user_res import menu_items
    from tbpipeline_neww.user_wnd import WS_VISIBLE, wm
    m = wm(wine)
    for h in m.children.get(m.desktop, []):
        w = m.get(h)
        if w is None or not w.style & WS_VISIBLE or not w.menu:
            continue
        for top in menu_items(wine, w.menu) or []:
            if top["text"].replace("&", "").strip().lower() != "go" or not top["sub"]:
                continue
            for item in menu_items(wine, top["sub"]) or []:
                label = item["text"].replace("&", "").split("\t")[0].strip().lower()
                if label.startswith("next") and not item["flags"] & (MF_GRAYED | MF_DISABLED):
                    return h, item["id"]
    return None


def screen_hash(wine):
    """A short hash of the screen, or None before GDI exists (a book that stops that early)."""
    g = getattr(wine, "gdi", None)
    if g is None:
        return None
    return hashlib.sha256(g.screen.tobytes()).hexdigest()[:16]


def _inside(box, outer):
    return outer[0] <= box[0] and outer[1] <= box[1] and box[2] <= outer[2] and box[3] <= outer[3]


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Texts:
    """Where text is drawn, followed through blits to the screen: gdi16 calls drawn() for each
    TextOut/ExtTextOut and blitted() for each raster operation when wine.draw_watch is set.
    Boxes are in the surface's pixels; a page drawn off screen and copied up keeps its words."""

    def __init__(self):
        self.by_image = {}

    def _list(self, img):
        entry = self.by_image.get(id(img))
        if entry is None or entry[0] is not img:
            entry = self.by_image[id(img)] = (img, [])
        return entry[1]

    def drawn(self, img, box, text):
        texts = self._list(img)
        texts[:] = [t for t in texts if not _overlaps(t[0], box)]
        if text.strip():
            texts.append((box, text))

    def blitted(self, img, box, src, srcpos):
        texts = self._list(img)
        texts[:] = [t for t in texts if not _overlaps(t[0], box)]
        if src is None or src is img:
            return
        sl, st = srcpos
        sbox = (sl, st, sl + box[2] - box[0], st + box[3] - box[1])
        dx, dy = box[0] - sl, box[1] - st
        for b, text in self._list(src):
            if _inside(b, sbox):
                texts.append(((b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy), text))

    def on(self, img):
        entry = self.by_image.get(id(img))
        return list(entry[1]) if entry is not None and entry[0] is img else []


NEXT_TEXT = re.compile(r"^\s*(next(\s+page)?|continue|forward|>|>>|\u2192)\s*(>|>>|\u00bb)?\s*$", re.I)


def next_text(wine):
    """The centre of the text on the screen that reads like a Next button ("Next", "Continue",
    ">>"), the lowest, then rightmost one; or None."""
    watch = getattr(wine, "draw_watch", None)
    g = getattr(wine, "gdi", None)
    if watch is None or g is None:
        return None
    hits = [b for b, text in watch.on(g.screen) if NEXT_TEXT.match(text)]
    if not hits:
        return None
    b = max(hits, key=lambda b: (b[3], b[2]))
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


class Walk:
    """The page walk: on each idle, one way of going to the next page. A way that left the
    screen as it was gives way to the next one (Go > Next as a WM_COMMAND, Ctrl+Right, a click
    on a Next text); when every way in a row left it unchanged, the walk is stuck and ends.
    log holds one letter per step, upper case when the screen changed after it."""

    WAYS = ("menu", "key", "text")
    LETTER = {"menu": "m", "key": "k", "text": "t"}

    def __init__(self, pages, find_menu=None, find_text=None, post=None):
        self.pages = pages
        self.find_menu = find_menu or next_command
        self.find_text = find_text or next_text
        self.post = post or _post_command
        self.way, self.unchanged, self.steps = 0, 0, 0
        self.before = None
        self.log = []
        self.screens = []
        self.stuck = False

    def look(self, wine):
        h = screen_hash(wine)
        if h is not None and (not self.screens or self.screens[-1] != h):
            self.screens.append(h)
        return h

    def __call__(self, wine):
        now = self.look(wine)
        if self.log:
            if now != self.before:
                self.log[-1] = self.log[-1].upper()
                self.unchanged = 0
            else:
                self.unchanged += 1
                self.way = (self.way + 1) % len(self.WAYS)
        if self.steps >= self.pages:
            return None
        tried = 0
        while tried < len(self.WAYS) and self.unchanged < len(self.WAYS):
            way = self.WAYS[self.way]
            script = self._try(wine, way)
            if script is not None:
                self.steps += 1
                self.before = now
                self.log.append(self.LETTER[way])
                return script
            # Not there to try: counts as a way that did not move the page.
            self.unchanged += 1
            self.way = (self.way + 1) % len(self.WAYS)
            tried += 1
        self.stuck = True
        return None

    def _try(self, wine, way):
        x = 320 + self.steps + 1
        if way == "menu":
            target = self.find_menu(wine)
            if target is None:
                return None
            self.post(wine, target)
            return f"wait 4000; move {x},240"
        if way == "key":
            return NEXT.format(x=x)
        spot = self.find_text(wine)
        if spot is None:
            return None
        return f"click {spot[0]},{spot[1]}; wait 4000; move {x},240"

    def summary(self):
        letters = "".join(self.log).lower()
        return {"walk": "".join(self.log), "menu_next": letters.count("m"), "keys": letters.count("k"),
                "text_clicks": letters.count("t"), "moved": sum(c.isupper() for c in self.log),
                "stuck": self.stuck, "screens": len(set(self.screens))}


def _post_command(wine, target):
    from tbpipeline_neww.user_wnd import wm
    m = wm(wine)
    m.queue_of(m.task_of(target[0])).queue.append((target[0], WM_COMMAND, target[1], 0))


def run_one(root, book, pages, call_limit):
    from tbpipeline_neww import machine
    host = machine.Machine(root, book, input_script=FIRST, idle_stop=True)
    walk = Walk(pages)
    host.box.wine.draw_watch = Texts()
    host.box.wine.on_idle = walk
    host.call_limit = call_limit
    host.timeout_us = max(host.timeout_us, call_limit * 1000)
    host.run(limit=call_limit * 1000)
    wine = host.box.wine
    walk.look(wine)
    trace = wine.trace
    boxes = [t for t in trace if t.startswith("USER.1 MessageBox")]
    defaults = sorted({t.split(" (default")[0] for t in trace if "(default" in t})
    stop = str(host.stop)
    return {"stop": stop, "titles": titles(wine), "cause": cause_of(stop), "calls": host.calls,
            **walk.summary(), "messageboxes": boxes[:3], "messagebox_count": len(boxes),
            "defaults": defaults[:5], "default_count": len(defaults)}


def child(args):
    t0 = time.time()
    try:
        out = run_one(args.bin, args.one, args.pages, args.calls)
    except Exception as e:     # a crash in neww is a finding too
        out = {"stop": f"python {type(e).__name__}: {e}", "cause": f"python {type(e).__name__}"}
    out["seconds"] = round(time.time() - t0, 1)
    print("RESULT " + json.dumps(out), flush=True)


def run_book(args, book):
    t0 = time.time()
    cmd = [sys.executable, "-W", "ignore", "-m", "tbpipeline_neww.sweep", "--bin", args.bin,
           "--one", book, "--pages", str(args.pages), "--calls", str(args.calls)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        lines = [l for l in p.stdout.splitlines() if l.startswith("RESULT ")]
        if lines:
            out = json.loads(lines[-1][7:])
        else:
            tail = (p.stderr.strip().splitlines() or ["no output"])[-1]
            out = {"stop": f"process exit {p.returncode}: {tail}", "cause": "crash"}
    except subprocess.TimeoutExpired:
        out = {"stop": f"no stop in {args.timeout} s", "cause": "timeout",
               "seconds": round(time.time() - t0, 1)}
    out["book"] = book
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bin", required=True, help="the ToolBook runtime folder (TB80RTM.EXE, its DLLs)")
    ap.add_argument("--out", help="JSON lines, one per book")
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--calls", type=int, default=3000000)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--one", help=argparse.SUPPRESS)
    ap.add_argument("books", nargs="*")
    args = ap.parse_args(argv)
    if args.one:
        return child(args)
    out = open(args.out, "a") if args.out else None
    with ThreadPoolExecutor(args.jobs) as pool:
        for r in pool.map(lambda b: run_book(args, b), args.books):
            r["pass"] = opened(r)
            line = json.dumps(r)
            print(f"{os.path.basename(r['book'])}: {'pass' if r['pass'] else 'stop'} {r.get('cause')} | screens {r.get('screens')} | "
                  f"walk {r.get('walk', '')} | calls {r.get('calls')} | {r.get('stop', '')[:120]}", flush=True)
            if out:
                out.write(line + "\n")
                out.flush()


if __name__ == "__main__":
    main()
