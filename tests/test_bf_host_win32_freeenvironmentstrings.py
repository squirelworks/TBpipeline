"""KERNEL32.FreeEnvironmentStringsA/W, called from a 32-bit DLL, answer as Wine does.

Wine (commit 2528aff2): kernelbase.spec:403 exports FreeEnvironmentStringsA
as FreeEnvironmentStringsW, which is HeapFree(GetProcessHeap(), 0, ptr)
(dlls/kernelbase/process.c:1702). RtlFreeHeap (dlls/ntdll/heap.c:2078)
returns TRUE for NULL, and FALSE with ERROR_INVALID_PARAMETER (87) for a
pointer that is no block of the heap.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain frees
either the block GetEnvironmentStrings returned or a given pointer, and
keeps the results.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from unicorn import UcError

from tbpipeline_bf.nedllhost.win32 import TEB
from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

RESULT, BLOCK = BASE + 0x2F04, BASE + 0x2F08
KEEP = lambda at: bytes([0xA3]) + struct.pack("<I", at)


class FreeEnvironmentStrings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def run_entry(self, code, free="FreeEnvironmentStringsA", get="GetEnvironmentStrings"):
        imports = [("KERNEL32.dll", get), ("KERNEL32.dll", free)]
        write(self.dir.name, "TESTW32.DLL", build([(None, code + ATTACH)], imports=imports))
        self.h = host()
        self.hinst, _ = run(self.h)
        return struct.unpack("<II", bytes(self.h.uc.mem_read(RESULT, 8)))

    def free_own(self, **names):
        # block = Get...(); keep it; Free...(block); keep the result
        return self.run_entry([call_import(0), KEEP(BLOCK), bytes([0x50]), call_import(1), KEEP(RESULT)], **names)

    def free_value(self, value):
        return self.run_entry([bytes([0x68]) + struct.pack("<I", value), call_import(1), KEEP(RESULT)])

    def test_freeing_the_environment_block(self):
        result, block = self.free_own()
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(self.hinst, BASE, "FreeEnvironmentStringsA pops 4")
        self.assertEqual(result, 1)
        self.assertNotIn(block, self.h.regions32)
        with self.assertRaises(UcError):
            self.h.uc.mem_read(block, 1)

    def test_the_w_names(self):
        result, _ = self.free_own(free="FreeEnvironmentStringsW", get="GetEnvironmentStringsW")
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(result, 1)

    def test_null_is_true(self):
        result, _ = self.free_value(0)
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(result, 1)

    def test_a_pointer_that_is_no_block_is_invalid_parameter(self):
        result, _ = self.free_value(BASE + 0x2E00)
        self.assertEqual(result, 0)
        self.assertEqual(struct.unpack("<I", bytes(self.h.uc.mem_read(TEB + 0x34, 4)))[0], 87)


if __name__ == "__main__":
    unittest.main()
