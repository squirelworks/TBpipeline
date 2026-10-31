"""GDI.80 GetDeviceCaps answers for the screen as Wine's null driver does.

Wine's GetDeviceCaps16 (dlls/gdi.exe16/gdi.c) returns GetDeviceCaps cast
to INT16, with NUMCOLORS -1 turned into 2048. The screen's values come
from nulldrv_GetDeviceCaps (dlls/win32u/driver.c): 32 bits per pixel when
no display reports a mode, 96 DPI for an application that is not DPI
aware, one plane, no palette, and 0 for a capability it does not know.
AX = 1 said the screen had one bit per pixel and one pixel per inch.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

HDC = 0x0001


def caps(index):
    host = fake_host()
    far_call(host, "GDI", 80, [index, HDC], pop=4)
    return host, host.uc.reg_read(UC_X86_REG_AX)


class GetDeviceCaps(unittest.TestCase):
    def test_bits_per_pixel(self):
        host, ax = caps(12)  # BITSPIXEL
        self.assertEqual(ax, 32)
        self.assertEqual(host.ax1, [], "GetDeviceCaps fell through to AX = 1")

    def test_the_values_the_runtime_asks_for(self):
        self.assertEqual(caps(14)[1], 1)  # PLANES
        self.assertEqual(caps(88)[1], 96)  # LOGPIXELSX
        self.assertEqual(caps(90)[1], 96)  # LOGPIXELSY
        self.assertEqual(caps(24)[1], 2048)  # NUMCOLORS: -1 becomes 2048
        self.assertEqual(caps(104)[1], 0)  # SIZEPALETTE
        self.assertEqual(caps(38)[1], 0xBE99)  # RASTERCAPS, no RC_PALETTE

    def test_screen_size_matches_get_system_metrics(self):
        self.assertEqual((caps(8)[1], caps(10)[1]), (800, 600))  # HORZRES, VERTRES

    def test_unknown_capability_is_zero(self):
        self.assertEqual(caps(200)[1], 0)


if __name__ == "__main__":
    unittest.main()
