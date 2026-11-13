"""DrawText and DrawFocusRect, from Wine 2528aff2.

DrawText16 (dlls/user.exe16/user.c:809) copies the RECT16 to a RECT and back around DrawTextA,
which is DrawTextExW (dlls/user32/text.c:865). neww has the lines it can lay out the way
TEXT_NextLineW (text.c:602) does without breaking or shortening them: one line with
DT_SINGLELINE, else a line per CR/LF. Word breaks, ellipses, tab expansion, DT_MODIFYSTRING
and a mnemonic's underscore stop by name.
"""

import struct

from . import gdi16
from .handlers import api

DT_CENTER, DT_RIGHT, DT_VCENTER, DT_BOTTOM = 0x1, 0x2, 0x4, 0x8
DT_WORDBREAK, DT_SINGLELINE, DT_EXPANDTABS, DT_TABSTOP = 0x10, 0x20, 0x40, 0x80
DT_NOCLIP, DT_EXTERNALLEADING, DT_CALCRECT, DT_NOPREFIX = 0x100, 0x200, 0x400, 0x800
DT_EDITCONTROL, DT_PATH_ELLIPSIS, DT_END_ELLIPSIS, DT_MODIFYSTRING = 0x2000, 0x4000, 0x8000, 0x10000
DT_WORD_ELLIPSIS = 0x40000
ETO_CLIPPED = 4
CR, LF, PREFIX = "\r", "\n", "&"


def _signed(v):
    """A 16-bit value as signed, whether the spec unpacked it as word or s_word."""
    return v - 0x10000 if 0 <= v and v & 0x8000 else v


def next_line(text, i, flags):
    """TEXT_NextLineW (text.c:602) without word breaks or ellipses: the line from i, its
    prefixes taken out ("&&" is one "&"), up to a CR or LF unless DT_SINGLELINE; then
    past one CR, LF or CR LF (text.c:776-783). Returns (line, the next i or None at the end,
    the offset of the underscored character or -1)."""
    out, prefix_at = [], -1
    while i < len(text):
        ch = text[i]
        if ch in (CR, LF) and not flags & DT_SINGLELINE:
            break
        if not flags & DT_NOPREFIX and ch == PREFIX and i + 1 < len(text):
            i += 1
            if text[i] != PREFIX:
                prefix_at = len(out)
            out.append(text[i])
            i += 1
            continue
        out.append(ch)
        i += 1
    if i >= len(text):
        return "".join(out), None, prefix_at
    if text[i] == CR:
        i += 1
        if i < len(text) and text[i] == LF:
            i += 1
    elif text[i] == LF:
        i += 1
    return "".join(out), (i if i < len(text) else None), prefix_at


@api("USER", "DrawText")
def draw_text16(wine, arg, hdc, ptr, count, rect_ptr, flags):
    """DrawText16 -> DrawTextExW (text.c:865). Returns the height drawn (y - top, or 1)."""
    count = _signed(count)
    dc = gdi16._dc(wine, hdc)
    if dc is None or not ptr or not rect_ptr:
        return 0
    unsupported = flags & (DT_WORDBREAK | DT_EXPANDTABS | DT_TABSTOP | DT_MODIFYSTRING | DT_PATH_ELLIPSIS
                           | DT_END_ELLIPSIS | DT_WORD_ELLIPSIS | DT_EDITCONTROL)
    if flags & DT_SINGLELINE:
        unsupported &= ~DT_WORDBREAK                         # text.c:889
    if unsupported:
        return 0, 0, f"USER.85 DrawText with flags {flags:#x}: neww lays out lines without word breaks, tabs or ellipses"
    if count == -1:
        from .kernel16 import cstr
        raw = cstr(wine, ptr >> 16, ptr & 0xFFFF, 0x8000)
    else:
        raw = gdi16.read(wine, ptr, max(count, 0))
    text = raw.decode("cp1252", "replace")
    left, top, right, bottom = struct.unpack("<hhhh", gdi16.read(wine, rect_ptr, 8))
    m = gdi16.text_metrics(wine, dc)
    lh = m["height"] + (m["external"] if flags & DT_EXTERNALLEADING else 0)
    if text and count == 0:
        return lh                                            # text.c:908
    if not text:
        if flags & DT_CALCRECT:
            bottom = top + lh if flags & DT_SINGLELINE else top
            gdi16.write(wine, rect_ptr, struct.pack("<hhhh", left, top, left, bottom))
        return lh                                            # text.c:914-926
    stop = gdi16.scaled_text(dc, "DrawText", text)
    if stop:
        return stop
    if flags & DT_CALCRECT:
        flags |= DT_NOCLIP
    x, y, max_width, i = left, top, 0, 0
    while True:
        last_line = not flags & DT_NOCLIP and y + lh > bottom
        line, i, prefix_at = next_line(text, i, flags)
        if prefix_at != -1 and not flags & DT_CALCRECT:
            return 0, 0, f"USER.85 DrawText {text!r}: the mnemonic's underscore (TEXT_DrawUnderscore), which neww does not draw yet"
        width = gdi16.text_width(wine, dc, line)
        if flags & DT_CENTER:
            x = (left + right - width) // 2
        elif flags & DT_RIGHT:
            x = right - width
        if flags & DT_SINGLELINE:
            # size.cy is the line's extent height, tmHeight (text.c:986-990).
            if flags & DT_VCENTER:
                y = top + (bottom - top) // 2 - m["height"] // 2
            elif flags & DT_BOTTOM:
                y = bottom - m["height"]
        if not flags & DT_CALCRECT:
            # ExtTextOutW with ETO_CLIPPED to the rectangle unless DT_NOCLIP (text.c:1004).
            saved = dc.text_align
            dc.text_align = saved & 1                        # TA_LEFT | TA_TOP, keeping TA_UPDATECP
            gdi16.draw_text(wine, dc, x, y, line,
                            clip_rect=None if flags & DT_NOCLIP else (left, top, right, bottom))
            dc.text_align = saved
        else:
            max_width = max(max_width, width)
        y += lh
        if i is None or last_line:
            break
    if flags & DT_CALCRECT:
        gdi16.write(wine, rect_ptr, struct.pack("<hhhh", left, top, left + max_width, y))
    wine.trace[-1] += f" {text!r}"
    return (y - top) or 1


def focus_points(l, t, r, b):
    """The pixels DrawFocusRect inverts, in device units. user32 uitools.c:1485 draws
    Rectangle() with a PS_ALTERNATE pen in R2_NOT and no brush. dibdrv_Rectangle
    (win32u/dibdrv/graphics.c:1371) takes the inclusive rectangle and draws it as one closed
    dashed polyline, anticlockwise from the top right (:1410); the dash ({1, 1} for
    PS_ALTERNATE) starts on (reset_dash_origin) and runs on round the corners, each segment
    leaving out its end point."""
    r, b = r - 1, b - 1
    if r < l or b < t:
        return []
    path = []
    corners = [(r, t), (l, t), (l, b), (r, b), (r, t)]
    for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
        dx, dy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
        x, y = x0, y0
        while (x, y) != (x1, y1):
            path.append((x, y))
            x, y = x + dx, y + dy
    return [p for k, p in enumerate(path) if k % 2 == 0]


@api("USER", "DrawFocusRect")
def draw_focus_rect(wine, arg, hdc, rect_ptr):
    """DrawFocusRect16 (dlls/user.exe16/user.c:2969) -> DrawFocusRect: every other pixel of the
    outline inverted (focus_points). Void in 16 bits."""
    dc = gdi16._dc(wine, hdc)
    if dc is None:
        return arg.regs("ax"), 0
    left, top, right, bottom = struct.unpack("<hhhh", gdi16.read(wine, rect_ptr, 8))
    if gdi16.scaled(dc):
        return 0, 0, "USER.466 DrawFocusRect in a scaling map mode: neww draws it in MM_TEXT units only"
    img, (ox, oy) = gdi16.surface(wine, dc)
    box = gdi16.clip_box(wine, dc)
    l, t = gdi16.lp_to_dp(dc, left, top)
    r, b = gdi16.lp_to_dp(dc, right, bottom)
    for x, y in focus_points(min(l, r), min(t, b), max(l, r), max(t, b)):
        px, py = x + ox, y + oy
        if box[0] <= px < box[2] and box[1] <= py < box[3]:
            c = img.getpixel((px, py))
            img.putpixel((px, py), tuple(255 - v for v in c) if isinstance(c, tuple) else 255 - c)
    return arg.regs("ax"), 0
