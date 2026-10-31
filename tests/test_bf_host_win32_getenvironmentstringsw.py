"""KERNEL32.GetEnvironmentStringsW, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2): kernelbase GetEnvironmentStringsW
(dlls/kernelbase/process.c:1555) copies get_env_length(Environment) WCHARs
(process.c:1456: each string with its NUL, then one more NUL) into a new
heap block, a new copy on every call. This host gives the guest no
variables, as KERNEL.131 GetDOSEnvironment does, so the block is one NUL
WCHAR.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetEnvironmentStringsW twice and keeps both results.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tbpipeline_bf.nedllhost import win32
from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

FIRST, SECOND = BASE + 0x2F04, BASE + 0x2F08


class GetEnvironmentStringsW(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def call(self):
        entry = [call_import(0), bytes([0xA3]) + struct.pack("<I", FIRST),
                 call_import(0), bytes([0xA3]) + struct.pack("<I", SECOND)] + ATTACH
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", "GetEnvironmentStringsW")]))
        self.h = host()
        self.hinst, _ = run(self.h)
        return struct.unpack("<II", bytes(self.h.uc.mem_read(FIRST, 8)))

    def test_an_empty_environment_is_one_nul_and_each_call_is_a_new_copy(self):
        first, second = self.call()
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(self.hinst, BASE)
        self.assertNotEqual(first, 0)
        self.assertNotEqual(first, second, "each call returns a new copy")
        self.assertEqual(bytes(self.h.uc.mem_read(first, 2)), b"\0\0")

    def test_variables_are_utf16_strings_then_a_nul(self):
        with mock.patch.object(win32, "ENVIRONMENT", ["A=1", "PATH=C:\\"]):
            first, _ = self.call()
        expect = "A=1\0PATH=C:\\\0\0".encode("utf-16-le")
        self.assertEqual(bytes(self.h.uc.mem_read(first, len(expect))), expect)


if __name__ == "__main__":
    unittest.main()
