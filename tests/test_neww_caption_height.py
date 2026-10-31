"""GetSystemMetrics SM_CYCAPTION is 19, Wine's default caption at 96 dpi.

win32u sysparams.c returns iCaptionHeight + 1. iCaptionHeight is the
CaptionHeight default, -270 twips, 18 pixels at 96 dpi. Wine's
normalize_nonclientmetrics raises it to 2 + tmHeight of the caption font
if that is more. The caption font is the default GUI font at -11 pixels,
bold, and Wine's Tahoma Bold (fonts/tahomabd.sfd) is 13 pixels tall
there, so 18 stands. No binary needed.
"""

import unittest

from tests.test_neww_getsystemmetrics import run


class CaptionHeight(unittest.TestCase):
    def test_cycaption(self):
        host, ax = run(4)
        self.assertEqual((host.stop, ax), ("dos exit 0x0", 19))


if __name__ == "__main__":
    unittest.main()
