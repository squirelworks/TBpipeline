"""Wine's built-in window classes, whose window procedures are Wine's own code, not the guest's.

win32u class.c registers the built-in classes, each with the window procedure handle
MAKE_WNDPROC(index): 0xFFFF0000 | index, index being its ntuser_client_procs value. A 16-bit
program sees that procedure through user.exe16 message.c alloc_win16_thunk: a 15-byte packed
WINPROC_THUNK, popl %eax ; pushl $proc ; pushl %eax ; ljmp __wine_call_wndproc (USER.1010),
at offset index * 15 of a GMEM_FIXED block from GlobalAlloc16. Calling the thunk, or passing it to CallWindowProc, or sending to a
window that has it, runs the procedure here.

The classes are registered the first time one is looked up: neww gives them their atoms then,
where Wine registers every built-in class when user32 starts.

Only SCROLLBAR is here so far (win32u scroll.c). Each other built-in class still stops by name.
"""

import struct

from .guest import Call  # noqa: F401  (procedures may yield guest calls)
from .handlers import api
from . import gdi16

# include/ntuser.h enum ntuser_client_procs
NTUSER_WNDPROC_SCROLLBAR = 0

WINPROC_HANDLE = 0xFFFF0000
THUNK_SIZE = 15            # sizeof(WINPROC_THUNK), packed: 2 + 2 + 4 + 2 + 1 + 4
MAX_WINPROCS16 = 1024

CS_VREDRAW, CS_HREDRAW, CS_DBLCLKS, CS_PARENTDC = 0x0001, 0x0002, 0x0008, 0x0080
IDC_ARROW = 32512

# winuser.h
SB_HORZ, SB_VERT, SB_CTL, SB_BOTH = 0, 1, 2, 3
SBS_HORZ, SBS_VERT = 0x0000, 0x0001
SBS_TOPALIGN = SBS_LEFTALIGN = 0x0002
SBS_BOTTOMALIGN = SBS_RIGHTALIGN = 0x0004
SBS_SIZEBOXTOPLEFTALIGN, SBS_SIZEBOXBOTTOMRIGHTALIGN = 0x0002, 0x0004
SBS_SIZEBOX, SBS_SIZEGRIP = 0x0008, 0x0010
ESB_ENABLE_BOTH, ESB_DISABLE_BOTH = 0x0000, 0x0003
SIF_RANGE, SIF_PAGE, SIF_POS, SIF_DISABLENOSCROLL, SIF_TRACKPOS = 0x01, 0x02, 0x04, 0x08, 0x10
SIF_ALL = SIF_RANGE | SIF_PAGE | SIF_POS | SIF_TRACKPOS
SIF_RETURNPREV = 0x1000
DLGC_WANTARROWS = 0x0001
# win32u sysparams.c at 96 dpi: SM_CXVSCROLL and SM_CYHSCROLL.
SM_CXVSCROLL = SM_CYHSCROLL = 16

WM_CREATE, WM_ENABLE, WM_PAINT, WM_ERASEBKGND = 0x01, 0x0A, 0x0F, 0x14
WM_SETFOCUS, WM_KILLFOCUS, WM_GETDLGCODE, WM_SETCURSOR = 0x07, 0x08, 0x87, 0x20
WM_KEYDOWN, WM_KEYUP, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = (
    0x100, 0x101, 0x200, 0x201, 0x202, 0x203)
WM_NCMOUSEMOVE, WM_SYSTIMER, WM_MOUSELEAVE, WM_NCMOUSELEAVE, WM_GETOBJECT = 0xA0, 0x118, 0x2A3, 0x2A2, 0x3D
WM_USER = 0x400


class ScrollInfo:
    """win32u struct scroll_info. A control's starts zeroed (calloc); a window's bars start
    with max 100 (get_scroll_info_ptr)."""

    def __init__(self, max_val=0):
        self.cur = 0
        self.min = 0
        self.max = max_val
        self.page = 0
        self.flags = ESB_ENABLE_BOTH


# ------------------------------------------------------------------ the procedure thunks

def winproc16(wine, index):
    """alloc_win16_thunk for MAKE_WNDPROC(index): the thunk's SEGPTR as an int."""
    sel = getattr(wine, "winproc_selector", None)
    if sel is None:
        relay = wine.gate_address("USER", 1010) if wine.gate_address else None
        if relay is None:
            return 0
        # GlobalAlloc16(GMEM_FIXED | GMEM_ZEROINIT, MAX_WINPROCS16 * sizeof(WINPROC_THUNK)).
        handle, _dx, why = wine._global_alloc(0x0040, MAX_WINPROCS16 * THUNK_SIZE)
        if why:
            return 0
        sel = wine.selector_of(handle)
        wine.winproc_selector = sel
        wine.winproc_relay = relay
    relay = wine.winproc_relay
    thunk = struct.pack("<HHIHBHH", 0x5866, 0x6866, WINPROC_HANDLE | index, 0x5066, 0xEA, relay[1], relay[0])
    wine.write(sel, index * THUNK_SIZE, thunk)
    return sel << 16 | index * THUNK_SIZE


def host_index(wine, proc):
    """winproc_to_index for a thunk of a built-in procedure neww has, else None."""
    sel = getattr(wine, "winproc_selector", None)
    if sel is None or proc is None or proc >> 16 != sel:
        return None
    off = proc & 0xFFFF
    if off % THUNK_SIZE:
        return None
    index = off // THUNK_SIZE
    return index if index in PROCS else None


def call_host(wine, index, hwnd, msg, wp, lp):
    """Run a built-in window procedure on a 16-bit message: a generator, the LRESULT."""
    result = yield from PROCS[index](wine, hwnd, msg & 0xFFFF, wp & 0xFFFF, lp & 0xFFFFFFFF)
    return (result or 0) & 0xFFFFFFFF


@api("USER", "__wine_call_wndproc")
def wine_call_wndproc(wine, arg, hwnd, msg, wp, lp, proc):
    """message.c __wine_call_wndproc (USER.1010): what a procedure thunk jumps to."""
    index = proc & 0xFFFF if proc >> 16 == 0xFFFF else None
    if index not in PROCS:
        return 0, 0, f"USER.1010 __wine_call_wndproc({proc:#x}): a Wine window procedure neww does not have"
    result = yield from call_host(wine, index, hwnd, msg, wp, lp)
    return result


# ------------------------------------------------------------------ the classes

def builtin_class(wine, name):
    """The built-in class called name (a str, or an atom), registered on first use, or None."""
    from .user_wnd import WndClass, wm, user_module
    m = wm(wine)
    key = name.lower() if isinstance(name, str) else next(
        (k for k, v in wine.messages.items() if v == name), None)
    descr = BUILTIN.get(key)
    if descr is None:
        return None
    registered = getattr(wine, "builtin_classes", None)
    if registered is None:
        registered = wine.builtin_classes = {}
    cls = registered.get(key)
    if cls is None:
        index, cname, style, extra = descr
        atom = wine.add_atom(cname)
        cursor = system_cursor(wine, IDC_ARROW)
        cls = WndClass(atom, cname, user_module(wine), style, winproc16(wine, index), 0, extra,
                       user_module(wine), 0, cursor, 0, 0, 0)
        cls.builtin = True
        registered[key] = cls
        m.classes.append(cls)
    return cls


def system_cursor(wine, name):
    """LoadImageW(0, IDC_*, IMAGE_CURSOR, 0, 0, LR_SHARED): the shared system cursor."""
    from .user_res import _icon_block, _shared, ICON_SIZE
    shared, found = _shared(wine, ("system", False, name))
    if found:
        return found
    handle, why = _icon_block(wine, ICON_SIZE, ICON_SIZE, (0, 0))
    if why:
        return 0
    shared[("system", False, name)] = handle
    return handle


# ------------------------------------------------------------------ SCROLLBAR, win32u scroll.c

def _uw():
    from . import user_wnd
    return user_wnd


def scroll_info(wine, hwnd, bar, alloc):
    """get_scroll_info_ptr: a control's state, or a window's horizontal or vertical bar."""
    w = _uw().wm(wine).get(hwnd)
    if w is None or hwnd == _uw().wm(wine).desktop:
        return None
    if bar == SB_CTL:
        return getattr(w, "scroll_ctl", None)
    if bar not in (SB_HORZ, SB_VERT):
        return None
    bars = getattr(w, "scroll_bars", None)
    if bars is None and alloc:
        bars = w.scroll_bars = (ScrollInfo(100), ScrollInfo(100))
    if bars is None:
        return None
    return bars[bar]


def refresh(wine, hwnd, bar):
    """refresh_scroll_bar draws the bar at once with GetDCEx. neww draws no scroll bar yet: a
    visible bar stops, an invisible one has nothing to draw."""
    uw = _uw()
    if bar == SB_CTL and uw.is_visible(wine, hwnd):
        return f"SCROLLBAR {hwnd:#x}: Wine draws a visible scroll bar (draw_scroll_bar), and neww draws none yet"
    if bar != SB_CTL:
        w = uw.wm(wine).get(hwnd)
        style = uw.WS_HSCROLL if bar == SB_HORZ else uw.WS_VSCROLL
        if w is not None and w.style & style and uw.is_visible(wine, hwnd):
            return f"scroll bar {bar} of {hwnd:#x}: Wine draws it in the frame, and neww draws none yet"
    return None


def set_scroll_info(wine, hwnd, bar, mask, page, pos, nmin, nmax, redraw):
    """set_scroll_info. Returns (value, stop)."""
    info = scroll_info(wine, hwnd, bar, True)
    if info is None:
        return 0, None
    action_refresh = False
    show = hide = repaint_arrows = False
    ret = info.cur if mask & SIF_RETURNPREV else 0
    if mask & SIF_PAGE and info.page != page:
        info.page = page
        action_refresh = True
    if mask & SIF_POS and info.cur != pos:
        info.cur = pos
        action_refresh = True
    if mask & SIF_RANGE:
        if nmin > nmax or ((nmax - nmin) & 0xFFFFFFFF) >= 0x80000000:
            action_refresh = True
            info.min = info.max = 0
        elif info.min != nmin or info.max != nmax:
            action_refresh = True
            info.min, info.max = nmin, nmax
    if info.page < 0:
        info.page = 0
    elif info.page > info.max - info.min + 1:
        info.page = info.max - info.min + 1
    if info.cur < info.min:
        info.cur = info.min
    elif info.cur > info.max - max(info.page - 1, 0):
        info.cur = info.max - max(info.page - 1, 0)
    if mask & SIF_ALL and mask & (SIF_RANGE | SIF_PAGE | SIF_DISABLENOSCROLL):
        new_flags = info.flags
        if info.min >= info.max - max(info.page - 1, 0):
            if mask & SIF_DISABLENOSCROLL:
                new_flags = ESB_DISABLE_BOTH
                action_refresh = True
            elif bar != SB_CTL and action_refresh:
                hide = True
        elif mask != SIF_PAGE:
            new_flags = ESB_ENABLE_BOTH
            if bar != SB_CTL and action_refresh:
                show = True
        if bar == SB_CTL and redraw and _uw().is_visible(wine, hwnd) and new_flags in (ESB_ENABLE_BOTH, ESB_DISABLE_BOTH):
            return 0, (f"SetScrollInfo({hwnd:#x}) with redraw on a visible scroll bar: Wine enables or disables "
                       "the window and draws it, and neww draws none yet")
        if info.flags != new_flags:
            info.flags = new_flags
            repaint_arrows = True
    if not mask & SIF_RETURNPREV:
        ret = info.cur
    if hide or show:
        return ret, (f"SetScrollInfo({hwnd:#x}, bar {bar}) {'hides' if hide else 'shows'} the window's scroll bar: "
                     "Wine changes its frame with SWP_FRAMECHANGED, which neww does not do yet")
    if redraw or repaint_arrows:
        why = refresh(wine, hwnd, bar)
        if why:
            return ret, why
    return ret, None


def get_scroll_info(wine, hwnd, bar):
    """The (min, max, page, pos) a SCROLLINFO gets, or None."""
    info = scroll_info(wine, hwnd, bar, False)
    if info is None:
        return None
    return info.min, info.max, info.page, info.cur


def create_scroll_bar(wine, hwnd, cs_ptr):
    """create_scroll_bar from the CREATESTRUCT16 at cs_ptr."""
    uw = _uw()
    w = uw.wm(wine).get(hwnd)
    info = w.scroll_ctl = ScrollInfo(0)
    (_params, _inst, _menu, _parent, cy, cx, y, x, style, _name, _cls, _ex) = struct.unpack(
        "<IHHHhhhhIIII", gdi16.read(wine, cs_ptr, 34))
    if style & uw.WS_DISABLED:
        info.flags = ESB_DISABLE_BOTH
    move = None
    if style & (SBS_SIZEGRIP | SBS_SIZEBOX):
        if style & SBS_SIZEBOXTOPLEFTALIGN:
            move = (x, y, SM_CXVSCROLL + 1, SM_CYHSCROLL + 1)
        elif style & SBS_SIZEBOXBOTTOMRIGHTALIGN:
            move = (x + cx - SM_CXVSCROLL - 1, y + cy - SM_CYHSCROLL - 1, SM_CXVSCROLL + 1, SM_CYHSCROLL + 1)
    elif style & SBS_VERT:
        if style & SBS_LEFTALIGN:
            move = (x, y, SM_CXVSCROLL + 1, cy)
        elif style & SBS_RIGHTALIGN:
            move = (x + cx - SM_CXVSCROLL - 1, y, SM_CXVSCROLL + 1, cy)
    else:
        if style & SBS_TOPALIGN:
            move = (x, y, cx, SM_CYHSCROLL + 1)
        elif style & SBS_BOTTOMALIGN:
            move = (x, y + cy - SM_CYHSCROLL - 1, cx, SM_CYHSCROLL + 1)
    if move:
        # NtUserMoveWindow(..., FALSE)
        yield from uw.set_window_pos(wine, hwnd, 0, *move, uw.SWP_NOZORDER | uw.SWP_NOACTIVATE | uw.SWP_NOREDRAW)
    return 0


def scroll_bar_window_proc(wine, hwnd, msg, wp, lp):
    """scroll_bar_window_proc on the 16-bit message, as WINPROC_CallProc16To32A passes it."""
    uw = _uw()
    if uw.wm(wine).get(hwnd) is None:
        return 0
    if msg == WM_CREATE:
        result = yield from create_scroll_bar(wine, hwnd, lp)
        return result
    if msg == WM_ENABLE:
        info = scroll_info(wine, hwnd, SB_CTL, False)
        if info is not None:
            info.flags = ESB_ENABLE_BOTH if wp else ESB_DISABLE_BOTH
            why = refresh(wine, hwnd, SB_CTL)
            if why:
                yield why
        return 0
    if msg == WM_ERASEBKGND:
        return 1
    if msg == WM_GETDLGCODE:
        return DLGC_WANTARROWS
    if msg == WM_SETCURSOR:
        if uw.wm(wine).get(hwnd).style & SBS_SIZEGRIP:
            yield f"SCROLLBAR {hwnd:#x} WM_SETCURSOR with SBS_SIZEGRIP: Wine loads a sizing cursor"
            return 0
        result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    if msg == WM_PAINT:
        yield f"SCROLLBAR {hwnd:#x} WM_PAINT: Wine draws the bar (draw_scroll_bar), and neww draws none yet"
        return 0
    if msg in (WM_KEYDOWN, WM_KEYUP, WM_LBUTTONDBLCLK, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_NCMOUSEMOVE,
               WM_NCMOUSELEAVE, WM_MOUSEMOVE, WM_MOUSELEAVE, WM_SYSTIMER, WM_SETFOCUS, WM_KILLFOCUS):
        yield (f"SCROLLBAR {hwnd:#x} {uw.MESSAGE_NAMES.get(msg, hex(msg))}: Wine tracks the bar or its caret, "
               "and neww has no scroll bar tracking yet")
        return 0
    if msg == WM_GETOBJECT:
        result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    if msg >= WM_USER:
        # A 16-bit program's SBM_* messages are WM_USER + n: WINPROC_CallProc16To32A maps them.
        yield f"SCROLLBAR {hwnd:#x} message {msg:#x}: a 16-bit scroll bar message neww does not map yet"
        return 0
    result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
    return result


PROCS = {NTUSER_WNDPROC_SCROLLBAR: scroll_bar_window_proc}

# win32u class.c builtin_classes: (index, name, style, window extra bytes). The extra bytes are
# sizeof(struct scroll_info *), 4 in a 32-bit process.
BUILTIN = {
    "scrollbar": (NTUSER_WNDPROC_SCROLLBAR, "ScrollBar", CS_DBLCLKS | CS_VREDRAW | CS_HREDRAW | CS_PARENTDC, 4),
}


# ------------------------------------------------------------------ USER scroll calls, wnd.c

def _scroll_window(wine, hwnd):
    return _uw().wm(wine).get(hwnd)


def _ctl_proc_ok(wine, hwnd, call):
    """A SB_CTL call goes to the window as a message. neww runs it only when the window still
    has the built-in procedure."""
    w = _scroll_window(wine, hwnd)
    if host_index(wine, w.proc) != NTUSER_WNDPROC_SCROLLBAR:
        return f"{call} on {hwnd:#x}, SB_CTL: Wine sends SBM_* to its procedure, which is not the SCROLLBAR one"
    return None


@api("USER", "SetScrollPos")
def set_scroll_pos16(wine, arg, hwnd, bar, pos, redraw):
    """SetScrollPos16 -> SetScrollPos: SIF_POS | SIF_RETURNPREV. SB_CTL goes to the window as
    SBM_SETSCROLLINFO, whose procedure is set_scroll_info."""
    if _scroll_window(wine, hwnd) is None:
        return 0
    if bar == SB_CTL:
        why = _ctl_proc_ok(wine, hwnd, "USER.62 SetScrollPos")
        if why:
            return 0, 0, why
    value, why = set_scroll_info(wine, hwnd, bar, SIF_POS | SIF_RETURNPREV, 0, pos, 0, 0, redraw)
    if why:
        return 0, 0, f"USER.62 {why}"
    return value & 0xFFFF


@api("USER", "GetScrollPos")
def get_scroll_pos16(wine, arg, hwnd, bar):
    """GetScrollPos16 -> GetScrollPos: SBM_GETPOS for SB_CTL, else GetScrollInfo's nPos or 0."""
    if _scroll_window(wine, hwnd) is None:
        return 0
    if bar == SB_CTL:
        why = _ctl_proc_ok(wine, hwnd, "USER.63 GetScrollPos")
        if why:
            return 0, 0, why
    got = get_scroll_info(wine, hwnd, bar)
    return (got[3] if got else 0) & 0xFFFF


@api("USER", "SetScrollRange")
def set_scroll_range16(wine, arg, hwnd, bar, nmin, nmax, redraw):
    """SetScrollRange16 (void): a range wider than 0x7FFF becomes (0, 0), then SetScrollRange,
    which is SetScrollInfo with SIF_RANGE for every bar; SB_CTL goes to the window as
    SBM_SETSCROLLINFO, whose procedure is set_scroll_info."""
    ax = arg.regs("ax")
    if _scroll_window(wine, hwnd) is None:
        return ax, 0
    if bar == SB_CTL:
        why = _ctl_proc_ok(wine, hwnd, "USER.64 SetScrollRange")
        if why:
            return 0, 0, why
    if nmax - nmin > 0x7FFF:
        nmin = nmax = 0
    _value, why = set_scroll_info(wine, hwnd, bar, SIF_RANGE, 0, 0, nmin, nmax, redraw)
    if why:
        return 0, 0, f"USER.64 {why}"
    return ax, 0


@api("USER", "GetScrollRange")
def get_scroll_range16(wine, arg, hwnd, bar, min_ptr, max_ptr):
    """GetScrollRange16 -> GetScrollRange: the range, (0, 0) when the bar has no state."""
    if _scroll_window(wine, hwnd) is None:
        return 0
    if bar == SB_CTL:
        why = _ctl_proc_ok(wine, hwnd, "USER.65 GetScrollRange")
        if why:
            return 0, 0, why
    got = get_scroll_info(wine, hwnd, bar)
    lo, hi = (got[0], got[1]) if got else (0, 0)
    if min_ptr:
        gdi16.write(wine, min_ptr, struct.pack("<h", max(-0x8000, min(lo, 0x7FFF))))
    if max_ptr:
        gdi16.write(wine, max_ptr, struct.pack("<h", max(-0x8000, min(hi, 0x7FFF))))
    return 1
