"""newl GetVersion stays 0x0A03 and __WINFLAGS stays 0x0C25."""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_newl.layer import EQUATES, Layer
from tests.newl_fixture import BY_ORDINAL, OFFSET, Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


class Constants(unittest.TestCase):
    def test_get_version(self):
        self.assertEqual(Layer().call("KERNEL", 3), 0x0A03)

    def test_winflags_equate(self):
        self.assertEqual(EQUATES["KERNEL"][178], ("__WINFLAGS", 0x0C25))

    def test_get_winflags_matches(self):
        self.assertEqual(Layer().call("KERNEL", 132), 0x0C25)

    @unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl linker cannot be built")
    def test_winflags_fixup_is_the_constant(self):
        """A reloc to KERNEL.178 is written as 0x0C25, not as a gate offset."""
        from tbpipeline_newl.cpu import Cpu

        code = b"\xb8\xff\xff\xf4"  # mov ax, __WINFLAGS; hlt
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / "TB80RTM.EXE", "TB80RTM",
                  [Seg(code, [(OFFSET, BY_ORDINAL, 1, 1, 178)]), Seg(b"\x00" * 0x2000, flags=1)],
                  modules=["KERNEL"], auto=2, stack=0x200)
            host = Cpu(tmp)
        self.assertEqual(struct.unpack_from("<H", host.exe["segments"][0]["data"], 1)[0], 0x0C25)


if __name__ == "__main__":
    unittest.main()
