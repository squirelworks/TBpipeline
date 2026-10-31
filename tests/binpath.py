"""The one place a test asks for a ToolBook binary.

TBK_BIN is the --b directory. When it is unset, or a file the test
needs is not in it, the test skips and says which. There is no default
directory and no archive fallback.
"""

import os
import unittest
from pathlib import Path


def bin_or_skip(*names: str) -> Path:
    names = names or ("TB80RTM.EXE",)
    raw = os.environ.get("TBK_BIN")
    if not raw:
        raise unittest.SkipTest("TBK_BIN is not set, so there is no --b directory to run against.")
    root = Path(raw).expanduser()
    missing = [name for name in names if not (root / name).is_file()]
    if missing:
        raise unittest.SkipTest(f"TBK_BIN is {root}, and it has no {', '.join(missing)}.")
    return root
