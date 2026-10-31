"""Item 21: every far call that still gets AX = 1 is a line in 02_launch.txt."""

import re
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call
from tbpipeline_bf.nehost.pass04 import ax1_line
from tbpipeline_bf import run

LINE = re.compile(r"^ax=1 (\S+)\.(\d+) from 0x([0-9a-f]{4}):0x([0-9a-f]{4}) stack( [0-9a-f]{4}){4}$")


class Ax1Log(unittest.TestCase):
    def test_line_format(self):
        line = ax1_line("USER", 266, [1, 0x20, 0xBEEF, 0], 0x40, 0x105)
        self.assertEqual(line, "ax=1 USER.266 from 0x0040:0x0105 stack 0001 0020 beef 0000")
        self.assertRegex(line, LINE)

    def test_fake_call_is_logged(self):
        host = fake_host()
        far_call(host, "USER", 300, [0x1111, 0x2222, 0x3333, 0x4444, 0x5555])
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1)
        self.assertEqual(len(host.ax1), 1)
        match = LINE.match(host.ax1[0])
        self.assertIsNotNone(match, host.ax1[0])
        self.assertEqual(match.group(1), "USER")
        self.assertEqual(match.group(2), "300")
        self.assertTrue(host.ax1[0].endswith("stack 1111 2222 3333 4444"))

    def test_unnamed_site_still_logged(self):
        host = fake_host()
        far_call(host, None, 77, [7])
        self.assertTrue(host.ax1[0].startswith("ax=1 ?.77 "), host.ax1[0])

    def test_answered_call_is_not_logged(self):
        # GetWinFlags has a real answer. It is not an AX = 1 call.
        host = fake_host()
        far_call(host, "KERNEL", 132, [])
        self.assertEqual(host.ax1, [])

    def test_launch_note_carries_every_line(self):
        host = fake_host()
        far_call(host, "USER", 300, [1, 2, 3, 4])
        far_call(host, "GDI", 301, [5, 6, 7, 8])
        lines = run.launch_ax1(host)
        self.assertEqual(len(lines), 2)
        self.assertIn("GDI.301", lines[1])


if __name__ == "__main__":
    unittest.main()
