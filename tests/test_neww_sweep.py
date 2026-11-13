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
        from tbpipeline_neww.sweep import Marks, next_text
        w = window_wine()
        w.draw_watch = Marks()
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
    def walk(self, menu=True, text=None, pics=(), centre=None):
        from tbpipeline_neww.sweep import Walk
        posted = []
        walk = Walk(6, find_menu=lambda w: (0x40, 102) if menu else None,
                    find_text=lambda w: text, post=lambda w, t: posted.append(t),
                    find_pictures=lambda w: list(pics), find_centre=lambda w: centre)
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
        self.assertIsNotNone(walk(same))                          # menu
        self.assertTrue(walk(same).startswith("click 300,400"))   # menu did nothing: the Next text
        self.assertTrue(walk(same).startswith("key ctrl+right"))  # no pictures: the key
        self.assertIsNone(walk(same))                             # none moved it: stuck
        s = walk.summary()
        self.assertEqual((s["walk"], s["stuck"], s["moved"]), ("mtk", True, 0))

    def test_ways_not_there_are_skipped(self):
        walk, posted = self.walk(menu=False)
        self.assertTrue(walk(self.screen(0)).startswith("key ctrl+right"))
        self.assertEqual(posted, [])
        # The key did nothing, and there is no menu, Next text or picture: stuck.
        self.assertIsNone(walk(self.screen(0)))
        self.assertTrue(walk.summary()["stuck"])

    def test_the_page_limit_ends_the_walk(self):
        walk, _posted = self.walk()
        for v in range(6):
            walk(self.screen(v))
        self.assertIsNone(walk(self.screen(9)))
        self.assertFalse(walk.summary()["stuck"])
        self.assertEqual(walk.summary()["moved"], 6)

    def test_pictures_are_probed_and_the_one_that_works_is_kept(self):
        # No menu, no Next text: a course with picture buttons. Bottom-right first; (500, 600)
        # does nothing, (100, 600) turns the page and is tried first from then on.
        walk, _posted = self.walk(menu=False, pics=[(500, 600), (100, 600), (50, 50)])
        self.assertTrue(walk(self.screen(0)).startswith("click 500,600"))
        self.assertTrue(walk(self.screen(0)).startswith("click 100,600"))
        self.assertTrue(walk(self.screen(1)).startswith("click 100,600"))
        self.assertTrue(walk(self.screen(2)).startswith("click 100,600"))
        s = walk.summary()
        self.assertEqual(s["walk"], "pPPp")
        self.assertEqual(s["picture_clicks"], 4)
        self.assertEqual(s["clicked"], [[500, 600], [100, 600]])

    def test_pictures_that_do_nothing_run_out(self):
        walk, _posted = self.walk(menu=False, pics=[(500, 600), (100, 600)])
        same = self.screen(0)
        self.assertTrue(walk(same).startswith("click 500,600"))
        self.assertTrue(walk(same).startswith("click 100,600"))
        self.assertTrue(walk(same).startswith("key ctrl+right"))
        self.assertIsNone(walk(same))
        self.assertTrue(walk.summary()["stuck"])

    def test_a_title_page_gets_a_click_in_the_middle(self):
        walk, _posted = self.walk(menu=False, centre=(512, 394))
        pics = []
        walk.find_pictures = lambda w: list(pics)
        self.assertTrue(walk(self.screen(0)).startswith("click 512,394"))   # no buttons yet
        self.assertTrue(walk(self.screen(1)).startswith("click 512,394"))   # a second title page
        pics.append((808, 600))
        self.assertTrue(walk(self.screen(2)).startswith("click 808,600"))   # then the buttons
        self.assertEqual(walk.summary()["walk"], "CCp")


class PicturesOnScreen(unittest.TestCase):
    def test_a_button_bitmap_composed_into_the_page_is_found_on_screen(self):
        # NIDA's Next: a 29 x 29 bitmap BitBlt into the page buffer, which is BitBlt to the
        # window; a page-sized bitmap is no button.
        from tests.test_neww_batch2 import by_name, window_wine
        from tbpipeline_neww import gdi16
        from tbpipeline_neww.sweep import Marks, pictures
        w = window_wine()
        w.draw_watch = Marks()
        g = gdi16.gdi(w)
        screen = gdi16.new_dc(w)

        def mem_dc(cx, cy):
            dc = by_name(w, "GDI", "CreateCompatibleDC", screen)[0]
            by_name(w, "GDI", "SelectObject", dc, by_name(w, "GDI", "CreateCompatibleBitmap", screen, cx, cy)[0])
            return dc
        page, button, icon = mem_dc(600, 440), mem_dc(29, 29), mem_dc(20, 20)
        copy = (0xCC, 0x0020)
        by_name(w, "GDI", "BitBlt", page, 560, 400, 29, 29, button, 0, 0, copy)
        by_name(w, "GDI", "BitBlt", page, 20, 400, 20, 20, icon, 0, 0, copy)
        self.assertEqual(pictures(w), [])
        by_name(w, "GDI", "BitBlt", screen, 200, 170, 600, 440, page, 0, 0, copy)
        self.assertEqual(pictures(w), [(774, 584), (230, 580)])
        # Text drawn over a button keeps it; a fill over it forgets it.
        gdi16.draw_text(w, g.objects[screen], 762, 576, "Go")
        self.assertEqual(pictures(w)[0], (774, 584))
        gdi16.fill(w, g.objects[screen], (750, 560, 800, 620), 1)
        self.assertEqual(pictures(w), [(230, 580)])

    def test_a_button_clipped_by_the_window_edge_still_counts(self):
        # Parallel Resonance's Next sits at the page's right edge: the page buffer is wider
        # than the window, and the copy to the screen cuts the button by a pixel.
        from tests.test_neww_batch2 import by_name, window_wine
        from tbpipeline_neww import gdi16
        from tbpipeline_neww.sweep import Marks, pictures
        w = window_wine()
        w.draw_watch = Marks()
        screen = gdi16.new_dc(w)

        def mem_dc(cx, cy):
            dc = by_name(w, "GDI", "CreateCompatibleDC", screen)[0]
            by_name(w, "GDI", "SelectObject", dc, by_name(w, "GDI", "CreateCompatibleBitmap", screen, cx, cy)[0])
            return dc
        page, button = mem_dc(1280, 442), mem_dc(29, 29)
        copy = (0xCC, 0x0020)
        by_name(w, "GDI", "BitBlt", page, 596, 414, 29, 29, button, 0, 0, copy)
        by_name(w, "GDI", "BitBlt", screen, 797, 587, 27, 28, page, 596, 414, copy)
        self.assertEqual(pictures(w), [(810, 601)])


class PassAfterTheWalk(unittest.TestCase):
    def test_the_books_own_exit_after_a_click_is_a_pass(self):
        from tbpipeline_neww.sweep import opened
        base = {"titles": [], "open_titles": ["Course"], "open_messagebox_count": 0, "messagebox_count": 1}
        self.assertTrue(opened({**base, "cause": "exit", "walk": "PPp"}))
        self.assertTrue(opened({**base, "cause": "idle", "walk": "PP"}))
        # An exit before any step is still a stop, and so is a MessageBox while opening.
        self.assertFalse(opened({**base, "cause": "exit", "walk": ""}))
        self.assertFalse(opened({**base, "cause": "idle", "walk": "", "open_messagebox_count": 1}))
        self.assertFalse(opened({**base, "cause": "idle", "open_titles": ["ToolBook II - (Untitled)"]}))


if __name__ == "__main__":
    unittest.main()
