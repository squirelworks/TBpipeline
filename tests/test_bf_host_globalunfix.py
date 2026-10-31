"""KERNEL.198 GlobalUnfix is answered and returns nothing.

Wine's GlobalUnfix16 (krnl386.exe16/global.c) is a void function that only
lowers the block's lock count. This host keeps no lock counts, so the call
changes nothing and AX keeps its value. (DX carries the ordinal into the
host's thunk, so it is not checked.) The spec line is `198 pascal -ret16 GlobalUnfix(word)`, so
it pops 2. TB80RTM's helper at 0x0da8:0x050a calls it once; it fell through
to AX = 1.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call


class GlobalUnfix(unittest.TestCase):
    def test_answered_and_void(self):
        host = fake_host()
        host.uc.reg_write(UC_X86_REG_AX, 0x5A5A)
        far_call(host, "KERNEL", 198, [0x0ff0], pop=2)
        self.assertEqual(host.ax1, [], "GlobalUnfix fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0x5A5A)


if __name__ == "__main__":
    unittest.main()
