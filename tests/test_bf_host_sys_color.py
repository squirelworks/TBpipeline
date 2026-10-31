"""USER.180 GetSysColor returns Wine's default colour for the index.

Wine's GetSysColor16 (dlls/user.exe16/user.c) is GetSysColor, which reads
system_colors in dlls/win32u/sysparams.c and returns 0 for an index out of
range. The COLORREF comes back in DX:AX. AX = 1 was a near-black red for
every element.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call


def sys_color(index):
    host = fake_host()
    far_call(host, "USER", 180, [index & 0xFFFF], pop=2)
    ax, dx = host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)
    return host, ax | (dx << 16)


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


class GetSysColor(unittest.TestCase):
    def test_button_face(self):
        host, color = sys_color(15)  # COLOR_BTNFACE
        self.assertEqual(color, rgb(212, 208, 200))
        self.assertEqual(host.ax1, [], "GetSysColor fell through to AX = 1")

    def test_window_and_info_background(self):
        self.assertEqual(sys_color(5)[1], rgb(255, 255, 255))  # COLOR_WINDOW
        self.assertEqual(sys_color(24)[1], rgb(255, 255, 225))  # COLOR_INFOBK

    def test_out_of_range_is_zero(self):
        self.assertEqual(sys_color(31)[1], 0)
        self.assertEqual(sys_color(-1)[1], 0)


if __name__ == "__main__":
    unittest.main()
