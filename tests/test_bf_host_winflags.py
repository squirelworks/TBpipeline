"""Item 31: __WINFLAGS stays the constant 0x0C25, never a thunk offset.

The type-5 fixup for KERNEL.178 receives the value, in a DLL reloc and in
an EXE reloc. GetWinFlags through the thunk returns the same word.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tbpipeline_bf.nedllhost import pass06
from tests.bf_host_fake import fake_host, far_call

WINFLAGS = 0x0C25


class WinFlags(unittest.TestCase):
    def test_equate(self):
        self.assertEqual(pass06.EQUATES["KERNEL"][178], WINFLAGS)

    def test_dll_offset_fixup_gets_the_value(self):
        host = fake_host()
        host.dlls = {}
        host.arena.write(host.code, 0x40, b"\xff\xff")
        host._fix_dll("TB80BAS", host.code, 5, 1, 0x40, 1, 178, ["KERNEL"])
        self.assertEqual(struct.unpack("<H", host.arena.read(host.code, 0x40, 2))[0], WINFLAGS)

    def test_exe_offset_fixup_gets_the_value(self):
        host = fake_host()
        host.dlls = {}
        host.modnames = ["KERNEL"]
        host.file = b""
        host.named = []
        host.arena.write(host.code, 0x40, b"\xff\xff")
        host._bind(host.code, 5, 1, 0x40, 1, 178)
        self.assertEqual(struct.unpack("<H", host.arena.read(host.code, 0x40, 2))[0], WINFLAGS)

    def test_getwinflags_call(self):
        host = fake_host()
        far_call(host, "KERNEL", 132, [], pop=0)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), WINFLAGS)


if __name__ == "__main__":
    unittest.main()
