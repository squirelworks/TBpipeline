"""KERNEL.111 GlobalWire returns the block's 16:16 address, selector in CX too.

TBFILE32.DLL's CopyFile32 (TBFILE32.3) and getShortFileName32
(TBFILE32.22), which tb80axf.sbk links, wire their buffers with it.

Wine's GlobalWire16 (krnl386.exe16/global.c) is WIN16_GlobalLock16: the
block's SEGPTR in DX:AX, and the selector "must be returned in CX as
well". A handle that is not a block gives 0. The spec line is
`111 pascal GlobalWire(word) GlobalWire16`, so it pops 2. The call fell
through to AX = 1, a pointer of 0000:0001.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call

GMEM_MOVEABLE = 0x0002


def regs(host):
    return tuple(host.uc.reg_read(r) for r in (UC_X86_REG_DX, UC_X86_REG_AX, UC_X86_REG_CX))


class GlobalWire(unittest.TestCase):
    def test_block_address(self):
        host = fake_host()
        far_call(host, "KERNEL", 15, [0x100, 0, GMEM_MOVEABLE], pop=6)
        handle = host.uc.reg_read(UC_X86_REG_AX)
        far_call(host, "KERNEL", 111, [handle], pop=2)
        self.assertEqual(regs(host), (handle, 0, handle))
        self.assertEqual(host.ax1, [], "GlobalWire fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4, "2 popped")

    def test_not_a_block(self):
        host = fake_host()
        host.uc.reg_write(UC_X86_REG_CX, 0x1234)
        far_call(host, "KERNEL", 111, [0x7FF8], pop=2)
        self.assertEqual(regs(host), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
