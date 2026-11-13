"""The book sweep's stop summary (#227): what a stop line names, so findings group by cause."""

import unittest

from tbpipeline_neww.sweep import cause_of


class CauseOf(unittest.TestCase):
    def test_a_call_by_name(self):
        self.assertEqual(cause_of("USER.175 LoadBitmap(0, 32738): a user32 OBM_ bitmap"), "USER.175 LoadBitmap")
        self.assertEqual(cause_of("KERNEL32!GetShortPathNameA: @ stdcall GetShortPathNameA(str ptr long)"),
                         "KERNEL32!GetShortPathNameA")

    def test_idle_and_exit(self):
        self.assertEqual(cause_of("idle: input script done, TB80RTM waiting in PeekMessage"), "idle")
        self.assertEqual(cause_of("dos exit 0x0"), "exit")

    def test_other_lines_drop_their_numbers(self):
        self.assertEqual(cause_of("WM_NCHITTEST at (5, 5) on the frame of 0x28"), "WM_NCHITTEST at (5, 5) on the frame of N")


if __name__ == "__main__":
    unittest.main()
