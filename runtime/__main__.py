"""python3 -m tbpipeline.runtime --dbgrender [--b bin] [--c book.tbk]

The standalone reader is the debug route. It writes _debug/render.html
only when --dbgrender is passed.
"""

import sys

from tbpipeline.runtime.debug.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
