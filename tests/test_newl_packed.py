"""newl does not start the CPU on a self-loading image whose segments are still packed."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


def _bin(root, rtm_flags=0x0002, dll_flags=0x8000):
    build(root / "TB80RTM.EXE", "TB80RTM", [Seg(b"\xf4"), Seg(b"\x00" * 0x2000, flags=1)],
          auto=2, stack=0x200, ne_flags=rtm_flags)
    build(root / "TB80W16.DLL", "TB80W16", [Seg(b"\xcb")], entries=[(1, 0)], exe=False, ne_flags=dll_flags)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot be built")
class Packed(unittest.TestCase):
    def _run(self, **flags):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _bin(Path(tmp), **flags)
            host = Cpu(tmp)
            host.run(limit=100)
        return host

    def test_packed_files_stop_before_the_cpu(self):
        host = self._run(rtm_flags=0x0802, dll_flags=0x8800)
        self.assertIsNone(host.uc)
        self.assertEqual(
            host.stop,
            "packed TB80RTM.EXE, TB80W16.DLL: self-loading (NE flag 0x0800), and newl does not unpack. "
            "Unpack first: python3 -m tbpipeline_bf.nehost --unpack FILE -o FILE")

    def test_unpacked_files_run(self):
        host = self._run()
        self.assertEqual(host.packed, [])
        self.assertTrue(host.stop.startswith("hlt at "), host.stop)


if __name__ == "__main__":
    unittest.main()
