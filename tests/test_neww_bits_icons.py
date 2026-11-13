"""GetBitmapBits of a 32-bit bitmap and CreateIcon (#227): tb80acta.sbk reads a color bitmap's
bits and makes an icon of them. Wine 2528aff2 dlls/win32u/bitmap.c:231 and
dlls/user.exe16/user.c:2345, :2366."""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine


class BitmapBits(unittest.TestCase):
    def setUp(self):
        from tbpipeline_neww import gdi16
        self.w = window_wine()
        g = gdi16.gdi(self.w)
        bmp = g.new_bitmap(3, 2, 32)
        bmp.image.putpixel((0, 0), (0x11, 0x22, 0x33))
        self.h = g.add(bmp)

    def call(self, count, ptr):
        count &= 0xFFFFFFFF
        ax, dx, stop, _ = by_name(self.w, "GDI", "GetBitmapBits", self.h, (count >> 16, count & 0xFFFF), ptr)
        self.assertIsNone(stop)
        return ax | dx << 16

    def test_no_buffer_is_the_size(self):
        self.assertEqual(self.call(0, (0, 0)), 3 * 4 * 2)

    def test_bgrx_rows_top_down(self):
        self.assertEqual(self.call(-1, (DATA, 0x100)), 24)
        self.assertEqual(self.w.memory.read(DATA, 0x100, 4), b"\x33\x22\x11\x00")

    def test_count_is_kept_when_it_fits(self):
        self.assertEqual(self.call(5, (DATA, 0x100)), 5)


class CreateIcon(unittest.TestCase):
    def setUp(self):
        self.w = window_wine()
        self.w.selector_of = lambda handle: handle
        self.w.memory.write(DATA, 0x100, b"\xff\xff" * 2)            # AND: 2 rows of 16 px
        self.w.memory.write(DATA, 0x200, b"\x80\x00" * 2)            # XOR: 1 bit a pixel

    def test_planes_other_than_1_is_0(self):
        out = by_name(self.w, "USER", "CreateIcon", 0, 16, 2, 2, 1, (DATA, 0x100), (DATA, 0x200))
        self.assertEqual(out[:3], (0, 0, None))

    def test_the_block_is_cursoriconinfo_and_then_and_and_xor(self):
        handle, _dx, stop, _ = by_name(self.w, "USER", "CreateIcon", 0, 16, 2, 1, 1, (DATA, 0x100), (DATA, 0x200))
        self.assertIsNone(stop)
        head = self.w.read(handle, 0, 12)
        self.assertEqual(struct.unpack("<hhHHHBB", head), (0x4242, 0x4242, 16, 2, 2, 1, 1))
        self.assertEqual(self.w.read(handle, 12, 8), b"\xff\xff\xff\xff\x80\x00\x80\x00")
        self.assertEqual(self.w.icons[handle]["image"].getpixel((0, 0)), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
