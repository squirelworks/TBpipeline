"""KERNEL.516 GetVDMPointer32W turns a 16:16 pointer into a linear one.

Wine's GetVDMPointer32W16 (dlls/krnl386.exe16/thunk.c:2486) returns
K32WOWGetVDMPointer(vp, 0, fMode). With fMode set (protected mode) that
is the selector's descriptor base plus the offset. With fMode 0 (real
mode) it is seg * 16 + off. The spec line is
`516 pascal GetVDMPointer32W(segptr word) GetVDMPointer32W16`, so it
pops 6. A 32-bit DLL reads the 16-bit side's buffers through it.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, far_call, fake_host


def vdm_pointer(host, sel, off, mode):
    # Pascal: vp is pushed first, so fMode is word 0 and vp is words 1-2.
    far_call(host, "KERNEL", 516, [mode, off, sel], pop=6)
    return host.uc.reg_read(UC_X86_REG_AX) | (host.uc.reg_read(UC_X86_REG_DX) << 16)


class GetVDMPointer32W(unittest.TestCase):
    def test_protected_mode_is_base_plus_offset(self):
        host = fake_host()
        base = host.arena.segs[host.data]["base"]
        self.assertEqual(vdm_pointer(host, host.data, 0x1234, 1), base + 0x1234)
        self.assertEqual(host.ax1, [], "GetVDMPointer32W fell through to AX = 1")

    def test_real_mode_is_segment_times_sixteen(self):
        host = fake_host()
        self.assertEqual(vdm_pointer(host, 0xB800, 0x0010, 0), 0xB8010)

    def test_an_empty_descriptor_has_base_zero(self):
        host = fake_host()
        self.assertEqual(vdm_pointer(host, 0x7FF8, 0x20, 1), 0x20)

    def test_pops_six(self):
        host = fake_host()
        vdm_pointer(host, host.data, 0, 1)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4, "the return address is not past the 6 bytes")


if __name__ == "__main__":
    unittest.main()
