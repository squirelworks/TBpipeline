"""A full newl run on the real TB80RTM ends on a named stop. Needs TBK_BIN.

The committed result of a run is the stop line in the pull request, not a log.
"""

import os
import unittest

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None

try:
    from tests.binpath import bin_or_skip
except ImportError:
    bin_or_skip = None

NAMED = ("packed ", "fault at ", "gap ", "scan ", "OpenFile ", "dos exit ", "hlt at ", "instruction cap ", "time cap ")


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run TB80RTM")
class FullRun(unittest.TestCase):
    def test_stop_is_named(self):
        if bin_or_skip is None:
            self.skipTest("tests/binpath.py is not on this branch yet, so TBK_BIN cannot be read")
        root = bin_or_skip()
        from tbpipeline_newl.cpu import Cpu

        host = Cpu(root, book=os.environ.get("TBK_BOOK") or None)
        host.run()
        print(f"\nnewl stop: {host.stop}")
        self.assertTrue(host.stop.startswith(NAMED), f"anonymous stop: {host.stop}")


if __name__ == "__main__":
    unittest.main()
