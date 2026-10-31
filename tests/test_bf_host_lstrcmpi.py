"""USER.471 lstrcmpi compares the two strings without case.

TB80NET's WinMain compares its command line with "ToolBook", "ToolBook32"
and "ToolBook16or32". AX = 1 was "greater" for every pair, so none
matched and it exited 0 without creating its window.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

ONE = 0x100
TWO = 0x180


def compare(one, two):
    host = fake_host()
    host.arena.write(host.data, ONE, one + b"\x00")
    host.arena.write(host.data, TWO, two + b"\x00")
    far_call(host, "USER", 471, [TWO, host.data, ONE, host.data], pop=8)
    return host, host.uc.reg_read(UC_X86_REG_AX)


class Lstrcmpi(unittest.TestCase):
    def test_equal_without_case(self):
        host, ax = compare(b"ToolBook", b"TOOLBOOK")
        self.assertEqual(ax, 0)
        self.assertEqual(host.ax1, [], "lstrcmpi fell through to AX = 1")

    def test_less_is_negative(self):
        self.assertEqual(compare(b"ToolBook", b"ToolBook32")[1], 0xFFFF)

    def test_greater_is_positive(self):
        self.assertEqual(compare(b"toolbook32", b"ToolBook")[1], 1)


if __name__ == "__main__":
    unittest.main()
