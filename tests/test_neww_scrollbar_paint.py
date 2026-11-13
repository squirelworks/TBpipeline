"""Scroll bar painting: win32u/scroll.c draw_scroll_bar (:286) and refresh_scroll_bar (:379),
user32/scroll.c USER_ScrollBarDraw (:169), SCROLL_DrawArrows (:38) and SCROLL_DrawInterior
(:72), user32/uitools.c UITOOLS95_DrawFrameScroll (:972), and DefWindowProc's
WM_CTLCOLORSCROLLBAR, handle_control_color (win32u/defwnd.c:2337) with get_55aa_brush
(win32u/sysparams.c:7382).

No ToolBook bytes: windows are made by the handlers on fake memory (tests/test_neww_batch2.py).
"""

import unittest

from tests.test_neww_batch1_handlers import NUL, put
from tests.test_neww_batch2 import INST, by_name
from tests.test_neww_batch6 import control_wine, top_window

WHITE, FACE, DARK, BLACK, SHADOW = (255, 255, 255), (212, 208, 200), (64, 64, 64), (0, 0, 0), (128, 128, 128)


def pixel(w, hwnd, x, y):
    from tbpipeline_neww import gdi16, user_wnd
    ox, oy = user_wnd.screen_origin(w, hwnd)
    return gdi16.gdi(w).screen.getpixel((ox + x, oy + y))


class DefWindowProcScrollBarColor(unittest.TestCase):

    def test_ctlcolor_scrollbar_is_the_55aa_brush(self):
        from tbpipeline_neww import gdi16, user_wnd
        w = control_wine()
        hwnd = top_window(w)
        hdc = user_wnd.get_dc(w, hwnd)
        gen = user_wnd.def_window_proc(w, hwnd, 0x19, hdc, 5 << 16 | hwnd)
        try:
            gen.send(None)
            self.fail("DefWindowProc WM_CTLCOLOR yielded")
        except StopIteration as done:
            brush = done.value
        g = gdi16.gdi(w)
        obj = g.get(brush, gdi16.OBJ_BRUSH)
        # COLOR_3DHILIGHT is COLOR_WINDOW (both white), so the 0x55aa pattern brush.
        self.assertEqual(obj.style, gdi16.BS_PATTERN)
        bmp = g.get(obj.bitmap, gdi16.OBJ_BITMAP)
        self.assertEqual((bmp.width, bmp.height, bmp.bpp), (8, 8, 1))
        rows = [[bmp.image.getpixel((x, y))[0] > 127 for x in range(8)] for y in range(2)]
        self.assertEqual(rows[0], [False, True] * 4)    # 0x55
        self.assertEqual(rows[1], [True, False] * 4)    # 0xaa
        dc = g.get(hdc, gdi16.OBJ_DC)
        self.assertEqual(dc.text_color, 0xC8D0D4)       # COLOR_3DFACE
        self.assertEqual(dc.bk_color, 0xFFFFFF)         # COLOR_3DHILIGHT
        # Made once.
        self.assertEqual(user_wnd.brush_55aa(w), brush)


class ScrollBarPaint(unittest.TestCase):

    def setUp(self):
        self.w = control_wine()

    def bar(self, style, x=0, y=0, cx=100, cy=17, parent=0, reply=None):
        name = put(self.w, 0x60, "scrollbar")
        return by_name(self.w, "USER", "CreateWindow", name, NUL, style, x, y, cx, cy, parent, 0, INST, NUL,
                       reply=reply)[0]

    def shown_popup(self):
        # A popup bar (WS_POPUP, SBS_HORZ) shown with SW_SHOWNA, so it does not take the focus,
        # and with no owner: GetParent is 0, so no WM_CTLCOLORSCROLLBAR and the cache DC's
        # WHITE_BRUSH fills the interior.
        hwnd = self.bar((0x8000, 0x0000))
        self.assertIsNone(by_name(self.w, "USER", "ShowWindow", hwnd, 8)[2])
        return hwnd

    def test_set_scroll_range_with_redraw_draws_a_visible_bar(self):
        hwnd = self.shown_popup()
        ax, _dx, stop, calls = by_name(self.w, "USER", "SetScrollRange", hwnd, 2, 0, 10, 1)
        self.assertIsNone(stop)
        self.assertEqual(calls, [])
        # Left arrow (0,0)-(16,17), SM_CXVSCROLL 16 wide, EDGE_RAISED: 3DLIGHT then
        # BTNHIGHLIGHT top-left, 3DDKSHADOW then BTNSHADOW bottom-right.
        self.assertEqual(pixel(self.w, hwnd, 0, 0), FACE)
        self.assertEqual(pixel(self.w, hwnd, 1, 1), WHITE)
        self.assertEqual(pixel(self.w, hwnd, 15, 16), DARK)
        self.assertEqual(pixel(self.w, hwnd, 14, 15), SHADOW)
        # The arrow's triangle in the 16-pixel square: (9,5) (9,11) (6,8), a pixel up and
        # left, in COLOR_BTNTEXT.
        self.assertEqual(pixel(self.w, hwnd, 7, 7), BLACK)
        self.assertEqual(pixel(self.w, hwnd, 3, 7), FACE)
        # The thumb at position 0 sits right after the arrow, SM_CXVSCROLL wide (no page).
        self.assertEqual(pixel(self.w, hwnd, 16, 0), FACE)
        self.assertEqual(pixel(self.w, hwnd, 17, 1), WHITE)
        self.assertEqual(pixel(self.w, hwnd, 31, 16), DARK)
        self.assertEqual(pixel(self.w, hwnd, 24, 8), FACE)
        # The rest of the interior is the DC's brush.
        self.assertEqual(pixel(self.w, hwnd, 50, 8), WHITE)
        # The right arrow.
        self.assertEqual(pixel(self.w, hwnd, 99, 16), DARK)

    def test_moving_the_thumb_redraws(self):
        hwnd = self.shown_popup()
        by_name(self.w, "USER", "SetScrollRange", hwnd, 2, 0, 10, 0)
        _ax, _dx, stop, _calls = by_name(self.w, "USER", "SetScrollPos", hwnd, 2, 10, 1)
        self.assertIsNone(stop)
        # At the end: the thumb ends where the right arrow starts (100 - 16 = 84).
        self.assertEqual(pixel(self.w, hwnd, 83, 16), DARK)
        self.assertEqual(pixel(self.w, hwnd, 68, 0), FACE)
        self.assertEqual(pixel(self.w, hwnd, 24, 8), WHITE)

    def test_an_invisible_bar_draws_nothing(self):
        hwnd = self.bar((0x8000, 0x0000))
        before = pixel(self.w, hwnd, 24, 8)
        self.assertIsNone(by_name(self.w, "USER", "SetScrollRange", hwnd, 2, 0, 10, 1)[2])
        self.assertEqual(pixel(self.w, hwnd, 24, 8), before)

    def test_a_child_bar_asks_its_parent_for_the_brush(self):
        from tbpipeline_neww import gdi16, user_wnd
        parent = top_window(self.w)
        brush = user_wnd.brush_55aa(self.w)
        asked = []

        def reply(c):
            if c.words[1] == 0x19:
                asked.append((c.words[0], c.words[3], c.words[4]))
                return brush, 0
            return (1, 0) if c.words[1:2] == [0x81] else (0, 0)
        # WS_CHILD | WS_VISIBLE.
        hwnd = self.bar((0x5000, 0x0000), parent=parent)
        _ax, _dx, stop, _calls = by_name(self.w, "USER", "SetScrollRange", hwnd, 2, 0, 10, 1, reply=reply)
        self.assertIsNone(stop)
        # WM_CTLCOLOR to the parent: wParam the DC, lParam MAKELONG(hwnd, CTLCOLOR_SCROLLBAR).
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0][0], parent)
        self.assertEqual(asked[0][1:], (5, hwnd))
        # The pattern's 1 bits are the DC's background, 0 bits its text color (black, white
        # here: the guest did not set them).
        a, b = pixel(self.w, hwnd, 50, 8), pixel(self.w, hwnd, 51, 8)
        self.assertNotEqual(a, b)
        self.assertEqual({a, b}, {BLACK, WHITE})
        self.assertIsNotNone(gdi16.gdi(self.w).get(brush, gdi16.OBJ_BRUSH))


if __name__ == "__main__":
    unittest.main()
