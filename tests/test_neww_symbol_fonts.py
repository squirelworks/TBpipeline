"""SYMBOL_CHARSET faces (#225): a LOGFONT with charset 2 gets the installed symbol face of that
name, Wine's own (fonts/symbol.ttf, wingding.ttf) or a course's (NIDA's nida.ttf in the `--b`
folder), drawn through its (3, 0) cmap, so Wingdings 'w' is a bullet and Symbol 'p' is pi."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tbpipeline_neww import gdi16


def wine_font(name):
    src = os.environ.get("WINE_SRC")
    path = Path(src) / "fonts" / name if src else None
    if path is None or not path.exists():
        raise unittest.SkipTest(f"WINE_SRC with fonts/{name} is not set")
    return path


class SymbolFaces(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def gdi(self, *names, wine_src=False):
        for name in names:
            shutil.copy(wine_font(name), self.root / name)
        g = gdi16.Gdi()
        g.root = str(self.root)
        if not wine_src:
            env = os.environ.pop("WINE_SRC", None)
            if env is not None:
                self.addCleanup(os.environ.__setitem__, "WINE_SRC", env)
        return g

    def font(self, g, face, charset=2):  # SYMBOL_CHARSET
        return g.font_for(gdi16._logfont(-16, 0, 400, charset, 0x02, face))[0]

    def test_face_in_root_is_found_by_family_name(self):
        g = self.gdi("wingding.ttf")
        pil = self.font(g, "WINGDINGS")
        self.assertTrue(pil.path.endswith("wingding.ttf"), pil.path)
        self.assertTrue(pil.neww_symbol)

    def test_wingdings_w_draws_the_symbol_glyph(self):
        g = self.gdi("wingding.ttf")
        pil = self.font(g, "Wingdings")
        self.assertEqual(gdi16.glyph(pil, "w"), "")
        # The glyph at 0xF077 is Wine's rhombus4, not a blank: it has ink.
        self.assertIsNotNone(pil.getmask(gdi16.glyph(pil, "w")).getbbox())
        stand_in = self.font(g, "Arial", charset=0)
        self.assertEqual(gdi16.glyph(stand_in, "w"), "w")

    def test_unknown_symbol_face_gets_symbol(self):
        g = self.gdi("symbol.ttf")
        pil = self.font(g, "Some Course Face")
        self.assertTrue(pil.path.endswith("symbol.ttf"), pil.path)
        self.assertEqual(gdi16.glyph(pil, "p"), "")

    def test_wine_src_fonts_are_installed(self):
        wine_font("wingding.ttf")
        g = gdi16.Gdi()
        self.assertTrue(self.font(g, "Wingdings").path.endswith("wingding.ttf"))

    def test_non_symbol_charset_keeps_the_stand_in(self):
        g = self.gdi("wingding.ttf")
        pil = self.font(g, "Wingdings", charset=0)
        self.assertFalse(getattr(pil, "neww_symbol", False))

    def test_face_symbol_is_symbol_charset_whatever_the_charset(self):
        # Wine 2528aff2 dlls/win32u/font.c:4439, for Symbol only, not Wingdings.
        g = self.gdi("symbol.ttf", "wingding.ttf")
        self.assertTrue(self.font(g, "Symbol", charset=0).neww_symbol)
        self.assertFalse(getattr(self.font(g, "Wingdings", charset=0), "neww_symbol", False))

    def test_no_symbol_face_keeps_the_stand_in(self):
        g = self.gdi()
        pil = self.font(g, "Wingdings")
        self.assertFalse(getattr(pil, "neww_symbol", False))
        self.assertEqual(gdi16.glyph(pil, "w"), "w")


class Courses(unittest.TestCase):
    def run_book(self, root, book, script):
        from tbpipeline_neww import machine
        host = machine.Machine(str(root), book, input_script=script, idle_stop=True)
        host.call_limit = 6000000
        host.timeout_us = 10 ** 10
        host.run(limit=host.call_limit * 1000)
        print(f"\n  stopped {host.stop} | calls {host.calls}")
        self.assertEqual([t for t in host.box.wine.trace if "(default" in t], [])
        return {Path(k[1]).name.lower() for k in host.box.wine.gdi.fonts if k[0] == "symbol"}

    def test_logic_families_p100_bullets_are_wingdings(self):
        from tests.binpath import bin_or_skip
        book = os.environ.get("TBK_BOOK2")
        if not book:
            raise unittest.SkipTest("TBK_BOOK2 (LogicFamilies.tbk) is not set")
        wine_font("wingding.ttf")
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        faces = self.run_book(root, book, "wait 500; click 512,420; wait 500; click 808,600")
        self.assertIn("wingding.ttf", faces)

    def test_p430_pi_is_the_courses_nida_face(self):
        from tests.binpath import bin_or_skip
        book = os.environ.get("TBK_BOOK3")
        if not book:
            raise unittest.SkipTest("TBK_BOOK3 (93952606.TBK) is not set")
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk", "nida.ttf")
        script = "wait 15000; click 512,420; wait 8000" + "; click 808,600; wait 8000" * 6
        self.assertIn("nida.ttf", self.run_book(root, book, script))


if __name__ == "__main__":
    unittest.main()
