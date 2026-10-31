"""Item 23: TB80enu. The pass 06 log opens C:\\TOOLBOOK\\TB80enu, no extension.

One original file of that name in a temp TBK_INI directory, and the open
pointed at it. The startup test needs TBK_BIN and records what comes next.
"""

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unicorn.x86_const import UC_X86_REG_AX

from tests.binpath import bin_or_skip
from tests.bf_host_fake import fake_host, far_call

# Original bytes. What the real file holds is not known; this is a marker.
ENU = b"tbpipeline test file, not from an install\r\n"
NAME = b"C:\\TOOLBOOK\\TB80enu\x00"


def open_file(host, style=0):
    host.arena.write(host.data, 0x100, NAME)
    far_call(host, "KERNEL", 74, [style, 0x200, host.data, 0x100, host.data], pop=10)
    return host.uc.reg_read(UC_X86_REG_AX)


class Tb80enuOpen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "TB80enu").write_bytes(ENU)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_reads_the_supplied_file(self):
        host = fake_host()
        with mock.patch.dict(os.environ, {"TBK_INI": self.tmp.name}):
            handle = open_file(host, style=0x4000)
        self.assertNotEqual(handle, 0xFFFF)
        self.assertEqual(host.files[handle], ENU)
        self.assertEqual(host.open_styles, [("C:\\TOOLBOOK\\TB80enu", 0x4000)])

    def test_without_tbk_ini_the_open_still_refuses(self):
        host = fake_host()
        env = {k: v for k, v in os.environ.items() if k != "TBK_INI"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(open_file(host), 0xFFFF)

    def test_other_names_are_not_answered(self):
        host = fake_host()
        (Path(self.tmp.name) / "TB80ENU1.DLL").write_bytes(b"x")
        with mock.patch.dict(os.environ, {"TBK_INI": self.tmp.name}):
            self.assertIsNone(host._take_file("C:\\TOOLBOOK\\TB80ENU1.DLL"))


class Tb80enuStartup(unittest.TestCase):
    """Pass 06 with TB80.INI and TB80enu present. Skips without TBK_BIN."""

    def test_startup_with_tb80enu(self):
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80RCR.DLL", "TB80LNL.DLL",
                           "TB80OLE.DLL", "TB80UTL.DLL", "TB80W16.DLL")
        import tbpipeline_bf.nedllhost.pass06 as pass06
        from tests.test_bf_host_ini import INI
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "TB80.INI").write_bytes(INI)
            (Path(tmp) / "TB80enu").write_bytes(ENU)
            book = Path(tmp) / "fixture.tbk"
            book.write_bytes(b"\x00" * 0xC00 + struct.pack("<I", 0x22222222))
            env = {"TBK_INI": tmp, "TBK_UNPACKED": str(root)}
            with mock.patch.dict(os.environ, env), mock.patch.object(pass06, "UNPACKED", str(root)):
                host = pass06.Pass06(str(root / "TB80RTM.EXE"), str(book))
                host.run()
        names = [p.lower().replace("/", "\\").split("\\")[-1] for p in host.opens]
        # The extensionless TB80enu was the wsprintf buffer before USER.420
        # formatted it. With wsprintf answered, the entry asks for the
        # language DLL by its full name.
        self.assertIn("tb80enu1.dll", names, f"the entry did not ask for TB80enu1.DLL: {host.opens}")
        self.assertNotIn("tb80enu", names)
        after = host.opens[names.index("tb80enu1.dll") + 1:]
        print(f"\nTB80enu1.DLL asked for; styles {host.open_styles}; next opens {after or 'none'}; "
              f"stop {host.fault}; last ax=1 {host.ax1[-1] if host.ax1 else 'none'}")


if __name__ == "__main__":
    unittest.main()
