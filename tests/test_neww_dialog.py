"""Modal dialog boxes in neww (roadmap #201, item T9b).

Each test checks against the Wine function its docstring or comment names, at 2528aff2:
user.exe16 dialog.c DialogBoxIndirectParam16, DIALOG_CreateIndirect16 and
DIALOG_CreateControls16, user32 dialog.c DIALOG_DoDialogBox, IsDialogMessageW and EndDialog,
and user32 defdlg.c USER_DefDlgProcA. No ToolBook bytes: the template is built here, like
ToolBook's request box (a static and two push buttons in Helv 8), and the guest's calls are
answered by the test (tests/test_neww_batch2.py's harness).
"""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA, NUL, put
from tests.test_neww_batch2 import INST, by_name
from tests.test_neww_batch6 import control_wine, guest_reply, top_window

DLGPROC = 0x0130_0010
GATES = {"PeekMessage": (0x0710, 0x10), "GetMessage": (0x0710, 0x20), "TranslateMessage": (0x0710, 0x30),
         "DispatchMessage": (0x0710, 0x40)}
WM_SETTEXT, WM_INITDIALOG, WM_COMMAND, WM_KEYDOWN, WM_CTLCOLOR = 0x0C, 0x110, 0x111, 0x100, 0x19
VK_RETURN, VK_ESCAPE = 0x0D, 0x1B
TEMPLATE_OFF, TEXT_OFF, MSG_TEXT = 0x400, 0x600, "Do you want to exit the lesson?"


def request_box():
    """A 16-bit DLGTEMPLATE: WS_POPUP | WS_VISIBLE | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME |
    DS_SETFONT, at 30,20 and 213x52 dialog units, Helv 8, three items."""
    t = struct.pack("<IBhhhh", 0x90C800C0, 3, 30, 20, 213, 52) + b"\0" + b"\0" + b"   \0"
    t += struct.pack("<H", 8) + b"Helv\0"
    for x, y, cx, cy, ident, style, cls in ((6, 6, 200, 24, 0xEDA, 0x50020000, 0x82),
                                             (50, 32, 54, 14, 0xEDB, 0x50030001, 0x80),
                                             (110, 32, 54, 14, 0xEDC, 0x50010000, 0x80)):
        t += struct.pack("<hhhhHIB", x, y, cx, cy, ident, style, cls) + b"\0" + b"\0"
    return t


class DialogBox(unittest.TestCase):

    def setUp(self):
        self.w = control_wine()
        relay = self.w.gate_address

        def gates(module, ordinal):
            from tbpipeline_neww.handlers import spec_types
            for name, where in GATES.items():
                if module == "USER" and spec_types("USER", name)[0] == ordinal:
                    return where
            return relay(module, ordinal)
        self.w.gate_address = gates
        self.top = top_window(self.w)
        by_name(self.w, "USER", "ShowWindow", self.top, 1, reply=guest_reply)
        handle = by_name(self.w, "KERNEL", "GlobalAlloc", 0x42, (0, 0x200))[0]
        self.template = handle
        self.w.memory.write(self.w.selector_of(handle), 0, request_box())
        put(self.w, TEXT_OFF, MSG_TEXT)
        self.seen = []
        self.keys = []
        self.dialog = None

    def reply(self, call):
        """The guest: the dialog procedure, the message gates, and every other window
        procedure (answered as guest_reply does)."""
        where = (call.cs, call.ip)
        if where == GATES["PeekMessage"]:
            return 0, 0
        if where == GATES["GetMessage"]:
            sel, off = call.words[0], call.words[1]
            hwnd, key = self.keys.pop(0)
            if not hwnd:
                from tbpipeline_neww.user_wnd import wm
                hwnd = wm(self.w).focus     # a key goes to the focus window
            self.w.memory.write(sel, off, struct.pack("<HHHIIhh", hwnd, WM_KEYDOWN, key, 1, 0, 0, 0))
            return 1, 0
        if where in (GATES["TranslateMessage"], GATES["DispatchMessage"]):
            return 0, 0
        if (call.cs << 16 | call.ip) == DLGPROC:
            hwnd, msg, wp = call.words[0], call.words[1], call.words[2]
            self.seen.append((msg, wp, call.words[3] << 16 | call.words[4]))
            if msg == WM_INITDIALOG:
                self.dialog = hwnd
                by_name(self.w, "USER", "SetDlgItemText", hwnd, 0xEDA, (DATA, TEXT_OFF), reply=self.reply)
                return 1, 0
            if msg == WM_COMMAND:
                by_name(self.w, "USER", "EndDialog", hwnd, wp, reply=self.reply)
                return 1, 0
            return 0, 0
        return guest_reply(call)

    def run_box(self, keys):
        self.keys = list(keys)
        return by_name(self.w, "USER", "DialogBoxIndirectParam", INST, self.template, self.top, (DLGPROC >> 16, DLGPROC & 0xFFFF),
                       (0x1234, 0x5678), reply=self.reply)

    def test_return_ends_the_box_with_the_default_button(self):
        # DIALOG_CreateIndirect16 sends WM_INITDIALOG with the first tab item and the param
        # (dialog.c:466-470); Return is DM_GETDEFID's button (IsDialogMessageW, user32
        # dialog.c:1247-1262), whose WM_COMMAND ends the box; the answer is EndDialog's value.
        from tbpipeline_neww.user_wnd import wm
        ax, _dx, stop, _calls = self.run_box([(0, VK_RETURN)])
        self.assertIsNone(stop)
        self.assertIsNotNone(self.dialog)
        init = [s for s in self.seen if s[0] == WM_INITDIALOG]
        self.assertEqual(len(init), 1)
        self.assertEqual(init[0][2], 0x12345678)
        self.assertIn((WM_COMMAND, 0xEDB, init[0][1]), self.seen)
        self.assertEqual(ax, 0xEDB)
        # DIALOG_DoDialogBox destroys the dialog (dialog.c:842).
        self.assertIsNone(wm(self.w).get(self.dialog))

    def test_escape_sends_idcancel(self):
        # IsDialogMessageW (dialog.c:1241-1244): VK_ESCAPE is WM_COMMAND IDCANCEL.
        ax = self.run_box([(0, VK_ESCAPE)])[0]
        self.assertIn((WM_COMMAND, 2, 0), self.seen)
        self.assertEqual(ax, 2)

    def test_controls_are_placed_in_dialog_units_and_get_the_text(self):
        # DIALOG_CreateControls16 (dialog.c:200-207): x * xBaseUnit / 4, y * yBaseUnit / 8, the
        # dialog font's units (GdiGetCharDimensions); SetDlgItemText is WM_SETTEXT.
        from tbpipeline_neww.user_wnd import wm
        placed = {}

        def keep(call):
            out = self.reply(call)
            if self.dialog and not placed:
                m = wm(self.w)
                for h in m.children.get(self.dialog, []):
                    c = m.get(h)
                    placed[c.id] = (c.rect, c.text, c.style)
                placed["units"] = (m.get(self.dialog).dlg.xbase, m.get(self.dialog).dlg.ybase)
                placed["owner_disabled"] = bool(m.get(self.top).style & 0x08000000)
            return out
        by_name(self.w, "USER", "DialogBoxIndirectParam", INST, self.template, self.top, (DLGPROC >> 16, DLGPROC & 0xFFFF), (0, 0),
                reply=lambda c: (self.keys.append((0, VK_RETURN)) or keep(c)) if not self.keys else keep(c))
        xb, yb = placed["units"]
        self.assertGreater(xb, 0)
        self.assertEqual(placed[0xEDB][0][:2], ((50 * xb + 2) // 4, (32 * yb + 4) // 8))
        self.assertEqual(placed[0xEDA][1], MSG_TEXT)
        # DIALOG_DisableOwner while the box is up; EndDialog enables it again (dialog.c:925-927).
        self.assertTrue(placed["owner_disabled"])
        self.assertFalse(wm(self.w).get(self.top).style & 0x08000000)

    def test_a_template_that_does_not_lock_is_minus_one(self):
        # DialogBoxIndirectParam16 (dialog.c:772): GlobalLock16 fails, -1.
        self.assertEqual(by_name(self.w, "USER", "DialogBoxIndirectParam", INST, 0, self.top, (DLGPROC >> 16, DLGPROC & 0xFFFF),
                                 (0, 0))[0], 0xFFFF)


# ---------------------------------------------------------------- Logic Families

LESSON_EXIT, YES, NO = "click 512,425; ", "click 458,416; ", "click 570,416; "


def lesson_menu(script):
    """Logic Families walked to the Lesson Menu P900 as tests/test_neww_lf_walk.py does, then
    script. Needs TBK_BIN and TBK_BOOK2."""
    from tests.test_neww_lf_walk import TO_MENU, WAIT, walk
    return walk(TO_MENU + WAIT + script)


def dialogs(host):
    from tbpipeline_neww.user_wnd import wm
    m = wm(host.box.wine)
    return [w for w in m.windows.values() if getattr(w, "dlg", None) is not None]


class LessonExit(unittest.TestCase):
    """P900's Lesson Exit asks first: ToolBook's request box through DialogBoxIndirectParam."""

    def test_lesson_exit_shows_the_request_box(self):
        host, pages = lesson_menu(LESSON_EXIT + "wait 2000; move 10,10")
        self.assertEqual([p for p in pages if p][-1], "P900")
        self.assertTrue(host.stop.startswith("idle: input script done"), host.stop)
        boxes = dialogs(host)
        self.assertEqual(len(boxes), 1)
        from tbpipeline_neww.user_wnd import wm
        m = wm(host.box.wine)
        texts = {m.get(h).cls.name: m.get(h).text for h in m.children.get(boxes[0].hwnd, [])
                 if m.get(h).cls.name == "Static"}
        self.assertEqual(texts, {"Static": "Are you sure you want to Exit the Lesson?"})
        buttons = [m.get(h).text for h in m.children.get(boxes[0].hwnd, []) if m.get(h).cls.name == "Button"]
        self.assertEqual(buttons, ["&Yes", "&No"])

    def test_no_closes_the_box_and_stays_on_the_menu(self):
        host, pages = lesson_menu(LESSON_EXIT + "wait 2000; " + NO + "wait 2000; move 10,10")
        self.assertEqual(dialogs(host), [])
        self.assertTrue(host.stop.startswith("idle: input script done"), host.stop)
        # The clicks on the box draw no page, so the last page drawn is still the menu.
        self.assertEqual([p for p in pages if p][-1], "P900")
        self.assertEqual(sum(t.startswith("USER.240 DialogBoxIndirectParam") for t in host.box.wine.trace), 1)


if __name__ == "__main__":
    unittest.main()
