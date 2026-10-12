"""python3 -m tbpipeline_bf.nedllhost [--b bin]"""

import os
import sys

from tbpipeline_bf.binpath import unpacked
from tbpipeline_bf.nedllhost.bind import main as bind_main


def main():
    argv = sys.argv[1:]
    root = None
    i = 0
    while i < len(argv):
        if argv[i] in ("--b", "--bin") and i + 1 < len(argv):
            root = argv[i + 1]
            i += 2
            continue
        if not argv[i].startswith("--") and root is None:
            root = argv[i]
        i += 1
    if root is None:
        root = str(unpacked())
    if not os.path.isdir(root):
        print(f"not a ToolBook directory: {root}", file=sys.stderr)
        print("usage: python3 -m tbpipeline_bf.nedllhost --b ~/TBK/bin", file=sys.stderr)
        return 2
    sys.argv = [sys.argv[0], root]
    return bind_main()


if __name__ == "__main__":
    sys.exit(main())
