"""USER.179 GetSystemMetrics is Wine user.c GetSystemMetrics16.

Spec: `179 pascal -ret16 GetSystemMetrics(s_word) GetSystemMetrics16`,
pop 2. Wine passes the index to win32u sysparams.c get_system_metrics.
The cases that return a constant are answered. The cases that read the
registry, fonts, or display stop by index. An index that is not a case
is the switch's default, 0. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def run(index):
    from tbpipeline_neww.machine import Machine
    # push index ; call ; mov [0x40], ax
    code = bytes([0x68, index & 0xFF, (index >> 8) & 0xFF]) + neww_ne.call_far() + bytes([0xA3, 0x40, 0x00])
    with tempfile.TemporaryDirectory() as d:
        # 0xFFFF in the result word: a stop leaves it unwritten.
        neww_ne.exit_program_with(d, code, [(3, 1, 4, 1, 179)], modules=("USER", "KERNEL"), data=b"\x00" * 0x40 + b"\xFF\xFF" + b"\x00" * 0xBE)
        host = Machine(d).run(limit=5000)
    return host, host.word(host.uc.reg_read(UC_X86_REG_DS), 0x40)


class GetSystemMetrics(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import USER
        row = USER[179]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetSystemMetrics", (2,), 2, "word"))

    def test_constants(self):
        # SM_CXBORDER, SM_CXDLGFRAME, SM_CYDLGFRAME, SM_MOUSEPRESENT, SM_CMOUSEBUTTONS, SM_CMETRICS.
        for index, value in ((5, 1), (7, 3), (8, 3), (19, 1), (43, 3), (90, 90)):
            host, ax = run(index)
            self.assertEqual((host.stop, ax), ("dos exit 0x0", value), index)

    def test_not_a_case_is_zero(self):
        for index in (64, 1000, -1):
            host, ax = run(index)
            self.assertEqual((host.stop, ax), ("dos exit 0x0", 0), index)

    def test_fixed_at_96_dpi(self):
        # SM_CXVSCROLL: SCROLLWIDTH -240 twips; SM_CYMENU: MENUHEIGHT 18 + 1; SM_CXMAXTRACK.
        for index, value in ((2, 16), (15, 19), (59, 1036), (11, 32)):
            host, ax = run(index)
            self.assertEqual((host.stop, ax), ("dos exit 0x0", value), index)

    def test_minimum_track_width_from_wines_caption_font(self):
        # SM_CXMIN and SM_CXMINTRACK: 3 * 18 + 18 + 4 * 7 + 2 * 4 + 4, the 7 from Wine's Tahoma Bold.
        for index in (28, 34):
            host, ax = run(index)
            self.assertEqual((host.stop, ax), ("dos exit 0x0", 112), index)

    def test_menu_check_size_stops(self):
        # SM_CXMENUCHECK needs the menu check bitmap, which neww does not have.
        host, ax = run(71)
        self.assertEqual(
            host.stop,
            "USER.179 GetSystemMetrics(71): Wine reads it from the registry, fonts, or display, and neww has none of them",
        )
        self.assertEqual(ax, 0xFFFF)

    def test_caption_font_width_is_seven(self):
        # The 374 behind the 7, measured from Wine's own font when WINE_SRC has it.
        import os
        root = os.environ.get("WINE_SRC")
        font = os.path.join(root or "", "fonts", "tahomabd.ttf")
        if not root or not os.path.exists(font):
            raise unittest.SkipTest("WINE_SRC with fonts/tahomabd.ttf is not available")
        from PIL import ImageFont
        face = ImageFont.truetype(font, 11, layout_engine=ImageFont.Layout.BASIC)
        cx = int(face.getlength("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        self.assertEqual(cx, 374)
        self.assertEqual((cx // 26 + 1) // 2, 7)


if __name__ == "__main__":
    unittest.main()
