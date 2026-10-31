"""KERNEL32.GetCommandLineA, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2) runs a 16-bit program in winevdm. kernelbase's
create_vdm_process (dlls/kernelbase/process.c:378) gives that process the
command line `winevdm --app-name "<image path>" <command line>`, with
winevdm at C:\\windows\\syswow64\\winevdm.exe on a 64-bit Wine.
GetCommandLineA (process.c:1346) returns the ANSI copy, the same pointer
on every call. The task's image is EXE_PATH, as KERNEL.49 answers, and its
command line adds the book, as the PSP tail carries it.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetCommandLineA twice and keeps both results.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

FIRST, SECOND = BASE + 0x2F04, BASE + 0x2F08


class GetCommandLineA(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_winevdms_command_line_around_the_task(self):
        entry = [call_import(0), bytes([0xA3]) + struct.pack("<I", FIRST),
                 call_import(0), bytes([0xA3]) + struct.pack("<I", SECOND)] + ATTACH
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", "GetCommandLineA")]))
        h = host()
        hinst, _ = run(h)
        self.assertFalse(h.fault.startswith("win32"), h.fault)
        self.assertEqual(hinst, BASE)
        first, second = struct.unpack("<II", bytes(h.uc.mem_read(FIRST, 8)))
        self.assertNotEqual(first, 0)
        self.assertEqual(first, second, "the same pointer every call")
        text = bytes(h.uc.mem_read(first, 200)).split(b"\0", 1)[0].decode("latin1")
        self.assertEqual(text, 'C:\\windows\\syswow64\\winevdm.exe --app-name "C:\\TOOLBOOK\\TB80RTM.EXE" '
                               "C:\\TOOLBOOK\\TB80RTM.EXE fixture.tbk")


if __name__ == "__main__":
    unittest.main()
