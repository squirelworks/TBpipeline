"""KERNEL32.GetStdHandle, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2) GetStdHandle (dlls/kernelbase/process.c:1400)
returns the process parameters' std handle, or INVALID_HANDLE_VALUE with
ERROR_INVALID_HANDLE for any other value. The spec line is
`@ stdcall GetStdHandle(long)`, so the callee pops 4. winevdm is a GUI
program started by start.exe, which only hands a GUI child std handles that
aren't console handles (dlls/ntdll/unix/env.c:2160), so all three are NULL.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetStdHandle for input, output, error and a bad value, keeping each result.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

OUT = BASE + 0x2E00
TEB_LAST_ERROR = 0x0F010000 + 0x34


def ask(value, slot):
    return [bytes([0x68]) + struct.pack("<I", value), call_import(0),
            bytes([0xA3]) + struct.pack("<I", OUT + 4 * slot)]


class GetStdHandle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_null_std_handles_and_a_bad_value(self):
        entry = (ask(0xFFFFFFF6, 0) + ask(0xFFFFFFF5, 1) + ask(0xFFFFFFF4, 2)
                 + ask(5, 3) + ATTACH)
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", "GetStdHandle")]))
        h = host()
        hinst, _ = run(h)
        self.assertFalse(h.fault.startswith("win32"), h.fault)
        self.assertEqual(hinst, BASE, "the callee popped its one argument each time")
        stdin, stdout, stderr, bad = struct.unpack("<4I", bytes(h.uc.mem_read(OUT, 16)))
        self.assertEqual((stdin, stdout, stderr), (0, 0, 0))
        self.assertEqual(bad, 0xFFFFFFFF)
        self.assertEqual(struct.unpack("<I", bytes(h.uc.mem_read(TEB_LAST_ERROR, 4)))[0], 6)


if __name__ == "__main__":
    unittest.main()
