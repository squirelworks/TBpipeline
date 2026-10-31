"""KERNEL.353 lstrcpyn copies at most n - 1 characters and a NUL.

Wine's lstrcpyn16 (krnl386.exe16/kernel.c) is lstrcpynA on the mapped
pointer and returns dst. lstrcpynA copies while count > 1 and the source
has characters, then writes the NUL if count is not 0. The runtime calls it
four times before the WinExec wall. AX = 1 copied nothing and returned a
pointer of 0000:0001.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call

DST, SRC = 0x100, 0x180


def lstrcpyn(src, n):
    host = fake_host()
    host.arena.write(host.data, SRC, src + b"\x00")
    host.arena.write(host.data, DST, b"\xEE" * 16)
    d = host.data
    far_call(host, "KERNEL", 353, [n & 0xFFFF, SRC, d, DST, d], pop=10)
    ret = (host.uc.reg_read(UC_X86_REG_DX), host.uc.reg_read(UC_X86_REG_AX))
    return host, ret, host.arena.read(d, DST, 16)


class Lstrcpyn(unittest.TestCase):
    def test_cut_to_n_minus_one(self):
        host, ret, buf = lstrcpyn(b"ToolBook", 5)
        self.assertEqual(buf[:6], b"Tool\x00\xEE")
        self.assertEqual(ret, (host.data, DST), "returns dst")
        self.assertEqual(host.ax1, [], "lstrcpyn fell through to AX = 1")

    def test_shorter_source(self):
        self.assertEqual(lstrcpyn(b"TB", 8)[2][:4], b"TB\x00\xEE")

    def test_n_zero_writes_nothing(self):
        self.assertEqual(lstrcpyn(b"TB", 0)[2][:2], b"\xEE\xEE")

    def test_negative_n_has_no_limit(self):
        self.assertEqual(lstrcpyn(b"ToolBook", -1)[2][:10], b"ToolBook\x00\xEE")


if __name__ == "__main__":
    unittest.main()
