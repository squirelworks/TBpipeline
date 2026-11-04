"""The stand-in for Arial is Liberation Sans when the host has it: the same widths, so text
ToolBook measures to fit a field fits. DejaVu Sans, the fallback, is wider."""

import unittest
from pathlib import Path

from tbpipeline_neww import gdi16

LIBERATION = [Path(d) for d in ("/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2")]


class StandIn(unittest.TestCase):
    def font(self, face, weight=400):
        return gdi16.Gdi().font_for(gdi16._logfont(-16, 0, weight, 0, 0x22, face))[0]

    def test_arial_is_liberation_sans_when_installed(self):
        # The guard looks at the host's own folders, not at gdi16's list, so the test runs
        # wherever Liberation is installed.
        if not any((d / "LiberationSans-Regular.ttf").exists() for d in LIBERATION):
            raise unittest.SkipTest("no Liberation Sans on this host")
        self.assertTrue(self.font("Arial").path.endswith("LiberationSans-Regular.ttf"))
        self.assertTrue(self.font("Arial", 700).path.endswith("LiberationSans-Bold.ttf"))

    def test_every_kind_lists_names_with_a_fallback(self):
        for names in gdi16.TEXT_STANDIN.values():
            self.assertIsInstance(names, tuple)
            self.assertGreaterEqual(len(names), 2)


if __name__ == "__main__":
    unittest.main()
