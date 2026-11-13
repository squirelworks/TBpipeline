"""The book sweep's stop summary (#227): what a stop line names, so findings group by cause."""

import unittest

from tbpipeline_neww.sweep import cause_of


class CauseOf(unittest.TestCase):
    def test_a_call_by_name(self):
        self.assertEqual(cause_of("USER.175 LoadBitmap(0, 32738): a user32 OBM_ bitmap"), "USER.175 LoadBitmap")
        self.assertEqual(cause_of("KERNEL32!GetShortPathNameA: @ stdcall GetShortPathNameA(str ptr long)"),
                         "KERNEL32!GetShortPathNameA")

    def test_idle_and_exit(self):
        self.assertEqual(cause_of("idle: input script done, TB80RTM waiting in PeekMessage"), "idle")
        self.assertEqual(cause_of("dos exit 0x0"), "exit")

    def test_other_lines_drop_their_numbers(self):
        self.assertEqual(cause_of("WM_NCHITTEST at (5, 5) on the frame of 0x28"), "WM_NCHITTEST at (5, 5) on the frame of N")


if __name__ == "__main__":
    unittest.main()


class Opened(unittest.TestCase):
    def test_untitled_is_not_a_pass(self):
        # TB80RTM shows "ToolBook II - (Untitled)" and asks for a file when the book did not open.
        from tbpipeline_neww.sweep import opened
        ok = {"cause": "idle", "titles": ["Advanced Training"]}
        self.assertTrue(opened(ok))
        self.assertFalse(opened({**ok, "titles": ["ToolBook II - (Untitled)"]}))
        self.assertFalse(opened({**ok, "default_count": 1}))
        self.assertFalse(opened({**ok, "messagebox_count": 1}))
        self.assertFalse(opened({**ok, "cause": "USER.175 LoadBitmap"}))


class NextCommand(unittest.TestCase):
    def test_go_next_is_found_and_a_grayed_one_is_not(self):
        from tests.test_neww_batch2 import window_wine
        from tbpipeline_neww import user_res, user_wnd
        from tbpipeline_neww.sweep import next_command
        w = window_wine()
        m = user_wnd.wm(w)
        bar, go = user_res.new_menu(w, False), user_res.new_menu(w, True)
        user_res.menu_items(w, bar).append({"flags": 0x10, "id": 0, "text": "&Go", "sub": go})
        items = user_res.menu_items(w, go)
        items.append({"flags": 0, "id": 101, "text": "&Back\\tCtrl+Left", "sub": 0})
        items.append({"flags": 0, "id": 102, "text": "&Next\\tCtrl+Right", "sub": 0})
        h = 0x40
        win = user_wnd.Window(h, None, 0, 0)
        win.style, win.menu = user_wnd.WS_VISIBLE, bar
        m.windows[h] = win
        m.children[m.desktop].append(h)
        self.assertEqual(next_command(w), (h, 102))
        items[1]["flags"] = 0x1
        self.assertIsNone(next_command(w))
