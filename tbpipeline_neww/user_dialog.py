"""Modal dialog boxes, from Wine at WINE_COMMIT (2528aff2).

DialogBoxIndirectParam16 (user.exe16 dialog.c:767) locks the template, makes the dialog with
DIALOG_CreateIndirect16 (dialog.c:317) and runs user32's DIALOG_DoDialogBox (user32
dialog.c:778) until EndDialog. The dialog window's class is #32770, whose procedure is user32
USER_DefDlgProcA (defdlg.c:333): it calls the 16-bit dialog procedure kept at DWL_DLGPROC
first, and DEFDLG_Proc (defdlg.c:189) or DefWindowProc when that answers FALSE.

neww runs the dialog's message loop as Wine does, calling the program's own USER gates from a
trampoline: PeekMessage, GetMessage, TranslateMessage and DispatchMessage. So the loop waits,
switches tasks, cooks input and stops when idle exactly as the program's own loop would.
IsDialogMessage's keys are here: Tab, Escape and Return.

Not here yet, each stopping by name: a template with a menu, DS_CENTERMOUSE, and the arrow
keys' group moves.
"""

import struct

from .guest import Call
from .handlers import api
from . import gdi16

DIALOG_CLASS_ATOM = 32770
NTUSER_WNDPROC_DIALOG = 10
DLGWINDOWEXTRA = 30                     # winuser.h
DWL_MSGRESULT, DWL_DLGPROC = 0, 4       # winuser.h, a 32-bit DLGPROC slot as 16-bit code reads it
DS_ABSALIGN, DS_NOFAILCREATE, DS_SETFONT, DS_MODALFRAME, DS_NOIDLEMSG = 0x01, 0x10, 0x40, 0x80, 0x100
DS_CENTER, DS_CENTERMOUSE = 0x800, 0x1000
WS_EX_DLGMODALFRAME, WS_EX_NOPARENTNOTIFY = 0x1, 0x4
WS_CHILD, WS_VISIBLE, WS_DISABLED, WS_TABSTOP = 0x40000000, 0x10000000, 0x08000000, 0x00010000
CW_USEDEFAULT16 = 0x8000
SM_CXDLGFRAME = SM_CYDLGFRAME = 3       # win32u sysparams.c at 96 dpi
IDOK, IDCANCEL = 1, 2
BN_CLICKED = 0
DC_HASDEFID = 0x534B
DLGC_DEFPUSHBUTTON, DLGC_UNDEFPUSHBUTTON, DLGC_WANTTAB, DLGC_WANTARROWS = 0x10, 0x20, 0x2, 0x1
DLGC_WANTMESSAGE = 0x4
BS_PUSHBUTTON, BS_DEFPUSHBUTTON = 0, 1
VK_TAB, VK_RETURN, VK_SHIFT, VK_CANCEL, VK_ESCAPE, VK_EXECUTE = 0x09, 0x0D, 0x10, 0x03, 0x1B, 0x2B
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
PM_REMOVE = 1
MSGF_DIALOGBOX = 0
SW_SHOWNORMAL = 1

WM_NULL, WM_SETFOCUS, WM_ACTIVATE, WM_ERASEBKGND, WM_SHOWWINDOW = 0x00, 0x07, 0x06, 0x14, 0x18
WM_CTLCOLOR, WM_CLOSE, WM_QUIT, WM_SETFONT, WM_GETFONT, WM_NCDESTROY = 0x19, 0x10, 0x12, 0x30, 0x31, 0x82
WM_NEXTDLGCTL, WM_GETDLGCODE, WM_KEYDOWN, WM_INITDIALOG, WM_COMMAND = 0x28, 0x87, 0x100, 0x110, 0x111
WM_ENTERIDLE, WM_LBUTTONDOWN, WM_NCLBUTTONDOWN, WM_ENTERMENULOOP = 0x121, 0x201, 0xA1, 0x211
WM_TIMER, WM_COMPAREITEM, WM_VKEYTOITEM, WM_CHARTOITEM, WM_QUERYDRAGICON = 0x113, 0x39, 0x2E, 0x2F, 0x37
WM_USER = 0x400
DM_GETDEFID, DM_SETDEFID = WM_USER, WM_USER + 1
BM_SETSTYLE16 = WM_USER + 4
CTLCOLOR_DLG = 4
CONTROL_CLASSES = {0x80: "BUTTON", 0x81: "EDIT", 0x82: "STATIC", 0x83: "LISTBOX", 0x84: "SCROLLBAR",
                   0x85: "COMBOBOX"}


def _uw():
    from . import user_wnd
    return user_wnd


class DialogInfo:
    """user32 DIALOGINFO (controls.h): the focus to restore, the font, the base units, the
    result, and DF_END / DF_OWNERENABLED."""

    def __init__(self):
        self.focus = 0
        self.font = 0
        self.xbase = self.ybase = 0
        self.result = IDOK      # DIALOG_get_info (defdlg.c:299-303)
        self.ended = False
        self.owner_enabled = False


def dialog_info(wine, hwnd, create=False):
    """DIALOG_get_info (defdlg.c:290)."""
    w = _uw().wm(wine).get(hwnd)
    if w is None:
        return None
    info = getattr(w, "dlg", None)
    if info is None and create:
        info = w.dlg = DialogInfo()
    return info


def muldiv(a, b, c):
    """MulDiv: a * b / c rounded half away from zero."""
    if c == 0:
        return -1
    n = a * b
    q, r = divmod(abs(n), abs(c))
    if 2 * r >= abs(c):
        q += 1
    return q if (n >= 0) == (c > 0) else -q


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# ------------------------------------------------------------------ the template

class Reader:
    """A cursor over guest memory at (sel, off)."""

    def __init__(self, wine, sel, off=0):
        self.wine, self.sel, self.off = wine, sel, off

    def byte(self):
        b = self.wine.read(self.sel, self.off, 1)[0]
        self.off += 1
        return b

    def peek(self):
        return self.wine.read(self.sel, self.off, 1)[0]

    def word(self):
        v = struct.unpack("<H", bytes(self.wine.read(self.sel, self.off, 2)))[0]
        self.off += 2
        return v

    def dword(self):
        v = struct.unpack("<I", bytes(self.wine.read(self.sel, self.off, 4)))[0]
        self.off += 4
        return v

    def ptr(self):
        return self.sel << 16 | self.off

    def skip_string(self):
        start = self.ptr()
        while self.byte():
            pass
        return start

    def string(self):
        start = self.off
        self.skip_string()
        return bytes(self.wine.read(self.sel, start, self.off - start - 1)).decode("cp1252", "replace")


def parse_template(r):
    """DIALOG_ParseTemplate16 (user.exe16 dialog.c:243)."""
    t = {"style": r.dword(), "items": r.byte(), "x": s16(r.word()), "y": s16(r.word()),
         "cx": s16(r.word()), "cy": s16(r.word())}
    first = r.peek()
    if first == 0:
        r.byte()
        t["menu"] = None
    elif first == 0xFF:
        r.byte()
        t["menu"] = r.word()
    else:
        t["menu"] = r.string()
    if r.peek():
        t["class"] = r.skip_string()
    else:
        r.byte()
        t["class"] = DIALOG_CLASS_ATOM
    t["caption"] = r.skip_string()
    t["point"], t["face"] = 0, None
    if t["style"] & DS_SETFONT:
        t["point"] = s16(r.word())
        t["face"] = r.string()
    return t


def parse_control(r):
    """DIALOG_GetControl16 (user.exe16 dialog.c:108): the class, the caption (an integer id
    after 0xFF), and the creation data after its length byte."""
    c = {"x": s16(r.word()), "y": s16(r.word()), "cx": s16(r.word()), "cy": s16(r.word()),
         "id": r.word(), "style": r.dword()}
    if r.peek() & 0x80:
        c["class"] = CONTROL_CLASSES.get(r.byte(), "")
        c["class_ptr"] = None
    else:
        c["class_ptr"] = r.ptr()
        c["class"] = r.string()
    if r.peek() == 0xFF:
        r.byte()
        c["text_id"] = r.word()
        c["text_ptr"] = None
    else:
        c["text_id"] = None
        c["text_ptr"] = r.skip_string()
    size = r.byte()
    c["data"] = r.ptr() if size else 0
    r.off += size
    return c


# ------------------------------------------------------------------ helpers

def char_dimensions(wine, font):
    """GdiGetCharDimensions (win32u font.c) as sysparams.c get_dialog_base_units uses it:
    ((width of a-zA-Z) / 26 + 1) / 2 and the text height, with font selected."""
    uw = _uw()
    hdc = uw.get_dc(wine, 0)
    dc = gdi16.gdi(wine).objects[hdc]
    if font:
        dc.font = font
    (pil, height, *_r), _log = gdi16.realize(wine, dc)
    cx = round(pil.getlength("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    uw.release_dc(wine, 0, hdc)
    return (cx // 26 + 1) // 2, height


def children(wine, hwnd):
    return list(_uw().wm(wine).children.get(hwnd, []))


def get_dlg_item(wine, hdlg, ident):
    """GetDlgItem (user32 dialog.c:1310): the first child with the id."""
    m = _uw().wm(wine)
    for h in children(wine, hdlg):
        w = m.get(h)
        if w is not None and (w.id & 0xFFFF) == (ident & 0xFFFF):
            return h
    return 0


def next_tab_item(wine, hdlg, current, previous=False):
    """GetNextDlgTabItem (user32 dialog.c:1696) among the dialog's own children: the next
    visible, enabled child with WS_TABSTOP after current, wrapping round; with none, current."""
    m = _uw().wm(wine)
    kids = children(wine, hdlg)
    if previous:
        kids.reverse()
    if not kids:
        return 0
    start = kids.index(current) + 1 if current in kids else 0
    for h in kids[start:] + kids[:start]:
        w = m.get(h)
        if w is not None and w.style & WS_TABSTOP and w.style & WS_VISIBLE and not w.style & WS_DISABLED:
            return h
    return current if current in kids else 0


def _send(wine, hwnd, msg, wp=0, lp=0):
    result = yield from _uw().send(wine, hwnd, msg, wp, lp)
    return result


def _dlgcode(wine, hwnd):
    code = yield from _send(wine, hwnd, WM_GETDLGCODE, 0, 0)
    return code & 0xFFFF


def find_def_button(wine, hdlg):
    """DEFDLG_FindDefButton (defdlg.c:110): the first child answering DLGC_DEFPUSHBUTTON."""
    for h in children(wine, hdlg):
        code = yield from _dlgcode(wine, h)
        if code & DLGC_DEFPUSHBUTTON:
            return h
    return 0


def set_focus(wine, hwnd):
    yield from _uw().set_focus(wine, hwnd)


def restore_focus(wine, hdlg, just_activated):
    """DEFDLG_RestoreFocus (defdlg.c:74): the saved focus if it is still a child of the dialog,
    else the first tab item."""
    info = dialog_info(wine, hdlg)
    m = _uw().wm(wine)
    if info is None:
        return
    focus = info.focus
    if not focus or m.get(focus) is None or m.get(focus).parent != hdlg:
        focus = next_tab_item(wine, hdlg, 0)
        info.focus = focus
    if just_activated and m.focus and _uw().root_of(wine, m.focus) == hdlg and m.focus != hdlg:
        return
    if focus:
        yield from set_focus(wine, focus)


def set_def_button(wine, hdlg, info, new):
    """DEFDLG_SetDefButton (defdlg.c:150)."""
    old = get_dlg_item(wine, hdlg, info.result)
    code = 0
    if new:
        code = yield from _dlgcode(wine, new)
        if not code & (DLGC_UNDEFPUSHBUTTON | DLGC_DEFPUSHBUTTON):
            new = old
            code = (yield from _dlgcode(wine, new)) if new else 0
    if not old or not (yield from _dlgcode(wine, old)) & DLGC_DEFPUSHBUTTON:
        old = yield from find_def_button(wine, hdlg)
    if old and old != new:
        yield from _send(wine, old, BM_SETSTYLE16, BS_PUSHBUTTON, 1)
    if new and code & DLGC_UNDEFPUSHBUTTON:
        yield from _send(wine, new, BM_SETSTYLE16, BS_DEFPUSHBUTTON, 1)


# ------------------------------------------------------------------ the dialog procedure

def _dlgproc(w):
    return int.from_bytes(w.extra[DWL_DLGPROC:DWL_DLGPROC + 4], "little") if len(w.extra) >= 8 else 0


def _msgresult(w):
    return int.from_bytes(w.extra[DWL_MSGRESULT:DWL_MSGRESULT + 4], "little") if len(w.extra) >= 4 else 0


def defdlg_proc(wine, hwnd, msg, wp, lp, info):
    """DEFDLG_Proc (defdlg.c:189), for a message the dialog procedure left."""
    uw = _uw()
    m = uw.wm(wine)
    if msg == WM_ERASEBKGND:
        # defdlg.c:193-205: WM_CTLCOLORDLG to itself, the 16-bit WM_CTLCOLOR with CTLCOLOR_DLG.
        lpc = (CTLCOLOR_DLG << 16) | hwnd
        brush = (yield from _send(wine, hwnd, WM_CTLCOLOR, wp, lpc)) & 0xFFFF
        if not brush:
            out = yield from uw.def_window_proc(wine, hwnd, WM_CTLCOLOR, wp, lpc)
            brush = (out[0] if isinstance(out, tuple) else out or 0) & 0xFFFF
        dc = gdi16.gdi(wine).get(wp, gdi16.OBJ_DC)
        w = m.get(hwnd)
        if brush and dc is not None and w is not None:
            c = w.client
            gdi16.fill(wine, dc, (0, 0, c[2] - c[0], c[3] - c[1]), brush)
        return 1
    if msg == WM_SHOWWINDOW:
        if not wp and info is not None and m.focus and uw.root_of(wine, m.focus) == hwnd:
            info.focus = m.focus      # DEFDLG_SaveFocus
        result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    if msg == WM_ACTIVATE:
        if wp & 0xFFFF:
            yield from restore_focus(wine, hwnd, True)
        elif info is not None and m.focus and uw.root_of(wine, m.focus) == hwnd:
            info.focus = m.focus
        return 0
    if msg == WM_SETFOCUS:
        yield from restore_focus(wine, hwnd, False)
        return 0
    if msg == DM_SETDEFID:
        if info is not None and not info.ended:
            # DEFDLG_SetDefId (defdlg.c:125)
            old = get_dlg_item(wine, hwnd, info.result)
            new = get_dlg_item(wine, hwnd, wp)
            info.result = wp
            if old and (yield from _dlgcode(wine, old)) & DLGC_DEFPUSHBUTTON:
                yield from _send(wine, old, BM_SETSTYLE16, BS_PUSHBUTTON, 1)
            if new and (yield from _dlgcode(wine, new)) & DLGC_UNDEFPUSHBUTTON:
                yield from _send(wine, new, BM_SETSTYLE16, BS_DEFPUSHBUTTON, 1)
        return 1
    if msg == DM_GETDEFID:
        if info is not None and not info.ended:
            if info.result:
                return info.result & 0xFFFF | DC_HASDEFID << 16
            h = yield from find_def_button(wine, hwnd)
            if h:
                return m.get(h).id & 0xFFFF | DC_HASDEFID << 16
        return 0
    if msg == WM_NEXTDLGCTL:
        if info is not None:
            dest = wp
            if not lp & 0xFFFF:
                dest = next_tab_item(wine, hwnd, m.focus, bool(wp))
            if dest:
                yield from set_focus(wine, dest)
            yield from set_def_button(wine, hwnd, info, dest)
        return 0
    if msg in (WM_ENTERMENULOOP, WM_LBUTTONDOWN, WM_NCLBUTTONDOWN):
        result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    if msg == WM_GETFONT:
        return info.font if info is not None else 0
    if msg == WM_CLOSE:
        # defdlg.c:267-270
        cancel = get_dlg_item(wine, hwnd, IDCANCEL)
        m.queue_of(m.task_of(hwnd)).queue.append((hwnd, WM_COMMAND, IDCANCEL, BN_CLICKED << 16 | cancel))
        return 0
    if msg == WM_NCDESTROY:
        w = m.get(hwnd)
        if w is not None and getattr(w, "dlg", None) is not None:
            if info.font:
                gdi16.gdi(wine).objects.pop(info.font, None)
            w.dlg = None
        result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    return 0


DEFDLG_MESSAGES = (WM_ERASEBKGND, WM_SHOWWINDOW, WM_ACTIVATE, WM_SETFOCUS, DM_SETDEFID, DM_GETDEFID,
                   WM_NEXTDLGCTL, WM_GETFONT, WM_CLOSE, WM_NCDESTROY, WM_ENTERMENULOOP, WM_LBUTTONDOWN,
                   WM_NCLBUTTONDOWN)


def dialog_window_proc(wine, hwnd, msg, wp, lp):
    """USER_DefDlgProcA (defdlg.c:333): DWL_MSGRESULT cleared, the dialog procedure called
    (call_dialog_proc16, message.c:295: its LOWORD), then the defaults when it answers FALSE.
    WM_CTLCOLOR, the item messages and WM_INITDIALOG answer the procedure's own result, the
    rest DWL_MSGRESULT (defdlg.c:371-377)."""
    uw = _uw()
    m = uw.wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    info = dialog_info(wine, hwnd, create=True)
    if len(w.extra) >= 4:
        w.extra[DWL_MSGRESULT:DWL_MSGRESULT + 4] = bytes(4)
    proc = _dlgproc(w)
    result = 0
    if proc:
        ax, _dx = yield from uw.call_proc(wine, proc, hwnd, msg, wp, lp)
        result = ax & 0xFFFF
    w = m.get(hwnd)
    if not result and w is not None:
        if msg in DEFDLG_MESSAGES:
            out = yield from defdlg_proc(wine, hwnd, msg, wp, lp, info)
            return out
        if msg not in (WM_INITDIALOG, WM_VKEYTOITEM, WM_COMPAREITEM, WM_CHARTOITEM):
            out = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
            return out
    if msg in (WM_CTLCOLOR, WM_COMPAREITEM, WM_VKEYTOITEM, WM_CHARTOITEM, WM_QUERYDRAGICON, WM_INITDIALOG):
        return result
    return _msgresult(w) if w is not None else 0


# ------------------------------------------------------------------ making the dialog

def _enable(wine, hwnd, on):
    result = yield from _uw().enable_window(wine, None, hwnd, on)
    return result


def create_indirect(wine, inst, sel, owner, proc, param, modal):
    """DIALOG_CreateIndirect16 (user.exe16 dialog.c:317). Returns the dialog's HWND or 0."""
    uw = _uw()
    m = uw.wm(wine)
    r = Reader(wine, sel)
    t = parse_template(r)
    if t["menu"] is not None:
        yield f"DialogBox template {sel:#x}:0 has menu {t['menu']!r}: LoadMenu16 for a dialog is not in neww yet"
        return 0
    font = 0
    units = yield from _dialog_base_units(wine)
    xbase, ybase = units
    if t["style"] & DS_SETFONT:
        # dialog.c:349-372: -MulDiv(points, LOGPIXELSY, 72), FW_DONTCARE, DEFAULT_CHARSET,
        # PROOF_QUALITY, the face; the base units from GdiGetCharDimensions when it gives a width.
        pixels = muldiv(t["point"], 96, 72)
        log = gdi16._logfont(-pixels, 0, 0, 1, 0, t["face"] or "", quality=2)
        font = gdi16.gdi(wine).add(gdi16.GdiObject(gdi16.OBJ_FONT, log=log))
        cx, cy = char_dimensions(wine, font)
        if cx:
            xbase, ybase = cx, cy
    # dialog.c:376-387
    rect = (0, 0, muldiv(t["cx"], xbase, 4), muldiv(t["cy"], ybase, 8))
    ex = WS_EX_DLGMODALFRAME if t["style"] & DS_MODALFRAME else 0
    rect = uw.adjust_window_rect(rect, t["style"], False, ex)
    x, y = rect[0], rect[1]
    cx, cy = rect[2] - rect[0], rect[3] - rect[1]
    if (t["x"] & 0xFFFF) == CW_USEDEFAULT16:
        x = y = s16(CW_USEDEFAULT16)
    else:
        work = (0, 0, uw.SCREEN_W, uw.SCREEN_H)
        if t["style"] & DS_CENTER:
            x = (work[0] + work[2] - cx) // 2
            y = (work[1] + work[3] - cy) // 2
        elif t["style"] & DS_CENTERMOUSE:
            yield "DialogBox with DS_CENTERMOUSE: neww has no GetCursorPos placement for a dialog yet"
            return 0
        else:
            x += muldiv(t["x"], xbase, 4)
            y += muldiv(t["y"], ybase, 8)
            if not t["style"] & (WS_CHILD | DS_ABSALIGN) and owner and m.get(owner) is not None:
                ox, oy = uw.screen_origin(wine, owner)       # ClientToScreen(owner)
                x, y = x + ox, y + oy
        if not t["style"] & WS_CHILD:
            # dialog.c:420-436: fit it into the work area.
            dx = x + cx + SM_CXDLGFRAME - work[2]
            if dx > 0:
                x -= dx
            dy = y + cy + SM_CYDLGFRAME - work[3]
            if dy > 0:
                y -= dy
            x, y = max(x, work[0]), max(y, work[1])
    info_owner_enabled = False
    if modal and owner:
        # DIALOG_DisableOwner (dialog.c:86): the owner's root, if it is enabled.
        root = uw.root_of(wine, owner)
        rw = m.get(root)
        if rw is not None and not rw.style & WS_DISABLED:
            yield from _enable(wine, root, False)
            info_owner_enabled = True
    hwnd = yield from uw.create_window(wine, ex, t["class"], t["caption"], t["style"] & ~WS_VISIBLE,
                                       x & 0xFFFF, y & 0xFFFF, cx, cy, owner, 0, inst, 0)
    if not hwnd:
        if font:
            gdi16.gdi(wine).objects.pop(font, None)
        if modal and info_owner_enabled:
            yield from _enable(wine, uw.root_of(wine, owner), True)
        return 0
    info = dialog_info(wine, hwnd, create=True)
    info.focus, info.font, info.xbase, info.ybase = 0, font, xbase, ybase
    info.result, info.ended, info.owner_enabled = 0, False, info_owner_enabled
    w = m.get(hwnd)
    if len(w.extra) >= 8:
        w.extra[DWL_DLGPROC:DWL_DLGPROC + 4] = struct.pack("<I", proc & 0xFFFFFFFF)
    if font:
        yield from _send(wine, hwnd, WM_SETFONT, font, 0)
    ok = yield from create_controls(wine, hwnd, r, t, inst, info)
    if ok:
        # dialog.c:466-494
        info.focus = next_tab_item(wine, hwnd, 0)
        before = m.focus
        r_init = yield from _send(wine, hwnd, WM_INITDIALOG, info.focus, param)
        if r_init & 0xFFFF:
            info.focus = next_tab_item(wine, hwnd, 0)
            if info.focus:
                yield from set_focus(wine, info.focus)
        elif m.focus == before and m.get(hwnd) is not None and m.get(hwnd).style & WS_VISIBLE:
            info.focus = next_tab_item(wine, hwnd, 0)
            if info.focus:
                yield from set_focus(wine, info.focus)
        w = m.get(hwnd)
        if t["style"] & WS_VISIBLE and w is not None and not w.style & WS_VISIBLE:
            yield from uw.show_window(wine, hwnd, SW_SHOWNORMAL)
        return hwnd
    if m.get(hwnd) is not None:
        yield from uw.destroy_window(wine, hwnd)
    if modal and info_owner_enabled:
        yield from _enable(wine, uw.root_of(wine, owner), True)
    return 0


def _dialog_base_units(wine):
    from .user_res import get_dialog_base_units
    units = get_dialog_base_units(wine, None)
    return units & 0xFFFF, units >> 16
    yield  # a generator, for yield from


def create_controls(wine, hwnd, r, t, inst, info):
    """DIALOG_CreateControls16 (user.exe16 dialog.c:173): each control at its dialog units,
    WS_EX_NOPARENTNOTIFY and WS_CHILD, the dialog font sent, and the last default push button
    kept as the result id, an earlier one set back to BS_PUSHBUTTON."""
    uw = _uw()
    default = 0
    for _ in range(t["items"]):
        c = parse_control(r)
        mark = uw.scratch_mark(wine)
        cls = c["class_ptr"] or uw.scratch(wine, c["class"].encode("ascii") + b"\0")
        if c["text_ptr"] is not None:
            text = c["text_ptr"]
        else:
            text = uw.scratch(wine, bytes([0xFF, c["text_id"] & 0xFF, c["text_id"] >> 8, 0]))
        ctl = yield from uw.create_window(
            wine, WS_EX_NOPARENTNOTIFY, cls, text, c["style"] | WS_CHILD,
            muldiv(c["x"], info.xbase, 4) & 0xFFFF, muldiv(c["y"], info.ybase, 8) & 0xFFFF,
            muldiv(c["cx"], info.xbase, 4) & 0xFFFF, muldiv(c["cy"], info.ybase, 8) & 0xFFFF,
            hwnd, c["id"], inst, c["data"])
        uw.scratch_release(wine, mark)
        if not ctl:
            if t["style"] & DS_NOFAILCREATE:
                continue
            return False
        if info.font:
            yield from _send(wine, ctl, WM_SETFONT, info.font, 0)
        code = yield from _dlgcode(wine, ctl)
        if code & DLGC_DEFPUSHBUTTON:
            if default:
                yield from _send(wine, default, BM_SETSTYLE16, BS_PUSHBUTTON, 0)
            default = ctl
            info.result = c["id"]
    return True


# ------------------------------------------------------------------ the modal loop

def _gate(wine, name):
    from .handlers import spec_types
    ordinal = spec_types("USER", name)[0]
    where = wine.gate_address("USER", ordinal) if wine.gate_address else None
    return where


def _msg_block(wine):
    """A MSG16 of the loop's own, as DIALOG_DoDialogBox's MSG on its stack."""
    m = _uw().wm(wine)
    block = getattr(m, "dialog_msgs", None)
    if block is None:
        handle, _dx, why = wine._global_alloc(0x0040, 0x400)
        if why:
            return None
        block = m.dialog_msgs = [wine.selector_of(handle), 0]
    if block[1] + 16 > 0x400:
        return None
    off = block[1]
    block[1] += 16
    return block[0], off


def _release_msg_block(wine):
    _uw().wm(wine).dialog_msgs[1] -= 16


def is_dialog_message(wine, hdlg, msg):
    """IsDialogMessageW (user32 dialog.c:1150), the part before Translate and Dispatch: True
    when the message was a dialog key it handled."""
    uw = _uw()
    m = uw.wm(wine)
    h, message, wp = msg[0], msg[1], msg[2]
    if m.get(hdlg) is None or (h != hdlg and not uw.is_child_of(m, h, hdlg)):
        return None      # not the dialog's: TranslateMessage and DispatchMessage as usual
    if message != WM_KEYDOWN:
        return False
    code = yield from _dlgcode(wine, h)
    if code & DLGC_WANTMESSAGE:
        return False
    if wp == VK_TAB and not code & DLGC_WANTTAB:
        from .input16 import state
        shift = bool(state(wine).keys.get(VK_SHIFT)) if hasattr(state(wine), "keys") else False
        yield from _send(wine, hdlg, WM_NEXTDLGCTL, int(shift), 0)
        return True
    if wp in (VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN) and not code & DLGC_WANTARROWS:
        yield f"IsDialogMessage arrow key {wp:#x}: GetNextDlgGroupItem is not in neww yet"
        return True
    if wp in (VK_CANCEL, VK_ESCAPE):
        cancel = get_dlg_item(wine, hdlg, IDCANCEL)
        yield from _send(wine, hdlg, WM_COMMAND, IDCANCEL, cancel)
        return True
    if wp in (VK_EXECUTE, VK_RETURN):
        focus = m.focus
        fw = m.get(focus)
        if focus and fw is not None and uw.is_child_of(m, focus, hdlg) and \
                (yield from _dlgcode(wine, focus)) & DLGC_DEFPUSHBUTTON:
            yield from _send(wine, hdlg, WM_COMMAND, fw.id & 0xFFFF, BN_CLICKED << 16 | focus)
            return True
        dw = yield from _send(wine, hdlg, DM_GETDEFID, 0, 0)
        if dw >> 16 == DC_HASDEFID:
            ident = dw & 0xFFFF
            hdef = get_dlg_item(wine, hdlg, ident)
            if not hdef or not m.get(hdef).style & WS_DISABLED:
                yield from _send(wine, hdlg, WM_COMMAND, ident, BN_CLICKED << 16 | hdef)
        else:
            yield from _send(wine, hdlg, WM_COMMAND, IDOK, get_dlg_item(wine, hdlg, IDOK))
        return True
    return False


def do_dialog_box(wine, hwnd, owner):
    """DIALOG_DoDialogBox (user32 dialog.c:778), its PeekMessage, GetMessage, TranslateMessage
    and DispatchMessage made through the program's USER gates. Returns the result."""
    uw = _uw()
    m = uw.wm(wine)
    info = dialog_info(wine, hwnd)
    if info is None:
        return 0xFFFF
    gates = {n: _gate(wine, n) for n in ("PeekMessage", "GetMessage", "TranslateMessage", "DispatchMessage")}
    missing = [n for n, g in gates.items() if g is None]
    if missing:
        yield f"DialogBox loop: USER {', '.join(missing)} has no gate to call"
        return 0xFFFF
    block = _msg_block(wine)
    if block is None:
        yield "DialogBox loop: no room for another nested dialog's MSG"
        return 0xFFFF
    sel, off = block
    first_empty = True
    try:
        while not info.ended:
            cs, ip = gates["PeekMessage"]
            got, _dx = yield Call(cs, ip, words=[sel, off, 0, 0, 0, PM_REMOVE])
            if not got & 0xFFFF:
                if first_empty:
                    yield from uw.show_window(wine, hwnd, SW_SHOWNORMAL)
                    first_empty = False
                w = m.get(hwnd)
                if w is not None and not w.style & DS_NOIDLEMSG and owner:
                    yield from _send(wine, owner, WM_ENTERIDLE, MSGF_DIALOGBOX, hwnd)
                cs, ip = gates["GetMessage"]
                yield Call(cs, ip, words=[sel, off, 0, 0, 0])
            h, message, wp, lp = struct.unpack("<HHHI", bytes(wine.read(sel, off, 10)))
            if message == WM_QUIT:
                uw.wm(wine).quit = wp           # NtUserPostQuitMessage
                if m.get(hwnd) is None:
                    return 0
                break
            if m.get(hwnd) is None:
                return 0
            if not info.ended:
                handled = yield from is_dialog_message(wine, hwnd, (h, message, wp, lp))
                if not handled:
                    for name in ("TranslateMessage", "DispatchMessage"):
                        cs, ip = gates[name]
                        yield Call(cs, ip, words=[sel, off])
            if m.get(hwnd) is None:
                return 0
            if info.ended:
                break
            if first_empty and message == WM_TIMER:
                yield from uw.show_window(wine, hwnd, SW_SHOWNORMAL)
                first_empty = False
    finally:
        _release_msg_block(wine)
    result = info.result
    yield from uw.destroy_window(wine, hwnd)
    return result


# ------------------------------------------------------------------ USER calls

@api("USER", "DialogBoxIndirectParam")
def dialog_box_indirect_param(wine, arg, inst, template, owner, proc, param):
    """DialogBoxIndirectParam16 (user.exe16 dialog.c:767): -1 when the template does not lock
    or the dialog is not made, else the EndDialog value."""
    sel = wine.selector_of(template) if template else None
    if not sel:
        return 0xFFFF
    hwnd = yield from create_indirect(wine, inst, sel, owner, proc, param, True)
    if not hwnd:
        return 0xFFFF
    result = yield from do_dialog_box(wine, hwnd, owner)
    return result & 0xFFFF


@api("USER", "EndDialog")
def end_dialog(wine, arg, hwnd, retval):
    """EndDialog16 -> EndDialog (user32 dialog.c:909): FALSE for a window with no dialog info;
    else the result kept, DF_END, the owner enabled, the focus moved to the dialog, the dialog
    hidden, the owner made foreground, and WM_NULL posted to wake the loop. TRUE."""
    uw = _uw()
    m = uw.wm(wine)
    info = dialog_info(wine, hwnd)
    if info is None:
        return 0
    info.result = s16(retval)
    info.ended = True
    w = m.get(hwnd)
    owner = w.owner if not w.style & WS_CHILD else w.parent
    if owner and m.get(owner) is not None:
        yield from _enable(wine, owner, True)
    if m.focus and uw.is_child_of(m, m.focus, hwnd):
        yield from uw.set_focus(wine, hwnd)
    yield from uw.set_window_pos(wine, hwnd, 0, 0, 0, 0, 0, uw.SWP_NOMOVE | uw.SWP_NOSIZE | uw.SWP_NOZORDER
                                 | uw.SWP_NOACTIVATE | uw.SWP_HIDEWINDOW)
    if hwnd == m.active:
        if owner:
            yield from uw.set_foreground(wine, owner)
        else:
            yield from uw.activate_other(wine, hwnd)
    m.queue_of(m.task_of(hwnd)).queue.append((hwnd, WM_NULL, 0, 0))
    return 1


@api("USER", "GetDlgItem")
def get_dlg_item16(wine, arg, hdlg, ident):
    """GetDlgItem16 (user.exe16 dialog.c:542) -> GetDlgItem (user32 dialog.c:1310)."""
    return get_dlg_item(wine, hdlg, ident)


@api("USER", "SetDlgItemText")
def set_dlg_item_text(wine, arg, hdlg, ident, ptr):
    """SetDlgItemText16 (user.exe16 dialog.c:551): SendDlgItemMessage16 WM_SETTEXT. Void."""
    h = get_dlg_item(wine, hdlg, ident)
    if h:
        yield from _send(wine, h, 0x0C, 0, ptr)
    return arg.regs("ax"), 0


@api("USER", "GetDlgItemText")
def get_dlg_item_text(wine, arg, hdlg, ident, ptr, count):
    """GetDlgItemText16 (user.exe16 dialog.c:560): SendDlgItemMessage16 WM_GETTEXT."""
    h = get_dlg_item(wine, hdlg, ident)
    if not h:
        return 0
    result = yield from _send(wine, h, 0x0D, count, ptr)
    return result & 0xFFFF


@api("USER", "SendDlgItemMessage")
def send_dlg_item_message(wine, arg, hdlg, ident, msg, wp, lp):
    """SendDlgItemMessage16 (user.exe16 dialog.c:656): 0 with no such item."""
    h = get_dlg_item(wine, hdlg, ident)
    if not h:
        return 0
    result = yield from _send(wine, h, msg, wp, lp)
    return result


@api("USER", "DefDlgProc")
def def_dlg_proc16(wine, arg, hwnd, msg, wp, lp):
    """DefDlgProc16 (message.c:1641): the dialog defaults for a message, as USER_DefDlgProcA
    gives them when the dialog procedure answered FALSE."""
    info = dialog_info(wine, hwnd, create=True)
    if info is None:
        return 0
    if msg in DEFDLG_MESSAGES:
        result = yield from defdlg_proc(wine, hwnd, msg, wp, lp, info)
        return result
    if msg in (WM_INITDIALOG, WM_VKEYTOITEM, WM_COMPAREITEM, WM_CHARTOITEM):
        return 0
    result = yield from _uw().def_window_proc(wine, hwnd, msg, wp, lp)
    return result
