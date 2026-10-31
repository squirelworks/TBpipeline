"""Item 32: GetSystemMetrics(SM_PENWINDOWS) stays 0.

A nonzero value makes startup call RegisterPenApp through a null pointer.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call

SM_PENWINDOWS = 0x29


class PenWindows(unittest.TestCase):
    def test_pen_windows_is_zero(self):
        host = fake_host()
        far_call(host, "USER", 179, [SM_PENWINDOWS], pop=2)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_DX), 0)
        self.assertEqual(host.ax1, [], "SM_PENWINDOWS fell through to AX = 1")

    def test_the_table_still_answers_other_metrics(self):
        host = fake_host()
        far_call(host, "USER", 179, [0], pop=2)   # SM_CXSCREEN
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 800)


if __name__ == "__main__":
    unittest.main()
