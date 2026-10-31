"""KERNEL.112 GlobalUnWire is answered with TRUE and pops 2.

TBFILE32.DLL's CopyFile32 and getShortFileName32, which tb80axf.sbk
links, unwire their buffers with it after GlobalWire (KERNEL.111).

Wine's GlobalUnWire16 (krnl386.exe16/global.c) is !GlobalUnlock16(handle).
GlobalUnlock16 returns the lock count left after the decrement, or FALSE
for a handle that is not a block, so UnWire is TRUE in both cases. This
host keeps no lock counts (its GlobalUnlock answers 0), so it is always
TRUE. The spec line is `112 pascal -ret16 GlobalUnWire(word)
GlobalUnWire16`. The call fell through to AX = 1, the same number but
listed as unanswered.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call

GMEM_MOVEABLE = 0x0002


class GlobalUnWire(unittest.TestCase):
    def test_after_wire(self):
        host = fake_host()
        far_call(host, "KERNEL", 15, [0x100, 0, GMEM_MOVEABLE], pop=6)
        handle = host.uc.reg_read(UC_X86_REG_AX)
        far_call(host, "KERNEL", 18, [handle], pop=2)
        far_call(host, "KERNEL", 112, [handle], pop=2)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4, "2 popped")
        self.assertEqual(host.ax1, [], "GlobalUnWire fell through to AX = 1")

    def test_not_a_block(self):
        host = fake_host()
        far_call(host, "KERNEL", 112, [0x7FF8], pop=2)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1)
        self.assertEqual(host.ax1, [], "GlobalUnWire fell through to AX = 1")


if __name__ == "__main__":
    unittest.main()
