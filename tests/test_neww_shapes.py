"""GDI shapes: Polygon, Polyline, Ellipse, RoundRect, Arc, Pie, Chord.

Logic Families draws its chip pins with Polygon and each chip's notch with Arc. These had no
handler, so the spec row answered 0 and nothing was drawn. The interior takes the brush, the
outline the pen, each mixed by the DC's ROP2; a null brush or pen leaves its part out.
"""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA, NUL, put
from tests.test_neww_batch2 import by_name
from tests.test_neww_batch6 import control_wine

RED, BLUE = (0x0000, 0x00FF), (0x00FF, 0x0000)   # COLORREF as (high, low) words
NULL_BRUSH = 5


class Shapes(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()
        screen = self.call("CreateDC", put(self.w, 0x10, "DISPLAY"), NUL, NUL, NUL)
        self.dc = self.call("CreateCompatibleDC", screen)
        self.call("SelectObject", self.dc, self.call("CreateCompatibleBitmap", screen, 40, 40))
        self.call("SelectObject", self.dc, self.call("CreatePen", 0, 1, BLUE))
        self.call("SelectObject", self.dc, self.call("CreateSolidBrush", RED))

    def call(self, name, *a):
        return by_name(self.w, "GDI", name, *a)[0]

    def pixel(self, x, y):
        ax, dx = by_name(self.w, "GDI", "GetPixel", self.dc, x, y)[:2]
        return dx << 16 | ax

    def points(self, *pts):
        self.w.memory.write(DATA, 0x300, b"".join(struct.pack("<hh", *p) for p in pts))
        return (DATA, 0x300), len(pts)

    def test_polygon_fills_with_the_brush_and_outlines_with_the_pen(self):
        ptr, n = self.points((5, 5), (30, 5), (30, 30), (5, 30))
        self.assertEqual(self.call("Polygon", self.dc, ptr, n), 1)
        self.assertEqual(self.pixel(15, 15), 0x0000FF)
        self.assertEqual(self.pixel(5, 15), 0xFF0000)
        self.assertEqual(self.pixel(35, 35), 0)

    def test_polygon_with_one_point_is_false(self):
        ptr, n = self.points((5, 5))
        self.assertEqual(self.call("Polygon", self.dc, ptr, n), 0)

    def test_polyline_draws_only_the_pen(self):
        ptr, n = self.points((5, 10), (30, 10))
        self.assertEqual(self.call("Polyline", self.dc, ptr, n), 1)
        self.assertEqual(self.pixel(15, 10), 0xFF0000)
        self.assertEqual(self.pixel(15, 12), 0)

    def test_ellipse_fills_its_middle_not_its_corners(self):
        self.assertEqual(self.call("Ellipse", self.dc, 0, 0, 40, 40), 1)
        self.assertEqual(self.pixel(20, 20), 0x0000FF)
        self.assertEqual(self.pixel(1, 1), 0)

    def test_a_null_brush_leaves_the_inside(self):
        self.call("SelectObject", self.dc, self.call("GetStockObject", NULL_BRUSH))
        self.call("RoundRect", self.dc, 2, 2, 38, 38, 6, 6)
        self.assertEqual(self.pixel(20, 20), 0)
        self.assertEqual(self.pixel(20, 2), 0xFF0000)

    def test_arc_goes_counterclockwise_from_start_to_end(self):
        # Start at 3 o'clock, end at 9 o'clock: counterclockwise is the top half.
        self.assertEqual(self.call("Arc", self.dc, 0, 0, 40, 40, 40, 20, 0, 20), 1)
        self.assertEqual(self.pixel(20, 0), 0xFF0000)
        self.assertEqual(self.pixel(20, 39), 0)

    def test_pie_fills_its_slice(self):
        self.call("Pie", self.dc, 0, 0, 40, 40, 40, 20, 0, 20)
        self.assertEqual(self.pixel(20, 10), 0x0000FF)
        self.assertEqual(self.pixel(20, 30), 0)


if __name__ == "__main__":
    unittest.main()
