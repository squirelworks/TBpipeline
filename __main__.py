"""python3 -m tbpipeline [--b bin] [--c book.tbk]

--b is the ToolBook directory. Default is bin/ beside this package.
--c is the book. A bare filename is looked up in <bin>/courses/.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for name in ("runtime", "nehost", "nedllhost"):
    if not (HERE / name).is_dir():
        print(f"missing tbpipeline/{name}", file=sys.stderr)
        sys.exit(2)
os.environ.setdefault("TBK_UNPACKED", str(HERE / "bin"))

from tbpipeline.run import main

if __name__ == "__main__":
    sys.exit(main())
