"""GetSystemMetrics SM_CXSCREEN and SM_CYSCREEN are Wine's default display, 1024x768.

win32u sysparams.c get_system_metrics answers them from the primary
monitor. neww has no display driver. When the driver does not implement
UpdateDisplayDevices, update_display_devices calls
default_update_display_devices, which uses modes[2], 1024x768, if no
current mode is saved in the registry. No binary needed.
"""

import unittest

from tests.test_neww_getsystemmetrics import run


class ScreenSize(unittest.TestCase):
    def test_cxscreen(self):
        host, ax = run(0)
        self.assertEqual((host.stop, ax), ("dos exit 0x0", 1024))

    def test_cyscreen(self):
        host, ax = run(1)
        self.assertEqual((host.stop, ax), ("dos exit 0x0", 768))


if __name__ == "__main__":
    unittest.main()
