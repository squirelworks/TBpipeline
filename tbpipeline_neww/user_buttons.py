"""The BUTTON and STATIC built-in window procedures, from Wine at WINE_COMMIT (2528aff2).

A 16-bit program's button and static controls run user.exe16 message.c button_proc16
(message.c:1943) and static_proc16 (message.c:2536), which pass the message on to user32's
ButtonWndProc_common (button.c:171) and StaticWndProc_common (static.c:339). Both are here as
neww host procedures, on the 16-bit message, so a notification to the parent is the 16-bit
WM_COMMAND: wParam the id, lParam MAKELONG(hwnd, code) (message.c:1183-1186).

Painted so far: push buttons and default push buttons (PB_Paint, button.c:725), and the text
statics SS_LEFT, SS_CENTER, SS_RIGHT, SS_SIMPLE and SS_LEFTNOWORDWRAP (STATIC_PaintTextfn,
static.c:603). Every other button or static type stops by name when it would paint.

DrawText is drawn here, not through a USER.85 handler: one line, or lines broken at spaces
with DT_WORDBREAK, aligned left, centred or right, a lone '&' underlining the next letter
unless DT_NOPREFIX.
"""

from . import gdi16

# winuser.h
BS_PUSHBUTTON, BS_DEFPUSHBUTTON, BS_TYPEMASK = 0x0, 0x1, 0xF
BS_LEFT, BS_RIGHT, BS_CENTER, BS_MULTILINE, BS_NOTIFY, BS_FLAT = 0x100, 0x200, 0x300, 0x2000, 0x4000, 0x8000
BS_ICON, BS_BITMAP = 0x40, 0x80
BST_CHECKED, BST_INDETERMINATE, BST_PUSHED, BST_FOCUS = 0x1, 0x2, 0x4, 0x8
BUTTON_NSTATES, BUTTON_BTNPRESSED = 0x0F, 0x40           # button.c:55-56
BN_CLICKED = 0
DLGC_DEFPUSHBUTTON, DLGC_UNDEFPUSHBUTTON, DLGC_RADIOBUTTON = 0x10, 0x20, 0x40
DLGC_STATIC, DLGC_BUTTON = 0x100, 0x2000
SS_LEFT, SS_CENTER, SS_RIGHT, SS_SIMPLE, SS_LEFTNOWORDWRAP = 0x0, 0x1, 0x2, 0xB, 0xC
SS_TYPEMASK, SS_NOPREFIX, SS_NOTIFY = 0x1F, 0x80, 0x100
SS_ICON, SS_BITMAP = 0x3, 0xE
DT_CENTER, DT_RIGHT, DT_VCENTER, DT_WORDBREAK, DT_SINGLELINE, DT_EXPANDTABS = 0x1, 0x2, 0x4, 0x10, 0x20, 0x40
DT_NOPREFIX = 0x800
HTCLIENT, HTTRANSPARENT = 1, 0xFFFFFFFF
CTLCOLOR_BTN, CTLCOLOR_STATIC = 3, 6
MK_LBUTTON = 0x1
WS_DISABLED, WS_VISIBLE = 0x08000000, 0x10000000

WM_CREATE, WM_ENABLE, WM_SETFOCUS, WM_KILLFOCUS, WM_PAINT, WM_ERASEBKGND = 0x01, 0x0A, 0x07, 0x08, 0x0F, 0x14
WM_SETTEXT, WM_CTLCOLOR, WM_SETFONT, WM_GETFONT, WM_COMMAND = 0x0C, 0x19, 0x30, 0x31, 0x111
WM_NCHITTEST, WM_GETDLGCODE, WM_PRINTCLIENT = 0x84, 0x87, 0x318
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_CAPTURECHANGED = 0x215
WM_USER = 0x400
# winuser16.h: the 16-bit button messages, mapped by button_proc16 (message.c:1947-1954).
BM_GETCHECK16, BM_SETCHECK16, BM_GETSTATE16, BM_SETSTATE16, BM_SETSTYLE16 = (
    WM_USER, WM_USER + 1, WM_USER + 2, WM_USER + 3, WM_USER + 4)

# SYS_COLORS indexes
COLOR_WINDOWFRAME, COLOR_BTNFACE, COLOR_BTNSHADOW, COLOR_GRAYTEXT, COLOR_BTNTEXT = 6, 15, 16, 17, 18
COLOR_BTNHIGHLIGHT, COLOR_3DDKSHADOW, COLOR_3DLIGHT = 20, 21, 22


def _uw():
    from . import user_wnd
    return user_wnd


def _ctl(wine, hwnd):
    """The control's private data (NtUserGetPrivateData): state and font."""
    w = _uw().wm(wine).get(hwnd)
    if w is None:
        return None
    if not hasattr(w, "ctl_state"):
        w.ctl_state = 0
        w.ctl_font = 0
    return w


def _client(w):
    return (0, 0, w.client[2] - w.client[0], w.client[3] - w.client[1])


def _notify(wine, w, code):
    """BUTTON_NOTIFY_PARENT (button.c:60): WM_COMMAND to the parent, as 16-bit."""
    result = yield from _uw().send(wine, w.parent, WM_COMMAND, w.id & 0xFFFF, (code << 16) | w.hwnd)
    return result


# ------------------------------------------------------------------ drawing

def _sys(wine, dc, rect, index):
    gdi16.fill(wine, dc, rect, _uw().sys_color_brush(wine, index))


def draw_rect_edge(wine, dc, rect, lt_out, lt_in, rb_out, rb_in, middle):
    """UITOOLS95_DrawRectEdge (uitools.c:465) with BF_RECT, width 1: the outer edge top, left,
    bottom, right (uitools.c:517-540), the inner edge one pixel inside it, its ends one pixel in at each
    corner (uitools.c:543-566), and with BF_MIDDLE the rest in COLOR_BTNFACE (uitools.c:569-582)."""
    l, t, r, b = rect
    _sys(wine, dc, (l, t, r, t + 1), lt_out)
    _sys(wine, dc, (l, t, l + 1, b), lt_out)
    _sys(wine, dc, (l, b - 1, r, b), rb_out)
    _sys(wine, dc, (r - 1, t, r, b), rb_out)
    _sys(wine, dc, (l + 1, t + 1, r - 1, t + 2), lt_in)
    _sys(wine, dc, (l + 1, t + 1, l + 2, b - 1), lt_in)
    _sys(wine, dc, (l + 1, b - 2, r - 1, b - 1), rb_in)
    _sys(wine, dc, (r - 2, t + 1, r - 1, b - 1), rb_in)
    if middle:
        _sys(wine, dc, (l + 2, t + 2, r - 2, b - 2), COLOR_BTNFACE)


def draw_button_push(wine, dc, rect, pushed=False, flat=False):
    """UITOOLS95_DFC_ButtonPush (uitools.c:664): EDGE_SUNKEN when pushed or flat, else
    EDGE_RAISED, with BF_SOFT | BF_MIDDLE | BF_RECT. The colors are uitools.c's LTOuterSoft,
    LTInnerSoft, RBOuterSoft and RBInnerSoft at EDGE_RAISED (5) and EDGE_SUNKEN (10), and with
    DFCS_FLAT LTRBOuterFlat and LTRBInnerFlat (uitools.c:98-110, 486-490)."""
    if flat:
        draw_rect_edge(wine, dc, rect, COLOR_BTNSHADOW, COLOR_BTNFACE, COLOR_BTNSHADOW, COLOR_BTNFACE, True)
    elif pushed:
        draw_rect_edge(wine, dc, rect, COLOR_3DDKSHADOW, COLOR_BTNSHADOW, COLOR_BTNHIGHLIGHT, COLOR_3DLIGHT, True)
    else:
        draw_rect_edge(wine, dc, rect, COLOR_BTNHIGHLIGHT, COLOR_3DLIGHT, COLOR_3DDKSHADOW, COLOR_BTNSHADOW, True)


def draw_focus_rect(wine, dc, rect):
    """DrawFocusRect: a dotted rectangle drawn by inverting every other pixel."""
    img, (ox, oy) = gdi16.surface(wine, dc)
    box = gdi16.clip_box(wine, dc)
    l, t, r, b = gdi16.device_rect(dc, *rect)
    l, t, r, b = l + ox, t + oy, r + ox, b + oy
    if r - l < 1 or b - t < 1:
        return
    edge = [(x, t) for x in range(l, r)] + [(x, b - 1) for x in range(l, r)]
    edge += [(l, y) for y in range(t + 1, b - 1)] + [(r - 1, y) for y in range(t + 1, b - 1)]
    px = img.load()
    for x, y in sorted(set(edge)):
        if (x + y) % 2 == 0 and box[0] <= x < box[2] and box[1] <= y < box[3]:
            c = px[x, y]
            px[x, y] = (255 - c[0], 255 - c[1], 255 - c[2])


def _prefix(text, noprefix):
    """The text DrawText shows, and the index of the letter a lone '&' underlines, or None."""
    if noprefix:
        return text, None
    out, mark, i = [], None, 0
    while i < len(text):
        ch = text[i]
        if ch == "&" and i + 1 < len(text):
            if text[i + 1] != "&":
                mark = len(out)
            out.append(text[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out), mark


def text_lines(wine, dc, text, width, fmt):
    """DrawText's lines: one with DT_SINGLELINE; else one per line break, and with DT_WORDBREAK
    broken at the last space that keeps the line within width."""
    if fmt & DT_EXPANDTABS:
        text = text.replace("\t", " " * 8)
    if fmt & DT_SINGLELINE:
        return [text.replace("\r", "").replace("\n", "")]
    lines = []
    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not fmt & DT_WORDBREAK:
            lines.append(para)
            continue
        line = ""
        for word in para.split(" "):
            trial = word if not line else line + " " + word
            if line and gdi16.text_width(wine, dc, _prefix(trial, fmt & DT_NOPREFIX)[0]) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def draw_text(wine, dc, rect, text, fmt):
    """DrawText of text into rect (logical) with fmt; returns the height drawn."""
    (_pil, height, ascent, _descent, _size), _log = gdi16.realize(wine, dc)
    l, t, r, b = rect
    lines = text_lines(wine, dc, text, r - l, fmt)
    y = t
    if fmt & DT_SINGLELINE and fmt & DT_VCENTER:
        y = t + (b - t - height) // 2
    keep = dc.text_align
    dc.text_align = 0
    for line in lines:
        shown, mark = _prefix(line, fmt & DT_NOPREFIX)
        w = gdi16.text_width(wine, dc, shown)
        x = l
        if fmt & DT_CENTER:
            x = l + (r - l - w) // 2
        elif fmt & DT_RIGHT:
            x = r - w
        gdi16.draw_text(wine, dc, x, y, shown)
        if mark is not None and mark < len(shown):
            ux = x + gdi16.text_width(wine, dc, shown[:mark])
            uw = gdi16.text_width(wine, dc, shown[mark])
            gdi16.blit(wine, dc, gdi16.device_rect(dc, ux, y + ascent + 1, ux + uw, y + ascent + 2),
                       0xF00021, pattern=gdi16.rgb(dc.text_color))
        y += height
    dc.text_align = keep
    return y - t


def _with_font(wine, dc, font):
    old = dc.font
    if font and gdi16.gdi(wine).get(font, gdi16.OBJ_FONT) is not None:
        dc.font = font
    return old


# ------------------------------------------------------------------ BUTTON

def _button_type(w):
    return w.style & BS_TYPEMASK


def _pb_dt_flags(w):
    """BUTTON_BStoDT (button.c:501) for a push button: DT_SINGLELINE unless BS_MULTILINE,
    centred unless BS_LEFT or BS_RIGHT, and DT_VCENTER."""
    fmt = DT_WORDBREAK if w.style & BS_MULTILINE else DT_SINGLELINE
    align = w.style & BS_CENTER
    if align == BS_RIGHT:
        fmt |= DT_RIGHT
    elif align != BS_LEFT:
        fmt |= DT_CENTER
    return fmt | DT_VCENTER


def pb_paint(wine, hwnd, hdc):
    """PB_Paint (button.c:725): WM_CTLCOLOR to the parent (the colors stay fixed), a default
    button's COLOR_WINDOWFRAME outline (button.c:754-759), the push frame, the label offset
    one pixel while pushed (button.c:782-792), and the focus rectangle 2 pixels in."""
    uw = _uw()
    w = _ctl(wine, hwnd)
    dc = gdi16.gdi(wine).get(hdc, gdi16.OBJ_DC)
    if w is None or dc is None:
        return
    old_font = _with_font(wine, dc, w.ctl_font)
    parent = w.parent or hwnd
    yield from uw.send(wine, parent, WM_CTLCOLOR, hdc, (CTLCOLOR_BTN << 16) | hwnd)
    state = w.ctl_state
    rc = list(_client(w))
    default = _button_type(w) == BS_DEFPUSHBUTTON
    if default:
        _sys(wine, dc, tuple(rc), COLOR_WINDOWFRAME)
        rc = [rc[0] + 1, rc[1] + 1, rc[2] - 1, rc[3] - 1]
    pushed = bool(state & BST_PUSHED)
    draw_button_push(wine, dc, tuple(rc), pushed=pushed and not default and not w.style & BS_FLAT,
                     flat=pushed and default and not w.style & BS_FLAT)
    text = w.text or ""
    if text and not w.style & (BS_ICON | BS_BITMAP):
        fmt = _pb_dt_flags(w)
        r = tuple(rc)
        if pushed:
            r = (r[0] + 1, r[1] + 1, r[2] + 1, r[3] + 1)
        keep_mode, keep_color = dc.bk_mode, dc.text_color
        dc.bk_mode = 1  # TRANSPARENT
        if w.style & WS_DISABLED:
            # DrawStateW with DSS_DISABLED: the text embossed, highlight under shadow.
            dc.text_color = uw._colorref(gdi16.SYS_COLORS[COLOR_BTNHIGHLIGHT])
            draw_text(wine, dc, (r[0] + 1, r[1] + 1, r[2] + 1, r[3] + 1), text, fmt)
            dc.text_color = uw._colorref(gdi16.SYS_COLORS[COLOR_BTNSHADOW])
        else:
            dc.text_color = uw._colorref(gdi16.SYS_COLORS[COLOR_BTNTEXT])
        draw_text(wine, dc, r, text, fmt)
        dc.bk_mode, dc.text_color = keep_mode, keep_color
    if state & BST_FOCUS:
        draw_focus_rect(wine, dc, (rc[0] + 2, rc[1] + 2, rc[2] - 2, rc[3] - 2))
    dc.font = old_font


def _paint_button(wine, hwnd):
    """paint_button (button.c:149): when visible, a DC of its own, painted now."""
    uw = _uw()
    w = _ctl(wine, hwnd)
    if w is None or not uw.is_visible(wine, hwnd):
        return
    if _button_type(w) not in (BS_PUSHBUTTON, BS_DEFPUSHBUTTON):
        yield (f"BUTTON {hwnd:#x} type {_button_type(w):#x}: Wine paints it (button.c btnPaintFunc), "
               "and neww paints only push buttons yet")
        return
    hdc = uw.get_dc(wine, hwnd)
    try:
        yield from pb_paint(wine, hwnd, hdc)
    finally:
        uw.release_dc(wine, hwnd, hdc)


def _set_state(wine, hwnd, pushed):
    """BM_SETSTATE (button.c:476-484): BST_PUSHED set or cleared, and the button painted."""
    w = _ctl(wine, hwnd)
    w.ctl_state = (w.ctl_state | BST_PUSHED) if pushed else (w.ctl_state & ~BST_PUSHED)
    yield from _paint_button(wine, hwnd)


def button_window_proc(wine, hwnd, msg, wp, lp):
    """ButtonWndProc_common (button.c:171) through button_proc16, on the 16-bit message."""
    uw = _uw()
    w = _ctl(wine, hwnd)
    if w is None:
        return 0
    kind = _button_type(w)
    x, y = lp & 0xFFFF, (lp >> 16) & 0xFFFF
    x, y = x - 0x10000 if x & 0x8000 else x, y - 0x10000 if y & 0x8000 else y
    if msg == WM_GETDLGCODE:
        # button.c:188-198
        if kind == BS_PUSHBUTTON or kind == 0x8:  # BS_USERBUTTON
            return DLGC_BUTTON | DLGC_UNDEFPUSHBUTTON
        if kind == BS_DEFPUSHBUTTON:
            return DLGC_BUTTON | DLGC_DEFPUSHBUTTON
        if kind in (0x4, 0x9):  # BS_RADIOBUTTON, BS_AUTORADIOBUTTON
            return DLGC_BUTTON | DLGC_RADIOBUTTON
        if kind == 0x7:  # BS_GROUPBOX
            return DLGC_STATIC
        return DLGC_BUTTON
    if msg == WM_ENABLE:
        yield from _paint_button(wine, hwnd)
        return 0
    if msg == WM_CREATE:
        # button.c:204-211: BS_USERBUTTON becomes BS_PUSHBUTTON, the state BST_UNCHECKED.
        if kind > 0xB:  # MAX_BTN_TYPE is 12
            return 0xFFFFFFFF
        if kind == 0x8:
            w.style &= ~BS_TYPEMASK
        w.ctl_state = 0
        return 0
    if msg == WM_ERASEBKGND:
        # button.c:213-228: only BS_OWNERDRAW fills, and it answers 1.
        if kind == 0xB:
            yield f"BUTTON {hwnd:#x} BS_OWNERDRAW WM_ERASEBKGND: neww has no owner-drawn buttons yet"
        return 1
    if msg in (WM_PAINT, WM_PRINTCLIENT):
        # button.c:230-243
        if kind not in (BS_PUSHBUTTON, BS_DEFPUSHBUTTON):
            yield (f"BUTTON {hwnd:#x} type {kind:#x} WM_PAINT: Wine paints it (button.c btnPaintFunc), "
                   "and neww paints only push buttons yet")
            return 0
        if wp:
            yield from pb_paint(wine, hwnd, wp)
            return 0
        mark = uw.scratch_mark(wine)
        ps = uw.scratch(wine, bytes(32))
        hdc = yield from uw.begin_paint(wine, hwnd, ps)
        if hdc:
            dc = gdi16.gdi(wine).get(hdc, gdi16.OBJ_DC)
            keep = dc.bk_mode
            dc.bk_mode = 2  # OPAQUE
            yield from pb_paint(wine, hwnd, hdc)
            dc.bk_mode = keep
            uw.end_paint(wine, hwnd, ps)
        uw.scratch_release(wine, mark)
        return 0
    if msg in (WM_LBUTTONDOWN, WM_LBUTTONDBLCLK):
        if msg == WM_LBUTTONDBLCLK and (w.style & BS_NOTIFY or kind in (0x4, 0x8, 0xB)):
            yield from _notify(wine, w, 5)  # BN_DOUBLECLICKED, button.c:254-262
            return 0
        # button.c:264-269
        yield from uw.set_capture(wine, None, hwnd)
        w.ctl_state |= BUTTON_BTNPRESSED
        yield from uw.set_focus(wine, hwnd)
        yield from _set_state(wine, hwnd, True)
        return 0
    if msg == WM_LBUTTONUP:
        # button.c:275-310
        state = w.ctl_state
        if not state & BUTTON_BTNPRESSED:
            return 0
        state &= BUTTON_NSTATES
        w.ctl_state = state
        if not state & BST_PUSHED:
            yield from uw.release_capture(wine, None)
            return 0
        yield from _set_state(wine, hwnd, False)
        cx, cy = _client(w)[2:]
        if 0 <= x < cx and 0 <= y < cy:
            if kind in (0x2, 0x3, 0x5, 0x6, 0x9):
                yield (f"BUTTON {hwnd:#x} type {kind:#x} click: Wine checks it (button.c:285-301), "
                       "and neww has no check boxes or radio buttons yet")
                return 0
            yield from uw.release_capture(wine, None)
            yield from _notify(wine, w, BN_CLICKED)
        else:
            yield from uw.release_capture(wine, None)
        return 0
    if msg == WM_CAPTURECHANGED:
        # button.c:312-322
        if lp & 0xFFFF == hwnd:
            return 0
        if w.ctl_state & BUTTON_BTNPRESSED:
            w.ctl_state &= BUTTON_NSTATES
            if w.ctl_state & BST_PUSHED:
                yield from _set_state(wine, hwnd, False)
        return 0
    if msg == WM_MOUSEMOVE:
        # button.c:324-330
        if wp & MK_LBUTTON and uw.wm(wine).capture == hwnd:
            cx, cy = _client(w)[2:]
            yield from _set_state(wine, hwnd, 0 <= x < cx and 0 <= y < cy)
        return 0
    if msg == WM_SETTEXT:
        # button.c:332-374: the text set, then the button painted (a group box invalidated).
        result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
        if kind == 0x7:
            uw.invalidate(wine, hwnd, None, True)
        else:
            yield from _paint_button(wine, hwnd)
        return 1
    if msg == WM_SETFONT:
        # button.c:376-379
        w.ctl_font = wp
        if lp & 0xFFFF:
            uw.invalidate(wine, hwnd, None, True)
        return 0
    if msg == WM_GETFONT:
        return w.ctl_font
    if msg == WM_SETFOCUS:
        # button.c:384-396
        w.ctl_state |= BST_FOCUS
        yield from _paint_button(wine, hwnd)
        if w.style & BS_NOTIFY:
            yield from _notify(wine, w, 6)  # BN_SETFOCUS
        return 0
    if msg == WM_KILLFOCUS:
        # button.c:398-410
        state = w.ctl_state
        w.ctl_state = state & ~BST_FOCUS
        yield from _paint_button(wine, hwnd)
        if state & BUTTON_BTNPRESSED and uw.wm(wine).capture == hwnd:
            yield from uw.release_capture(wine, None)
        if w.style & BS_NOTIFY:
            yield from _notify(wine, w, 7)  # BN_KILLFOCUS
        uw.invalidate(wine, hwnd, None, False)
        return 0
    if msg == BM_SETSTYLE16:
        # button.c:416-426
        w.style = (w.style & ~BS_TYPEMASK) | (wp & BS_TYPEMASK)
        if lp & 0xFFFF:
            uw.invalidate(wine, hwnd, None, True)
        return 0
    if msg == BM_GETCHECK16:
        return w.ctl_state & 3
    if msg == BM_GETSTATE16:
        return w.ctl_state
    if msg == BM_SETSTATE16:
        yield from _set_state(wine, hwnd, bool(wp))
        return 0
    if msg == BM_SETCHECK16:
        yield f"BUTTON {hwnd:#x} BM_SETCHECK: neww has no check boxes or radio buttons yet"
        return 0
    result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
    return result


# ------------------------------------------------------------------ STATIC

TEXT_FORMAT = {
    # STATIC_PaintTextfn (static.c:613-637)
    SS_LEFT: DT_EXPANDTABS | DT_WORDBREAK,
    SS_CENTER: DT_CENTER | DT_EXPANDTABS | DT_WORDBREAK,
    SS_RIGHT: DT_RIGHT | DT_EXPANDTABS | DT_WORDBREAK,
    SS_SIMPLE: DT_SINGLELINE,
    SS_LEFTNOWORDWRAP: DT_EXPANDTABS,
}


def _ctlcolor_static(wine, w, hdc):
    """STATIC_SendWmCtlColorStatic (static.c:243): the parent's brush, or DefWindowProc's."""
    uw = _uw()
    parent = w.parent or w.hwnd
    lp = (CTLCOLOR_STATIC << 16) | w.hwnd
    brush = yield from uw.send(wine, parent, WM_CTLCOLOR, hdc, lp)
    brush &= 0xFFFF
    if not brush:
        out = yield from uw.def_window_proc(wine, parent, WM_CTLCOLOR, hdc, lp)
        if isinstance(out, tuple):
            if len(out) > 2 and out[2]:
                yield out[2]
            out = out[0]
        brush = (out or 0) & 0xFFFF
    return brush


def static_paint(wine, hwnd, hdc):
    """STATIC_PaintTextfn (static.c:603) after the WM_CTLCOLOR (static.c:389)."""
    uw = _uw()
    w = _ctl(wine, hwnd)
    dc = gdi16.gdi(wine).get(hdc, gdi16.OBJ_DC)
    if w is None or dc is None:
        return
    kind = w.style & SS_TYPEMASK
    if kind not in TEXT_FORMAT:
        brush = yield from _ctlcolor_static(wine, w, hdc)
        yield (f"STATIC {hwnd:#x} type {kind:#x} WM_PAINT: Wine paints it (static.c staticPaintFunc), "
               "and neww paints only the text statics yet")
        return
    brush = yield from _ctlcolor_static(wine, w, hdc)
    fmt = TEXT_FORMAT[kind]
    if w.style & SS_NOPREFIX:
        fmt |= DT_NOPREFIX
    old_font = _with_font(wine, dc, w.ctl_font)
    rc = _client(w)
    keep = dc.text_color
    if kind != SS_SIMPLE:
        gdi16.fill(wine, dc, rc, brush)
        if w.style & WS_DISABLED:
            dc.text_color = uw._colorref(gdi16.SYS_COLORS[COLOR_GRAYTEXT])
    if w.text:
        draw_text(wine, dc, rc, w.text, fmt)
    dc.text_color = keep
    dc.font = old_font


def _try_paint_static(wine, hwnd):
    """STATIC_TryPaintFcn (static.c:287): when visible, painted now with a DC of its own."""
    uw = _uw()
    if not uw.is_visible(wine, hwnd):
        return
    hdc = uw.get_dc(wine, hwnd)
    try:
        yield from static_paint(wine, hwnd, hdc)
    finally:
        uw.release_dc(wine, hwnd, hdc)


def static_window_proc(wine, hwnd, msg, wp, lp):
    """StaticWndProc_common (static.c:339) through static_proc16, on the 16-bit message."""
    uw = _uw()
    w = _ctl(wine, hwnd)
    if w is None:
        return 0
    kind = w.style & SS_TYPEMASK
    if msg == 0x81 and kind in (SS_ICON, SS_BITMAP):  # WM_NCCREATE
        yield (f"STATIC {hwnd:#x} type {kind:#x} WM_NCCREATE: static_proc16 loads its 16-bit icon or bitmap "
               "(message.c:2539-2565), and neww has none yet")
        return 0
    if msg == WM_CREATE:
        # static.c:350-357: a type past SS_TYPEMASK cannot happen once masked.
        return 0
    if msg == WM_ERASEBKGND:
        return 1  # static.c:374-376
    if msg in (WM_PAINT, WM_PRINTCLIENT):
        # static.c:379-396
        if wp:
            yield from static_paint(wine, hwnd, wp)
            return 0
        mark = uw.scratch_mark(wine)
        ps = uw.scratch(wine, bytes(32))
        hdc = yield from uw.begin_paint(wine, hwnd, ps)
        if hdc:
            yield from static_paint(wine, hwnd, hdc)
            uw.end_paint(wine, hwnd, ps)
        uw.scratch_release(wine, mark)
        return 0
    if msg == WM_ENABLE:
        yield from _try_paint_static(wine, hwnd)  # static.c:398-399
        if w.style & SS_NOTIFY:
            yield from _notify(wine, w, 3 if wp else 4)  # STN_ENABLE, STN_DISABLE
        return 0
    if msg == WM_SETTEXT:
        # static.c:493-502
        if kind in TEXT_FORMAT:
            result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
            yield from _try_paint_static(wine, hwnd)
            return result
        return 0
    if msg == WM_SETFONT:
        # static.c:504-512
        if kind in TEXT_FORMAT:
            w.ctl_font = wp
            if lp & 0xFFFF:
                uw.invalidate(wine, hwnd, None, True)
        return 0
    if msg == WM_GETFONT:
        return w.ctl_font
    if msg == WM_NCHITTEST:
        return HTCLIENT if w.style & SS_NOTIFY else HTTRANSPARENT  # static.c:517-521
    if msg == WM_GETDLGCODE:
        return DLGC_STATIC  # static.c:523-524
    if msg == WM_LBUTTONDOWN and w.style & SS_NOTIFY:
        yield from _notify(wine, w, 0)  # STN_CLICKED, static.c:526-531
        return 0
    result = yield from uw.def_window_proc(wine, hwnd, msg, wp, lp)
    return result
