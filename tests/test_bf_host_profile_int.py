"""KERNEL.127 GetPrivateProfileInt reads a number, or returns the default.

Before the WinExec wall the runtime reads numeric keys from
C:\\WINDOWS\\TB80.INI this way, with defaults 1774 and 5001. AX = 1 said
every key held 1. Wine's GetPrivateProfileInt16 (krnl386.exe16/file.c) is
GetPrivateProfileIntA cast to INT16: a missing or empty value gives the
default, and a present one is read by RtlUnicodeStringToInteger with base
0 (leading blanks, a sign, 0x / 0o / 0b prefixes, digits up to the first
that does not fit), so text with no digits is 0.
"""

import os
import tempfile
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

APP, KEY, FILE = 0x100, 0x140, 0x300
INI = b"C:\\WINDOWS\\TB80.INI"


def profile_int(key, default):
    host = fake_host()
    host.arena.write(host.data, APP, b"ToolBook startup\x00")
    host.arena.write(host.data, KEY, key + b"\x00")
    host.arena.write(host.data, FILE, INI + b"\x00")
    d = host.data
    far_call(host, "KERNEL", 127, [FILE, d, default & 0xFFFF, KEY, d, APP, d], pop=14)
    return host, host.uc.reg_read(UC_X86_REG_AX)


class ProfileInt(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("TBK_INI", None)

    def tearDown(self):
        os.environ.pop("TBK_INI", None)
        if self.saved is not None:
            os.environ["TBK_INI"] = self.saved

    def test_no_ini_returns_the_default(self):
        host, ax = profile_int(b"Width", 1774)
        self.assertEqual(ax, 1774)
        self.assertEqual(host.ax1, [], "GetPrivateProfileInt fell through to AX = 1")

    def test_values_in_the_supplied_ini(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "TB80.INI"), "wb") as f:
                f.write(
                    b"[toolbook STARTUP]\r\nwidth = 800\r\nhex=0x1F\r\nneg= -2\r\n"
                    b"word=yes\r\nempty=\r\ntail=12abc\r\n"
                )
            os.environ["TBK_INI"] = root
            self.assertEqual(profile_int(b"Width", 5001)[1], 800)
            self.assertEqual(profile_int(b"hex", 5001)[1], 0x1F)
            self.assertEqual(profile_int(b"neg", 5001)[1], 0xFFFE)
            self.assertEqual(profile_int(b"word", 5001)[1], 0)
            self.assertEqual(profile_int(b"empty", 5001)[1], 5001)
            self.assertEqual(profile_int(b"tail", 5001)[1], 12)
            self.assertEqual(profile_int(b"missing", 5001)[1], 5001)


if __name__ == "__main__":
    unittest.main()
