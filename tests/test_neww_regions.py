"""Regions of more than one rectangle: NtGdiCombineRgn's REGION_RegionOp (win32u/region.c),
y-x banded with REGION_UnionO and REGION_Coalesce, and the calls that read a region. No
ToolBook bytes: handlers on fake memory (tests/test_neww_batch2.py)."""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine


class ComplexRegions(unittest.TestCase):
    def setUp(self):
        from tbpipeline_neww import gdi16
        self.g16 = gdi16
        self.w = window_wine()

    def rgn(self, l, t, r, b):
        return by_name(self.w, "GDI", "CreateRectRgn", l, t, r, b)[0]

    def rects(self, h):
        return self.g16.region_rects(self.g16.gdi(self.w).get(h, self.g16.OBJ_REGION))

    def combine(self, a, b, mode):
        d = self.rgn(0, 0, 0, 0)
        ax, _dx, stop, _c = by_name(self.w, "GDI", "CombineRgn", d, a, b, mode)
        self.assertIsNone(stop)
        return d, ax

    def test_or_of_two_rows_with_a_gap(self):
        # qb_corpr's union: two list rows 4 pixels apart stay two rectangles, COMPLEXREGION.
        d, kind = self.combine(self.rgn(270, 136, 491, 178), self.rgn(270, 182, 491, 224), 2)
        self.assertEqual(kind, 3)
        self.assertEqual(self.rects(d), [(270, 136, 491, 178), (270, 182, 491, 224)])
        by_name(self.w, "GDI", "GetRgnBox", d, (DATA, 0x300))
        self.assertEqual(struct.unpack("<hhhh", self.w.memory.read(DATA, 0x300, 8)), (270, 136, 491, 224))

    def test_bands_split_and_coalesce(self):
        # Two overlapping squares: three bands, the middle one joined across.
        d, kind = self.combine(self.rgn(0, 0, 10, 10), self.rgn(5, 5, 15, 15), 2)
        self.assertEqual(self.rects(d), [(0, 0, 10, 5), (0, 5, 15, 10), (5, 10, 15, 15)])
        # Touching rows with the same columns coalesce into one rectangle.
        d, kind = self.combine(self.rgn(0, 0, 10, 5), self.rgn(0, 5, 10, 9), 2)
        self.assertEqual((kind, self.rects(d)), (2, [(0, 0, 10, 9)]))

    def test_diff_makes_a_hole_and_xor_and_and(self):
        d, kind = self.combine(self.rgn(0, 0, 10, 10), self.rgn(3, 3, 6, 6), 4)
        self.assertEqual(kind, 3)
        self.assertEqual(self.rects(d), [(0, 0, 10, 3), (0, 3, 3, 6), (6, 3, 10, 6), (0, 6, 10, 10)])
        x, _ = self.combine(self.rgn(0, 0, 10, 10), self.rgn(5, 0, 15, 10), 3)
        self.assertEqual(self.rects(x), [(0, 0, 5, 10), (10, 0, 15, 10)])
        a, kind = self.combine(d, self.rgn(0, 0, 4, 4), 1)
        self.assertEqual(self.rects(a), [(0, 0, 4, 3), (0, 3, 3, 4)])

    def test_readers_see_every_rectangle(self):
        d, _ = self.combine(self.rgn(0, 0, 10, 10), self.rgn(20, 0, 30, 10), 2)
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 12, 2, 18, 8))
        self.assertEqual(by_name(self.w, "GDI", "RectInRegion", d, (DATA, 0x300))[0], 0)
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 12, 2, 22, 8))
        self.assertEqual(by_name(self.w, "GDI", "RectInRegion", d, (DATA, 0x300))[0], 1)
        # FillRgn paints the two rectangles and not the gap.
        g = self.g16.gdi(self.w)
        hdc = self.g16.new_dc(self.w)
        red = by_name(self.w, "GDI", "CreateSolidBrush", (0, 0x00FF))[0]
        by_name(self.w, "GDI", "FillRgn", hdc, d, red)
        self.assertEqual(g.screen.getpixel((5, 5)), (255, 0, 0))
        self.assertEqual(g.screen.getpixel((25, 5)), (255, 0, 0))
        self.assertNotEqual(g.screen.getpixel((15, 5)), (255, 0, 0))

    def test_a_complex_clip_holds_drawing_to_its_rectangles(self):
        # qb_corpr selects a clip region of several rectangles: drawing lands in them only.
        d, _ = self.combine(self.rgn(0, 0, 10, 10), self.rgn(20, 0, 30, 10), 2)
        g = self.g16.gdi(self.w)
        hdc = self.g16.new_dc(self.w)
        self.assertEqual(by_name(self.w, "GDI", "SelectClipRgn", hdc, d)[:3], (3, 0, None))
        gap = g.screen.getpixel((15, 5))
        red = by_name(self.w, "GDI", "CreateSolidBrush", (0, 0x00FF))[0]
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 0, 0, 40, 40))
        by_name(self.w, "USER", "FillRect", hdc, (DATA, 0x300), red)
        self.assertEqual(g.screen.getpixel((5, 5)), (255, 0, 0))
        self.assertEqual(g.screen.getpixel((25, 5)), (255, 0, 0))
        self.assertEqual(g.screen.getpixel((15, 5)), gap)
        self.assertNotEqual(g.screen.getpixel((5, 20)), (255, 0, 0))
        # GetClipBox: the bounding box, COMPLEXREGION.
        self.assertEqual(by_name(self.w, "GDI", "GetClipBox", hdc, (DATA, 0x310))[0], 3)
        self.assertEqual(struct.unpack("<hhhh", self.w.memory.read(DATA, 0x310, 8)), (0, 0, 30, 10))

    def test_exclude_clip_rect_makes_a_hole(self):
        hdc = self.g16.new_dc(self.w)
        g = self.g16.gdi(self.w)
        by_name(self.w, "GDI", "IntersectClipRect", hdc, 0, 0, 30, 30)
        self.assertEqual(by_name(self.w, "GDI", "ExcludeClipRect", hdc, 10, 10, 20, 20)[0], 3)
        dc = g.objects[hdc]
        self.assertEqual(dc.clip_rects, [(0, 0, 30, 10), (0, 10, 10, 20), (20, 10, 30, 20), (0, 20, 30, 30)])
        before = g.screen.getpixel((15, 15))
        red = by_name(self.w, "GDI", "CreateSolidBrush", (0, 0x00FF))[0]
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 0, 0, 30, 30))
        by_name(self.w, "USER", "FillRect", hdc, (DATA, 0x300), red)
        self.assertEqual(g.screen.getpixel((15, 15)), before)
        self.assertEqual(g.screen.getpixel((5, 15)), (255, 0, 0))

if __name__ == "__main__":
    unittest.main()
