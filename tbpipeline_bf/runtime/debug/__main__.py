"""python3 -m tbpipeline_bf.runtime.debug --dbgrender --b ~/TBK/bin --c book.tbk"""

import sys

from tbpipeline_bf.cli import new_debug_dir, resolve
from tbpipeline_bf.runtime.debug import run


def main():
    _bin, book, dbgrender, theme, render, _open, _page = resolve(sys.argv[1:])
    if not book.is_file():
        print(f"not a book: {book}", file=sys.stderr)
        print("usage: python3 -m tbpipeline_bf.runtime.debug --dbgrender --b ~/TBK/bin --c book.tbk", file=sys.stderr)
        return 2
    out = new_debug_dir()
    lines, prompt = run(str(book), out, dbgrender=dbgrender, theme=theme, render=render)
    print("\n".join(lines))
    print(f"\n{prompt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
