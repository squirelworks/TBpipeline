"""documentation/host.md names every way a newl run can end."""

import unittest
from pathlib import Path

HOST = Path(__file__).resolve().parent.parent / "documentation" / "host.md"
STOPS = ("gap KERNEL.", "scan lodsw at", "OpenFile NAME: no book", "dos exit", "hlt at",
         "instruction cap 1000000", "time cap 15 s")


class HostMd(unittest.TestCase):
    def test_newl_stops_are_written_down(self):
        text = HOST.read_text(encoding="utf-8")
        section = text.split("## newl", 1)[1].split("## neww", 1)[0]
        for stop in STOPS:
            self.assertIn(stop, section)


if __name__ == "__main__":
    unittest.main()
