"""Item 67. A run ends on a named stop, and the cap is named when it is the end.

The loop test needs no binary. The full run needs TB80RTM.EXE in
TBK_BIN and skips without it.
"""

import re
import tempfile
import unittest

from tests import neww_ne

NAMED = re.compile(
    r"^(unimplemented \w+\.\d+|KERNEL\.\d+ |USER\.\d+ |contract disagrees |not linked: |dos exit |"
    r"instruction cap |\d+ second cap |packed image )"
)


class CapIsNamed(unittest.TestCase):
    def test_loop_ends_on_the_named_cap(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, bytes([0xEB, 0xFE]), [])
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.stop, "instruction cap 5,000 at 0x8:0x0 in TB80RTM segment 1 +0x0 with no gate call pending, after 0 calls")
        self.assertRegex(host.stop, NAMED)


class FullRun(unittest.TestCase):
    def test_tbk_bin_run_ends_on_a_named_stop(self):
        try:
            from tests.binpath import bin_or_skip
        except ImportError:
            raise unittest.SkipTest("tests/binpath.py is not on this branch yet, so there is no TBK_BIN helper")
        root = bin_or_skip("TB80RTM.EXE")
        from tbpipeline_neww.machine import Machine
        host = Machine(root).run()
        print(f"\nneww stop: {host.stop}")
        self.assertRegex(host.stop, NAMED)


if __name__ == "__main__":
    unittest.main()
