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


class ScreenHash(unittest.TestCase):
    def test_no_gdi_yet_is_none(self):
        # A book that stops before any GDI call has no wine.gdi: the sweep's look must not raise.
        from types import SimpleNamespace
        from tbpipeline_neww.sweep import Walk, screen_hash
        w = SimpleNamespace()
        self.assertIsNone(screen_hash(w))
        walk = Walk(3, find_menu=lambda w: None, find_text=lambda w: None)
        walk.look(w)
        self.assertEqual(walk.summary()["screens"], 0)


class TextsOnScreen(unittest.TestCase):
    def test_text_drawn_off_screen_follows_the_blit(self):
        # ToolBook draws a page into a memory DC and BitBlts it to the window.
        from tests.test_neww_batch2 import by_name, window_wine
        from tbpipeline_neww import gdi16
        from tbpipeline_neww.sweep import Texts, next_text
        w = window_wine()
        w.draw_watch = Texts()
        g = gdi16.gdi(w)
        screen = gdi16.new_dc(w)
        mem = by_name(w, "GDI", "CreateCompatibleDC", screen)[0]
        bmp = by_name(w, "GDI", "CreateCompatibleBitmap", screen, 200, 100)[0]
        by_name(w, "GDI", "SelectObject", mem, bmp)
        gdi16.draw_text(w, g.objects[mem], 120, 70, "Next >")
        gdi16.draw_text(w, g.objects[mem], 10, 10, "Welcome")
        self.assertIsNone(next_text(w))
        by_name(w, "GDI", "BitBlt", g.objects[screen].handle, 50, 60, 200, 100, mem, 0, 0, (0xCC, 0x0020))
        spot = next_text(w)
        self.assertIsNotNone(spot)
        x, y = spot
        self.assertTrue(170 < x < 230 and 130 < y < 150, spot)
        # Painting over it forgets it.
        gdi16.fill(w, g.objects[screen], (150, 120, 260, 160), 1)
        self.assertIsNone(next_text(w))

    def test_what_reads_like_next(self):
        from tbpipeline_neww.sweep import NEXT_TEXT
        for t in ("Next", "NEXT >", " Next page ", "Continue", ">>", "\u2192", "Forward"):
            self.assertTrue(NEXT_TEXT.match(t), t)
        for t in ("Next, read the text", "Nextel", "Back", "<<"):
            self.assertFalse(NEXT_TEXT.match(t), t)


class WalkWays(unittest.TestCase):
    def walk(self, menu=True, text=None):
        from tbpipeline_neww.sweep import Walk
        posted = []
        walk = Walk(6, find_menu=lambda w: (0x40, 102) if menu else None,
                    find_text=lambda w: text, post=lambda w, t: posted.append(t))
        return walk, posted

    def screen(self, value):
        from types import SimpleNamespace
        from PIL import Image
        return SimpleNamespace(gdi=SimpleNamespace(screen=Image.new("L", (2, 2), value)))

    def test_a_way_that_moves_the_page_is_kept(self):
        walk, posted = self.walk()
        for v in (0, 1, 2):
            self.assertIn("wait 4000", walk(self.screen(v)))
        self.assertEqual(posted, [(0x40, 102)] * 3)
        self.assertEqual(walk.summary()["walk"], "MMm")

    def test_an_unchanged_screen_tries_the_next_way_then_stops(self):
        walk, _posted = self.walk(text=(300, 400))
        same = self.screen(0)
        self.assertIsNotNone(walk(same))                       # menu
        self.assertTrue(walk(same).startswith("key ctrl+right"))  # menu did nothing: the key
        self.assertTrue(walk(same).startswith("click 300,400"))   # then the Next text
        self.assertIsNone(walk(same))                           # none moved it: stuck
        s = walk.summary()
        self.assertEqual((s["walk"], s["stuck"], s["moved"]), ("mkt", True, 0))

    def test_ways_not_there_are_skipped(self):
        walk, posted = self.walk(menu=False)
        self.assertTrue(walk(self.screen(0)).startswith("key ctrl+right"))
        self.assertEqual(posted, [])
        # The key did nothing, no Next text, no menu: stuck.
        self.assertIsNone(walk(self.screen(0)))
        self.assertTrue(walk.summary()["stuck"])

    def test_the_page_limit_ends_the_walk(self):
        walk, _posted = self.walk()
        for v in range(6):
            walk(self.screen(v))
        self.assertIsNone(walk(self.screen(9)))
        self.assertFalse(walk.summary()["stuck"])
        self.assertEqual(walk.summary()["moved"], 6)


if __name__ == "__main__":
    unittest.main()
