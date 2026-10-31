"""Batch 6: what the real run needed to get from the SCROLLBAR window to a drawn first page.

Each test checks against the Wine function its docstring or comment names. No ToolBook bytes:
the NE files are built by tests/neww_ne.py, and handlers run on fake memory
(tests/test_neww_batch2.py's harness).
"""

import struct
import tempfile
import unittest

from tests import neww_ne
from tests.test_neww_batch1_handlers import DATA, NUL, put
from tests.test_neww_batch2 import INST, by_name, register, window_wine

RELAY = (0x0700, 1010 * 8)


def control_wine():
    w = window_wine()
    w.gate_address = lambda module, ordinal: RELAY if (module, ordinal) == ("USER", 1010) else None
    return w


def guest_reply(c):
    return (1, 0) if c.words[1:2] == [0x81] else (0, 0)


def top_window(w, style=(0x10CF, 0)):
    _atom, cls = register(w)
    return by_name(w, "USER", "CreateWindow", cls, put(w, 0x40, "Book"), style,
                   10, 20, 300, 200, 0, 0, INST, NUL, reply=guest_reply)[0]


def rect(w, off):
    return struct.unpack("<hhhh", w.memory.read(DATA, off, 8))


# ---------------------------------------------------------------- SCROLLBAR

class ScrollBarClass(unittest.TestCase):
    """win32u class.c builtin_classes and user.exe16 message.c alloc_win16_thunk."""

    def setUp(self):
        self.w = control_wine()

    def create(self, style, x=0, y=0, cx=100, cy=50):
        name = put(self.w, 0x60, "scrollbar")
        return by_name(self.w, "USER", "CreateWindow", name, NUL, style, x, y, cx, cy, 0, 0, INST, NUL)

    def test_the_class_is_wines_with_a_thunk_procedure(self):
        # SBS_VERT | SBS_RIGHTALIGN, a popup so it has no parent, not visible.
        hwnd, _dx, stop, calls = self.create((0x8000, 0x0005))
        self.assertIsNone(stop)
        self.assertNotEqual(hwnd, 0)
        # Every message went to Wine's own procedure: no guest call.
        self.assertEqual(calls, [])
        proc = by_name(self.w, "USER", "GetWindowLong", hwnd, 0xFFFC)
        sel, off = proc[1], proc[0]
        # NTUSER_WNDPROC_SCROLLBAR is index 0, at offset 0 of the GlobalAlloc16 block.
        self.assertEqual(off, 0)
        self.assertEqual(sel, self.w.winproc_selector)
        # popl %eax ; pushl $0xFFFF0000 ; pushl %eax ; ljmp USER.1010: 15 bytes, packed.
        thunk = self.w.memory.read(sel, 0, 15)
        self.assertEqual(thunk, bytes.fromhex("6658" "6668" "0000ffff" "6650" "ea") + struct.pack("<HH", RELAY[1], RELAY[0]))

    def test_right_align_makes_it_one_scroll_width_wide(self):
        # create_scroll_bar: SBS_RIGHTALIGN moves it to x + cx - SM_CXVSCROLL - 1, SM_CXVSCROLL + 1 wide.
        hwnd = self.create((0x8000, 0x0005), x=5, y=6, cx=100, cy=50)[0]
        by_name(self.w, "USER", "GetWindowRect", hwnd, (DATA, 0x300))
        self.assertEqual(rect(self.w, 0x300), (5 + 100 - 17, 6, 5 + 100, 6 + 50))

    def test_ctl_range_and_position(self):
        hwnd = self.create((0x8000, 0x0001))[0]
        call = lambda name, *a: by_name(self.w, "USER", name, *a)
        self.assertIsNone(call("SetScrollRange", hwnd, 2, 10, 20, 0)[2])
        # set_scroll_info clamps the position to the range; SetScrollPos answers the old one.
        self.assertEqual(call("SetScrollPos", hwnd, 2, 50, 0)[0], 10)
        self.assertEqual(call("GetScrollPos", hwnd, 2)[0], 20)
        call("GetScrollRange", hwnd, 2, (DATA, 0x300), (DATA, 0x302))
        self.assertEqual(struct.unpack("<hh", self.w.memory.read(DATA, 0x300, 4)), (10, 20))

    def test_a_window_bar_starts_at_100(self):
        # get_scroll_info_ptr gives a window's bars a range of 0..100.
        hwnd = top_window(self.w, style=(0x00CF, 0))
        self.assertEqual(by_name(self.w, "USER", "SetScrollPos", hwnd, 1, 30, 0)[0], 0)
        self.assertEqual(by_name(self.w, "USER", "GetScrollPos", hwnd, 1)[0], 30)
        by_name(self.w, "USER", "GetScrollRange", hwnd, 1, (DATA, 0x300), (DATA, 0x302))
        self.assertEqual(struct.unpack("<hh", self.w.memory.read(DATA, 0x300, 4)), (0, 100))

    def test_wine_call_wndproc_with_an_unknown_procedure_stops(self):
        _ax, _dx, stop, _calls = by_name(self.w, "USER", "__wine_call_wndproc", 0x22, 0x0F, 0, (0, 0), (0xFFFF, 0x0005))
        self.assertIn("USER.1010 __wine_call_wndproc(0xffff0005)", stop)


# ---------------------------------------------------------------- rectangles

class Rects(unittest.TestCase):
    """user.c's rectangle functions over RECT16."""

    def setUp(self):
        self.w = control_wine()

    def call(self, name, *a):
        return by_name(self.w, "USER", name, *a)[0]

    def put(self, off, l, t, r, b):
        self.w.memory.write(DATA, off, struct.pack("<hhhh", l, t, r, b))
        return (DATA, off)

    def test_set_offset_inflate(self):
        r = (DATA, 0x300)
        self.call("SetRect", r, 1, 2, 3, 4)
        self.call("OffsetRect", r, 10, -1)
        self.call("InflateRect", r, 2, 3)
        self.assertEqual(rect(self.w, 0x300), (9, -2, 15, 6))
        self.call("SetRectEmpty", r)
        self.assertEqual(rect(self.w, 0x300), (0, 0, 0, 0))
        self.assertEqual(self.call("IsRectEmpty", r), 1)

    def test_intersect_union_subtract(self):
        a, b, out = self.put(0x300, 0, 0, 10, 10), self.put(0x308, 5, 5, 20, 20), (DATA, 0x310)
        self.assertEqual(self.call("IntersectRect", out, a, b), 1)
        self.assertEqual(rect(self.w, 0x310), (5, 5, 10, 10))
        self.assertEqual(self.call("UnionRect", out, a, b), 1)
        self.assertEqual(rect(self.w, 0x310), (0, 0, 20, 20))
        # No overlap: IntersectRect empties the result and answers FALSE.
        c = self.put(0x318, 30, 30, 40, 40)
        self.assertEqual(self.call("IntersectRect", out, a, c), 0)
        self.assertEqual(rect(self.w, 0x310), (0, 0, 0, 0))
        # SubtractRect: a whole side cut off leaves a rectangle.
        d = self.put(0x320, 5, -1, 11, 11)
        self.assertEqual(self.call("SubtractRect", out, a, d), 1)
        self.assertEqual(rect(self.w, 0x310), (0, 0, 5, 10))

    def test_pt_in_rect_and_equal(self):
        a = self.put(0x300, 0, 0, 10, 10)
        self.assertEqual(self.call("PtInRect", a, (9, 0)), 1)       # POINT16 as a long: y high, x low
        self.assertEqual(self.call("PtInRect", a, (0, 10)), 0)      # right edge excluded
        self.assertEqual(self.call("EqualRect", a, self.put(0x308, 0, 0, 10, 10)), 1)

    def test_free_system_resources(self):
        # A fresh 16-bit heap of LocalInit16(sel, 0x100, 0x100 + 65520) is 99% free.
        from tbpipeline_neww.user16 import fresh_heap_percent
        self.assertEqual(fresh_heap_percent(0x100), 99)
        for kind in (0, 1, 2):
            self.assertEqual(self.call("GetFreeSystemResources", kind), 99)
        self.assertEqual(self.call("GetFreeSystemResources", 3), 0)

    def test_realize_palette_is_zero(self):
        # nulldrv_RealizePalette: a display with no palette realizes nothing.
        self.assertEqual(by_name(self.w, "USER", "RealizePalette", 0x1004)[:3], (0, 0, None))


# ---------------------------------------------------------------- GDI

class Gdi(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()

    def call(self, name, *a):
        return by_name(self.w, "GDI", name, *a)[0]

    def color_dc(self, cx=4, cy=4):
        screen = self.call("CreateDC", put(self.w, 0x10, "DISPLAY"), NUL, NUL, NUL)
        dc = self.call("CreateCompatibleDC", screen)
        self.call("SelectObject", dc, self.call("CreateCompatibleBitmap", screen, cx, cy))
        return dc

    def dib(self):
        """A 2x2 24-bit bottom-up DIB: bottom row red, green; top row blue, white."""
        self.w.memory.write(DATA, 0x400, struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, 0, 0, 0, 0, 0))
        rows = bytes([0, 0, 255, 0, 255, 0, 0, 0]) + bytes([255, 0, 0, 255, 255, 255, 0, 0])
        self.w.memory.write(DATA, 0x500, rows)
        return (DATA, 0x500), (DATA, 0x400)

    def pixel(self, dc, x, y):
        ax, dx = by_name(self.w, "GDI", "GetPixel", dc, x, y)[:2]
        return dx << 16 | ax

    def test_stretch_di_bits_doubles_and_answers_the_height(self):
        # nulldrv_StretchDIBits: SRCCOPY answers the DIB's height.
        dc = self.color_dc()
        bits, info = self.dib()
        got = self.call("StretchDIBits", dc, 0, 0, 4, 4, 0, 0, 2, 2, bits, info, 0, (0x00CC, 0x0020))
        self.assertEqual(got, 2)
        self.assertEqual(self.pixel(dc, 0, 0), 0xFF0000)       # top left: blue (COLORREF 0x00BBGGRR)
        self.assertEqual(self.pixel(dc, 3, 0), 0xFFFFFF)
        self.assertEqual(self.pixel(dc, 1, 3), 0x0000FF)       # bottom left: red
        self.assertEqual(self.pixel(dc, 3, 3), 0x00FF00)

    def test_stretch_di_bits_off_the_dib_is_zero(self):
        dc = self.color_dc()
        bits, info = self.dib()
        self.assertEqual(self.call("StretchDIBits", dc, 0, 0, 4, 4, 5, 5, 2, 2, bits, info, 0, (0x00CC, 0x0020)), 0)

    def test_mul_div(self):
        # gdi.c MulDiv16: rounded away from zero, -32768 for a zero divisor or an overflow.
        for a, b, d, want in ((10, 3, 4, 8), (-10, 3, 4, -8), (7, 1, -2, -4), (5, 5, 0, -32768), (30000, 30000, 1, -32768)):
            self.assertEqual(self.call("MulDiv", a & 0xFFFF, b & 0xFFFF, d & 0xFFFF), want & 0xFFFF, (a, b, d))

    def test_lp_to_dp_moves_by_the_origins(self):
        dc = self.color_dc()
        self.call("SetViewportOrg", dc, 5, 6)
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 1, 2, 3, 4))
        self.assertEqual(self.call("LPtoDP", dc, (DATA, 0x300), 2), 1)
        self.assertEqual(struct.unpack("<hhhh", self.w.memory.read(DATA, 0x300, 8)), (6, 8, 8, 10))
        self.assertEqual(self.call("DPtoLP", dc, (DATA, 0x300), 2), 1)
        self.assertEqual(struct.unpack("<hhhh", self.w.memory.read(DATA, 0x300, 8)), (1, 2, 3, 4))

    def test_fill_rgn_and_rect_in_region(self):
        dc = self.color_dc()
        rgn = self.call("CreateRectRgn", 1, 1, 3, 3)
        brush = self.call("CreateSolidBrush", (0x0000, 0x00FF))
        self.assertEqual(self.call("FillRgn", dc, rgn, brush), 1)
        self.assertEqual(self.pixel(dc, 1, 1), 0x0000FF)
        self.assertEqual(self.pixel(dc, 3, 3), 0)
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 2, 2, 0, 0))   # ordered first
        self.assertEqual(self.call("RectInRegionOld", rgn, (DATA, 0x300)), 1)
        self.w.memory.write(DATA, 0x300, struct.pack("<hhhh", 3, 3, 9, 9))
        self.assertEqual(self.call("RectInRegion", rgn, (DATA, 0x300)), 0)

    def test_combine_or_with_an_empty_first_region_is_the_second(self):
        a, b, d = self.call("CreateRectRgn", 0, 0, 0, 0), self.call("CreateRectRgn", 0, 2, 152, 23), self.call("CreateRectRgn", 0, 0, 0, 0)
        self.assertEqual(self.call("CombineRgn", d, a, b, 2), 2)
        self.call("GetRgnBox", d, (DATA, 0x300))
        self.assertEqual(rect(self.w, 0x300), (0, 2, 152, 23))

    def test_memory_dc_caps_are_the_displays(self):
        # The dib driver has no GetDeviceCaps: nulldrv answers for a memory DC too.
        dc = self.color_dc()
        from tests.test_neww_batch1_handlers import call
        self.assertEqual(call(self.w, "GDI", 80, dc, 88)[:2], (96, 0))

    def test_spec_name_with_a_space_before_the_arguments(self):
        # '439 pascal -ret16 StretchDIBits (word ...)': the space is allowed.
        from tbpipeline_neww.handlers import spec_types
        self.assertEqual(spec_types("GDI", "StretchDIBits")[0], 439)


# ---------------------------------------------------------------- windows

class Windows(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()

    def test_style_change_sends_nothing_to_a_16_bit_procedure(self):
        # WINPROC_CallProc32ATo16 drops WM_STYLECHANGING and WM_STYLECHANGED.
        hwnd = top_window(self.w, style=(0x00CF, 0))
        ax, dx, stop, calls = by_name(self.w, "USER", "SetWindowLong", hwnd, 0xFFF0, (0x00C0, 0x0000))
        self.assertIsNone(stop)
        self.assertEqual(calls, [])
        self.assertEqual(dx << 16 | ax, 0x00CF0000 | 0x04000000)
        style = by_name(self.w, "USER", "GetWindowLong", hwnd, 0xFFF0)
        # A top-level window keeps WS_CLIPSIBLINGS.
        self.assertEqual(style[1] << 16 | style[0], 0x00C00000 | 0x04000000)

    def test_ex_style_window_edge_follows_the_frame(self):
        hwnd = top_window(self.w, style=(0x00CF, 0))
        by_name(self.w, "USER", "SetWindowLong", hwnd, 0xFFEC, (0, 0))
        ex = by_name(self.w, "USER", "GetWindowLong", hwnd, 0xFFEC)
        self.assertEqual(ex[0] & 0x100, 0x100)   # fix_exstyle: WS_THICKFRAME gives WS_EX_WINDOWEDGE

    def test_visibility_change_stops(self):
        hwnd = top_window(self.w, style=(0x00CF, 0))
        stop = by_name(self.w, "USER", "SetWindowLong", hwnd, 0xFFF0, (0x10CF, 0))[2]
        self.assertIn("changes WS_VISIBLE", stop)

    def test_is_menu(self):
        hwnd = top_window(self.w)
        menu = by_name(self.w, "USER", "GetSystemMenu", hwnd, 0)[0]
        self.assertEqual(by_name(self.w, "USER", "IsMenu", menu)[0], 1)
        self.assertEqual(by_name(self.w, "USER", "IsMenu", 0x7777)[0], 0)

    def test_drag_accept_files_sets_the_ex_style(self):
        hwnd = top_window(self.w)
        by_name(self.w, "SHELL", "DragAcceptFiles", hwnd, 1)
        ex = by_name(self.w, "USER", "GetWindowLong", hwnd, 0xFFEC)
        self.assertEqual(ex[0] & 0x10, 0x10)

    def test_window_from_point_asks_the_window(self):
        # window_from_point: the window under the point gets WM_NCHITTEST; the desktop is last.
        hwnd = top_window(self.w)
        point = (100 << 16) | 50
        got = by_name(self.w, "USER", "WindowFromPoint", (100, 50), reply=lambda c: (1, 0))
        self.assertEqual(got[0], hwnd)
        self.assertEqual([c.words[1] for c in got[3]], [0x84])
        self.assertEqual(got[3][0].words[3:5], [100, 50])
        # HTTRANSPARENT goes on to the next window down, here the desktop.
        from tbpipeline_neww.user_wnd import wm
        got = by_name(self.w, "USER", "WindowFromPoint", (100, 50), reply=lambda c: (0xFFFF, 0xFFFF))
        self.assertEqual(got[0], wm(self.w).desktop)
        self.assertEqual(point >> 16, 100)

    def test_def_window_proc_hit_test(self):
        hwnd = top_window(self.w)
        from tbpipeline_neww.user_wnd import wm
        w = wm(self.w).get(hwnd)
        cl, ct = w.client[:2]
        self.assertEqual(by_name(self.w, "USER", "DefWindowProc", hwnd, 0x84, 0, (ct + 1, cl + 1))[0], 1)
        self.assertEqual(by_name(self.w, "USER", "DefWindowProc", hwnd, 0x84, 0, (900, 900))[0], 0)

    def test_cursor(self):
        # NtUserGetCursor before any SetCursor: the shared IDC_WAIT cursor; after, the one set.
        first = by_name(self.w, "USER", "GetCursor")[0]
        self.assertNotEqual(first, 0)
        by_name(self.w, "USER", "SetCursor", 0x1234)
        self.assertEqual(by_name(self.w, "USER", "GetCursor")[0], 0x1234)
        by_name(self.w, "USER", "SetCursorPos", 2000, 7)
        by_name(self.w, "USER", "GetCursorPos", (DATA, 0x300))
        self.assertEqual(struct.unpack("<hh", self.w.memory.read(DATA, 0x300, 4)), (1023, 7))
        # set_cursor_pos queues a WM_MOUSEMOVE hardware message at the clipped position.
        raw = self.w.input.raw[-1]
        self.assertEqual((raw.msg, raw.x, raw.y), (0x200, 1023, 7))

    def test_activate_app_goes_to_the_new_tasks_windows_only(self):
        # set_active_window: from no active window, WM_ACTIVATEAPP (TRUE, old thread 0) goes to
        # the new thread's top-level windows, and not to another task's.
        from tbpipeline_neww.user_wnd import wm, set_active
        a = top_window(self.w, style=(0x00CF, 0))
        b = top_window(self.w, style=(0x00CF, 0))
        m = wm(self.w)
        self.w.htask = 0x222
        m.get(a).task, m.get(b).task = 0x111, 0x222
        m.active = 0
        sent = []
        gen = set_active(self.w, b, focus=False)
        try:
            req = next(gen)
            while True:
                if isinstance(req, str):
                    self.fail(req)
                sent.append((req.words[0], req.words[1], req.words[2], req.words[3] << 16 | req.words[4]))
                req = gen.send((0, 0))
        except StopIteration:
            pass
        self.assertEqual([s for s in sent if s[1] == 0x1C], [(b, 0x1C, 1, 0)])


# ---------------------------------------------------------------- modules

def dll(directory, name, modules=()):
    from tests.test_neww_dll_init import LIBMAIN
    blob = bytearray(neww_ne.build(name, [(0x0000, LIBMAIN, []), (0x0001, b"\x00" * 64, [])],
                                   modules=modules, entry=(1, 0), auto=2, heap=0x40, exe=False))
    struct.pack_into("<H", blob, 0x40 + 0x0C, 0x8001)
    neww_ne.write(directory, f"{name}.DLL", bytes(blob))


class Modules(unittest.TestCase):
    def run_program(self, dlls, modules=("KERNEL", "TB80UTL", "TB80W16")):
        from tbpipeline_neww.machine import Machine
        from tests.test_neww_inittask import program
        d = tempfile.mkdtemp()
        program(d, modules=modules)
        for name, deps in dlls:
            dll(d, name, deps)
        return Machine(d).run(limit=5000)

    def test_import_cycle_loads_each_once(self):
        # NE_InitializeDLLs clears dlls_to_init before walking it, so a cycle ends.
        host = self.run_program([("TB80UTL", ("TB80W16",)), ("TB80W16", ("TB80UTL",))])
        self.assertEqual(host.stop, "dos exit 0x0")

    def test_usage_counts_each_importer(self):
        # NE_LoadDLLs: the first importer loads a DLL (1), each later one adds 1.
        host = self.run_program([("TB80UTL", ()), ("TB80W16", ("TB80UTL",))])
        w = host.box.wine
        self.assertEqual(w.usage[w.modules["TB80UTL"]], 2)
        self.assertEqual(w.usage[w.modules["TB80W16"]], 1)

    def test_is_bad_code_ptr_reads_the_descriptor(self):
        # selector.c IsBadCodePtr16: a code block neww allocates is code, as Wine's thunks are.
        host = self.run_program([("TB80UTL", ()), ("TB80W16", ())])
        sel = host._alloc_code(0x100)
        self.assertTrue(host._is_code(sel))
        data = host.box.exe.segments[1].selector
        self.assertFalse(host._is_code(data))


# ---------------------------------------------------------------- the real book

class RealBook(unittest.TestCase):
    def test_first_page_draws(self):
        # TBK_BIN and TBK_BOOK: the title page's bitmap and text are drawn, and no error box shows.
        import os
        from tests.binpath import bin_or_skip
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL")
        book = os.environ.get("TBK_BOOK")
        if not book:
            raise unittest.SkipTest("TBK_BOOK is not set")
        from tbpipeline_neww.machine import Machine
        host = Machine(str(root), book)
        host.call_limit = 12000
        host.run(limit=12000 * 1000)
        trace = host.box.wine.trace
        print(f"\nneww stop: {host.stop} after {len(trace)} trace lines")
        self.assertEqual([t for t in trace if t.startswith("USER.1 MessageBox")], [])
        self.assertTrue(any(t.startswith("GDI.439 StretchDIBits") for t in trace))
        texts = [t for t in trace if t.startswith("GDI.33 TextOut")]
        self.assertTrue(any("Nida Corporation" in t for t in texts), texts[:3])
        # The page's pixels are not the desktop's: something was drawn in the book's window.
        shot = host.box.wine.gdi.screen
        self.assertGreater(len(set(shot.crop((108, 114, 660, 500)).getdata())), 1000)


if __name__ == "__main__":
    unittest.main()
