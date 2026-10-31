"""KERNEL32.GetProcAddress, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2): kernelbase get_proc_address
(dlls/kernelbase/loader.c:66) treats lpProcName as a name when its high
word is not 0 and as an ordinal otherwise, and asks ntdll's
LdrGetProcedureAddress (dlls/ntdll/loader.c:2066). A missing export is
NULL with ERROR_PROC_NOT_FOUND (127); a handle that is no loaded module is
NULL with ERROR_MOD_NOT_FOUND (126). A NULL handle means the process
image, which a 16-bit process doesn't have here, so it stops the run.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetProcAddress and keeps EAX.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tbpipeline_bf.nedllhost.win32 import STUBS32, SYSTEM_HANDLES, TEB
from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

KEPT = BASE + 0x2F04
TEXT = BASE + 0x2E00
NOP = [bytes([0xC3])]


def entry(module, proc):
    """DllMain: GetProcAddress(module, proc), keep EAX, then ATTACH. A str proc is written at TEXT."""
    code = b""
    if isinstance(proc, str):
        for i, ch in enumerate(proc.encode() + b"\0"):
            code += bytes([0xC6, 0x05]) + struct.pack("<I", TEXT + i) + bytes([ch])
        proc = TEXT
    code += bytes([0x68]) + struct.pack("<I", proc) + bytes([0x68]) + struct.pack("<I", module)
    return [code, call_import(0), bytes([0xA3]) + struct.pack("<I", KEPT)] + ATTACH


class GetProcAddress(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def call(self, module, proc):
        dll = build([(None, entry(module, proc)), ("Nop", NOP)], imports=[("KERNEL32.dll", "GetProcAddress")])
        write(self.dir.name, "TESTW32.DLL", dll)
        self.h = host()
        hinst, _ = run(self.h)
        self.hinst = hinst
        return struct.unpack("<I", bytes(self.h.uc.mem_read(KEPT, 4)))[0]

    def nop(self):
        return BASE + self.h.pe32[next(iter(self.h.pe32))]["names"]["Nop"]

    def last_error(self):
        return struct.unpack("<I", bytes(self.h.uc.mem_read(TEB + 0x34, 4)))[0]

    def test_an_export_by_name(self):
        got = self.call(BASE, "Nop")
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(self.hinst, BASE, "GetProcAddress pops 8")
        self.assertEqual(got, self.nop())

    def test_an_export_by_ordinal(self):
        got = self.call(BASE, 1)
        self.assertEqual(got, self.nop())

    def test_a_missing_export_is_null_with_proc_not_found(self):
        got = self.call(BASE, "Absent")
        self.assertEqual(got, 0)
        self.assertEqual(self.last_error(), 127)

    def test_an_unknown_handle_is_null_with_mod_not_found(self):
        got = self.call(0x50000000, "Nop")
        self.assertEqual(got, 0)
        self.assertEqual(self.last_error(), 126)

    def test_a_system_dll_export_is_a_stub(self):
        got = self.call(SYSTEM_HANDLES["KERNEL32"], "GetVersion")
        self.assertGreaterEqual(got, STUBS32)
        self.assertEqual(self.h.api32[(got - STUBS32) // 8], ("KERNEL32", "GetVersion"))

    def test_null_handle_stops_the_run(self):
        self.call(0, "Nop")
        self.assertEqual(self.h.fault, "win32 KERNEL32.GetProcAddress NULL hModule: the process has no 32-bit image")


if __name__ == "__main__":
    unittest.main()
