"""Where the unpacked ToolBook binaries live.

`--b` and `TBK_UNPACKED` are the same directory. The default is `bin/`
beside this package. Probes used to point at a sandbox path. That path
is not part of the release.
"""

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def unpacked():
    raw = os.environ.get("TBK_UNPACKED")
    if raw:
        return Path(raw).expanduser()
    return PACKAGE / "bin"
