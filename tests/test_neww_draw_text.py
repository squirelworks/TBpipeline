"""DrawText and DrawFocusRect (#227): the Instructor templates (learn1.tbk and its kin) draw their
choice labels with DrawText(DT_SINGLELINE) and a focus rectangle, once the walk turns pages.
Wine 2528aff2 dlls/user32/text.c:602, :865 and uitools.c:1485."""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine


class NextLine(unittest.TestCase):
    def test_prefixes_and_line_breaks(self):
        from tbpipeline_neww.user_text import next_line, DT_SINGLELINE, DT_NOPREFIX
        self.assertEqual(next_line("&Open", 0, 0), ("Open", None, 0))
        self.assertEqual(next_line("A && B", 0, 0), ("A & B", None, -1))
        self.assertEqual(next_line("&Open", 0, DT_NOPREFIX), ("&Open", None, -1))
        self.assertEqual(next_line("one\r\ntwo", 0, 0), ("one", 5, -1))
        self.assertEqual(next_line("one\r\ntwo", 5, 0), ("two", None, -1))
        self.assertEqual(next_line("one\ntwo", 0, DT_SINGLELINE), ("one\ntwo", None, -1))
        # text.c:655: a last "&" is thrown away too; the offset is then past the line.
        self.assertEqual(next_line("Open&", 0, 0), ("Open", None, 4))
        self.assertEqual(next_line("&a&b", 0, 0), ("ab", None, 1))


class FocusPoints(unittest.TestCase):
    def test_every_other_pixel_round_from_the_top_right(self):
        from tbpipeline_neww.user_text import focus_points
        # A 3x3 rectangle: the path (2,0) (1,0) (0,0) (0,1) (0,2) (1,2) (2,2) (2,1), on, off, ...
        self.assertEqual(focus_points(0, 0, 3, 3), [(2, 0), (0, 0), (0, 2), (2, 2)])
        self.assertEqual(focus_points(0, 0, 0, 5), [])


class DrawText(unittest.TestCase):
    def setUp(self):
        self.w = window_wine()
        self.dc = by_name(self.w, "GDI", "CreateCompatibleDC", 0)[0]
        bmp = by_name(self.w, "GDI", "CreateCompatibleBitmap", self.dc, 64, 32)[0]
        by_name(self.w, "GDI", "SelectObject", self.dc, bmp)
        self.w.memory.write(DATA, 0x100, b"Choice #1\0")

    def draw(self, rect, flags, count=0xFFFF):
        self.w.memory.write(DATA, 0x200, struct.pack("<hhhh", *rect))
        out = by_name(self.w, "USER", "DrawText", self.dc, (DATA, 0x100), count, (DATA, 0x200), flags)
        return out, struct.unpack("<hhhh", self.w.memory.read(DATA, 0x200, 8))

    def test_calcrect_is_the_text_extent(self):
        from tbpipeline_neww import gdi16
        (ax, _dx, stop, _), rect = self.draw((4, 2, 4, 2), 0x20 | 0x400)
        dc = gdi16._dc(self.w, self.dc)
        height = gdi16.text_metrics(self.w, dc)["height"]
        self.assertIsNone(stop)
        self.assertEqual(ax, height)
        self.assertEqual(rect, (4, 2, 4 + gdi16.text_width(self.w, dc, "Choice #1"), 2 + height))

    def test_drawing_returns_the_height(self):
        (ax, _dx, stop, _), _rect = self.draw((0, 0, 64, 32), 0x20)
        self.assertIsNone(stop)
        self.assertGreater(ax, 0)

    def test_count_0_is_the_line_height_and_draws_nothing(self):
        (ax, _dx, stop, _), _rect = self.draw((0, 0, 64, 32), 0x20, count=0)
        self.assertIsNone(stop)
        self.assertGreater(ax, 0)

    def pixels(self, text, flags):
        from tbpipeline_neww import gdi16
        self.w.memory.write(DATA, 0x100, text + b"\0")
        dc = gdi16._dc(self.w, self.dc)
        img, _origin = gdi16.surface(self.w, dc)
        img.paste((0, 0, 0), (0, 0) + img.size)
        by_name(self.w, "GDI", "SetTextColor", self.dc, (0xFF, 0xFFFF))
        by_name(self.w, "GDI", "SetBkMode", self.dc, 1)
        (_ax, _dx, stop, _), _rect = self.draw((0, 0, 64, 32), flags)
        self.assertIsNone(stop)
        return img.copy(), dc

    def test_the_prefixed_character_is_underscored(self):
        """TEXT_DrawUnderscore (text.c:823): a text-colored line at tmAscent + 1 from the extent
        before the character to the extent through it less one, its last pixel left out."""
        from tbpipeline_neww import gdi16
        plain, dc = self.pixels(b"Open", 0x20)
        marked, _dc = self.pixels(b"&Open", 0x20)
        y = gdi16.text_metrics(self.w, dc)["ascent"] + 1
        end = gdi16.text_width(self.w, dc, "O") - 1
        changed = {(x, yy) for x in range(64) for yy in range(32)
                   if plain.getpixel((x, yy)) != marked.getpixel((x, yy))}
        self.assertTrue(changed)
        self.assertTrue(all(yy == y and 0 <= x < end for x, yy in changed), changed)
        self.assertEqual(marked.getpixel((0, y)), (255, 255, 255))

    def test_word_break_stops_by_name(self):
        (_ax, _dx, stop, _), _rect = self.draw((0, 0, 64, 32), 0x10)
        self.assertIn("word breaks", stop)


if __name__ == "__main__":
    unittest.main()
