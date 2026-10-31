"""KERNEL.58 GetProfileString copies a WIN.INI value, or the default.

Wine's GetProfileString16 (krnl386.exe16/file.c) is
GetPrivateProfileString16(section, entry, def_val, buffer, len, "win.ini").
The runtime calls it once before the WinExec wall. AX = 1 left the buffer
as it was and said one character came back.
"""

import os
import tempfile
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

APP, KEY, DEF, BUF = 0x100, 0x140, 0x180, 0x200


def profile(app, key, default, size):
    host = fake_host()
    host.arena.write(host.data, APP, app + b"\x00")
    host.arena.write(host.data, KEY, key + b"\x00")
    host.arena.write(host.data, DEF, default + b"\x00")
    host.arena.write(host.data, BUF, b"\xEE" * 32)
    d = host.data
    far_call(host, "KERNEL", 58, [size, BUF, d, DEF, d, KEY, d, APP, d], pop=18)
    return host, host.uc.reg_read(UC_X86_REG_AX), host.arena.read(d, BUF, 32)


class ProfileStringWinIni(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("TBK_INI", None)

    def tearDown(self):
        os.environ.pop("TBK_INI", None)
        if self.saved is not None:
            os.environ["TBK_INI"] = self.saved

    def test_no_win_ini_copies_the_default(self):
        host, n, buf = profile(b"intl", b"sLanguage", b"enu", 32)
        self.assertEqual((n, buf[:4]), (3, b"enu\x00"))
        self.assertEqual(host.ax1, [], "GetProfileString fell through to AX = 1")

    def test_a_key_in_win_ini(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "WIN.INI"), "wb") as f:
                f.write(b"[intl]\r\nsLanguage=deu\r\n")
            os.environ["TBK_INI"] = root
            _, n, buf = profile(b"Intl", b"slanguage", b"enu", 32)
        self.assertEqual((n, buf[:4]), (3, b"deu\x00"))


if __name__ == "__main__":
    unittest.main()
