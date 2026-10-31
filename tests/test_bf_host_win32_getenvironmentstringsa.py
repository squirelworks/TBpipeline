"""KERNEL32.GetEnvironmentStrings, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2): kernelbase.spec:530 exports GetEnvironmentStrings as
GetEnvironmentStringsA (dlls/kernelbase/process.c:1535). That converts
get_env_length(Environment) WCHARs with WideCharToMultiByte(CP_ACP) into a
new heap block, a new copy on every call. This host gives the guest no
variables, so the block is one NUL byte. Code page 1252 turns a character
it lacks into '?'.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls the
import twice and keeps both results.
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


class GetEnvironmentStringsA(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def call(self, name="GetEnvironmentStrings"):
        entry = [call_import(0), bytes([0xA3]) + struct.pack("<I", FIRST),
                 call_import(0), bytes([0xA3]) + struct.pack("<I", SECOND)] + ATTACH
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", name)]))
        self.h = host()
        self.hinst, _ = run(self.h)
        return struct.unpack("<II", bytes(self.h.uc.mem_read(FIRST, 8)))

    def test_an_empty_environment_is_one_nul_and_each_call_is_a_new_copy(self):
        first, second = self.call()
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(self.hinst, BASE)
        self.assertNotEqual(first, 0)
        self.assertNotEqual(first, second, "each call returns a new copy")
        self.assertEqual(bytes(self.h.uc.mem_read(first, 1)), b"\0")

    def test_the_a_name_is_the_same_answer(self):
        first, _ = self.call("GetEnvironmentStringsA")
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(bytes(self.h.uc.mem_read(first, 1)), b"\0")

    def test_variables_are_ansi_strings_then_a_nul(self):
        with mock.patch.object(win32, "ENVIRONMENT", ["A=é", "B=一"]):
            first, _ = self.call()
        expect = b"A=\xe9\0B=?\0\0"
        self.assertEqual(bytes(self.h.uc.mem_read(first, len(expect))), expect)


if __name__ == "__main__":
    unittest.main()
