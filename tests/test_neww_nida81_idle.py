"""Roadmap #201 T2: nida81 with no input script ends on the named idle stop.

Without --input, nida81 draws P0 and then only waits for timers: TB80RTM's PeekMessage loop
takes WM_TIMER and the call limit used to land somewhere inside it (20,001 calls at --cap
20000). With the idle stop that the command line asks for, the run ends by name at the first
point where only a later timer would end the wait. Needs TBK_BIN and TBK_BOOK (nida81.tbk).
"""

import os
import unittest


class Nida81Idle(unittest.TestCase):
    def test_nida81_ends_idle_on_p0_without_an_error_box(self):
        from tests.binpath import bin_or_skip
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        book = os.environ.get("TBK_BOOK")
        if not book:
            raise unittest.SkipTest("TBK_BOOK is not set")
        from tbpipeline_neww.machine import Machine
        host = Machine(str(root), book, idle_stop=True)
        cap = 20000
        host.call_limit = cap
        host.timeout_us = max(host.timeout_us, cap * 1000)
        host.run(limit=cap * 1000)
        trace = host.box.wine.trace
        print(f"\nneww stop: {host.stop} after {host.calls} calls")
        self.assertTrue(host.stop.startswith("idle: no input script, TB80RTM waiting in PeekMessage"),
                        host.stop)
        self.assertLess(host.calls, cap)
        self.assertIn("GDI.33 TextOut 'P0'", trace)
        self.assertEqual(host.box.wine.messageboxes, [])


if __name__ == "__main__":
    unittest.main()
