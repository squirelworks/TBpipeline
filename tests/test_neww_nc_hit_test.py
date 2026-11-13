"""The non-client area: handle_nc_hit_test (win32u/defwnd.c:1925), handle_nc_lbutton_down
(:2194) and handle_sys_command (:961). No ToolBook bytes: windows are made by the handlers on
fake memory (tests/test_neww_batch2.py)."""

import unittest

from tests.test_neww_batch6 import control_wine, top_window


def first(gen):
    """The first thing a generator yields, or ('return', value)."""
    try:
        return gen.send(None)
    except StopIteration as done:
        return ("return", done.value)


class HitTest(unittest.TestCase):
    def setUp(self):
        from tbpipeline_neww import user_wnd as uw
        self.uw = uw
        self.w = control_wine()
        # WS_OVERLAPPEDWINDOW | WS_VISIBLE at (10, 20), 300 x 200: a thick frame (SM_CXFRAME
        # 4), a caption (SM_CYCAPTION 19), the system menu and both boxes.
        self.hwnd = top_window(self.w)
        self.win = uw.wm(self.w).get(self.hwnd)
        # The test's procedure answered WM_NCCALCSIZE with 0: give it DefWindowProc's client.
        self.win.client = uw.nc_calc_size(self.w, self.win, self.win.rect)
        self.assertEqual(self.win.client, (14, 43, 306, 216))

    def hit(self, x, y):
        hit, stop = self.uw.nc_hit_test(self.w, self.win, x, y)
        self.assertIsNone(stop)
        return hit

    def test_outside_and_client(self):
        uw = self.uw
        self.assertEqual(self.win.rect, (10, 20, 310, 220))
        self.assertEqual(self.hit(9, 100), uw.HTNOWHERE)
        self.assertEqual(self.hit(100, 100), uw.HTCLIENT)

    def test_sizing_borders(self):
        uw = self.uw
        # Inside the frame is (14, 24)-(306, 216); the corners reach SM_CXSIZE 18 along it.
        self.assertEqual(self.hit(10, 20), uw.HTTOPLEFT)
        self.assertEqual(self.hit(31, 21), uw.HTTOPLEFT)
        self.assertEqual(self.hit(32, 21), uw.HTTOP)
        self.assertEqual(self.hit(11, 100), uw.HTLEFT)
        self.assertEqual(self.hit(308, 100), uw.HTRIGHT)
        self.assertEqual(self.hit(309, 219), uw.HTBOTTOMRIGHT)
        self.assertEqual(self.hit(100, 217), uw.HTBOTTOM)

    def test_caption_and_its_buttons(self):
        uw = self.uw
        # The caption is y 24 to 24 + 19 - 1. The system menu is SM_CYCAPTION - 1 wide from
        # the left, close SM_CYCAPTION from the right, then maximize and minimize SM_CXSIZE each.
        self.assertEqual(self.hit(20, 30), uw.HTSYSMENU)
        self.assertEqual(self.hit(295, 30), uw.HTCLOSE)
        self.assertEqual(self.hit(280, 30), uw.HTMAXBUTTON)
        self.assertEqual(self.hit(260, 30), uw.HTMINBUTTON)
        self.assertEqual(self.hit(150, 30), uw.HTCAPTION)

    def test_menu_bar_and_scroll_bars(self):
        uw = self.uw
        self.win.menu = 0x99
        self.win.style |= uw.WS_VSCROLL | uw.WS_HSCROLL
        self.win.client = (14, 62, 290, 200)
        self.assertEqual(self.hit(100, 50), uw.HTMENU)
        self.assertEqual(self.hit(295, 100), uw.HTVSCROLL)
        self.assertEqual(self.hit(100, 205), uw.HTHSCROLL)
        self.assertEqual(self.hit(295, 205), uw.HTSIZE)

    def test_a_thin_border(self):
        uw = self.uw
        # WS_POPUP | WS_BORDER: SM_CXBORDER 1 is the border, and nothing else is non-client.
        self.win.style = uw.WS_POPUP | uw.WS_BORDER | uw.WS_VISIBLE
        self.win.client = (11, 21, 309, 219)
        self.assertEqual(self.hit(10, 100), uw.HTBORDER)
        self.assertEqual(self.hit(11, 100), uw.HTCLIENT)


class ButtonDown(unittest.TestCase):
    def setUp(self):
        from tbpipeline_neww import user_wnd as uw
        self.uw = uw
        self.w = control_wine()
        self.hwnd = top_window(self.w)

    def test_menu_bar_press_sends_sc_mousemenu(self):
        uw = self.uw
        got = first(uw.def_window_proc(self.w, self.hwnd, uw.WM_NCLBUTTONDOWN, uw.HTMENU, 50 << 16 | 100))
        # The window's own procedure gets WM_SYSCOMMAND SC_MOUSEMENU with the point.
        self.assertEqual(got.words[1:], [0x112, 0xF090, 50, 100])

    def test_border_press_does_nothing(self):
        uw = self.uw
        self.assertEqual(first(uw.def_window_proc(self.w, self.hwnd, uw.WM_NCLBUTTONDOWN, uw.HTBORDER, 0)),
                         ("return", 0))

    def test_caption_press_stops_by_name(self):
        uw = self.uw
        got = first(uw.def_window_proc(self.w, self.hwnd, uw.WM_NCLBUTTONDOWN, uw.HTCAPTION, 0))
        self.assertIn("WM_NCLBUTTONDOWN hit 2", got)

    def test_sc_mousemenu_stops_at_menu_tracking(self):
        uw = self.uw
        got = first(uw.def_window_proc(self.w, self.hwnd, uw.WM_SYSCOMMAND, uw.SC_MOUSEMENU, 0))
        self.assertIn("SC_MOUSEMENU", got)
        self.assertIn("track_mouse_menu_bar", got)

    def test_sc_close_sends_wm_close(self):
        uw = self.uw
        got = first(uw.def_window_proc(self.w, self.hwnd, uw.WM_SYSCOMMAND, uw.SC_CLOSE, 0))
        self.assertEqual(got.words[1], uw.WM_CLOSE)

    def test_a_disabled_window_ignores_it(self):
        uw = self.uw
        uw.wm(self.w).get(self.hwnd).style |= uw.WS_DISABLED
        self.assertEqual(first(uw.def_window_proc(self.w, self.hwnd, uw.WM_SYSCOMMAND, uw.SC_CLOSE, 0)),
                         ("return", 0))


if __name__ == "__main__":
    unittest.main()
