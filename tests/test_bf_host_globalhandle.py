"""Item 27: KERNEL.21 GlobalHandle returns the handle in AX and the selector in DX.

TB80UTL's heap maker (segment 9, 0x0000) does GlobalAlloc, then
GlobalHandle, and keeps DX as the heap's selector. AX = 1 / DX = 0 gave
TB80BAS a heap selector of 0, its LocalAlloc ran with DS = 0, and the
runtime said "Not enough local memory."

In this host a global handle and its selector are the same value.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call

GMEM_MOVEABLE = 0x0002


class GlobalHandle(unittest.TestCase):
    def test_handle_and_selector(self):
        host = fake_host()
        far_call(host, "KERNEL", 15, [0x810, 0, GMEM_MOVEABLE], pop=6)
        handle = host.uc.reg_read(UC_X86_REG_AX)
        self.assertTrue(handle)
        far_call(host, "KERNEL", 21, [handle], pop=2)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), handle)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_DX), handle)
        self.assertIn(handle, host.arena.segs)
        self.assertEqual(host.ax1, [], "GlobalHandle fell through to AX = 1")

    def test_unknown_is_zero(self):
        host = fake_host()
        far_call(host, "KERNEL", 21, [0x7FF8], pop=2)
        self.assertEqual((host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)), (0, 0))


if __name__ == "__main__":
    unittest.main()
