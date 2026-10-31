"""GetSystemMetrics SM_CXFRAME and SM_CYFRAME are 4, Wine's default at 96 dpi.

win32u sysparams.c get_system_metrics returns SM_CXDLGFRAME, 3, plus
max(BorderWidth, 1). BorderWidth is TWIPS_ENTRY( BORDER, -15, ... ), and
get_twips_entry makes -15 twips muldiv(15, dpi, 1440) pixels. A Win16
task is DPI unaware, so the dpi is 96 and the border is 1. No binary needed.
"""

import unittest

from tests.test_neww_getsystemmetrics import run


class FrameSize(unittest.TestCase):
    def test_cxframe(self):
        host, ax = run(32)
        self.assertEqual((host.stop, ax), ("dos exit 0x0", 4))

    def test_cyframe(self):
        host, ax = run(33)
        self.assertEqual((host.stop, ax), ("dos exit 0x0", 4))


if __name__ == "__main__":
    unittest.main()
