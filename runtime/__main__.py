"""python3 -m tbpipeline.runtime [--b bin] [--c book.tbk]"""

import sys
from pathlib import Path

from tbpipeline.runtime.play import render
from tbpipeline.runtime.tbk import load
from tbpipeline.run import resolve


def main():
    bin_dir, book = resolve(sys.argv[1:])
    if not book.is_file():
        print(f"not a book: {book}", file=sys.stderr)
        print("usage: python3 -m tbpipeline.runtime --b ~/TBK/bin --c book.tbk", file=sys.stderr)
        return 2
    html = render(load(str(book)))
    out = Path.cwd() / "render.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} from {book}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
