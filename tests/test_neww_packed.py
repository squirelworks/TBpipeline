"""A segment with the iterated flag is not run as zeros.

TB80RTM.EXE as shipped is self-loading: 138 of its 139 segments have
the iterated flag. neww loaded them as zero bytes and ran empty memory
until the instruction cap. Now the run stops before the CPU starts and
names the image and the first packed segment.
"""

import tempfile
import unittest

from tests import neww_ne


class PackedImage(unittest.TestCase):
    def test_iterated_segment_stops_before_the_cpu(self):
        from tbpipeline_neww.machine import Machine
        code = neww_ne.mov_ax(0x4C00) + neww_ne.call_far() + bytes([0xF4])
        fixups = [(3, 1, 4, 1, 102)]
        with tempfile.TemporaryDirectory() as d:
            blob = neww_ne.build(
                "TB80RTM",
                [(0x0000, code, fixups), (0x0009, b"\x00" * 64, [])],
                modules=("KERNEL",), entry=(1, 0), auto=2,
            )
            neww_ne.write(d, "TB80RTM.EXE", blob)
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.calls, 0)
        self.assertEqual(
            host.stop,
            "packed image TB80RTM.EXE: 1 of 2 segments have the iterated flag, first is segment 2. "
            "neww does not unpack. --b must hold the unpacked images",
        )

    def test_unpacked_image_still_runs(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, b"", [])
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.stop, "dos exit 0x0")


if __name__ == "__main__":
    unittest.main()
