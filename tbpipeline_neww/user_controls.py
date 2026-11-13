"""Wine's built-in window classes, whose window procedures are Wine's own code, not the guest's.

win32u class.c registers the built-in classes, each with the window procedure handle
MAKE_WNDPROC(index): 0xFFFF0000 | index, index being its ntuser_client_procs value. A 16-bit
program sees that procedure through user.exe16 message.c alloc_win16_thunk: a 15-byte packed
WINPROC_THUNK, popl %eax ; pushl $proc ; pushl %eax ; ljmp __wine_call_wndproc (USER.1010),
at offset index * 15 of a GMEM_FIXED block from GlobalAlloc16. Calling the thunk, or passing it to CallWindowProc, or sending to a
window that has it, runs the procedure here.

The classes are registered the first time one is looked up: neww gives them their atoms then,
where Wine registers every built-in class when user32 starts.

SCROLLBAR (win32u scroll.c), BUTTON (user32 button.c), STATIC (user32 static.c) and the dialog
class #32770 (user32 defdlg.c, in user_dialog) are here.
Each other built-in class still stops by name.
"""

import struct

from .guest import Call  # noqa: F401  (procedures may yield guest calls)
from .handlers import api
from . import gdi16

# include/ntuser.h enum ntuser_client_procs
NTUSER_WNDPROC_SCROLLBAR = 0
NTUSER_WNDPROC_BUTTON = 7
NTUSER_WNDPROC_DIALOG = 10
NTUSER_WNDPROC_STATIC = 14

WINPROC_HANDLE = 0xFFFF0000
THUNK_SIZE = 15            # sizeof(WINPROC_THUNK), packed: 2 + 2 + 4 + 2 + 1 + 4
MAX_WINPROCS16 = 1024

CS_VREDRAW, CS_HREDRAW, CS_DBLCLKS, CS_PARENTDC, CS_SAVEBITS = 0x0001, 0x0002, 0x0008, 0x0080, 0x0800
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
    if name == DIALOG_CLASS_ATOM or name == f"#{DIALOG_CLASS_ATOM}":
        key = "#32770"
    else:
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
        atom = DIALOG_CLASS_ATOM if key == "#32770" else wine.add_atom(cname)
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


def refresh(wine, hwnd, bar, arrows=True, interior=True):
    """refresh_scroll_bar (win32u/scroll.c:379): draw_scroll_bar at once on a cache DC from
    GetDCEx. A generator; returns a stop string or None. Scroll bars in a window's frame are
    not drawn yet: a visible one stops."""
    uw = _uw()
    if bar == SB_CTL:
        if not uw.is_visible(wine, hwnd):
            return None
        hdc = uw.get_dc(wine, hwnd)
        yield from draw_scroll_bar(wine, hwnd, hdc, arrows, interior)
        uw.release_dc(wine, hwnd, hdc)
        return None
    if bar != SB_CTL:
        w = uw.wm(wine).get(hwnd)
        style = uw.WS_HSCROLL if bar == SB_HORZ else uw.WS_VSCROLL
        if w is not None and w.style & style and uw.is_visible(wine, hwnd):
            return f"scroll bar {bar} of {hwnd:#x}: Wine draws it in the frame, and neww draws none yet"
    return None


def set_scroll_info(wine, hwnd, bar, mask, page, pos, nmin, nmax, redraw):
    """set_scroll_info (win32u/scroll.c), a generator. Returns (value, stop)."""
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
            # NtUserEnableWindow: WM_ENABLE sets the flags and redraws (scroll.c:1290).
            yield from _uw().enable_window(wine, None, hwnd, int(new_flags == ESB_ENABLE_BOTH))
            info = scroll_info(wine, hwnd, bar, False)
            if info is None:
                return 0, None
        if info.flags != new_flags:
            info.flags = new_flags
            repaint_arrows = True
    if not mask & SIF_RETURNPREV:
        ret = info.cur
    if hide or show:
        return ret, (f"SetScrollInfo({hwnd:#x}, bar {bar}) {'hides' if hide else 'shows'} the window's scroll bar: "
                     "Wine changes its frame with SWP_FRAMECHANGED, which neww does not do yet")
    if redraw or repaint_arrows:
        why = yield from refresh(wine, hwnd, bar, True, bool(redraw))
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


# win32u/scroll.c:43-49 and user32/scroll.c:30
SCROLL_MIN_RECT, SCROLL_MIN_THUMB, SCROLL_ARROW_THUMB_OVERLAP = 4, 17, 0
ESB_DISABLE_LTUP, ESB_DISABLE_RTDN = 0x1, 0x2
WM_CTLCOLOR, CTLCOLOR_SCROLLBAR = 0x19, 5
# winuser.h DrawFrameControl
DFCS_SCROLLUP, DFCS_SCROLLDOWN, DFCS_SCROLLLEFT, DFCS_SCROLLRIGHT = 0x0, 0x1, 0x2, 0x3
DFCS_INACTIVE, DFCS_PUSHED = 0x100, 0x200
# SYS_COLORS indexes
COLOR_WINDOWFRAME, COLOR_BTNFACE, COLOR_BTNSHADOW, COLOR_BTNTEXT = 6, 15, 16, 18
COLOR_BTNHIGHLIGHT, COLOR_3DDKSHADOW, COLOR_3DLIGHT = 20, 21, 22


def scroll_bar_rect(wine, hwnd):
    """get_scroll_bar_rect (win32u/scroll.c:187) for SB_CTL: the client rectangle, then the
    arrow size, the thumb's size and its position from the bar's start (:233-276). Returns
    (rect, arrow, thumb_size, thumb_pos, vertical)."""
    uw = _uw()
    w = uw.wm(wine).get(hwnd)
    rect = (0, 0, w.client[2] - w.client[0], w.client[3] - w.client[1])
    vertical = bool(w.style & SBS_VERT)
    pixels = rect[3] - rect[1] if vertical else rect[2] - rect[0]
    if pixels <= 2 * SM_CXVSCROLL + SCROLL_MIN_RECT:
        arrow = (pixels - SCROLL_MIN_RECT) // 2 if pixels > SCROLL_MIN_RECT else 0
        return rect, arrow, 0, 0, vertical
    info = scroll_info(wine, hwnd, SB_CTL, True)
    arrow = SM_CXVSCROLL
    pixels -= 2 * (SM_CXVSCROLL - SCROLL_ARROW_THUMB_OVERLAP)
    if info.page:
        thumb = max(gdi16._muldiv(pixels, info.page, info.max - info.min + 1), SCROLL_MIN_THUMB)
    else:
        thumb = SM_CXVSCROLL
    pixels -= thumb
    if pixels < 0 or (info.flags & ESB_DISABLE_BOTH) == ESB_DISABLE_BOTH:
        return rect, arrow, 0, 0, vertical
    top = info.max - max(info.page - 1, 0)
    if info.min >= top:
        pos = arrow - SCROLL_ARROW_THUMB_OVERLAP
    else:
        pos = arrow - SCROLL_ARROW_THUMB_OVERLAP + gdi16._muldiv(pixels, info.cur - info.min, top - info.min)
    return rect, arrow, thumb, pos, vertical


def _with(dc, pen=None, brush=None):
    saved = (dc.pen, dc.brush)
    if pen is not None:
        dc.pen = pen
    if brush is not None:
        dc.brush = brush
    return saved


def _polygon(wine, dc, points, index):
    """Polygon with the system color's brush and pen (SYSCOLOR_GetPen, PS_SOLID width 1)."""
    uw = _uw()
    saved = _with(dc, uw.sys_color_pen(wine, index), uw.sys_color_brush(wine, index))

    def paint(draw, to, what, width):
        xy = [to(*p) for p in points]
        if what == "fill":
            draw.polygon(xy, fill=1)
        else:
            draw.line(xy + xy[:1], fill=1, width=width)
    gdi16.paint_shape(wine, dc, paint)
    dc.pen, dc.brush = saved


def draw_frame_scroll(wine, dc, rect, flags):
    """UITOOLS95_DrawFrameScroll (user32/uitools.c:972) for the four arrows: the triangle in
    the square in rect (UITOOLS_MakeSquareRect, :612), the button as EDGE_RAISED with
    BF_MIDDLE (no BF_SOFT) or, pushed, UITOOLS95_DFC_ButtonPush, then the arrow: inactive, a
    COLOR_BTNHIGHLIGHT one first and the COLOR_BTNSHADOW one a pixel up and left; else in
    COLOR_BTNTEXT, a pixel up and left unless pushed."""
    from .user_buttons import draw_rect_edge, draw_button_push
    l, t, r, b = rect
    width, height = r - l, b - t
    diam = min(width, height)
    ml, mt, mr, mb = l, t, r, b
    if width < height:
        mt = t + (height - width) // 2
        mb = mt + diam
    elif width > height:
        ml = l + (width - height) // 2
        mr = ml + diam
    small = diam - 2
    tri = max(2, int(290 * small / 1000) - 1) if small >= 0 else max(2, -(-290 * small // 1000) - 1)
    c = lambda n: int(n * small / 1000)      # C integer division truncates toward zero
    kind = flags & 0xFF
    if kind == DFCS_SCROLLDOWN:
        x2, y2 = ml + c(470) + 2, mt + c(687) + 1
        line = [(x2 - tri, y2 - tri), (x2 + tri, y2 - tri), (x2, y2)]
    elif kind == DFCS_SCROLLUP:
        x2, y2 = ml + c(470) + 2, mb - (c(687) + 1)
        line = [(x2 - tri, y2 + tri), (x2 + tri, y2 + tri), (x2, y2)]
    elif kind == DFCS_SCROLLLEFT:
        x2, y2 = mr - (c(687) + 1), mt + c(470) + 2
        line = [(x2 + tri, y2 - tri), (x2 + tri, y2 + tri), (x2, y2)]
    else:
        x2, y2 = ml + c(687) + 1, mt + c(470) + 2
        line = [(x2 - tri, y2 - tri), (x2 - tri, y2 + tri), (x2, y2)]
    if not flags & 0xFF00:
        draw_rect_edge(wine, dc, rect, COLOR_3DLIGHT, COLOR_BTNHIGHLIGHT, COLOR_3DDKSHADOW, COLOR_BTNSHADOW, True)
    else:
        draw_button_push(wine, dc, rect, pushed=bool(flags & DFCS_PUSHED))
    if flags & DFCS_INACTIVE:
        _polygon(wine, dc, line, COLOR_BTNHIGHLIGHT)
    if flags & DFCS_INACTIVE or not flags & DFCS_PUSHED:
        line = [(x - 1, y - 1) for x, y in line]
    _polygon(wine, dc, line, COLOR_BTNSHADOW if flags & DFCS_INACTIVE else COLOR_BTNTEXT)


def draw_scroll_bar(wine, hwnd, hdc, arrows=True, interior=True):
    """draw_scroll_bar (win32u/scroll.c:286) for SB_CTL with arrows and interior, no tracking:
    USER_ScrollBarDraw (user32/scroll.c:169), SCROLL_DrawArrows (:38) and SCROLL_DrawInterior
    (:72). The interior's brush is the parent's answer to WM_CTLCOLORSCROLLBAR, the 16-bit
    WM_CTLCOLOR with CTLCOLOR_SCROLLBAR; the thumb is a COLOR_BTNFACE Rectangle in the
    COLOR_WINDOWFRAME pen under DrawEdge(EDGE_RAISED, BF_RECT)."""
    from .user_buttons import draw_rect_edge
    uw = _uw()
    w = uw.wm(wine).get(hwnd)
    dc = gdi16.gdi(wine).get(hdc, gdi16.OBJ_DC)
    if w is None or dc is None or not uw.is_visible(wine, hwnd):
        return
    info = scroll_info(wine, hwnd, SB_CTL, True)
    if w.style & (SBS_SIZEGRIP | SBS_SIZEBOX):
        yield f"SCROLLBAR {hwnd:#x} WM_PAINT with SBS_SIZEGRIP or SBS_SIZEBOX: neww draws only the bar"
        return
    rect, arrow, thumb, pos, vertical = scroll_bar_rect(wine, hwnd)
    l, t, r, b = rect
    if r <= l or b <= t:
        return
    if arrows and arrow:
        first = (l, t, r, t + arrow) if vertical else (l, t, l + arrow, b)
        last = (l, b - arrow, r, b) if vertical else (r - arrow, t, r, b)
        draw_frame_scroll(wine, dc, first, (DFCS_SCROLLUP if vertical else DFCS_SCROLLLEFT)
                          | (DFCS_INACTIVE if info.flags & ESB_DISABLE_LTUP else 0))
        draw_frame_scroll(wine, dc, last, (DFCS_SCROLLDOWN if vertical else DFCS_SCROLLRIGHT)
                          | (DFCS_INACTIVE if info.flags & ESB_DISABLE_RTDN else 0))
    if not interior:
        return
    # SendMessageW(GetParent(hwnd), WM_CTLCOLORSCROLLBAR): a popup with no owner has no
    # parent, the send fails with 0 and SelectObject(0) leaves the DC's brush.
    parent = uw.get_parent(wine, None, hwnd)
    brush = 0
    if parent:
        brush = yield from uw.send(wine, parent, WM_CTLCOLOR, hdc, (CTLCOLOR_SCROLLBAR << 16) | hwnd)
        brush = (brush[0] if isinstance(brush, tuple) else brush) & 0xFFFF
    saved = _with(dc, uw.sys_color_pen(wine, COLOR_WINDOWFRAME),
                  brush if gdi16.gdi(wine).get(brush, gdi16.OBJ_BRUSH) is not None else None)
    span = arrow - SCROLL_ARROW_THUMB_OVERLAP
    il, it, ir, ib = (l, t + span, r, b - span) if vertical else (l + span, t, r - span, b)

    def patcopy(x0, y0, x1, y1):
        gdi16.current_brush_blit(wine, dc, gdi16.device_rect(dc, x0, y0, x1, y1), 0xF00021)
    if not pos:
        patcopy(il, it, ir, ib)
    else:
        if vertical:
            patcopy(il, it, ir, it + pos - span)
            it += pos - span
            patcopy(il, it + thumb, ir, ib)
            ib = it + thumb
        else:
            patcopy(il, it, il + pos - span, ib)
            il += pos - span
            patcopy(il + thumb, it, ir, ib)
            ir = il + thumb
        dc.brush = uw.sys_color_brush(wine, COLOR_BTNFACE)
        gdi16._device_rectangle(wine, dc, gdi16.gdi(wine).get(dc.pen, gdi16.OBJ_PEN), gdi16.device_rect(dc, il + 1, it + 1, ir - 1, ib - 1))
        draw_rect_edge(wine, dc, (il, it, ir, ib), COLOR_3DLIGHT, COLOR_BTNHIGHLIGHT, COLOR_3DDKSHADOW, COLOR_BTNSHADOW, False)
    dc.pen, dc.brush = saved
    if hwnd == uw.wm(wine).focus:
        yield f"SCROLLBAR {hwnd:#x} WM_PAINT with the focus: Wine moves the caret to the thumb, which neww does not do yet"


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
            why = yield from refresh(wine, hwnd, SB_CTL)
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
        # scroll.c:1355: the DC in wParam, else BeginPaint's.
        if wp:
            yield from draw_scroll_bar(wine, hwnd, wp)
            return 0
        mark = uw.scratch_mark(wine)
        ps = uw.scratch(wine, bytes(32))
        hdc = yield from uw.begin_paint(wine, hwnd, ps)
        if hdc:
            yield from draw_scroll_bar(wine, hwnd, hdc)
            uw.end_paint(wine, hwnd, ps)
        uw.scratch_release(wine, mark)
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


from .user_buttons import button_window_proc, static_window_proc  # noqa: E402
from .user_dialog import dialog_window_proc, DLGWINDOWEXTRA, DIALOG_CLASS_ATOM  # noqa: E402

PROCS = {
    NTUSER_WNDPROC_SCROLLBAR: scroll_bar_window_proc,
    NTUSER_WNDPROC_BUTTON: button_window_proc,
    NTUSER_WNDPROC_STATIC: static_window_proc,
    NTUSER_WNDPROC_DIALOG: dialog_window_proc,
}

# win32u class.c builtin_classes: (index, name, style, window extra bytes), in a 32-bit process.
# ScrollBar: sizeof(struct scroll_info *). Button (class.c:99): sizeof(UINT) + 2 * sizeof(HANDLE).
# Static (class.c:148): 2 * sizeof(HANDLE). The dialog class #32770 (class.c:120): DLGWINDOWEXTRA,
# its name the integer atom 32770 (DIALOG_CLASS_ATOM).
BUILTIN = {
    "scrollbar": (NTUSER_WNDPROC_SCROLLBAR, "ScrollBar", CS_DBLCLKS | CS_VREDRAW | CS_HREDRAW | CS_PARENTDC, 4),
    "button": (NTUSER_WNDPROC_BUTTON, "Button", CS_DBLCLKS | CS_VREDRAW | CS_HREDRAW | CS_PARENTDC, 12),
    "static": (NTUSER_WNDPROC_STATIC, "Static", CS_DBLCLKS | CS_PARENTDC, 8),
    "#32770": (NTUSER_WNDPROC_DIALOG, "#32770", CS_SAVEBITS | CS_DBLCLKS, DLGWINDOWEXTRA),
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
    value, why = yield from set_scroll_info(wine, hwnd, bar, SIF_POS | SIF_RETURNPREV, 0, pos, 0, 0, redraw)
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
    _value, why = yield from set_scroll_info(wine, hwnd, bar, SIF_RANGE, 0, 0, nmin, nmax, redraw)
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
