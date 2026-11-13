"""The caret (#227, group A): USER.163-169 and 183, as Wine 2528aff2 dlls/win32u/input.c:2375-2738
and server/queue.c:203, :3905, :3933 keep it. The NetClass system books (nc81*.sbk) call these
on their first page."""

import struct
import unittest
from unittest import mock

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine

HWND = 0x1234
REGS = {"dx": 0}


class Caret(unittest.TestCase):
    def setUp(self):
        from tbpipeline_neww import user_caret, user_wnd
        self.uc, self.uw = user_caret, user_wnd
        self.w = window_wine()
        m = user_wnd.wm(self.w)
        real = m.get
        m.get = lambda h: object() if h == HWND else real(h)
        self.drawn = []
        patch = mock.patch.object(user_caret, "display", lambda wine, c, hwnd, rect: self.drawn.append((hwnd, rect)))
        patch.start()
        self.addCleanup(patch.stop)

    def call(self, name, *args):
        return by_name(self.w, "USER", name, *args, regs=REGS)

    def timers(self):
        return {k: v for k, v in self.uw.wm(self.w).timers.items() if k[1] & self.uc.SYSTEM_TIMER}

    def test_create_makes_it_hidden_and_off(self):
        # server/queue.c:203: hide 1, state 0; a 0 size is SM_CXBORDER/SM_CYBORDER (input.c:2455).
        self.call("CreateCaret", HWND, 0, 0, 20)
        c = self.uc.caret(self.w)
        self.assertEqual((c.hwnd, c.rect, c.hide, c.state), (HWND, (0, 0, 1, 20), 1, 0))
        self.assertEqual(self.drawn, [])

    def test_show_draws_it_and_starts_the_blink(self):
        # input.c:2646: hidden 1 -> 0 draws it and sets SYSTEM_TIMER_CARET.
        self.call("CreateCaret", HWND, 0, 2, 16)
        self.call("SetCaretPos", 10, 5)
        self.assertEqual(self.drawn, [])                     # hidden: SetCaretPos does not draw
        self.call("ShowCaret", HWND)
        self.assertEqual(self.drawn, [(HWND, (10, 5, 12, 21))])
        self.assertEqual(list(self.timers()), [(HWND, self.uc.SYSTEM_TIMER | 0xFFFF)])

    def test_moving_a_shown_caret_draws_it_off_then_on(self):
        # input.c:2629: old place off (it was on), new place on.
        self.call("CreateCaret", HWND, 0, 2, 16)
        self.call("ShowCaret", HWND)
        self.drawn.clear()
        self.call("SetCaretPos", 4, 4)
        self.assertEqual(self.drawn, [(HWND, (0, 0, 2, 16)), (HWND, (4, 4, 6, 20))])

    def test_hide_counts_and_stops_the_blink(self):
        self.call("CreateCaret", HWND, 0, 2, 16)
        self.call("ShowCaret", HWND)
        self.call("HideCaret", HWND)
        self.call("HideCaret", HWND)
        c = self.uc.caret(self.w)
        self.assertEqual((c.hide, c.state), (2, 0))
        self.assertEqual(self.timers(), {})
        self.call("ShowCaret", HWND)
        self.assertEqual(c.hide, 1)                          # still hidden: no draw
        self.assertEqual(len(self.drawn), 2)                 # shown once, drawn off once

    def test_another_window_is_refused(self):
        # server/queue.c:3947: STATUS_ACCESS_DENIED for a window that is not the caret's.
        self.call("CreateCaret", HWND, 0, 2, 16)
        self.call("ShowCaret", 0x9999)
        self.assertEqual(self.uc.caret(self.w).hide, 1)

    def test_blink_toggles_through_dispatch(self):
        # message.c:4055: WM_SYSTIMER SYSTEM_TIMER_CARET goes to toggle_caret, not the window.
        self.call("CreateCaret", HWND, 0, 2, 16)
        self.call("ShowCaret", HWND)
        msg = self.uw.next_message(self.w, 0, 0, 0, True)
        self.assertEqual(msg[:3], (HWND, 0x118, 0xFFFF))
        self.w.memory.write(DATA, 0x200, struct.pack("<HHHII", HWND, 0x118, 0xFFFF, 0, 0))
        self.assertEqual(self.call("DispatchMessage", (DATA, 0x200))[2], None)
        self.assertEqual(self.uc.caret(self.w).state, 0)
        self.assertEqual(len(self.drawn), 2)

    def test_destroy_hides_a_shown_caret(self):
        self.call("CreateCaret", HWND, 1, 2, 16)
        self.assertEqual(self.uc.caret(self.w).color, self.uc.GRAY)
        self.call("ShowCaret", HWND)
        self.call("DestroyCaret")
        c = self.uc.caret(self.w)
        self.assertEqual((c.hwnd, c.color, self.timers()), (0, None, {}))
        self.assertEqual(self.drawn[-1], (HWND, (0, 0, 2, 16)))

    def test_get_caret_pos_and_blink_time(self):
        self.call("CreateCaret", HWND, 0, 2, 16)
        self.call("SetCaretPos", 7, 9)
        self.call("GetCaretPos", (DATA, 0x300))
        self.assertEqual(struct.unpack("<hh", self.w.memory.read(DATA, 0x300, 4)), (7, 9))
        self.assertEqual(self.call("GetCaretBlinkTime")[0], 500)
        self.call("SetCaretBlinkTime", 250)
        self.assertEqual(self.call("GetCaretBlinkTime")[0], 250)

    def test_a_real_bitmap_stops_by_name(self):
        self.assertIn("CreateCaret with a bitmap", self.call("CreateCaret", HWND, 0x40, 0, 0)[2])


class Draw(unittest.TestCase):
    def test_xor_with_white_inverts(self):
        from PIL import Image
        from tbpipeline_neww.user_caret import _xor
        img = Image.new("RGB", (2, 2), (0x10, 0x80, 0xFF))
        self.assertEqual(_xor(img, (0xFF, 0xFF, 0xFF)).getpixel((0, 0)), (0xEF, 0x7F, 0x00))


if __name__ == "__main__":
    unittest.main()
