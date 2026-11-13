"""What the NIDA ATT course 93952606.TBK ("Parallel Resonance") calls when it leaves (#226):
FreeLibrary at a module's last use, OleFlushClipboard, NotifyRegister and NotifyUnregister.

The synthetic tests run the handlers on fake memory (tests/test_neww_batch2.py's harness), each
against the Wine 2528aff2 function its comment names. The course tests need TBK_BIN and
TBK_BOOK3, and walk the course from its Lesson Menu (P900): the Final Quiz to its score page,
the lesson, and Lesson Exit, which ends the task.
"""

import os
import re
import unittest

from tests.test_neww_batch2 import by_name, window_wine


class FreeLibraryAtLastUse(unittest.TestCase):
    """dlls/krnl386.exe16/ne_module.c:1143 NE_FreeModule: at count 0 the module is unloaded,
    its WEP first (MODULE_CallWEP, :1112)."""

    def setUp(self):
        self.w = window_wine()
        self.w.modules["TBX"] = 0x300
        self.w.usage[0x300] = 1
        self.w._exe_ptr = lambda handle: handle
        self.w.release_module = lambda name: 0
        self.finished = []

    def test_last_use_calls_the_wep_then_unloads(self):
        from tbpipeline_neww.guest import Call
        wep = Call(0x400, 0x10, words=[0])

        def unload(name):
            return [wep], lambda: self.finished.append(name)
        self.w.unload_module = unload
        _ax, _dx, stop, made = by_name(self.w, "KERNEL", "FreeLibrary", 0x300)
        self.assertIsNone(stop)
        self.assertEqual(made, [wep])
        self.assertEqual(made[0].words, [0])           # WEP_FREE_DLL
        self.assertEqual(self.finished, ["TBX"])

    def test_a_module_with_no_wep_is_unloaded_at_once(self):
        self.w.unload_module = lambda name: ([], lambda: self.finished.append(name))
        _ax, _dx, stop, made = by_name(self.w, "KERNEL", "FreeLibrary", 0x300)
        self.assertIsNone(stop)
        self.assertEqual((made, self.finished), ([], ["TBX"]))

    def test_an_unload_neww_cannot_finish_stops_by_name(self):
        self.w.unload_module = lambda name: "unloading TBX frees TBY too"
        stop = by_name(self.w, "KERNEL", "FreeLibrary", 0x300)[2]
        self.assertIn("unloading TBX frees TBY too", stop)

    def test_a_later_use_only_counts_down(self):
        self.w.usage[0x300] = 2
        released = []
        self.w.release_module = released.append
        self.w.unload_module = lambda name: self.fail("unloaded with a use left")
        self.assertIsNone(by_name(self.w, "KERNEL", "FreeLibrary", 0x300)[2])
        self.assertEqual(released, ["TBX"])

    def test_loading_an_unloaded_module_again_stops(self):
        # Wine would load it afresh and run its LibMain again.
        del self.w.modules["TBX"]
        self.w.unloaded["TBX"] = "TBX.DLL"
        self.w.trace.append("KERNEL.95 LoadLibrary")
        stop = self.w._load_library("C:\\TBK\\TBX.DLL")[2]
        self.assertIn("FreeLibrary unloaded it", stop)


class OleFlushClipboard(unittest.TestCase):
    """dlls/ole2.dll16/ole2.c:270 -> dlls/ole32/clipboard.c:2277 OleFlushClipboard."""

    def test_before_ole_initialize_it_is_e_fail(self):
        w = window_wine()
        self.assertEqual(by_name(w, "OLE2", "OleFlushClipboard")[0], 0x4005)   # E_FAIL, -ret16

    def test_after_ole_initialize_with_no_source_it_is_s_ok(self):
        w = window_wine()
        by_name(w, "OLE2", "OleInitialize", (0, 0))
        ax, _dx, stop, _made = by_name(w, "OLE2", "OleFlushClipboard")
        self.assertEqual((ax, stop), (0, None))


class Notify(unittest.TestCase):
    """dlls/toolhelp.dll16/toolhelp.c:550 NotifyRegister16 and :580 NotifyUnregister16."""

    def test_unregister_with_nothing_registered_is_false(self):
        w = window_wine()
        ax, _dx, stop, _made = by_name(w, "TOOLHELP", "NotifyUnregister", 0)
        self.assertEqual((ax, stop), (0, None))

    def test_register_then_unregister_for_the_current_task(self):
        w = window_wine()
        self.assertEqual(by_name(w, "TOOLHELP", "NotifyRegister", 0, (0x1234, 0x10), 0x0F)[0], 1)
        self.assertEqual(by_name(w, "TOOLHELP", "NotifyUnregister", w.htask)[0], 1)
        self.assertEqual(by_name(w, "TOOLHELP", "NotifyUnregister", 0)[0], 0)


E_BASE = "wait 15000; click 512,420; wait 8000" + "; click 808,600; wait 8000" * 9   # to P900
MENU_QUIZ, MENU_LESSON, MENU_EXIT = "click 514,311", "click 514,257", "click 514,366"
BEGIN, OK, YES = "click 480,272", "click 453,601", "click 457,416"
# The quiz page is drawn in a memory DC and blitted to the window at (201, 173); a choice's
# letter button is left of its text.
PAGE_X, PAGE_Y = 201, 173
CHOICE_ROWS = (110, 175, 240, 305)


class Course(unittest.TestCase):
    def setUp(self):
        from tests.binpath import bin_or_skip
        from tbpipeline_neww import gdi16
        self.book = os.environ.get("TBK_BOOK3")
        if not self.book:
            raise unittest.SkipTest("TBK_BOOK3 (93952606.TBK) is not set")
        self.root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        self.pages, self.q, self.choices = [], None, []
        draw = gdi16.draw_text

        def watch(wine, dc, x, y, text, *a, **k):
            t = text.strip()
            if re.fullmatch(r"P\d+", t) and (not self.pages or self.pages[-1] != t):
                self.pages.append(t)
            m = re.fullmatch(r"Question (\d+)\.", t)
            if m:
                if self.q != int(m.group(1)):
                    self.q, self.choices = int(m.group(1)), []
            elif dc.memory and self.q and any(abs(y - r) <= 3 for r in CHOICE_ROWS) \
                    and all(abs(c[1] - y) > 3 for c in self.choices):
                self.choices.append((x, y))
            return draw(wine, dc, x, y, text, *a, **k)
        gdi16.draw_text = watch
        self.addCleanup(setattr, gdi16, "draw_text", draw)

    def run_course(self, script, driver=None):
        from tbpipeline_neww import machine
        host = machine.Machine(str(self.root), self.book, input_script=script, idle_stop=True)
        host.box.wine.on_idle = driver
        host.call_limit = 6000000
        host.timeout_us = 10 ** 11
        host.run(limit=host.call_limit * 1000)
        print(f"\n  stopped {host.stop} | calls {host.calls} | pages {' '.join(self.pages)}")
        trace = host.box.wine.trace
        self.assertEqual([t for t in trace if "(default" in t], [])
        self.assertEqual([t for t in trace if t.startswith("USER.1 MessageBox")], [])
        return host

    def test_final_quiz_to_its_score_page_and_the_review(self):
        answered, waits, score = set(), {}, []

        def driver(wine):
            # Answer "a" on each question once its four choices are drawn, then OK. Until they
            # are, let the course's timers run: it shows the next question from a timer.
            if self.pages and self.pages[-1] == "P10303":
                if score:
                    return None
                score.append(True)
                return f"wait 4000; click 408,451; wait 4000; {OK}; wait 20000; move 900,700"
            if not self.q or self.q in answered:
                return None
            if len(self.choices) < 4:
                waits[self.q] = waits.get(self.q, 0) + 1
                return f"wait 3000; move {900 + waits[self.q]},700" if waits[self.q] <= 3 else None
            answered.add(self.q)
            x, y = min(self.choices, key=lambda c: c[1])
            return f"wait 4000; click {PAGE_X + x - 35},{PAGE_Y + y + 9}; wait 4000; {OK}; wait 8000; move 900,700"

        host = self.run_course(f"{E_BASE}; {MENU_QUIZ}; wait 15000; {BEGIN}; wait 20000; move 900,700", driver)
        self.assertTrue(host.stop.startswith("idle:"), host.stop)
        self.assertEqual(answered, set(range(1, 11)))
        self.assertEqual(self.pages[self.pages.index("P900"):], ["P900", "P10004", "P10303", "P900", "P10410"])

    def test_the_lesson_opens_from_the_menu(self):
        host = self.run_course(f"{E_BASE}; {MENU_LESSON}; wait 15000; move 900,700")
        self.assertTrue(host.stop.startswith("idle:"), host.stop)
        self.assertEqual(self.pages[-2:], ["P900", "P1001"])

    def test_lesson_exit_yes_unloads_the_toolbook_dlls(self):
        host = self.run_course(f"{E_BASE}; {MENU_EXIT}; wait 15000; {YES}; wait 15000; move 900,700")
        trace = host.box.wine.trace
        for name in ("TBCBT", "TBWIN", "TBFILE32"):
            self.assertIn(f"  {name} unloaded, its WEP called", trace)
        self.assertIn("OLE2.76 OleFlushClipboard", trace)
        # TB80OLE releases its automation object (#233), and the 32-bit DLLs are detached.
        for name in ("TB80F32L", "TB80RMT", "TB80W32"):
            self.assertIn(f"  {name} DllMain(PROCESS_DETACH)", trace)
            self.assertIn(f"  {name} unloaded", trace)
        self.assertEqual(host.stop, "dos exit 0x0")


if __name__ == "__main__":
    unittest.main()
