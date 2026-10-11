"""python3 -m tbpipeline [--b bin] [--c book.tbk]

--b is the ToolBook directory. Default is bin/ under the repo root.
--c is the book. A bare filename is looked up in <bin>/courses/.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for name in ("runtime", "nehost", "nedllhost"):
    if not (Path(__file__).resolve().parent / name).is_dir():
        print(f"missing tbpipeline/{name}", file=sys.stderr)
        sys.exit(2)
os.environ.setdefault("TBK_UNPACKED", str(ROOT / "bin"))

from tbpipeline.run import main

if __name__ == "__main__":
    sys.exit(main())
