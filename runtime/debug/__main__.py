"""python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c book.tbk"""

import sys
from pathlib import Path

from tbpipeline.run import resolve
from tbpipeline.runtime.debug import run


def main():
    _bin, book, debug = resolve(sys.argv[1:])
    if not book.is_file():
        print(f"not a book: {book}", file=sys.stderr)
        print("usage: python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c book.tbk", file=sys.stderr)
        return 2
    out = Path(__file__).resolve().parents[2] / "_debug"
    lines, prompt = run(str(book), out, debug=debug or True, stage2_failed=False)
    print("\n".join(lines))
    print(f"\n{prompt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
