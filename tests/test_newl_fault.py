"""A CPU exception in newl names the place, the bytes there, and a null data selector."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class Fault(unittest.TestCase):
    def test_call_through_a_null_table(self):
        """The shape TB80W16 segment 8 faults on: les bx, es:[bx]; lcall es:[bx+0x20] with ES = 0."""
        from tbpipeline_newl.cpu import Cpu

        code = b"\x31\xdb\x8e\xc3" + b"\x26\xff\x5f\x20"  # xor bx,bx; mov es,bx; lcall es:[bx+0x20]
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / "TB80RTM.EXE", "TB80RTM", [Seg(code), Seg(b"\x00" * 0x2000, flags=1)],
                  auto=2, stack=0x200)
            host = Cpu(tmp)
            host.run(limit=100)
        cs = host.exe["segments"][0]["selector"]
        self.assertTrue(host.stop.startswith(
            f"fault at {cs:#x}:0x4 (TB80RTM segment 1) bytes 26 ff 5f 20, null ES: "), host.stop)

    def test_unmapped_names_the_place(self):
        from tbpipeline_newl.cpu import Cpu

        code = b"\xbe\xf0\xff\xad\xf4"  # mov si,0xfff0; lodsw: past every page this fixture maps
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / "TB80RTM.EXE", "TB80RTM", [Seg(code), Seg(b"\x00" * 0x2000, flags=1)],
                  auto=2, stack=0x200)
            host = Cpu(tmp)
            host.run(limit=100)
        cs = host.exe["segments"][0]["selector"]
        self.assertRegex(host.stop, rf"^unmapped 0x[0-9a-f]+ at {cs:#x}:0x3 \(TB80RTM segment 1\)$")


if __name__ == "__main__":
    unittest.main()
