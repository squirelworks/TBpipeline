"""KERNEL32.GetStartupInfoA, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2) GetStartupInfoA (dlls/kernel32/kernel_main.c:82)
copies startup_infoA, which copy_startup_info (kernel_main.c:87) makes once
from the process parameters. `wine PROGRAM.EXE` starts a 16-bit program
through start.exe, which calls CreateProcessW with STARTF_USESHOWWINDOW and
SW_SHOWNORMAL (programs/start/start.c:594). create_process_params
(dlls/kernelbase/process.c:176) makes the title the program's path and
leaves the desktop empty, which still converts to an allocated "". With no
STARTF_USESTDHANDLES the std handles are INVALID_HANDLE_VALUE. The spec
line is `@ stdcall GetStartupInfoA(ptr)`, so the callee pops 4.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetStartupInfoA twice, into two structs.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

FIRST, SECOND = BASE + 0x2E00, BASE + 0x2E80


def push(addr):
    return bytes([0x68]) + struct.pack("<I", addr)


class GetStartupInfoA(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_fills_the_struct_wine_makes_for_a_started_program(self):
        entry = [push(FIRST), call_import(0), push(SECOND), call_import(0)] + ATTACH
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", "GetStartupInfoA")]))
        h = host()
        hinst, _ = run(h)
        self.assertFalse(h.fault.startswith("win32"), h.fault)
        self.assertEqual(hinst, BASE, "the callee popped its one argument")
        first = bytes(h.uc.mem_read(FIRST, 68))
        self.assertEqual(first, bytes(h.uc.mem_read(SECOND, 68)), "the same struct every call")
        (cb, reserved, desktop, title, x, y, xsize, ysize, xcc, ycc, fill, flags, show,
         cbreserved2, reserved2, stdin, stdout, stderr) = struct.unpack("<IIIIIIIIIIIIHHIIII", first)
        self.assertEqual(cb, 68)
        self.assertEqual(reserved, 0)
        self.assertNotEqual(desktop, 0)
        self.assertEqual(bytes(h.uc.mem_read(desktop, 1)), b"\0")
        self.assertEqual(bytes(h.uc.mem_read(title, 64)).split(b"\0", 1)[0], b"C:\\TOOLBOOK\\TB80RTM.EXE")
        self.assertEqual((x, y, xsize, ysize, xcc, ycc, fill), (0,) * 7)
        self.assertEqual((flags, show), (1, 1), "STARTF_USESHOWWINDOW, SW_SHOWNORMAL")
        self.assertEqual((cbreserved2, reserved2), (0, 0))
        self.assertEqual((stdin, stdout, stderr), (0xFFFFFFFF,) * 3)


if __name__ == "__main__":
    unittest.main()
