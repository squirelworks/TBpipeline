"""KERNEL32.GetModuleHandleA, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2): kernelbase GetModuleHandleA
(dlls/kernelbase/loader.c:336) goes through GetModuleHandleExW to ntdll's
LdrGetDllHandleEx (dlls/ntdll/loader.c:3539). That adds ".dll" to a name
with no extension (append_dll_ext, loader.c:785) and finds a loaded module
by base name, ignoring case. A module that isn't loaded gives NULL, with
ERROR_MOD_NOT_FOUND (126) as the last error. NULL asks for the process
image, which a 16-bit process doesn't have here, so it stops the run.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetModuleHandleA with a string from its own data and keeps EAX.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tbpipeline_bf.nedllhost.win32 import SYSTEM_HANDLES, TEB
from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

KEPT = BASE + 0x2F04
TEXT = BASE + 0x2E00


def entry(name):
    """DllMain: write name at TEXT, GetModuleHandleA(TEXT), keep EAX, then ATTACH."""
    code = b""
    for i, ch in enumerate(name.encode() + b"\0"):
        code += bytes([0xC6, 0x05]) + struct.pack("<I", TEXT + i) + bytes([ch])     # mov byte [TEXT+i], ch
    if name:
        code += bytes([0x68]) + struct.pack("<I", TEXT)                           # push TEXT
    else:
        code += bytes([0x6A, 0x00])                                                # push 0
    return [code, call_import(0), bytes([0xA3]) + struct.pack("<I", KEPT)] + ATTACH


class GetModuleHandleA(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def call(self, name):
        write(self.dir.name, "TESTW32.DLL", build([(None, entry(name))], imports=[("KERNEL32.dll", "GetModuleHandleA")]))
        h = host()
        hinst, _ = run(h)
        self.h = h
        return hinst, struct.unpack("<I", bytes(h.uc.mem_read(KEPT, 4)))[0]

    def last_error(self):
        return struct.unpack("<I", bytes(self.h.uc.mem_read(TEB + 0x34, 4)))[0]

    def test_a_system_dll_by_name(self):
        hinst, got = self.call("kernel32.dll")
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(hinst, BASE)
        self.assertEqual(got, SYSTEM_HANDLES["KERNEL32"])

    def test_no_extension_gets_dll(self):
        _, got = self.call("Kernel32")
        self.assertEqual(got, SYSTEM_HANDLES["KERNEL32"])

    def test_the_calling_dll_itself(self):
        _, got = self.call("testw32.dll")
        self.assertEqual(got, BASE)

    def test_a_module_not_loaded_is_null_with_mod_not_found(self):
        _, got = self.call("NOSUCH.DLL")
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(got, 0)
        self.assertEqual(self.last_error(), 126)

    def test_null_stops_the_run(self):
        self.call("")
        self.assertEqual(self.h.fault, "win32 KERNEL32.GetModuleHandleA NULL: the process has no 32-bit image")


if __name__ == "__main__":
    unittest.main()
