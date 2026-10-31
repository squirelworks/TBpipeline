"""KERNEL.515 GetProcAddress32W finds an export of a 32-bit DLL.

Wine's GetProcAddress32W16 (dlls/krnl386.exe16/thunk.c:2535) is
GetProcAddress((HMODULE)hModule, lpszProc): the export's address, by
name or by an ordinal in the low word of lpszProc, or 0 when there is
none. The spec line is `515 pascal GetProcAddress32W(long str)
GetProcAddress32W16`, so it pops 8. A Win32 system DLL has no image in
this host, so its export is an import stub that WIN32 answers by name,
and an unanswered one stops the run when it is called.

The DLL is loaded with LoadLibraryEx32W (#144), as TB80W16 does, and is a
tiny original PE built by tests/pe32.py.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_SP

from tbpipeline_bf.nedllhost.win32 import STUBS32
from tests.bf_host_fake import STACK_TOP, far_call
from tests.pe32 import BASE, build, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

PROC = 0x140
ADD = [bytes([0x8B, 0x44, 0x24, 0x04, 0x03, 0x44, 0x24, 0x08, 0xC2, 0x08, 0x00])]
SUB = [bytes([0x8B, 0x44, 0x24, 0x04, 0x2B, 0x44, 0x24, 0x08, 0xC2, 0x08, 0x00])]


def get_proc(h, hmod, name=None, ordinal=None):
    if name is not None:
        h.arena.write(h.data, PROC, name.encode() + b"\x00")
        words = [PROC, h.data]
    else:
        words = [ordinal, 0]
    far_call(h, "KERNEL", 515, words + [hmod & 0xFFFF, hmod >> 16], pop=8)
    return h.uc.reg_read(UC_X86_REG_AX) | (h.uc.reg_read(UC_X86_REG_DX) << 16)


class GetProcAddress32W(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()
        write(self.dir.name, "TESTW32.DLL", build([(None, ATTACH), ("Add", ADD), ("Sub", SUB)]))
        self.h = host()
        hinst, _ = run(self.h)
        self.assertEqual(hinst, BASE)

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_finds_an_export_by_name(self):
        add = get_proc(self.h, BASE, name="Add")
        sub = get_proc(self.h, BASE, name="Sub")
        self.assertEqual(add, BASE + 0x1010)
        self.assertEqual(sub, BASE + 0x1020)
        self.assertEqual(self.h.ax1, [], "GetProcAddress32W fell through to AX = 1")

    def test_finds_an_export_by_ordinal(self):
        # pe32 numbers the named exports from ordinal 1.
        self.assertEqual(get_proc(self.h, BASE, ordinal=2), BASE + 0x1020)

    def test_a_missing_name_is_zero(self):
        self.assertEqual(get_proc(self.h, BASE, name="NoSuchProc"), 0)

    def test_a_module_that_is_not_loaded_is_zero(self):
        self.assertEqual(get_proc(self.h, 0x20000000, name="Add"), 0)

    def test_a_system_dll_export_is_a_stub_named_for_its_call(self):
        stub = get_proc(self.h, 0x7FE00000, name="GetVersion")
        self.assertGreaterEqual(stub, STUBS32)
        self.assertEqual(self.h.api32[(stub - STUBS32) // 8], ("KERNEL32", "GetVersion"))

    def test_pops_eight(self):
        get_proc(self.h, BASE, name="Add")
        self.assertEqual(self.h.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4)


if __name__ == "__main__":
    unittest.main()
