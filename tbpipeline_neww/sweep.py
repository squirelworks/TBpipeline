"""Run many ToolBook books through neww and record where each one stops (#227).

    python3 -m tbpipeline_neww.sweep --bin TBK_BIN --out results.jsonl BOOK...

Each book runs in its own process, with a time limit, so one that hangs or crashes does not
take the others with it. The walk is the same for every book: the first page, then up to
--pages presses of Ctrl+Right (ToolBook's next page), each followed by a wait and a mouse
move so the book's timers run. A course with its own Next button may not move on a key
press; the screens count says how far each one got.

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


def run_one(root, book, pages, call_limit):
    from tbpipeline_neww import machine
    host = machine.Machine(root, book, input_script=FIRST, idle_stop=True)
    screens, steps = [], [0]

    def look(wine):
        h = hashlib.sha256(wine.gdi.screen.tobytes()).hexdigest()[:16]
        if not screens or screens[-1] != h:
            screens.append(h)

    def driver(wine):
        look(wine)
        if steps[0] >= pages:
            return None
        steps[0] += 1
        return NEXT.format(x=320 + steps[0])
    host.box.wine.on_idle = driver
    host.call_limit = call_limit
    host.timeout_us = max(host.timeout_us, call_limit * 1000)
    host.run(limit=call_limit * 1000)
    wine = host.box.wine
    look(wine)
    trace = wine.trace
    boxes = [t for t in trace if t.startswith("USER.1 MessageBox")]
    defaults = sorted({t.split(" (default")[0] for t in trace if "(default" in t})
    stop = str(host.stop)
    return {"stop": stop, "titles": titles(wine), "cause": cause_of(stop), "calls": host.calls, "keys": steps[0],
            "screens": len(set(screens)), "messageboxes": boxes[:3], "messagebox_count": len(boxes),
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
                  f"calls {r.get('calls')} | {r.get('stop', '')[:120]}", flush=True)
            if out:
                out.write(line + "\n")
                out.flush()


if __name__ == "__main__":
    main()
