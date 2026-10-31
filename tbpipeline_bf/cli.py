"""The launcher arguments and the debug folder.

Kept out of run.py so the reader can read --b and --c without importing
the host. run.py imports unicorn and pass 06. This file does not.
"""

from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def new_debug_dir():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = HERE / "_debug" / f"db-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve(argv):
    bin_dir = HERE / "bin"
    course = None
    theme = "default"
    render = "new"
    page = None
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
        if arg == "--theme" and i + 1 < len(argv):
            theme = argv[i + 1]
            i += 2
            continue
        if arg == "--render" and i + 1 < len(argv):
            render = argv[i + 1]
            i += 2
            continue
        if arg == "--page" and i + 1 < len(argv):
            page = argv[i + 1]
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
    return bin_dir, book, "--dbgrender" in argv, theme, render, "--open" in argv, page
