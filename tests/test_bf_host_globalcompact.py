"""KERNEL.25 GlobalCompact reports Wine's largest free block.

Wine's GlobalCompact16 (krnl386.exe16/global.c) is
`return GLOBAL_MAX_ALLOC_SIZE;`, and GLOBAL_MAX_ALLOC_SIZE is 0x00ff0000
(16M - 64K). The spec line is `25 pascal GlobalCompact(long)`, so it pops 4
and returns the DWORD in DX:AX. TB80RTM calls it once, with 0, right after
GetFreeSpace. The AX = 1 default left DX as it was.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call


class GlobalCompact(unittest.TestCase):
    def test_max_alloc_size(self):
        for wanted in ([0, 0], [0x1000, 0], [0xFFFF, 0xFFFF]):
            host = fake_host()
            host.uc.reg_write(UC_X86_REG_DX, 0x1234)
            far_call(host, "KERNEL", 25, wanted, pop=4)
            dx, ax = host.uc.reg_read(UC_X86_REG_DX), host.uc.reg_read(UC_X86_REG_AX)
            self.assertEqual((dx << 16) | ax, 0x00FF0000, wanted)
            self.assertEqual(host.ax1, [], "GlobalCompact fell through to AX = 1")


if __name__ == "__main__":
    unittest.main()
