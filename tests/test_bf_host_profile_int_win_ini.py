"""KERNEL.57 GetProfileInt reads a number from WIN.INI, or the default.

Wine's GetProfileInt16 (krnl386.exe16/file.c) is
GetPrivateProfileInt16(section, entry, def_val, "win.ini"). The runtime
calls it once before the WinExec wall. AX = 1 said the key held 1.
"""

import os
import tempfile
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

APP, KEY = 0x100, 0x140


def profile_int(app, key, default):
    host = fake_host()
    host.arena.write(host.data, APP, app + b"\x00")
    host.arena.write(host.data, KEY, key + b"\x00")
    d = host.data
    far_call(host, "KERNEL", 57, [default & 0xFFFF, KEY, d, APP, d], pop=10)
    return host, host.uc.reg_read(UC_X86_REG_AX)


class ProfileIntWinIni(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("TBK_INI", None)

    def tearDown(self):
        os.environ.pop("TBK_INI", None)
        if self.saved is not None:
            os.environ["TBK_INI"] = self.saved

    def test_no_win_ini_returns_the_default(self):
        host, ax = profile_int(b"windows", b"DoubleClickSpeed", 452)
        self.assertEqual(ax, 452)
        self.assertEqual(host.ax1, [], "GetProfileInt fell through to AX = 1")

    def test_a_key_in_win_ini(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "WIN.INI"), "wb") as f:
                f.write(b"[Windows]\r\nDoubleClickSpeed=0x200\r\n")
            os.environ["TBK_INI"] = root
            self.assertEqual(profile_int(b"windows", b"doubleclickspeed", 452)[1], 0x200)
            self.assertEqual(profile_int(b"windows", b"missing", 452)[1], 452)


if __name__ == "__main__":
    unittest.main()
