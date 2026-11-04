"""BUTTON and STATIC: Wine's built-in control classes in neww (roadmap #201, item T9a).

Each test checks against the Wine function its docstring or comment names, at 2528aff2:
user32 button.c ButtonWndProc_common and PB_Paint, user32 static.c StaticWndProc_common and
STATIC_PaintTextfn, user32 uitools.c UITOOLS95_DFC_ButtonPush, and user.exe16 message.c's
16-bit WM_COMMAND. No ToolBook bytes: the windows are made on fake memory
(tests/test_neww_batch2.py's harness).
"""

import unittest

from tests.test_neww_batch1_handlers import NUL, put
from tests.test_neww_batch2 import INST, by_name
from tests.test_neww_batch6 import control_wine, guest_reply, top_window

WM_CTLCOLOR, WM_COMMAND, WM_NCHITTEST, WM_GETDLGCODE = 0x19, 0x111, 0x84, 0x87
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
BM_SETSTATE16 = 0x403
WHITE, BLACK, FACE, SHADOW, DKSHADOW = (255, 255, 255), (0, 0, 0), (212, 208, 200), (128, 128, 128), (64, 64, 64)


class Controls(unittest.TestCase):

    def setUp(self):
        self.w = control_wine()
        self.top = top_window(self.w)
        by_name(self.w, "USER", "ShowWindow", self.top, 1, reply=guest_reply)

    def child(self, cls, text, style, x, y, cx, cy, ident):
        out = by_name(self.w, "USER", "CreateWindow", put(self.w, 0x60, cls), put(self.w, 0x80, text),
                      style, x, y, cx, cy, self.top, ident, INST, NUL, reply=guest_reply)
        self.assertIsNone(out[2])
        self.assertNotEqual(out[0], 0, f"CreateWindow {cls!r}")
        return out[0]

    def send(self, hwnd, msg, wp=0, lp=(0, 0), reply=guest_reply):
        return by_name(self.w, "USER", "SendMessage", hwnd, msg, wp, lp, reply=reply)

    def pixel(self, hwnd, x, y):
        from tbpipeline_neww.user_wnd import screen_origin
        ox, oy = screen_origin(self.w, hwnd)
        return self.w.gdi.screen.getpixel((ox + x, oy + y))

    def test_a_click_sends_bn_clicked_to_the_parent_as_16_bit_wm_command(self):
        # button.c:264-310 WM_LBUTTONDOWN then WM_LBUTTONUP inside: BUTTON_NOTIFY_PARENT(BN_CLICKED)
        # (button.c:60), which message.c:1183-1186 gives a 16-bit parent as wParam = id,
        # lParam = MAKELONG(hwnd, BN_CLICKED).
        btn = self.child("button", "Yes", (0x5001, 0x0000), 10, 10, 80, 24, 0x77)
        self.assertIsNone(self.send(btn, WM_LBUTTONDOWN, 1, (5, 5))[2])
        _ax, _dx, stop, calls = self.send(btn, WM_LBUTTONUP, 0, (5, 5))
        self.assertIsNone(stop)
        commands = [c.words for c in calls if c.words[1] == WM_COMMAND]
        self.assertEqual(commands, [[self.top, WM_COMMAND, 0x77, 0, btn]])

    def test_a_release_outside_sends_nothing(self):
        # button.c:302-309: outside the client the capture is released, no notification.
        btn = self.child("button", "No", (0x5000, 0x0000), 10, 10, 80, 24, 0x78)
        self.send(btn, WM_LBUTTONDOWN, 1, (5, 5))
        calls = self.send(btn, WM_LBUTTONUP, 0, (5, 200))[3]
        self.assertEqual([c for c in calls if c.words[1] == WM_COMMAND], [])

    def test_dialog_codes_and_static_hit_test(self):
        # button.c:188-198 and static.c:517-524.
        push = self.child("button", "a", (0x5000, 0x0000), 0, 0, 40, 20, 1)
        default = self.child("button", "b", (0x5000, 0x0001), 0, 30, 40, 20, 2)
        text = self.child("static", "c", (0x5000, 0x0000), 0, 60, 40, 20, 3)
        self.assertEqual(self.send(push, WM_GETDLGCODE)[0], 0x2000 | 0x20)
        self.assertEqual(self.send(default, WM_GETDLGCODE)[0], 0x2000 | 0x10)
        self.assertEqual(self.send(text, WM_GETDLGCODE)[0], 0x100)
        self.assertEqual(self.send(text, WM_NCHITTEST, 0, (5, 5))[:2], (0xFFFF, 0xFFFF))

    def test_push_button_frame_is_raised_and_default_one_is_outlined(self):
        # PB_Paint (button.c:725): DFC_BUTTONPUSH raised and soft (uitools.c:664, 39-82): white
        # outer top-left, COLOR_3DDKSHADOW outer bottom-right, COLOR_BTNSHADOW inner bottom-right.
        # A default button has a COLOR_WINDOWFRAME outline first (button.c:754-759).
        push = self.child("button", "", (0x5000, 0x0000), 10, 10, 60, 24, 1)
        default = self.child("button", "", (0x5000, 0x0001), 10, 50, 60, 24, 2)
        for h in (push, default):
            self.assertIsNone(by_name(self.w, "USER", "UpdateWindow", h, reply=guest_reply)[2])
        self.assertEqual(self.pixel(push, 0, 0), WHITE)
        self.assertEqual(self.pixel(push, 59, 23), DKSHADOW)
        self.assertEqual(self.pixel(push, 58, 22), SHADOW)
        self.assertEqual(self.pixel(push, 30, 12), FACE)
        self.assertEqual(self.pixel(default, 0, 0), BLACK)
        self.assertEqual(self.pixel(default, 1, 1), WHITE)
        self.assertEqual(self.pixel(default, 58, 22), DKSHADOW)

    def test_pushed_default_button_is_flat(self):
        # BM_SETSTATE (button.c:476-484) repaints; PB_Paint gives a pushed default button
        # DFCS_FLAT, a COLOR_BTNSHADOW frame (uitools.c:98-110).
        default = self.child("button", "", (0x5000, 0x0001), 10, 50, 60, 24, 2)
        self.assertIsNone(self.send(default, BM_SETSTATE16, 1)[2])
        self.assertEqual(self.pixel(default, 0, 0), BLACK)
        self.assertEqual(self.pixel(default, 1, 1), SHADOW)
        self.assertEqual(self.pixel(default, 58, 22), SHADOW)

    def test_static_text_wraps_on_the_brush_defwindowproc_gives(self):
        # static.c:243-253: the parent answers WM_CTLCOLOR with 0 here, so DefWindowProc's
        # brush (COLOR_BTNFACE for CTLCOLOR_STATIC) fills the client; SS_LEFT is DT_WORDBREAK
        # (static.c:615-617), so the text takes more than one line.
        text = self.child("static", "Are you sure you want to exit this lesson?", (0x5000, 0x0000),
                          10, 100, 120, 60, 3)
        _ax, _dx, stop, calls = by_name(self.w, "USER", "UpdateWindow", text, reply=guest_reply)
        self.assertIsNone(stop)
        self.assertIn([self.top, WM_CTLCOLOR], [c.words[:2] for c in calls])
        self.assertEqual(self.pixel(text, 119, 59), FACE)
        rows = [y for y in range(60) if any(self.pixel(text, x, y) == BLACK for x in range(120))]
        self.assertTrue(rows, "no text drawn")
        self.assertGreater(rows[-1] - rows[0], 20, "the text did not wrap to a second line")
        self.assertTrue(all(self.pixel(text, x, 0) in (FACE, BLACK) for x in range(120)))


if __name__ == "__main__":
    unittest.main()
