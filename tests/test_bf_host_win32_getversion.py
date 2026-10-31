"""KERNEL32.GetVersion, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2) reports Windows 6.2 build 9200, NT platform, to an
application with no manifest: kernelbase's init_current_version
(dlls/kernelbase/version.c:197) picks windows8_version_info (version.c:130).
GetVersion (version.c:1462) packs it as
MAKELONG(MAKEWORD(major, minor), (platform ^ 2) << 14), then ORs in
LOWORD(build) << 16 on NT: 0x23F00206.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
GetVersion and keeps EAX for the test.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

KEPT = BASE + 0x2F04
# mov [KEPT], eax
KEEP = [bytes([0xA3]) + struct.pack("<I", KEPT)]


class GetVersion(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_returns_wines_version_for_an_app_without_a_manifest(self):
        entry = [call_import(0)] + KEEP + ATTACH
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", "GetVersion")]))
        h = host()
        hinst, _ = run(h)
        self.assertFalse(h.fault.startswith("win32"), h.fault)
        self.assertEqual(hinst, BASE)
        version = struct.unpack("<I", bytes(h.uc.mem_read(KEPT, 4)))[0]
        self.assertEqual(version, 0x23F00206)
        self.assertEqual(version & 0xFF, 6, "major")
        self.assertEqual((version >> 8) & 0xFF, 2, "minor")
        self.assertEqual(version >> 31, 0, "the top bit is clear on NT")
        self.assertEqual(version >> 16, 9200, "build")


if __name__ == "__main__":
    unittest.main()
