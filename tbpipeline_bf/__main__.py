"""python3 -m tbpipeline_bf [--b bin] [--c book.tbk]
python3 -m tbpipeline_bf --open book.tbk [--page P20000]

--b is the ToolBook directory. Default is bin/ beside this package.
--c is the book. A bare filename is looked up in <bin>/courses/.
--open reads the book without the 16-bit host.
"""

import os
import sys
from pathlib import Path

if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
    print(__doc__.strip())
    sys.exit(0)

HERE = Path(__file__).resolve().parent
for name in ("runtime", "nehost", "nedllhost"):
    if not (HERE / name).is_dir():
        print(f"missing tbpipeline_bf/{name}", file=sys.stderr)
        sys.exit(2)
os.environ.setdefault("TBK_UNPACKED", str(HERE / "bin"))

from tbpipeline_bf.run import main

if __name__ == "__main__":
    sys.exit(main())
