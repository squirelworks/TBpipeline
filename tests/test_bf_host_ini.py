"""Item 22: TB80.INI. An original INI in a temp directory, and the open pointed at it.

The fake-call tests need no binary. The startup test needs TBK_BIN and
records whether the entry gets past the INI open, and what it asks for next.
"""

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.binpath import bin_or_skip
from tests.bf_host_fake import fake_host, far_call

# Original. Not from an install. Three lines.
INI = b"; written by tests/test_bf_host_ini.py, not taken from an install\r\n[tbpipeline]\r\nfixture=1\r\n"
NAME = b"C:\\WINDOWS\\TB80.INI\x00"


def open_file(host, name=NAME):
    """KERNEL.74 OpenFile(lpFileName, lpReOpenBuff, uStyle). Pascal, 10 bytes."""
    host.arena.write(host.data, 0x100, name)
    far_call(host, "KERNEL", 74, [0, 0x200, host.data, 0x100, host.data], pop=10)
    return host.uc.reg_read(UC_X86_REG_AX)


def lread(host, handle, count):
    """KERNEL.82 _lread(hFile, lpBuffer, wBytes). Pascal, 8 bytes."""
    far_call(host, "KERNEL", 82, [count, 0x400, host.data, handle], ret_ip=0x205, pop=8)
    n = host.uc.reg_read(UC_X86_REG_AX)
    return host.arena.read(host.data, 0x400, n)


class IniOpen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "TB80.INI").write_bytes(INI)
        self.assertEqual(len(INI.splitlines()), 3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ini_open_reads_the_file_in_tbk_ini(self):
        host = fake_host()
        with mock.patch.dict(os.environ, {"TBK_INI": self.tmp.name}):
            handle = open_file(host)
        self.assertNotEqual(handle, 0xFFFF)
        self.assertEqual(lread(host, handle, 0x100), INI)
        self.assertEqual(host.opens, ["C:\\WINDOWS\\TB80.INI"])

    def test_without_tbk_ini_the_open_still_refuses(self):
        host = fake_host()
        env = {k: v for k, v in os.environ.items() if k != "TBK_INI"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(open_file(host), 0xFFFF)

    def test_book_open_is_unchanged(self):
        host = fake_host(book=b"BOOK")
        with mock.patch.dict(os.environ, {"TBK_INI": self.tmp.name}):
            handle = open_file(host, b"C:\\COURSES\\fixture.tbk\x00")
        self.assertEqual(lread(host, handle, 4), b"BOOK")

    def test_dos_open_keeps_the_ini_bytes(self):
        # INT 21h AH=3Dh used to overwrite every handle with the book.
        host = fake_host(book=b"BOOK")
        host.arena.write(host.data, 0x100, b"TB80.INI\x00")
        host.uc.reg_write(UC_X86_REG_DX, 0x100)
        host.uc.reg_write(UC_X86_REG_AX, 0x3D00)
        with mock.patch.dict(os.environ, {"TBK_INI": self.tmp.name}):
            host._dos()
        handle = host.uc.reg_read(UC_X86_REG_AX)
        self.assertEqual(host.files[handle], INI)


class IniStartup(unittest.TestCase):
    """Pass 06 with the INI present. Skips without TBK_BIN."""

    def test_startup_with_ini(self):
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80RCR.DLL", "TB80LNL.DLL",
                           "TB80OLE.DLL", "TB80UTL.DLL", "TB80W16.DLL")
        import tbpipeline_bf.nedllhost.pass06 as pass06
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "TB80.INI").write_bytes(INI)
            book = Path(tmp) / "fixture.tbk"
            book.write_bytes(b"\x00" * 0xC00 + struct.pack("<I", 0x22222222))
            env = {"TBK_INI": tmp, "TBK_UNPACKED": str(root)}
            with mock.patch.dict(os.environ, env), mock.patch.object(pass06, "UNPACKED", str(root)):
                host = pass06.Pass06(str(root / "TB80RTM.EXE"), str(book))
                host.run()
        names = [p.lower().replace("/", "\\").split("\\")[-1] for p in host.opens]
        self.assertIn("tb80.ini", names, f"the entry did not ask for TB80.INI: {host.opens}")
        after = host.opens[names.index("tb80.ini") + 1:]
        print(f"\nINI open answered; next opens {after or 'none'}; stop {host.fault}; "
              f"last ax=1 {host.ax1[-1] if host.ax1 else 'none'}")


if __name__ == "__main__":
    unittest.main()
