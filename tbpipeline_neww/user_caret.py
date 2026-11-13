"""The caret, from Wine 2528aff2 dlls/win32u/input.c:2375-2738 and server/queue.c.

USER.163-169 and 183 forward to user32 (dlls/user.exe16/window.c:1018-1090). The server keeps
the caret per thread input (a Win16 task here): its window, its rectangle, a hide count and
an on/off state (server/queue.c:203 set_caret_window, :3905, :3933). win32u keeps the caret
bitmap and the blink time, draws the caret by inverting it into the window's DC
(display_caret, input.c:2381), and blinks it with the system timer SYSTEM_TIMER_CARET, which
DispatchMessage handles itself (dlls/win32u/message.c:4055 -> toggle_caret, input.c:2711).
"""

import struct

from PIL import Image

from . import gdi16
from .handlers import api

SYSTEM_TIMER_CARET = 0xFFFF            # dlls/win32u/ntuser_private.h:38
SYSTEM_TIMER = 0x10000                 # neww's timer-key flag for a system timer
GRAY = (0x80, 0x80, 0x80)              # GRAY_BRUSH, for CreateCaret's bitmap (HBITMAP)1


class Caret:
    def __init__(self):
        self.hwnd = 0
        self.rect = (0, 0, 0, 0)
        self.hide = 0
        self.state = 0
        self.color = None              # the uniform bitmap's color: white or gray
        self.timeout = 500             # input.c:2378; CursorBlinkRate is not set in neww's registry


def caret(wine, task=None):
    from .user_wnd import wm
    q = wm(wine).queue_of(task or wine.htask)
    if getattr(q, "caret", None) is None:
        q.caret = Caret()
    return q.caret


def display(wine, c, hwnd, rect):
    """display_caret (input.c:2381): BitBlt the caret bitmap into the window's DC with
    SRCINVERT. The bitmap is uniform, so each pixel is XORed with its color. neww's cache DC
    is MM_TEXT, so the rectangle is in device units from the client origin."""
    from .user_wnd import get_dc, release_dc
    if not hwnd or c.color is None:
        return
    g = gdi16.gdi(wine)
    hdc = get_dc(wine, hwnd)
    dc = g.objects[hdc]
    ox, oy = dc.origin
    x0, y0, x1, y1 = rect[0] + ox, rect[1] + oy, rect[2] + ox, rect[3] + oy
    cx0, cy0, cx1, cy1 = dc.clip
    x0, y0, x1, y1 = max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1)
    if x0 < x1 and y0 < y1:
        box = (x0, y0, x1, y1)
        g.screen.paste(_xor(g.screen.crop(box), c.color), box)
    release_dc(wine, hwnd, hdc)


def _signed(v):
    return v - 0x10000 if v & 0x8000 else v


def _xor(img, color):
    return Image.merge("RGB", tuple(ch.point(lambda v, k=k: v ^ k) for ch, k in zip(img.split(), color)))


def _timers(wine, hwnd):
    from .user_wnd import wm
    m = wm(wine)
    return m, m.queue_of(m.task_of(hwnd)).timers


def set_system_timer(wine, hwnd, ident, elapse):
    m, timers = _timers(wine, hwnd)
    timers[(hwnd, SYSTEM_TIMER | ident)] = [max(elapse, 10), 0, m.clock + max(elapse, 10)]


def kill_system_timer(wine, hwnd, ident):
    _m, timers = _timers(wine, hwnd)
    timers.pop((hwnd, SYSTEM_TIMER | ident), None)


def _set_window(c, hwnd, width, height):
    """server/queue.c:203 set_caret_window and :3905: the old window, rectangle, hide count and
    state, then the new window, hidden once and off; the rectangle keeps its corner only for
    the same window."""
    old = (c.hwnd, c.rect, c.hide, c.state)
    if not hwnd or hwnd != c.hwnd:
        c.rect = (0, 0, 0, 0)
    c.hwnd, c.hide, c.state = hwnd, 1, 0
    c.rect = (c.rect[0], c.rect[1], c.rect[0] + width, c.rect[1] + height)
    return old


def _hide_previous(wine, c, old):
    prev, rect, hidden, state = old
    if prev and not hidden:
        kill_system_timer(wine, prev, SYSTEM_TIMER_CARET)
        if state:
            display(wine, c, prev, rect)


@api("USER", "CreateCaret")
def create_caret(wine, arg, hwnd, bitmap, width, height):
    """NtUserCreateCaret (input.c:2420). For no bitmap or (HBITMAP)1 the caret is a uniform
    width x height bitmap, white or gray (:2453-2475), 1 pixel for a 0 size (SM_CXBORDER).
    Void in 16 bits: AX is left."""
    from .user_wnd import wm
    if not hwnd or wm(wine).get(hwnd) is None:
        return arg.regs("ax"), 0
    if bitmap not in (0, 1):
        return 0, 0, "USER.163 CreateCaret with a bitmap: neww draws only the uniform caret"
    width = _signed(width) or 1           # SM_CXBORDER, SM_CYBORDER: 1
    height = _signed(height) or 1
    c = caret(wine)
    old = _set_window(c, hwnd, width, height)
    _hide_previous(wine, c, old)
    c.color = GRAY if bitmap else (0xFF, 0xFF, 0xFF)
    return arg.regs("ax"), 0


@api("USER", "DestroyCaret")
def destroy_caret(wine, arg):
    """NtUserDestroyCaret (input.c:2512)."""
    c = caret(wine)
    old = _set_window(c, 0, 0, 0)
    _hide_previous(wine, c, old)
    c.color = None
    return arg.regs("ax"), 0


@api("USER", "SetCaretPos")
def set_caret_pos(wine, arg, x, y):
    """NtUserSetCaretPos (input.c:2602): the rectangle moves (server/queue.c:3952) and the state
    goes on if it moved (:3975). If it is shown and moved, it is drawn off at the old place,
    on at the new one, and the blink timer starts again."""
    x, y = _signed(x), _signed(y)
    c = caret(wine)
    hwnd, r, state, hidden = c.hwnd, c.rect, c.state, c.hide
    c.rect = (x, y, r[2] + x - r[0], r[3] + y - r[1])
    if x != r[0] or y != r[1]:
        c.state = 1
    if not hidden and (x != r[0] or y != r[1]):
        if hwnd == 0:
            return 0, 0, "USER.165 SetCaretPos with no caret window: Wine would draw it on the desktop"
        if state:
            display(wine, c, hwnd, r)
        display(wine, c, hwnd, c.rect)
        set_system_timer(wine, hwnd, SYSTEM_TIMER_CARET, c.timeout)
    return arg.regs("ax"), 0


def _owns(c, hwnd):
    """server/queue.c:3947: a window that is not the caret's is STATUS_ACCESS_DENIED."""
    return not hwnd or hwnd == c.hwnd


@api("USER", "ShowCaret")
def show_caret(wine, arg, hwnd):
    """NtUserShowCaret (input.c:2646): one less hidden (not below 0), state on; at 0 it is
    drawn and blinks."""
    c = caret(wine)
    if _owns(c, hwnd):
        hidden = c.hide
        c.hide, c.state = max(c.hide - 1, 0), 1
        if hidden == 1:
            display(wine, c, c.hwnd, c.rect)
            set_system_timer(wine, c.hwnd, SYSTEM_TIMER_CARET, c.timeout)
    return arg.regs("ax"), 0


@api("USER", "HideCaret")
def hide_caret(wine, arg, hwnd):
    """NtUserHideCaret (input.c:2681): one more hidden, state off; if it was shown, it is drawn
    off when it was on, and stops blinking."""
    c = caret(wine)
    if _owns(c, hwnd):
        hidden, state = c.hide, c.state
        c.hide, c.state = c.hide + 1, 0
        if not hidden:
            if state:
                display(wine, c, c.hwnd, c.rect)
            kill_system_timer(wine, c.hwnd, SYSTEM_TIMER_CARET)
    return arg.regs("ax"), 0


def toggle(wine, hwnd):
    """toggle_caret (input.c:2711), for WM_SYSTIMER SYSTEM_TIMER_CARET."""
    c = caret(wine)
    if not _owns(c, hwnd):
        return
    c.state = 0 if c.state else 1
    if not c.hide:
        display(wine, c, c.hwnd, c.rect)


@api("USER", "GetCaretPos")
def get_caret_pos(wine, arg, ptr):
    """NtUserGetCaretPos (input.c:2569): the rectangle's corner. Void in 16 bits."""
    c = caret(wine)
    gdi16.write(wine, ptr, struct.pack("<hh", c.rect[0], c.rect[1]))
    return arg.regs("ax"), 0


@api("USER", "SetCaretBlinkTime")
def set_caret_blink_time(wine, arg, ms):
    """NtUserSetCaretBlinkTime (input.c:2557): the next timer set uses it. Void in 16 bits."""
    caret(wine).timeout = ms
    return arg.regs("ax"), 0


@api("USER", "GetCaretBlinkTime")
def get_caret_blink_time(wine, arg):
    return caret(wine).timeout & 0xFFFF
