#!/usr/bin/env python3
"""Pipeline rewrite. One command, four stages, a USER stub.

  python3 artifacts/pipeline/run.py [book.tbk]

Startup is the SoftICE load order. Launch is the TB80RUN handoff to
TB80NET. The 16-bit side is the Unicorn host with a USER stub:
ordinal 266 is SetMessageQueue and returns 1. Open, process, and
render then read the book the engine never reached.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("TBK_UNPACKED", str(ROOT / "bin"))

from .runtime import debug as reader_debug
from .nehost.loadseq import ORDER, FILES
import tbpipeline.nedllhost.pass06 as pass06
pass06.UNPACKED = os.environ.get("TBK_UNPACKED", str(ROOT / "bin"))
from unicorn.x86_const import UC_X86_REG_AX
from .nedllhost.pass06 import Pass06

OUT = Path(__file__).resolve().parent
DEBUG = ROOT / "_debug"

# Only ordinals we have pinned to USER. 1 and 5 are KERNEL at startup.
USER = {
    266: "SetMessageQueue",
}


class Host(Pass06):
    def _on_out(self, uc, port, size, value, user):
        super()._on_out(uc, port, size, value, user)
        if not self.calls:
            return
        ordinal = self.calls[-1]
        if not isinstance(ordinal, int):
            return
        name = USER.get(ordinal)
        if name and (not self.user_hits or self.user_hits[-1] != name):
            self.user_hits.append(name)
            print(f"  user {name}", file=sys.stderr, flush=True)
        if ordinal == 266:
            uc.reg_write(UC_X86_REG_AX, 1)


def note(name, text):
    DEBUG.mkdir(exist_ok=True)
    path = DEBUG / name
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return path


def stages(bin_dir, book_path, debug=False):
    lines = []

    block = ["stage 1 startup", f"  bin {bin_dir}"]
    present, absent = [], []
    for kind, name in ORDER:
        filename = FILES.get(name)
        path = os.path.join(bin_dir, filename) if filename else ""
        (present if path and os.path.isfile(path) else absent).append(name)
    block.append(f"  on disk {len(present)}: {', '.join(present)}")
    block.append(f"  absent {len(absent)}: {', '.join(absent[:8])}")
    note("01_startup.txt", "\n".join(block))
    lines.extend(block)

    block = [
        "stage 2 launch",
        "  TB80RUN WinExec TB80NET.EXE <book>",
        "  TB80NET loads TB80RTM, entry segment 2:0x35A",
    ]
    host = Host(os.path.join(bin_dir, "TB80RTM.EXE"), book_path)
    host.user_hits = []
    cs, ip, raw = host.run()
    block.append(f"  stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}")
    block.append(f"  user {host.user_hits or 'none'}")
    block.append(f"  engine opens {host.opens or 'none'}")
    note("02_launch.txt", "\n".join(block))
    lines.extend(block)
    stage2_failed = not host.opens or bool(host.fault)
    fallback, prompt = reader_debug.run(book_path, DEBUG, debug, stage2_failed)
    lines.extend(fallback)
    print(f"\n{prompt}", file=sys.stderr)
    return lines


def resolve(argv):
    bin_dir = ROOT / "bin"
    course = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--b", "--bin") and i + 1 < len(argv):
            bin_dir = Path(argv[i + 1])
            i += 2
            continue
        if arg in ("--c", "--course") and i + 1 < len(argv):
            course = argv[i + 1]
            i += 2
            continue
        if not arg.startswith("--") and course is None:
            course = arg
        i += 1
    bin_dir = bin_dir.expanduser().resolve()
    if course is None:
        course = "9e954d01.tbk"
    book = Path(course).expanduser()
    if not book.is_file():
        book = bin_dir / "courses" / course
    return bin_dir, book, "--debug" in argv


def main():
    bin_dir, book, debug = resolve(sys.argv[1:])
    if not book.is_file():
        print(f"not a book: {book}", file=sys.stderr)
        print("usage: python3 -m tbpipeline --b ~/TBK/bin --c ~/TBK/bin/courses/9e954d01.tbk", file=sys.stderr)
        print("       python3 -m tbpipeline 9e954d01.tbk", file=sys.stderr)
        return 2
    pass06.UNPACKED = str(bin_dir)
    lines = stages(str(bin_dir), str(book), debug)
    text = "\n".join(lines) + "\n"
    note("RUN.txt", text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
