"""Item 33: OLE CreateDispTypeInfo returns HRESULT 0 in DX:AX, not S_FALSE.

AX = 1 is S_FALSE. The caller then dropped the object and called
Release on a null pointer. The out-pointer must get a dummy IUnknown.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call


class OleHresult(unittest.TestCase):
    def call(self, ordinal, pop):
        host = fake_host()
        host.arena.write(host.data, 0x300, b"\x00" * 4)
        # Out-pointer is the last push: words[0] = offset, words[1] = selector.
        far_call(host, "OLE2DISP", ordinal, [0x300, host.data, 0, 0, 0, 0], pop=pop)
        return host

    def test_create_disp_type_info(self):
        host = self.call(31, 12)
        self.assertEqual((host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)), (0, 0))
        off, sel = struct.unpack("<HH", host.arena.read(host.data, 0x300, 4))
        self.assertIn(sel, host.arena.segs, "the out-pointer did not get an object")
        self.assertEqual(host.ax1, [])

    def test_create_std_dispatch(self):
        host = self.call(32, 16)
        self.assertEqual((host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)), (0, 0))


if __name__ == "__main__":
    unittest.main()
