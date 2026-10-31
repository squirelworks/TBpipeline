"""Item 28: TB80BMP ordinal 3. The far call at 0x1FCD is bound through the DLL's relocs.

The committed tests use a tiny original NE image. A far call into another
segment of the image is followed; a call to an import stops and names it
with the stack; a return is reported with AX:DX. The real DLL runs only
with TBK_BIN. No compressed picture is committed; with no stream file the
probe passes the same dummy "BM" stream the first version did.
"""

import struct
import unittest
from pathlib import Path

from tests.binpath import bin_or_skip
from tests.fixtures import ne
from tbpipeline_bf.nehost import bmp_bitmap
from tbpipeline_bf.nehost.bmp_bitmap import Probe

FAR_CALL = b"\x9a\xff\xff\x00\x00"   # call far, offset is the reloc chain end


def image(callee):
    """Segment 1 calls far into segment 2 at offset 0. Segment 3 is data."""
    entry = b"\x55\x8b\xec" + FAR_CALL + b"\x5d\xca\x04\x00"   # push bp; mov bp,sp; call; pop bp; retf 4
    seg1 = (entry, [(3, 0, 4, 2, 0)], False)
    return ne.build([seg1, callee, (bytes(0x20), [], True)], modules=["GDI"])


class BmpProbe(unittest.TestCase):
    def test_internal_far_call_is_followed_and_import_is_named(self):
        # Segment 2: push 0x1234 ; call far GDI.29 (unbound in the image).
        seg2 = (b"\x68\x34\x12" + FAR_CALL + b"\xcb", [(3, 1, 4, 1, 29)], False)
        probe = Probe(image(seg2), seg=1, entry=0, dgroup=3)
        stop = probe.run()
        self.assertEqual(stop[0], "gate", probe.lines())
        self.assertEqual(stop[1], "GDI.29")
        lines = probe.lines()
        self.assertEqual(lines[1], "stopped at import GDI.29")
        # Return address into segment 2, then the pushed word.
        words = lines[2].split()[3:]
        self.assertEqual(words[2], "1234")

    def test_return_is_reported(self):
        seg2 = (b"\xb8\x28\x00\xba\x00\x00\xcb", [], False)   # mov ax,40 ; mov dx,0 ; retf
        probe = Probe(image(seg2), seg=1, entry=0, dgroup=3)
        stop = probe.run()
        self.assertEqual(stop[0], "returned", probe.lines())
        self.assertEqual(probe.lines()[1], "returned ax=0x0028 dx=0x0000")

    def test_cap_is_named_not_raised(self):
        self.assertEqual(bmp_bitmap.COUNT, 2000)
        seg2 = (b"\xeb\xfe", [], False)   # jmp $
        probe = Probe(image(seg2), seg=1, entry=0, dgroup=3)
        self.assertIsNone(probe.run())
        self.assertTrue(probe.lines()[1].startswith("instruction count 2000 reached at segment 2"))

    def test_record_is_not_rewritten(self):
        record = Path(bmp_bitmap.__file__).with_name("bmp_bitmap.txt")
        self.assertNotIn("write_text", Path(bmp_bitmap.__file__).read_text())
        self.assertTrue(record.read_text().startswith("TB80BMP TBKBITMAP seg 3:0x3e0"))


class BmpProbeReal(unittest.TestCase):
    def test_tb80bmp_ordinal_3(self):
        root = bin_or_skip("TB80BMP.DLL")
        probe = Probe((root / "TB80BMP.DLL").read_bytes())
        probe.run()
        print("\n" + "\n".join(probe.lines()))
        self.assertIsNotNone(probe.stop, "\n".join(probe.lines()))


if __name__ == "__main__":
    unittest.main()
