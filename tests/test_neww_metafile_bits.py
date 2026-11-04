"""Roadmap #201 T5: a packed book picture comes through neww as a metafile with its DIBs.

TB80RTM unpacks a class 0x19 picture itself and hands the bytes to GDI.160 SetMetaFileBits.
Wine's SetMetaFileBits16 returns the global handle it was given (dlls/gdi.exe16/metafile.c:295,
Wine 2528aff2), so the metafile is the block behind that handle. On NIDA ATT 93952606.TBK
("Parallel Resonance") the page after P430 holds two packed pictures. opentoolbook8 SETTLED.md
reads them as class 0x19 records: object 23 is 61056 metafile bytes stored as 41364, object 9 is
51584 stored as 11289. Each metafile draws an 8-bit DIB twice, SRCPAINT then SRCAND.

The synthetic test needs nothing. The course test needs TBK_BIN and TBK_BOOK3, the path of
93952606.TBK with nida81.tbk beside it, and skips without them.
"""

import os
import struct
import unittest
from unittest import mock

from tests.test_neww_batch2 import by_name, window_wine

STRETCH_DIB = 0x0F43
SRCPAINT = 0x00EE0086
SRCAND = 0x008800C6
NEXT = "click 808,600; wait 8000"
# Title click, then Next seven times: the seventh leaves P430.
INPUT = "wait 15000; click 512,420; wait 8000; " + "; ".join([NEXT] * 7)


def stretch_dibs(metafile: bytes):
    """(rop, width, height, bpp, colors, record bytes, bytes the header implies) per StretchDIB."""
    found = []
    at = 18
    while at + 6 <= len(metafile):
        words, function = struct.unpack_from("<IH", metafile, at)
        if function == 0 or words == 0:
            break
        if function == STRETCH_DIB:
            rop, = struct.unpack_from("<I", metafile, at + 6)
            info = at + 6 + 22
            size, width, height, _planes, bpp, _comp, _img, _x, _y, used, _imp = struct.unpack_from(
                "<IiiHHIIiiII", metafile, info)
            colors = used or (1 << bpp if bpp <= 8 else 0)
            stride = (width * bpp + 31) // 32 * 4
            found.append((rop, size, width, height, bpp, words * 2,
                          6 + 22 + size + 4 * colors + stride * abs(height)))
        at += words * 2
    return found


class SetMetaFileBits(unittest.TestCase):
    def test_the_metafile_handle_is_the_block_handle(self):
        w = window_wine()
        self.assertEqual(by_name(w, "GDI", "SetMetaFileBits", 0x43DC)[:3], (0x43DC, 0, None))


class PackedPictureInTheCourse(unittest.TestCase):
    def test_page_after_p430_hands_gdi_two_unpacked_metafiles(self):
        from tests.binpath import bin_or_skip
        from tbpipeline_neww import machine
        from tbpipeline_neww.handlers import HANDLERS, spec_types
        book = os.environ.get("TBK_BOOK3")
        if not book:
            raise unittest.SkipTest("TBK_BOOK3 (93952606.TBK) is not set")
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        key = ("GDI", spec_types("GDI", "SetMetaFileBits")[0])
        # Before the handler, the spec row's default answers 0.
        handler = HANDLERS.get(key, lambda wine, arg: (0, 0, None))
        seen = []
        hosts = []

        def kept(wine, arg):
            out = handler(wine, arg)
            host = hosts[0]
            sel = out[0]
            seg = host.box.selectors.get(sel)
            data = bytes(host.uc.mem_read(seg.base, len(seg.data))) if seg is not None else b""
            seen.append((sel, data))
            return out

        host = machine.Machine(str(root), book, input_script=INPUT)
        hosts.append(host)
        host.call_limit = 200000
        host.timeout_us = 10 ** 10
        with mock.patch.dict(HANDLERS, {key: kept}):
            host.run(limit=host.call_limit * 1000)
        print(f"\n  stopped {host.stop} | calls {host.calls}")

        self.assertEqual(len(seen), 2)
        self.assertTrue(all(sel for sel, _ in seen))
        self.assertEqual([len(data) for _, data in seen], [61056, 51584])
        for (_, data), (width, height) in zip(seen, [(203, 144), (159, 154)]):
            self.assertEqual(struct.unpack_from("<HHH", data, 0), (1, 9, 0x300))
            dibs = stretch_dibs(data)
            self.assertEqual([d[0] for d in dibs], [SRCPAINT, SRCAND])
            for _rop, size, w, h, bpp, record, implied in dibs:
                self.assertEqual((size, w, h, bpp), (40, width, height, 8))
                self.assertEqual(record, implied)


if __name__ == "__main__":
    unittest.main()
