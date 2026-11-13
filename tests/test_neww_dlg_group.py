"""GetNextDlgGroupItem (user32/dialog.c:1528), which IsDialogMessage's arrow keys use (:1223)."""

import unittest


class NextGroupItem(unittest.TestCase):
    def setUp(self):
        from tests.test_neww_batch2 import window_wine
        from tbpipeline_neww import user_wnd as uw
        self.uw = uw
        self.w = window_wine()
        m = uw.wm(self.w)
        self.dlg = self.add(m.desktop, uw.WS_VISIBLE | uw.WS_POPUP, 0x100)
        G = 0x00020000
        # Two groups: a, b, c (a starts it) and d, e (d starts it); c is disabled.
        self.a = self.add(self.dlg, uw.WS_CHILD | uw.WS_VISIBLE | G, 0x104)
        self.b = self.add(self.dlg, uw.WS_CHILD | uw.WS_VISIBLE, 0x108)
        self.c = self.add(self.dlg, uw.WS_CHILD | uw.WS_VISIBLE | uw.WS_DISABLED, 0x10C)
        self.d = self.add(self.dlg, uw.WS_CHILD | uw.WS_VISIBLE | G, 0x110)
        self.e = self.add(self.dlg, uw.WS_CHILD | uw.WS_VISIBLE, 0x114)

    def add(self, parent, style, h):
        uw = self.uw
        m = uw.wm(self.w)
        win = uw.Window(h, None, parent, 0)
        win.style = style
        m.windows[h] = win
        m.children.setdefault(parent, []).append(h)
        return h

    def nxt(self, h, previous=False):
        from tbpipeline_neww.user_dialog import next_group_item
        return next_group_item(self.w, self.dlg, h, previous)

    def test_next_wraps_within_the_group_and_skips_disabled(self):
        self.assertEqual(self.nxt(self.a), self.b)
        self.assertEqual(self.nxt(self.b), self.a)     # c is disabled, d starts another group
        self.assertEqual(self.nxt(self.d), self.e)
        self.assertEqual(self.nxt(self.e), self.d)

    def test_previous(self):
        self.assertEqual(self.nxt(self.a, True), self.b)
        self.assertEqual(self.nxt(self.e, True), self.d)

    def test_no_control_is_the_first_child(self):
        self.assertEqual(self.nxt(0), self.a)
        self.assertEqual(self.nxt(0, True), 0)


if __name__ == "__main__":
    unittest.main()
