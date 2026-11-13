"""Run many ToolBook books through neww and record where each one stops (#227).

    python3 -m tbpipeline_neww.sweep --bin TBK_BIN --out results.jsonl BOOK...

Each book runs in its own process, with a time limit, so one that hangs or crashes does not
take the others with it. The walk is the same for every book: the first page, then up to
--pages steps to the next page, each followed by a wait and a mouse move so the book's
timers run. A step is Go > Next (the menu item's WM_COMMAND), a click on text that reads like a
Next button, a click on a button-sized picture (bottom-right first; the one that turned a
page is tried first after that), a click in the middle of the window (a title page), or
Ctrl+Right (ToolBook's next page key). A way that leaves
the screen unchanged gives way to the next, and the walk ends when none moves it. The walk
letters (m, t, p, k; upper case when the screen changed) and the screens count say how far
it got.

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
    """A pass: the book opened (idle with no MessageBox, no spec-row defaults, and a main window
    that is not the runtime's empty "(Untitled)" one) and the walk ended idle, or in the book's
    own exit after the walk clicked something (its Exit button). MessageBoxes and titles count
    as they were when the book first went idle, when the sweep has them."""
    cause = result.get("cause")
    ended = cause == "idle" or (cause == "exit" and bool(result.get("walk")))
    boxes = result.get("open_messagebox_count", result.get("messagebox_count"))
    titles = result.get("open_titles", result.get("titles")) or []
    return (ended and not boxes and not result.get("default_count")
            and not any("(Untitled)" in t for t in titles))


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


class Marks:
    """What is drawn where, followed through blits to the screen: gdi16 calls drawn() for each
    TextOut/ExtTextOut and blitted() for each raster operation when wine.draw_watch is set.
    A mark is (box, kind, value): a "text" with its string, or a "picture", a button-sized
    bitmap copied in (value its size). Boxes are in the surface's pixels, so a page composed
    off screen and copied up keeps its words and pictures."""

    def __init__(self):
        self.by_image = {}

    def _list(self, img):
        entry = self.by_image.get(id(img))
        if entry is None or entry[0] is not img:
            entry = self.by_image[id(img)] = (img, [])
        return entry[1]

    def drawn(self, img, box, text):
        marks = self._list(img)
        # Text over a picture (a caption on a button) leaves the picture.
        marks[:] = [m for m in marks if m[1] != "text" or not _overlaps(m[0], box)]
        if text.strip():
            marks.append((box, "text", text))

    def blitted(self, img, box, src, srcpos):
        marks = self._list(img)
        marks[:] = [m for m in marks if not _overlaps(m[0], box)]
        if src is None or src is img:
            return
        sl, st = srcpos
        sbox = (sl, st, sl + box[2] - box[0], st + box[3] - box[1])
        dx, dy = box[0] - sl, box[1] - st
        for b, kind, value in self._list(src):
            # A mark the copy cuts (the window's edge clips a button by a pixel) comes along
            # cut; text must come whole.
            if _inside(b, sbox) or (kind == "picture" and _overlaps(b, sbox)):
                b = (max(b[0], sbox[0]), max(b[1], sbox[1]), min(b[2], sbox[2]), min(b[3], sbox[3]))
                marks.append(((b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy), kind, value))
        if button_sized(src.size) and button_sized((box[2] - box[0], box[3] - box[1])):
            marks.append((box, "picture", src.size))

    def on(self, img, kind=None):
        entry = self.by_image.get(id(img))
        if entry is None or entry[0] is not img:
            return []
        return [m for m in entry[1] if kind is None or m[1] == kind]


def button_sized(size):
    """A bitmap the size of a button or icon: from 8 x 8 up to 160 x 120 pixels."""
    w, h = size
    return 8 <= w <= 160 and 8 <= h <= 120


NEXT_TEXT = re.compile(r"^\s*(next(\s+page)?|continue|forward|>|>>|\u2192)\s*(>|>>|\u00bb)?\s*$", re.I)


def _centre(b):
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def next_text(wine):
    """The centre of the text on the screen that reads like a Next button ("Next", "Continue",
    ">>"), the lowest, then rightmost one; or None."""
    watch = getattr(wine, "draw_watch", None)
    g = getattr(wine, "gdi", None)
    if watch is None or g is None:
        return None
    hits = [b for b, _kind, text in watch.on(g.screen, "text") if NEXT_TEXT.match(text)]
    if not hits:
        return None
    return _centre(max(hits, key=lambda b: (b[3], b[2])))


def pictures(wine):
    """The centres of the button-sized pictures on the screen, bottom-right first: where a
    course's Next button usually is."""
    watch = getattr(wine, "draw_watch", None)
    g = getattr(wine, "gdi", None)
    if watch is None or g is None:
        return []
    spots = []
    for b, _kind, _size in watch.on(g.screen, "picture"):
        c = _centre(b)
        if c not in spots:
            spots.append(c)
    return sorted(spots, key=lambda c: (-(c[0] + c[1]), -c[0]))


def window_centre(wine):
    """The centre of the active window's client area on the screen (a title page that goes on
    with a click anywhere), or None."""
    from tbpipeline_neww.user_wnd import screen_origin, wm
    m = wm(wine)
    w = m.get(m.active) if m.active else None
    if w is None:
        return None
    x, y = screen_origin(wine, w.hwnd)
    cx, cy = w.client[2] - w.client[0], w.client[3] - w.client[1]
    if cx <= 0 or cy <= 0:
        return None
    return x + cx // 2, y + cy // 2


class Walk:
    """The page walk: on each idle, one way of going to the next page. A way that left the
    screen as it was gives way to the next one: Go > Next as a WM_COMMAND, a click on a Next
    text, a click on a button picture, a click in the middle of the window (a title page),
    Ctrl+Right. Pictures are tried one after another,
    bottom-right first, and the one that turned a page is tried first after that. When every
    way in a row left the screen unchanged, the walk is stuck and ends. log holds one letter
    per step, upper case when the screen changed after it."""

    WAYS = ("menu", "text", "picture", "centre", "key")
    LETTER = {"menu": "m", "key": "k", "text": "t", "picture": "p", "centre": "c"}
    PROBES = 8          # pictures tried on one screen before giving up on them

    def __init__(self, pages, find_menu=None, find_text=None, post=None, find_pictures=None, find_centre=None):
        self.pages = pages
        self.find_menu = find_menu or next_command
        self.find_text = find_text or next_text
        self.find_pictures = find_pictures or pictures
        self.find_centre = find_centre or window_centre
        self.post = post or _post_command
        self.way, self.unchanged, self.steps = 0, 0, 0
        self.before = None
        self.log = []
        self.screens = []
        self.stuck = False
        self.last_way = self.last_spot = self.known = None
        self.failed = {}
        self.visited = set()
        self.opened_at = None       # the trace length at the first idle: the book is open
        self.clicked = []

    def look(self, wine):
        h = screen_hash(wine)
        if h is not None and (not self.screens or self.screens[-1] != h):
            self.screens.append(h)
        return h

    def _rotate(self):
        self.unchanged += 1
        self.way = (self.way + 1) % len(self.WAYS)

    def __call__(self, wine):
        now = self.look(wine)
        new = now not in self.visited
        self.visited.add(now)
        if self.opened_at is None:
            self.opened_at = len(getattr(wine, "trace", []))
        if self.log:
            # A page turned when the screen is one the walk has not seen: going back to a
            # page already seen (a Back button) is no progress.
            if new:
                self.log[-1] = self.log[-1].upper()
                self.unchanged = 0
                if self.last_way == "picture":
                    self.known = self.last_spot
                elif self.last_way == "centre":
                    # Past a title page: look for buttons first, then click through again.
                    self.way = self.WAYS.index("picture")
            elif self.last_way == "picture":
                self.failed.setdefault(self.before, set()).add(self.last_spot)
                if self.known == self.last_spot:
                    self.known = None
                if self._picture(wine, now) is None:
                    self._rotate()
            else:
                self._rotate()
        if self.steps >= self.pages:
            return None
        tried = 0
        while tried < len(self.WAYS) and self.unchanged < len(self.WAYS):
            way = self.WAYS[self.way]
            script = self._try(wine, way, now)
            if script is not None:
                self.steps += 1
                self.before = now
                self.last_way = way
                self.log.append(self.LETTER[way])
                return script
            # Not there to try: counts as a way that did not move the page.
            self._rotate()
            tried += 1
        self.stuck = True
        return None

    def _picture(self, wine, screen):
        failed = self.failed.get(screen, set())
        if len(failed) >= self.PROBES:
            return None
        spots = [c for c in self.find_pictures(wine) if c not in failed]
        if self.known in spots:
            return self.known
        return spots[0] if spots else None

    def _try(self, wine, way, screen):
        x = 320 + self.steps + 1
        if way == "menu":
            target = self.find_menu(wine)
            if target is None:
                return None
            self.post(wine, target)
            return f"wait 4000; move {x},240"
        if way == "key":
            return NEXT.format(x=x)
        if way == "text":
            spot = self.find_text(wine)
        elif way == "picture":
            spot = self._picture(wine, screen)
        else:
            spot = self.find_centre(wine)
        if spot is None:
            return None
        self.last_spot = spot
        if spot not in self.clicked:
            self.clicked.append(spot)
        return f"click {spot[0]},{spot[1]}; wait 4000; move {x},240"

    def summary(self):
        letters = "".join(self.log).lower()
        return {"walk": "".join(self.log), "menu_next": letters.count("m"), "keys": letters.count("k"),
                "text_clicks": letters.count("t"), "picture_clicks": letters.count("p"),
                "centre_clicks": letters.count("c"),
                "moved": sum(c.isupper() for c in self.log), "stuck": self.stuck,
                "screens": len(set(self.screens)), "clicked": [list(c) for c in self.clicked[:6]]}


def _post_command(wine, target):
    from tbpipeline_neww.user_wnd import wm
    m = wm(wine)
    m.queue_of(m.task_of(target[0])).queue.append((target[0], WM_COMMAND, target[1], 0))


def run_one(root, book, pages, call_limit):
    from tbpipeline_neww import machine
    host = machine.Machine(root, book, input_script=FIRST, idle_stop=True)
    walk = Walk(pages)
    host.box.wine.draw_watch = Marks()
    first = {}

    def on_idle(wine):
        if not first:
            first["titles"] = titles(wine)
        return walk(wine)
    host.box.wine.on_idle = on_idle
    host.call_limit = call_limit
    host.timeout_us = max(host.timeout_us, call_limit * 1000)
    host.run(limit=call_limit * 1000)
    wine = host.box.wine
    walk.look(wine)
    trace = wine.trace
    boxes = [t for t in trace if t.startswith("USER.1 MessageBox")]
    defaults = sorted({t.split(" (default")[0] for t in trace if "(default" in t})
    stop = str(host.stop)
    opened_at = walk.opened_at if walk.opened_at is not None else len(trace)
    open_boxes = [t for t in trace[:opened_at] if t.startswith("USER.1 MessageBox")]
    return {"stop": stop, "titles": titles(wine), "cause": cause_of(stop), "calls": host.calls,
            **walk.summary(), "open_titles": first.get("titles", titles(wine)),
            "open_messagebox_count": len(open_boxes),
            "messageboxes": boxes[:3], "messagebox_count": len(boxes),
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
