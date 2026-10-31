"""newl ends a scan of GlobalAlloc memory nothing wrote at the first miss, and names it."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


def _rtm(root, plant):
    """GlobalAlloc 0x2000, GlobalLock, then lodsw from 0x1276 until 0x0012.
    plant writes 0x0012 at 0x1276 before the scan, the way a record would be."""
    code = bytearray()
    relocs = []

    def far(ordinal):
        relocs.append((FAR, BY_ORDINAL, len(code) + 1, 1, ordinal))
        code.extend(b"\x9a\xff\xff\x00\x00")

    code += b"\x68\x40\x00\x68\x00\x00\x68\x00\x20"  # push 0x40; push 0; push 0x2000
    far(15)
    code += b"\x50"  # push ax
    far(18)
    code += b"\x8e\xda\x8e\xc2"  # mov ds, dx; mov es, dx
    if plant:
        code += b"\xbf\x76\x12\xb8\x12\x00\xab"  # mov di, 0x1276; mov ax, 0x12; stosw
    code += b"\xfc\xbe\x76\x12"  # cld; mov si, 0x1276
    loop = len(code)
    code += b"\xad\x3d\x12\x00"  # lodsw; cmp ax, 0x12
    code += bytes([0x75, (loop - (len(code) + 2)) & 0xFF])  # jne loop
    code += b"\xf4"
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(bytes(code), relocs), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["KERNEL"], auto=2, stack=0x200)
    return loop


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class StartupScan(unittest.TestCase):
    def _run(self, plant):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            loop = _rtm(Path(tmp), plant)
            host = Cpu(tmp)
            host.run(limit=100_000)
        return host, loop

    def test_scan_of_unwritten_block_stops_at_first_miss(self):
        host, loop = self._run(plant=False)
        cs = host.exe["segments"][0]["selector"]
        sel = next(iter(host.blocks.values()))["selector"]
        self.assertEqual(
            host.stop,
            f"scan lodsw at {cs:#x}:{loop:#x} read {sel:#x}:0x1276, "
            f"GlobalAlloc block 0x1 that nothing wrote, looking for 0x0012")

    def test_scan_that_finds_a_written_record_goes_on(self):
        host, _ = self._run(plant=True)
        self.assertTrue(host.stop.startswith("hlt at "), host.stop)


if __name__ == "__main__":
    unittest.main()
