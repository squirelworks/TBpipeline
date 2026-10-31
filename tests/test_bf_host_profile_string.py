"""KERNEL.128 GetPrivateProfileString copies the value, or the default.

Before the WinExec wall the runtime reads its "ToolBook startup" keys
from C:\\WINDOWS\\TB80.INI this way. AX = 1 left the buffer as it was and
said one character came back. As in Windows (Wine's
GetPrivateProfileStringA), a missing key copies the default without its
trailing blanks, cut to size - 1 and NUL-terminated, and returns its
length. A key in the INI that TBK_INI supplies copies its value.
"""

import os
import tempfile
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

APP, KEY, DEF, BUF, FILE = 0x100, 0x140, 0x180, 0x200, 0x300
INI = b"C:\\WINDOWS\\TB80.INI"


def profile(host, key, default, size):
    host.arena.write(host.data, APP, b"ToolBook startup\x00")
    host.arena.write(host.data, KEY, key + b"\x00")
    host.arena.write(host.data, DEF, default + b"\x00")
    host.arena.write(host.data, FILE, INI + b"\x00")
    host.arena.write(host.data, BUF, b"\xEE" * 32)
    d = host.data
    far_call(host, "KERNEL", 128, [FILE, d, size, BUF, d, DEF, d, KEY, d, APP, d], pop=22)
    return host.uc.reg_read(UC_X86_REG_AX), host.arena.read(d, BUF, 32)


class ProfileString(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("TBK_INI", None)

    def tearDown(self):
        os.environ.pop("TBK_INI", None)
        if self.saved is not None:
            os.environ["TBK_INI"] = self.saved

    def test_no_ini_copies_the_default(self):
        n, buf = profile(fake_host(), b"Width", b"640  ", 32)
        self.assertEqual((n, buf[:4]), (3, b"640\x00"))

    def test_the_default_is_cut_to_size(self):
        n, buf = profile(fake_host(), b"Width", b"123456", 4)
        self.assertEqual((n, buf[:5]), (3, b"123\x00\xEE"))

    def test_empty_default(self):
        n, buf = profile(fake_host(), b"DrawDirect", b"", 32)
        self.assertEqual((n, buf[:1]), (0, b"\x00"))

    def test_a_key_in_the_supplied_ini(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "TB80.INI"), "wb") as f:
                f.write(b"[toolbook STARTUP]\r\nwidth = 800\r\n")
            os.environ["TBK_INI"] = root
            n, buf = profile(fake_host(), b"Width", b"640", 32)
        self.assertEqual((n, buf[:4]), (3, b"800\x00"))


if __name__ == "__main__":
    unittest.main()
