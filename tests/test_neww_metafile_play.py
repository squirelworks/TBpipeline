"""Issue #221: map modes and metafile playback, so the NIDA ATT course 93952606.TBK
("Parallel Resonance") gets past P430.

Leaving P430, ToolBook draws two packed pictures as metafiles: SaveDC, MM_ANISOTROPIC with the
*Ex window and viewport calls, then EnumMetaFile with a callback that plays each record with
PlayMetaFileRecord. Each metafile sets its window extent and draws an 8-bit DIB twice with
META_STRETCHDIB (SRCPAINT, then SRCAND). On main the *Ex calls and EnumMetaFile were answered 0
by their spec rows and LPtoDP stopped in map mode 8.

Every value is Wine 2528aff2:
- dlls/win32u/mapping.c:113 set_map_mode, :89 MAPPING_FixIsotropic, :265 lp_to_dp, :185 dp_to_lp,
  :300/:333 the Scale*ExtEx calls; dlls/win32u/dc.c:417 construct_window_to_viewport;
  dlls/win32u/ntgdi_private.h:108 GDI_ROUND
- dlls/gdi32/dc.c:1164-1310 the Get/Set/Offset window and viewport calls
- dlls/gdi.exe16/gdi.c:535-614 (the Win 3.0 forms) and :3103-3291 (the Ex forms)
- dlls/gdi.exe16/metafile.c:115 DeleteMetaFile16, :153 IsValidMetaFile16, :172 PlayMetaFile16,
  :185 EnumMetaFile16, :275 GetMetaFileBits16; dlls/gdi.exe16/gdi.c:2072 PlayMetaFileRecord16
- dlls/gdi32/metafile.c:361 PlayMetaFile, :528 PlayMetaFileRecord, :113 bitmap_info_size

The synthetic tests need nothing. The course test needs TBK_BIN and TBK_BOOK3 (the path of
93952606.TBK with nida81.tbk and the nc81/tb80 system books beside it) and skips without them.
"""

import os
import struct
import unittest

from tests.test_neww_batch1_handlers import DATA, NUL, put
from tests.test_neww_batch2 import by_name
from tests.test_neww_batch6 import control_wine

MM_TEXT, MM_LOMETRIC, MM_ISOTROPIC, MM_ANISOTROPIC = 1, 2, 7, 8
OUT = (DATA, 0x380)
SRCCOPY = (0x00CC, 0x0020)


def record(function, *words, tail=b""):
    body = struct.pack(f"<{len(words)}H", *(w & 0xFFFF for w in words)) + tail
    assert len(body) % 2 == 0
    return struct.pack("<IH", 3 + len(body) // 2, function) + body


def metafile(records, objects=0):
    body = b"".join(records) + record(0x0000)
    words = (18 + len(body)) // 2
    biggest = max(struct.unpack_from("<I", r)[0] for r in records + [record(0)])
    return struct.pack("<HHHIHIH", 1, 9, 0x300, words, objects, biggest, 0) + body


# A 2x2 24-bit bottom-up DIB: bottom row red, green; top row blue, white.
DIB = (struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, 0, 0, 0, 0, 0)
       + bytes([0, 0, 255, 0, 255, 0, 0, 0]) + bytes([255, 0, 0, 255, 255, 255, 0, 0]))


def stretch_dib(x, y, w, h, sx, sy, sw, sh, rop=0x00CC0020):
    """META_STRETCHDIB: rdParm is rop (2 words), usage, then srcH srcW ySrc xSrc destH destW yDst
    xDst, last argument first, and the packed DIB."""
    return record(0x0F43, rop & 0xFFFF, rop >> 16, 0, sh, sw, sy, sx, h, w, y, x, tail=DIB)


class Base(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()

    def call(self, name, *a):
        ax, dx, stop, _made = by_name(self.w, "GDI", name, *a)
        self.assertIsNone(stop, name)
        return ax

    def dc(self, cx=4, cy=4):
        screen = self.call("CreateDC", put(self.w, 0x10, "DISPLAY"), NUL, NUL, NUL)
        dc = self.call("CreateCompatibleDC", screen)
        self.call("SelectObject", dc, self.call("CreateCompatibleBitmap", screen, cx, cy))
        return dc

    def pair(self):
        return struct.unpack("<hh", self.w.memory.read(DATA, 0x380, 4))

    def pixel(self, dc, x, y):
        ax, dx = by_name(self.w, "GDI", "GetPixel", dc, x, y)[:2]
        return dx << 16 | ax


class MapModes(Base):
    def test_anisotropic_lp_to_dp_scales_and_rounds(self):
        dc = self.dc()
        self.assertEqual(self.call("SetMapMode", dc, MM_ANISOTROPIC), MM_TEXT)
        self.assertEqual(self.call("SetWindowExtEx", dc, 3, 3, OUT), 1)
        self.assertEqual(self.pair(), (1, 1))                      # the old extent
        self.assertEqual(self.call("SetViewportExtEx", dc, 2, -2 & 0xFFFF, OUT), 1)
        self.assertEqual(self.call("SetWindowOrgEx", dc, 1, 1, OUT), 1)
        self.assertEqual(self.pair(), (0, 0))
        self.assertEqual(self.call("SetViewportOrgEx", dc, 10, 20, OUT), 1)
        # x * 2/3 + (10 - 2/3), y * -2/3 + (20 + 2/3), each GDI_ROUNDed.
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 0, 0, 2, 2))
        self.assertEqual(self.call("LPtoDP", dc, (DATA, 0x300), 2), 1)
        self.assertEqual(struct.unpack("<hhhh", self.w.memory.read(DATA, 0x300, 8)), (9, 21, 11, 19))
        self.w.memory.write(DATA, 0x300, struct.pack("<hh", 11, 19))
        self.assertEqual(self.call("DPtoLP", dc, (DATA, 0x300), 1), 1)
        self.assertEqual(struct.unpack("<hh", self.w.memory.read(DATA, 0x300, 4)), (3, 3))   # 2.5 rounds up

    def test_get_ex_calls_write_the_pairs(self):
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.call("SetWindowExtEx", dc, 7, 9, NUL)
        self.call("SetViewportExtEx", dc, 5, 6, NUL)
        self.call("SetWindowOrgEx", dc, -3 & 0xFFFF, 4, NUL)
        self.call("SetViewportOrgEx", dc, 11, 12, NUL)
        for name, want in (("GetWindowExtEx", (7, 9)), ("GetViewportExtEx", (5, 6)),
                           ("GetWindowOrgEx", (-3, 4)), ("GetViewportOrgEx", (11, 12))):
            self.assertEqual(self.call(name, dc, OUT), 1, name)
            self.assertEqual(self.pair(), want, name)

    def test_extents_stay_outside_isotropic_and_anisotropic(self):
        # SetWindowExtEx: TRUE and the old size, nothing changed, in the fixed modes.
        dc = self.dc()
        self.assertEqual(self.call("SetWindowExtEx", dc, 5, 5, OUT), 1)
        self.call("GetWindowExtEx", dc, OUT)
        self.assertEqual(self.pair(), (1, 1))

    def test_a_zero_extent_is_false(self):
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.assertEqual(self.call("SetViewportExtEx", dc, 0, 5, OUT), 0)
        self.assertEqual(self.call("SetWindowExt", dc, 0, 5), 0)

    def test_win30_forms_answer_the_old_pair(self):
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.assertEqual(self.call("SetWindowExt", dc, 7, 9), 1)              # LOWORD of (1, 1)
        self.assertEqual(by_name(self.w, "GDI", "SetWindowExt", dc, 2, 3)[:2], (7, 9))
        self.assertEqual(by_name(self.w, "GDI", "OffsetWindowOrg", dc, 2, 3)[:2], (0, 0))
        self.assertEqual(by_name(self.w, "GDI", "GetWindowOrg", dc)[:2], (2, 3))

    def test_lometric_takes_the_display_size(self):
        # set_map_mode: window = HORZSIZE/VERTSIZE (271, 203 mm) x 10, viewport = (1024, -768).
        dc = self.dc()
        self.assertEqual(self.call("SetMapMode", dc, MM_LOMETRIC), MM_TEXT)
        self.call("GetWindowExtEx", dc, OUT)
        self.assertEqual(self.pair(), (2710, 2030))
        self.call("GetViewportExtEx", dc, OUT)
        self.assertEqual(self.pair(), (1024, -768))

    def test_isotropic_shrinks_the_wider_viewport_extent(self):
        # MAPPING_FixIsotropic: 800 * 271 / (1024 * 100) > 300 * 203 / (768 * 100), so
        # cx = GDI_ROUND(800 * ydim / xdim) = 300.
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ISOTROPIC)
        self.call("SetWindowExtEx", dc, 100, 100, NUL)
        self.call("SetViewportExtEx", dc, 800, 300, NUL)
        self.call("GetViewportExtEx", dc, OUT)
        self.assertEqual(self.pair(), (300, 300))

    def test_scale_viewport_ext(self):
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.call("SetViewportExtEx", dc, 10, 10, NUL)
        self.assertEqual(self.call("ScaleViewportExtEx", dc, 3, 2, 1, 4, OUT), 1)
        self.assertEqual(self.pair(), (10, 10))
        self.call("GetViewportExtEx", dc, OUT)
        self.assertEqual(self.pair(), (15, 2))
        self.assertEqual(self.call("ScaleViewportExtEx", dc, 0, 2, 1, 4, OUT), 0)

    def test_stretch_di_bits_fills_the_device_size(self):
        # A 2x2 logical destination at scale 2 is 4x4 device pixels.
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.call("SetWindowExtEx", dc, 2, 2, NUL)
        self.call("SetViewportExtEx", dc, 4, 4, NUL)
        self.w.memory.write(DATA, 0x400, DIB)
        self.call("StretchDIBits", dc, 0, 0, 2, 2, 0, 0, 2, 2, (DATA, 0x428), (DATA, 0x400), 0, SRCCOPY)
        self.call("SetMapMode", dc, MM_TEXT)
        self.assertEqual(self.pixel(dc, 0, 0), 0xFF0000)        # top left blue
        self.assertEqual(self.pixel(dc, 3, 3), 0x00FF00)        # bottom right green
        self.assertEqual(self.pixel(dc, 1, 3), 0x0000FF)        # bottom left red

    def test_text_through_a_scaling_transform_stops_by_name(self):
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.call("SetViewportExtEx", dc, 2, 2, NUL)
        stop = by_name(self.w, "GDI", "TextOut", dc, 0, 0, put(self.w, 0x10, "Hi"), 2)[2]
        self.assertIn("MM_TEXT units only", stop)


class Metafiles(Base):
    def block(self, data):
        handle = by_name(self.w, "KERNEL", "GlobalAlloc", 0x42, (0, len(data)))[0]
        sel = self.w.selector_of(handle)
        self.w.memory.write(sel, 0, data)
        return handle, sel

    def picture(self):
        """Window extent 2x2, a DIB drawn over it, as ToolBook's packed pictures do."""
        return metafile([record(0x001E), record(0x020B, 0, 0), record(0x020C, 2, 2),
                         record(0x0416, 2, 2, 0, 0), stretch_dib(0, 0, 2, 2, 0, 0, 2, 2),
                         record(0x0127, -1 & 0xFFFF)])

    def scaled_dc(self):
        dc = self.dc()
        self.call("SetMapMode", dc, MM_ANISOTROPIC)
        self.call("SetViewportExtEx", dc, 4, 4, NUL)
        return dc

    def test_play_metafile_draws_through_the_dcs_transform(self):
        dc = self.scaled_dc()
        hmf, _sel = self.block(self.picture())
        self.assertEqual(self.call("IsValidMetaFile", hmf), 1)
        self.assertEqual(self.call("PlayMetaFile", dc, hmf), 1)
        self.call("GetWindowExtEx", dc, OUT)
        self.assertEqual(self.pair(), (1, 1))                   # META_RESTOREDC put it back
        self.call("SetMapMode", dc, MM_TEXT)
        self.assertEqual(self.pixel(dc, 0, 0), 0xFF0000)
        self.assertEqual(self.pixel(dc, 3, 3), 0x00FF00)

    def test_play_metafile_keeps_the_brush_and_deletes_its_objects(self):
        dc = self.dc()
        brush = self.call("CreateSolidBrush", (0, 0x00FF))
        self.call("SelectObject", dc, brush)
        logbrush = struct.pack("<HIH", 0, 0x00FF0000, 0)
        mf = metafile([record(0x02FC, *struct.unpack("<4H", logbrush)), record(0x012D, 0),
                       record(0x061D, 0x0021, 0x00F0, 2, 2, 0, 0)], objects=1)
        hmf, _sel = self.block(mf)
        before = set(self.w.gdi.objects)
        self.assertEqual(self.call("PlayMetaFile", dc, hmf), 1)
        self.assertEqual(self.pixel(dc, 1, 1), 0xFF0000)        # PatBlt with the record's brush
        self.assertEqual(self.w.gdi.objects[dc].brush, brush)
        self.assertEqual(set(self.w.gdi.objects), before)       # the record's brush is deleted

    def test_enum_metafile_calls_back_for_every_record(self):
        dc = self.scaled_dc()
        mf = self.picture()
        hmf, sel = self.block(mf)
        seen = []

        def reply(call):
            seen.append(call.words)
            _hdc, _ts, _to, msel, moff, _n, _dh, _dl = call.words
            by_name(self.w, "GDI", "PlayMetaFileRecord", dc, NUL, (msel, moff), 0)
            return 1, 0

        ax, _dx, stop, made = by_name(self.w, "GDI", "EnumMetaFile", dc, hmf, (0x0120, 0x0040),
                                      (0x1234, 0x5678), reply=reply)
        self.assertIsNone(stop)
        self.assertEqual(ax, 1)
        # Six records and META_EOF; no objects, so the table is NULL (a discarded block's lock).
        self.assertEqual(len(made), 7)
        self.assertEqual((made[0].cs, made[0].ip), (0x0120, 0x0040))
        self.assertEqual(seen[0], [dc, 0, 0, sel, 18, 0, 0x1234, 0x5678])
        self.assertEqual(seen[1][3:5], [sel, 18 + 6])
        self.call("SetMapMode", dc, MM_TEXT)
        self.assertEqual(self.pixel(dc, 3, 3), 0x00FF00)

    def test_enum_metafile_stops_on_a_zero_answer(self):
        dc = self.dc()
        hmf, _sel = self.block(self.picture())
        ax, _dx, stop, made = by_name(self.w, "GDI", "EnumMetaFile", dc, hmf, (0x0120, 0x0040), (0, 0),
                                      reply=lambda call: (0, 0))
        self.assertIsNone(stop)
        self.assertEqual((ax, len(made)), (0, 1))

    def test_enum_metafile_table_is_a_zeroed_guest_block(self):
        dc = self.dc()
        logbrush = struct.unpack("<4H", struct.pack("<HIH", 0, 0x000000FF, 0))
        hmf, _sel = self.block(metafile([record(0x02FC, *logbrush)], objects=2))
        tables = []

        def reply(call):
            _hdc, tsel, toff, msel, moff, n, _dh, _dl = call.words
            tables.append(self.w.memory.read(tsel, toff, 2 * n))
            by_name(self.w, "GDI", "PlayMetaFileRecord", dc, (tsel, toff), (msel, moff), n)
            tables.append(self.w.memory.read(tsel, toff, 2 * n))
            return 1, 0

        before = set(self.w.gdi.objects)
        by_name(self.w, "GDI", "EnumMetaFile", dc, hmf, (0x0120, 0x0040), (0, 0), reply=reply)
        self.assertEqual(tables[0], b"\0\0\0\0")
        handle = struct.unpack("<H", tables[1][:2])[0]
        self.assertTrue(handle)
        self.assertNotIn(handle, before)
        self.assertNotIn(handle, self.w.gdi.objects)            # deleted when the walk ends

    def test_get_metafile_bits_and_delete(self):
        hmf, _sel = self.block(self.picture())
        self.assertEqual(self.call("GetMetaFileBits", hmf), hmf)
        self.assertEqual(self.call("DeleteMetaFile", hmf), 1)

    def test_an_unplayed_record_stops_by_name(self):
        dc = self.dc()
        hmf, _sel = self.block(metafile([record(0x0538, 0)]))
        stop = by_name(self.w, "GDI", "PlayMetaFile", dc, hmf)[2]
        self.assertIn("META_POLYPOLYGON", stop)


class CourseGetsPastP430(unittest.TestCase):
    def test_seventh_next_draws_p440_and_ends_idle(self):
        from tests.binpath import bin_or_skip
        from tbpipeline_neww import machine
        book = os.environ.get("TBK_BOOK3")
        if not book:
            raise unittest.SkipTest("TBK_BOOK3 (93952606.TBK) is not set")
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        script = "wait 15000; click 512,420; wait 8000" + "; click 808,600; wait 8000" * 7
        host = machine.Machine(str(root), book, input_script=script, idle_stop=True)
        host.call_limit = 1000000
        host.timeout_us = 10 ** 10
        host.run(limit=host.call_limit * 1000)
        print(f"\n  stopped {host.stop} | calls {host.calls}")
        trace = host.box.wine.trace
        self.assertTrue(host.stop.startswith("idle:"), host.stop)
        self.assertNotIn("default", " ".join(t for t in trace if "EnumMetaFile" in t))
        self.assertIn("GDI.351 ExtTextOut 'P440'", trace)
        self.assertEqual(sum(1 for t in trace if t.startswith("GDI.175 EnumMetaFile")), 2)
        self.assertEqual(sum(1 for t in trace if t.startswith("GDI.176 PlayMetaFileRecord")), 22)


if __name__ == "__main__":
    unittest.main()
