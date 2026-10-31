"""USER windows, classes and messages, from Wine dlls/user.exe16 and win32u at WINE_COMMIT.

The window manager is wine.wm. Window handles are Wine's user handle numbers,
FIRST_USER_HANDLE (0x0020) + 2 * index, the desktop first. Wine's own session
makes other user objects before the task's first window, so the numbers are
neww's order, not the ones a Wine session would print.

A message sent to a window whose procedure is guest code is a guest call
(guest.Call) from inside the gate, with DS = ES = SS and AX the window's
instance, as Wine's call_window_proc16 makes it. A handler that may send
messages is a generator: each `yield from send(...)` that reaches guest code
becomes one guest call, and its DX:AX comes back as the result.

The 16-bit structures a message carries (CREATESTRUCT16, WINDOWPOS16, ...)
are written to a scratch block, released when the message returns, where
Wine writes them on the 16-bit stack.

Where Wine needs input, a display or a real clock, the docstring says what
neww does instead: there is no input, the screen is 1024x768, and time is a
counter that moves only when the task waits for a message.
"""

import struct

from .guest import Call
from .handlers import api, signed
from . import gdi16

FIRST_USER_HANDLE = 0x0020

WS_POPUP, WS_CHILD, WS_MINIMIZE, WS_VISIBLE = 0x80000000, 0x40000000, 0x20000000, 0x10000000
WS_DISABLED, WS_CLIPSIBLINGS, WS_CLIPCHILDREN, WS_MAXIMIZE = 0x08000000, 0x04000000, 0x02000000, 0x01000000
WS_CAPTION, WS_BORDER, WS_DLGFRAME = 0x00C00000, 0x00800000, 0x00400000
WS_VSCROLL, WS_HSCROLL, WS_SYSMENU, WS_THICKFRAME = 0x00200000, 0x00100000, 0x00080000, 0x00040000
WS_EX_DLGMODALFRAME, WS_EX_NOPARENTNOTIFY, WS_EX_TOPMOST = 0x1, 0x4, 0x8
WS_EX_TOOLWINDOW, WS_EX_WINDOWEDGE, WS_EX_CLIENTEDGE, WS_EX_STATICEDGE = 0x80, 0x100, 0x200, 0x20000

CS_VREDRAW, CS_HREDRAW, CS_OWNDC, CS_CLASSDC, CS_PARENTDC, CS_GLOBALCLASS = 1, 2, 0x20, 0x40, 0x80, 0x4000

WM_CREATE, WM_DESTROY, WM_MOVE, WM_SIZE, WM_ACTIVATE = 0x01, 0x02, 0x03, 0x05, 0x06
WM_SETFOCUS, WM_KILLFOCUS, WM_ENABLE, WM_SETREDRAW = 0x07, 0x08, 0x0A, 0x0B
WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH, WM_PAINT, WM_CLOSE = 0x0C, 0x0D, 0x0E, 0x0F, 0x10
WM_QUERYENDSESSION, WM_QUERYOPEN, WM_QUIT, WM_ERASEBKGND = 0x11, 0x13, 0x12, 0x14
WM_SHOWWINDOW, WM_CTLCOLOR, WM_ACTIVATEAPP, WM_CANCELMODE, WM_SETCURSOR = 0x18, 0x19, 0x1C, 0x1F, 0x20
WM_MOUSEACTIVATE, WM_CHILDACTIVATE, WM_GETMINMAXINFO, WM_ICONERASEBKGND = 0x21, 0x22, 0x24, 0x27
WM_SETFONT, WM_GETFONT, WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED = 0x30, 0x31, 0x46, 0x47
WM_NCCREATE, WM_NCDESTROY, WM_NCCALCSIZE, WM_NCHITTEST, WM_NCPAINT, WM_NCACTIVATE = 0x81, 0x82, 0x83, 0x84, 0x85, 0x86
WM_TIMER, WM_SYSTIMER, WM_PARENTNOTIFY, WM_QUERYNEWPALETTE = 0x113, 0x118, 0x210, 0x30F
WM_PAINTICON, WM_SYNCPAINT = 0x26, 0x88

SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOREDRAW, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x8, 0x10
SWP_FRAMECHANGED, SWP_SHOWWINDOW, SWP_HIDEWINDOW, SWP_NOCOPYBITS = 0x20, 0x40, 0x80, 0x100
SWP_NOOWNERZORDER, SWP_NOSENDCHANGING, SWP_DEFERERASE = 0x200, 0x400, 0x2000
SWP_NOCLIENTSIZE, SWP_NOCLIENTMOVE, SWP_STATECHANGED = 0x800, 0x1000, 0x8000
SWP_AGG_NOGEOMETRYCHANGE = SWP_NOSIZE | SWP_NOMOVE | SWP_NOCLIENTSIZE | SWP_NOCLIENTMOVE
SWP_AGG_NOPOSCHANGE = SWP_AGG_NOGEOMETRYCHANGE | SWP_NOZORDER
SWP_AGG_STATUSFLAGS = SWP_AGG_NOPOSCHANGE | SWP_FRAMECHANGED | SWP_HIDEWINDOW | SWP_SHOWWINDOW
SWP_AGG_NOCLIENTCHANGE = SWP_NOCLIENTSIZE | SWP_NOCLIENTMOVE

HWND_TOP, HWND_BOTTOM = 0, 1
CW_USEDEFAULT16 = -0x8000

# win32u sysparams.c at 96 dpi: caption 18, menu 18, border width 1, padded border 0, scroll 16.
CAPTION_HEIGHT, MENU_HEIGHT, BORDER_WIDTH, PADDED_BORDER, SCROLL = 18, 18, 1, 0, 16
CXEDGE = 2
SCREEN_W, SCREEN_H = gdi16.SCREEN
# The work area of the one monitor: the whole screen, there is no taskbar.
WORK = (0, 0, SCREEN_W, SCREEN_H)
# SM_CXMAXTRACK and SM_CYMAXTRACK: the virtual screen + 4 + 2 * SM_CXFRAME (4).
MAX_TRACK = (SCREEN_W + 4 + 8, SCREEN_H + 4 + 8)
# SM_CYMIN: SM_CYCAPTION (19) + 2 * SM_CYFRAME (4). SM_CXMIN needs the caption font's average
# width (get_text_metr_size), which neww does not have: 3 * 18 + 18 + 8 + 4 + 4 * width.
CY_MIN = 19 + 8
CX_MIN_WITHOUT_FONT = 3 * 18 + 18 + 8 + 4

SYSTEM_CLASSES = ("button", "combobox", "combolbox", "edit", "listbox", "mdiclient", "scrollbar", "static",
                  "#32770", "#32768", "#32772")


class WndClass:
    def __init__(self, atom, name, module, style, proc, cls_extra, wnd_extra, inst, icon, cursor, brush, menu, icon_sm):
        self.atom, self.name, self.module, self.style, self.proc = atom, name, module, style, proc
        self.cls_extra, self.wnd_extra, self.inst = cls_extra, wnd_extra, inst
        self.icon, self.cursor, self.brush, self.menu, self.icon_sm = icon, cursor, brush, menu, icon_sm
        self.extra = bytearray(cls_extra)
        self.dc = 0


class Window:
    def __init__(self, hwnd, cls, parent, owner):
        self.hwnd, self.cls, self.parent, self.owner = hwnd, cls, parent, owner
        self.style = self.exstyle = 0
        self.proc = cls.proc if cls else None
        self.inst = 0
        self.id = 0
        self.menu = 0
        self.text = None
        self.rect = (0, 0, 0, 0)    # window rectangle in the parent's client coordinates
        self.client = (0, 0, 0, 0)  # client rectangle in the parent's client coordinates
        self.extra = bytearray(cls.wnd_extra if cls else 0)
        self.props = {}
        self.need_size = False
        self.update = None          # invalid part of the client, client coordinates
        self.erase = False
        self.ncpaint = False
        self.dc = 0
        self.destroyed = False
        self.sysmenu = 0
        # The task that created the window: its messages go to that task's queue.
        self.task = 0


class TaskQueue:
    """A task's message queue: posted messages, the quit flag, its timers. Wine keeps one per
    thread (a Win16 task is a thread): win32u's message queue and its timer list."""

    def __init__(self):
        self.queue = []          # posted messages: (hwnd, msg, wp, lp)
        self.quit = None
        self.timers = {}         # (hwnd, id) -> [interval, proc, due]


class WM:
    def __init__(self, wine):
        self.wine = wine
        self.classes = []
        self.windows = {}
        self.order = []          # z order of each parent's children: parent -> [hwnd, top first]
        self.next_index = 0
        self.active = 0
        self.focus = 0
        self.capture = 0
        self.foreground = 0
        # Task handle -> TaskQueue. queue, quit and timers are the current task's.
        self.queues = {}
        self.clock = 0
        self.cursor = 0
        self.scratch = None
        self.scratch_top = 0
        self.desktop = self._handle()
        desk = Window(self.desktop, None, 0, 0)
        desk.style = WS_POPUP | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN
        desk.rect = desk.client = (0, 0, SCREEN_W, SCREEN_H)
        self.windows[self.desktop] = desk
        self.children = {self.desktop: [], 0: []}

    def _handle(self):
        h = FIRST_USER_HANDLE + (self.next_index << 1)
        self.next_index += 1
        return h

    def get(self, hwnd):
        w = self.windows.get(hwnd)
        return w if w is not None and not w.destroyed else None

    def queue_of(self, task):
        q = self.queues.get(task)
        if q is None:
            q = self.queues[task] = TaskQueue()
        return q

    def task_of(self, hwnd):
        """The task whose queue a window's messages go to: the one that created it."""
        w = self.windows.get(hwnd)
        return w.task if w is not None else self.wine.htask

    @property
    def queue(self):
        return self.queue_of(self.wine.htask).queue

    @queue.setter
    def queue(self, value):
        self.queue_of(self.wine.htask).queue = value

    @property
    def quit(self):
        return self.queue_of(self.wine.htask).quit

    @quit.setter
    def quit(self, value):
        self.queue_of(self.wine.htask).quit = value

    @property
    def timers(self):
        return self.queue_of(self.wine.htask).timers


def wm(wine):
    if getattr(wine, "wm", None) is None:
        wine.wm = WM(wine)
    return wine.wm


def string_at(wine, ptr, limit=0x10000):
    if not ptr or not ptr >> 16:
        return None
    return gdi16.cstr(wine, ptr, limit).decode("cp1252", "replace")


# ------------------------------------------------------------------ scratch memory

def scratch(wine, data):
    """Room for a structure Wine would put on the 16-bit stack. Returns its SEGPTR."""
    m = wm(wine)
    if m.scratch is None:
        handle, _dx, why = wine._global_alloc(0, 0x10000)
        if why:
            raise RuntimeError(why)
        m.scratch = wine.selector_of(handle)
        m.scratch_top = 0x10
    off = m.scratch_top
    size = (len(data) + 1) & ~1
    if off + size > 0x10000:
        raise RuntimeError("message scratch block full")
    wine.write(m.scratch, off, bytes(data))
    m.scratch_top += size
    return m.scratch << 16 | off


def scratch_mark(wine):
    return wm(wine).scratch_top


def scratch_release(wine, mark):
    m = wm(wine)
    if m.scratch is not None:
        m.scratch_top = mark


def read_rect(wine, ptr):
    return struct.unpack("<hhhh", gdi16.read(wine, ptr, 8))


def write_rect(wine, ptr, rect):
    gdi16.write(wine, ptr, struct.pack("<hhhh", *[max(-0x8000, min(0x7FFF, v)) for v in rect]))


# ------------------------------------------------------------------ geometry

def screen_origin(wine, hwnd):
    """Where a window's client (0, 0) is on the screen."""
    m = wm(wine)
    x = y = 0
    w = m.windows.get(hwnd)
    while w is not None and w.hwnd != m.desktop:
        x += w.client[0]
        y += w.client[1]
        w = m.windows.get(w.parent)
    return x, y


HTNOWHERE, HTCLIENT, HTTRANSPARENT = 0, 1, 0xFFFF


def nc_hit_test(wine, w, x, y):
    """defwnd.c handle_nc_hit_test, its first two tests: outside the window is HTNOWHERE,
    inside the client is HTCLIENT. The frame's parts (borders, caption, menu, scroll bars)
    stop for now. Returns (hit, stop)."""
    m = wm(wine)
    px, py = screen_origin(wine, w.parent) if w.parent and w.parent != m.desktop else (0, 0)
    l, t, r, b = w.rect
    if not (l + px <= x < r + px and t + py <= y < b + py):
        return HTNOWHERE, None
    cl, ct, cr, cb = w.client
    if cl + px <= x < cr + px and ct + py <= y < cb + py:
        return HTCLIENT, None
    return 0, (f"WM_NCHITTEST at ({x}, {y}) on the frame of {w.hwnd:#x}: Wine tells the border, caption, "
               "menu and scroll bars apart, and neww does not yet")


def window_origin(wine, hwnd):
    """Where a window's (0, 0) — its window rectangle's corner — is on the screen."""
    w = wm(wine).windows[hwnd]
    px, py = screen_origin(wine, w.parent) if w.parent else (0, 0)
    return px + w.rect[0], py + w.rect[1]


def is_visible(wine, hwnd):
    """IsWindowVisible: the window and all its parents have WS_VISIBLE."""
    m = wm(wine)
    w = m.get(hwnd)
    while w is not None:
        if not w.style & WS_VISIBLE:
            return False
        if w.hwnd == m.desktop:
            return True
        w = m.get(w.parent)
    return False


def visible_client(wine, hwnd):
    """The client rectangle on the screen, clipped by every parent's client."""
    m = wm(wine)
    w = m.windows[hwnd]
    ox, oy = screen_origin(wine, hwnd)
    box = (ox, oy, ox + w.client[2] - w.client[0], oy + w.client[3] - w.client[1])
    p = m.windows.get(w.parent)
    while p is not None and p.hwnd != m.desktop:
        px, py = screen_origin(wine, p.hwnd)
        box = gdi16._intersect(box, (px, py, px + p.client[2] - p.client[0], py + p.client[3] - p.client[1]))
        p = m.windows.get(p.parent)
    return gdi16._intersect(box, (0, 0, SCREEN_W, SCREEN_H))


def adjust_window_rect(rect, style, menu, ex):
    """win32u defwnd.c adjust_window_rect at 96 dpi."""
    l, t, r, b = rect
    adjust = 0
    if (ex & (WS_EX_STATICEDGE | WS_EX_DLGMODALFRAME)) == WS_EX_STATICEDGE:
        adjust = 1
    elif (ex & WS_EX_DLGMODALFRAME) or (style & (WS_THICKFRAME | WS_DLGFRAME)):
        adjust = 2
    if style & WS_THICKFRAME:
        adjust += BORDER_WIDTH + PADDED_BORDER
    if (style & (WS_BORDER | WS_DLGFRAME)) or (ex & WS_EX_DLGMODALFRAME):
        adjust += 1
    l, t, r, b = l - adjust, t - adjust, r + adjust, b + adjust
    if (style & WS_CAPTION) == WS_CAPTION:
        t -= (15 if ex & WS_EX_TOOLWINDOW else CAPTION_HEIGHT) + 1
    if menu:
        t -= MENU_HEIGHT + 1
    if ex & WS_EX_CLIENTEDGE:
        l, t, r, b = l - CXEDGE, t - CXEDGE, r + CXEDGE, b + CXEDGE
    return l, t, r, b


def nc_calc_size(wine, w, rect):
    """win32u defwnd.c handle_nc_calc_size: the client rectangle inside rect."""
    if w.style & WS_MINIMIZE:
        return rect[0], rect[1], rect[0], rect[1]
    al, at, ar, ab = adjust_window_rect((0, 0, 0, 0), w.style, False, w.exstyle & ~WS_EX_CLIENTEDGE)
    l, t, r, b = rect[0] - al, rect[1] - at, rect[2] - ar, rect[3] - ab
    if (w.style & (WS_CHILD | WS_POPUP)) != WS_CHILD and w.menu:
        t += MENU_HEIGHT + 1
    if w.exstyle & WS_EX_CLIENTEDGE and r - l > 2 * CXEDGE and b - t > 2 * CXEDGE:
        l, t, r, b = l + CXEDGE, t + CXEDGE, r - CXEDGE, b - CXEDGE
    if w.style & WS_VSCROLL and r - l >= SCROLL:
        r -= SCROLL
    if w.style & WS_HSCROLL and b - t > SCROLL:
        b -= SCROLL
    if t > b:
        b = t
    if l > r:
        r = l
    return l, t, r, b


# ------------------------------------------------------------------ sending

def proc_is_def(wine, proc):
    """A window procedure that is DefWindowProc's own gate stub, given out by GetWindowLong for
    a window with no guest procedure."""
    if proc is None:
        return True
    if wine.gate_address is None:
        return False
    stub = wine.gate_address("USER", 107)
    return stub is not None and proc == (stub[0] << 16 | stub[1])


def call_proc(wine, proc, hwnd, msg, wp, lp):
    """Call a 16-bit window procedure: one guest call. Returns (ax, dx)."""
    m = wm(wine)
    w = m.windows.get(hwnd)
    inst = w.inst if w is not None and w.inst else wine.ss
    ss = wine.ss
    return (yield Call(proc >> 16, proc & 0xFFFF, regs={"ds": ss, "es": ss, "ax": inst},
                       words=[hwnd, msg & 0xFFFF, wp & 0xFFFF, (lp >> 16) & 0xFFFF, lp & 0xFFFF]))


def send(wine, hwnd, msg, wp=0, lp=0):
    """SendMessage16 to one window: its procedure, as a guest call, or DefWindowProc."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    wine.trace.append(f"  -> {hwnd:#x} {MESSAGE_NAMES.get(msg, hex(msg))} {wp:#x} {lp:#x}")
    if w.task and w.task != wine.htask:
        yield (f"SendMessage {MESSAGE_NAMES.get(msg, hex(msg))} to {hwnd:#x}, a window of task {w.task:#x}: "
               "Wine delivers it in that task's thread, and neww does not switch tasks for a sent message yet")
        return 0
    if proc_is_def(wine, w.proc):
        result = yield from def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    from .user_controls import host_index, call_host
    index = host_index(wine, w.proc)
    if index is not None:
        # A thunk of Wine's own procedure: CallWindowProc16 calls it without 16-bit code.
        result = yield from call_host(wine, index, hwnd, msg, wp, lp)
        return result
    ax, dx = yield from call_proc(wine, w.proc, hwnd, msg, wp, lp)
    return ax | dx << 16


WH_CBT_INDEX = 5 + 1  # WH_CBT - WH_MINHOOK
HCBT_ACTIVATE, HCBT_CREATEWND = 5, 3


def call_hook(wine, index, code, wp, lp):
    """user.exe16 hook.c call_hook_16: the task's 16-bit hook procedure, Pascal
    (code, wParam, lParam), DS = ES = SS as WOWCallback16Ex leaves them. Only the low word of
    the result counts. Returns None when no hook of that kind is set."""
    hook = wine.hooks.get(index)
    if hook is None:
        return None
    proc = hook[1]
    wine.trace.append(f"  hook {index - 1} code {code} {wp:#x} {lp:#x}")
    ax, _dx = yield Call(proc >> 16, proc & 0xFFFF, regs={"ds": wine.ss, "es": wine.ss},
                         words=[code & 0xFFFF, wp & 0xFFFF, (lp >> 16) & 0xFFFF, lp & 0xFFFF])
    return ax


MESSAGE_NAMES = {v: k for k, v in globals().items() if k.startswith("WM_") and isinstance(v, int)}


def lresult(value):
    value &= 0xFFFFFFFF
    return value


# ------------------------------------------------------------------ DefWindowProc

def def_window_proc(wine, hwnd, msg, wp, lp):
    """win32u defwnd.c default_window_proc for the messages neww's windows get. The 16-bit
    message is read as WINPROC_CallProc16To32A converts it. Unlisted messages return 0, as the
    switch's default does for messages with no default action."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    if msg == WM_NCCREATE:
        if lp:
            cs = gdi16.read(wine, lp, 34)
            name_ptr = struct.unpack_from("<I", cs, 22)[0]
            w.text = string_at(wine, name_ptr)
            return 1
        return 0
    if msg == WM_NCDESTROY:
        w.text = None
        return 0
    if msg == WM_NCHITTEST:
        x, y = signed(lp & 0xFFFF), signed(lp >> 16 & 0xFFFF)
        hit, why = nc_hit_test(wine, w, x, y)
        if why:
            yield why
        return hit
    if msg == WM_NCCALCSIZE:
        if lp:
            if wp:
                r = read_rect(wine, lp)
                write_rect(wine, lp, nc_calc_size(wine, w, r))
            else:
                write_rect(wine, lp, nc_calc_size(wine, w, read_rect(wine, lp)))
        return 0
    if msg == WM_WINDOWPOSCHANGING:
        pos = list(struct.unpack("<HHhhhhH", gdi16.read(wine, lp, 14)))
        if pos[6] & SWP_NOSIZE:
            return 0
        if (w.style & WS_THICKFRAME) or not (w.style & (WS_POPUP | WS_CHILD)):
            info = yield from min_max_info(wine, hwnd)
            if isinstance(info, str):
                yield info
            pos[4] = min(pos[4], info[8])
            pos[5] = min(pos[5], info[9])
            if not w.style & WS_MINIMIZE:
                pos[4] = max(pos[4], info[6])
                pos[5] = max(pos[5], info[7])
            gdi16.write(wine, lp, struct.pack("<HHhhhhH", *pos))
        return 0
    if msg == WM_WINDOWPOSCHANGED:
        flags = struct.unpack_from("<H", gdi16.read(wine, lp, 14), 12)[0]
        c = w.client
        if not flags & SWP_NOCLIENTMOVE:
            yield from send(wine, hwnd, WM_MOVE, 0, (c[0] & 0xFFFF) | (c[1] & 0xFFFF) << 16)
        if not flags & SWP_NOCLIENTSIZE or flags & SWP_STATECHANGED:
            if w.style & WS_MINIMIZE:
                yield from send(wine, hwnd, WM_SIZE, 1, 0)
            else:
                yield from send(wine, hwnd, WM_SIZE, 2 if w.style & WS_MAXIMIZE else 0,
                                ((c[2] - c[0]) & 0xFFFF) | ((c[3] - c[1]) & 0xFFFF) << 16)
        return 0
    if msg in (WM_PAINT, WM_PAINTICON):
        ps = scratch_mark(wine)
        ptr = scratch(wine, bytes(32))
        hdc = yield from begin_paint(wine, hwnd, ptr)
        if hdc:
            end_paint(wine, hwnd, ptr)
        scratch_release(wine, ps)
        return 0
    if msg == WM_NCPAINT:
        draw_frame(wine, w)
        return 0
    if msg == WM_NCACTIVATE:
        if w.style & WS_MINIMIZE:
            return 1
        draw_frame(wine, w, active=bool(wp))
        return 1
    if msg in (WM_ERASEBKGND, WM_ICONERASEBKGND):
        brush = w.cls.brush if w.cls else 0
        if not brush:
            return 0
        dc = gdi16.gdi(wine).get(wp, gdi16.OBJ_DC)
        if dc is None:
            return 0
        img, (ox, oy) = gdi16.surface(wine, dc)
        l, t, r, b = gdi16.clip_box(wine, dc)
        rect = (l - ox + dc.wnd_org[0] - dc.vp_org[0], t - oy + dc.wnd_org[1] - dc.vp_org[1],
                r - ox + dc.wnd_org[0] - dc.vp_org[0], b - oy + dc.wnd_org[1] - dc.vp_org[1])
        gdi16.fill(wine, dc, rect, brush)
        return 1
    if msg == WM_SETTEXT:
        w.text = string_at(wine, lp)
        if (w.style & WS_CAPTION) == WS_CAPTION:
            draw_frame(wine, w, active=hwnd == m.active)
        return 1
    if msg == WM_GETTEXTLENGTH:
        return len((w.text or "").encode("cp1252", "replace"))
    if msg == WM_GETTEXT:
        if not wp:
            return 0
        data = (w.text or "").encode("cp1252", "replace")[:wp - 1]
        gdi16.write(wine, lp, data + b"\x00")
        return len(data)
    if msg == WM_CLOSE:
        yield from destroy_window(wine, hwnd)
        return 0
    if msg == WM_ACTIVATE:
        if wp & 0xFFFF and not w.style & WS_MINIMIZE:
            yield from set_focus(wine, hwnd)
        return 0
    if msg == WM_MOUSEACTIVATE:
        if w.style & WS_CHILD:
            r = yield from send(wine, w.parent, WM_MOUSEACTIVATE, wp, lp)
            if r:
                return r
        return 1
    if msg == WM_SETREDRAW:
        if wp:
            w.style |= WS_VISIBLE
        else:
            w.style &= ~WS_VISIBLE
        return 0
    if msg == WM_SETCURSOR:
        if w.style & WS_CHILD and w.parent != m.desktop:
            r = yield from send(wine, w.parent, WM_SETCURSOR, wp, lp)
            if r:
                return 1
        return 0
    if msg == WM_CTLCOLOR:
        # The 16-bit WM_CTLCOLOR: the DC in wParam, the type in HIWORD(lParam). Wine's
        # DEFWND_ControlColor: CTLCOLOR_SCROLLBAR gets its own colors, the rest the window's.
        dc = gdi16.gdi(wine).get(wp, gdi16.OBJ_DC)
        kind = lp >> 16
        if dc is not None:
            if kind == 5:  # CTLCOLOR_SCROLLBAR
                dc.bk_color = 0xFFFFFF
                return 0, 0, "DefWindowProc WM_CTLCOLOR scrollbar: Wine makes a dithered brush, neww has none"
            text = 8 if kind != 6 else 18  # COLOR_WINDOWTEXT, COLOR_BTNTEXT
            back = 5 if kind not in (4, 6) else 15  # COLOR_WINDOW, COLOR_BTNFACE
            dc.text_color = _colorref(gdi16.SYS_COLORS[text])
            dc.bk_color = _colorref(gdi16.SYS_COLORS[back])
            return sys_color_brush(wine, back)
        return 0
    if msg in (WM_QUERYOPEN, WM_QUERYENDSESSION):
        return 1
    if msg == WM_SHOWWINDOW:
        return 0
    if msg == WM_GETMINMAXINFO:
        return 0
    if msg == WM_SYNCPAINT:
        return 0
    if msg == WM_SETFONT or msg == WM_GETFONT:
        return 0
    return 0


def _colorref(c):
    return c[0] | c[1] << 8 | c[2] << 16


def sys_color_brush(wine, index):
    """GetSysColorBrush: one solid brush per system color, made once, never deleted."""
    m = wm(wine)
    brushes = getattr(m, "sys_brushes", None)
    if brushes is None:
        brushes = m.sys_brushes = {}
    if index not in brushes:
        g = gdi16.gdi(wine)
        obj = gdi16.GdiObject(gdi16.OBJ_BRUSH, style=gdi16.BS_SOLID, color=_colorref(gdi16.SYS_COLORS[index]), hatch=0)
        obj.stock = True
        brushes[index] = g.add(obj)
    return brushes[index]


def draw_frame(wine, w, active=None):
    """The non-client area: Wine's NC_DoNCPaint draws the frame, caption and menu bar. neww
    fills the frame with COLOR_ACTIVEBORDER (or the window frame color for a thin border), the
    caption with COLOR_ACTIVECAPTION or COLOR_INACTIVECAPTION and the title in COLOR_CAPTIONTEXT,
    and the menu bar with COLOR_MENU. Wine's gradient, buttons, icon and edges are not drawn."""
    from PIL import ImageDraw
    m = wm(wine)
    if not is_visible(wine, w.hwnd):
        return
    if active is None:
        active = w.hwnd == m.active
    g = gdi16.gdi(wine)
    ox, oy = window_origin(wine, w.hwnd)
    l, t, r, b = 0, 0, w.rect[2] - w.rect[0], w.rect[3] - w.rect[1]
    cx, cy = screen_origin(wine, w.hwnd)
    cl = (cx, cy, cx + w.client[2] - w.client[0], cy + w.client[3] - w.client[1])
    draw = ImageDraw.Draw(g.screen)
    outer = (ox + l, oy + t, ox + r - 1, oy + b - 1)
    if outer[2] < outer[0] or outer[3] < outer[1]:
        return
    if (w.style & WS_CHILD) and not w.style & (WS_BORDER | WS_DLGFRAME | WS_THICKFRAME | WS_CAPTION) \
            and not w.exstyle & (WS_EX_CLIENTEDGE | WS_EX_STATICEDGE | WS_EX_DLGMODALFRAME):
        return
    frame = gdi16.SYS_COLORS[10 if active else 11]
    # Paint the whole non-client ring, then put the client back as it was.
    keep = g.screen.crop(cl) if cl[2] > cl[0] and cl[3] > cl[1] else None
    draw.rectangle(outer, fill=frame)
    if w.style & (WS_BORDER | WS_DLGFRAME) or not w.style & (WS_CHILD | WS_POPUP):
        draw.rectangle(outer, outline=gdi16.SYS_COLORS[6])
    if (w.style & WS_CAPTION) == WS_CAPTION:
        adjust = adjust_window_rect((0, 0, 0, 0), w.style & ~WS_CAPTION | WS_BORDER, False, w.exstyle & ~WS_EX_CLIENTEDGE)
        top = oy - adjust[1]
        bar = (ox - adjust[0], top, ox + r - 1 + adjust[2], top + CAPTION_HEIGHT - 1)
        draw.rectangle(bar, fill=gdi16.SYS_COLORS[2 if active else 3])
        if w.text:
            dc_text(wine, (bar[0] + 4, bar[1] + 2), w.text, gdi16.SYS_COLORS[9 if active else 19], bold=True)
        if w.menu:
            mtop = top + CAPTION_HEIGHT + 1
            draw.rectangle((bar[0], mtop, bar[2], mtop + MENU_HEIGHT - 1), fill=gdi16.SYS_COLORS[4])
            draw_menu_bar(wine, w, bar[0], mtop)
    if keep is not None:
        g.screen.paste(keep, cl[:2])


def dc_text(wine, xy, text, color, bold=False, font=None):
    g = gdi16.gdi(wine)
    log = gdi16._logfont(-11, 0, 700 if bold else 400, 0, 0x22, "MS Shell Dlg")
    pil = g.font_for(log)[0] if font is None else font
    from PIL import ImageDraw
    ImageDraw.Draw(g.screen).text(xy, text, font=pil, fill=color)


def draw_menu_bar(wine, w, x, y):
    from .user_res import menu_items
    items = menu_items(wine, w.menu)
    cx = x + 6
    for item in items or []:
        text = (item.get("text") or "").replace("&", "")
        if not text:
            continue
        dc_text(wine, (cx, y + 2), text.split("\t")[0], gdi16.SYS_COLORS[7])
        cx += gdi16.gdi(wine).font_for(gdi16._logfont(-11, 0, 400, 0, 0x22, "MS Shell Dlg"))[0].getlength(text) + 14


# ------------------------------------------------------------------ min/max

def min_max_info(wine, hwnd):
    """win32u window.c get_min_max_info: the defaults, then WM_GETMINMAXINFO with a MINMAXINFO16.
    Returns the ten shorts: reserved, max size, max position, min track, max track."""
    m = wm(wine)
    w = m.windows[hwnd]
    style, ex = w.style, w.exstyle
    adjusted = style & ~WS_BORDER if (style & WS_CAPTION) == WS_CAPTION else style
    parent = m.windows.get(w.parent) or m.windows[m.desktop]
    pc = (0, 0, parent.client[2] - parent.client[0], parent.client[3] - parent.client[1])
    rc = adjust_window_rect(pc, adjusted, (style & WS_POPUP) and w.menu, ex)
    xinc, yinc = -rc[0], -rc[1]
    max_size = (rc[2] - rc[0], rc[3] - rc[1])
    if style & (WS_DLGFRAME | WS_BORDER) and not ex & WS_EX_TOOLWINDOW:
        min_track = None  # SM_CXMINTRACK, SM_CYMINTRACK
    else:
        min_track = (2 * xinc, 2 * yinc)
    max_pos = (-xinc, -yinc)
    wx, wy = window_origin(wine, hwnd)
    cx_min = min_track[0] if min_track else CX_MIN_WITHOUT_FONT
    cy_min = min_track[1] if min_track else CY_MIN
    values = [wx, wy, max_size[0], max_size[1], max_pos[0], max_pos[1], cx_min, cy_min, MAX_TRACK[0], MAX_TRACK[1]]
    mark = scratch_mark(wine)
    ptr = scratch(wine, struct.pack("<10h", *values))
    yield from send(wine, hwnd, WM_GETMINMAXINFO, 0, ptr)
    out = list(struct.unpack("<10h", gdi16.read(wine, ptr, 20)))
    scratch_release(wine, mark)
    if min_track is None and out[6] == CX_MIN_WITHOUT_FONT:
        # The app left SM_CXMINTRACK as it was. Its true value is CX_MIN_WITHOUT_FONT plus four
        # caption-font widths, which only matters for a window narrower than that.
        out[6] = None
    return out


def clamp_track(info, cx, cy):
    """cx, cy kept within the track sizes. Returns (cx, cy) or a stop when the unknown
    SM_CXMINTRACK could change the answer."""
    cx = min(cx, info[8])
    cy = min(cy, info[9])
    if info[6] is None:
        if cx < CX_MIN_WITHOUT_FONT + 4 * 16:
            return f"window width {cx} is under SM_CXMINTRACK, which needs the caption font's average width, and neww has no Wine font"
    else:
        cx = max(cx, info[6])
    cy = max(cy, info[7])
    return cx, cy


# ------------------------------------------------------------------ classes

def exe_ptr(wine, inst):
    return wine._exe_ptr(inst) if inst else 0


def user_module(wine):
    return wine.system_modules.get("USER", -1)


def find_class(wine, name, inst):
    """class.c find_class: the module's own class, then a global one. name is a str or an atom."""
    m = wm(wine)
    module = exe_ptr(wine, inst) if inst != user_module(wine) else 0
    atom = name if isinstance(name, int) else wine.messages.get(name.lower())
    if not atom:
        from .user_controls import builtin_class
        return builtin_class(wine, name)
    for cls in m.classes:
        if cls.atom == atom and cls.module == module and module:
            return cls
    for cls in m.classes:
        if cls.atom == atom and cls.style & CS_GLOBALCLASS and not getattr(cls, "builtin", False):
            return cls
    # The system classes come last: Wine's built-in controls.
    from .user_controls import builtin_class
    return builtin_class(wine, name)


def class_name_arg(wine, ptr):
    """A class name argument: an atom when the selector is 0, else the string."""
    if not ptr >> 16:
        return ptr & 0xFFFF
    return string_at(wine, ptr)


def register(wine, data, ex):
    """RegisterClassEx16 from a WNDCLASS16 or WNDCLASSEX16."""
    m = wm(wine)
    if ex:
        (_size, style, proc, cls_extra, wnd_extra, inst, icon, cursor, brush, menu, name,
         icon_sm) = struct.unpack("<IHIhhHHHHIIH", data[:32])
    else:
        style, proc, cls_extra, wnd_extra, inst, icon, cursor, brush, menu, name = struct.unpack("<HIhhHHHHII", data[:26])
        icon_sm = 0
    module = exe_ptr(wine, inst) or wine.modules.get(wine.exe_name, 0)
    cname = class_name_arg(wine, name)
    if cname is None or cname == "":
        return 0
    if isinstance(cname, str):
        if cname.lower() in SYSTEM_CLASSES:
            # A task's own class may have a system class's name: its module is the task's.
            pass
        atom = wine.add_atom(cname)
    else:
        atom = cname
        cname = next((k for k, v in wine.atom_names.items() if v == atom), f"#{atom}")
    for cls in m.classes:
        if cls.atom == atom and cls.module == module:
            # ERROR_CLASS_ALREADY_EXISTS
            return 0
    if cls_extra < 0 or wnd_extra < 0 or cls_extra > 40 or wnd_extra > 40:
        # Wine warns and clamps negatives to 0; Win16 limits the extra bytes to 40.
        cls_extra, wnd_extra = max(0, min(cls_extra, 40)), max(0, min(wnd_extra, 40))
    cls = WndClass(atom, cname, module, style, proc, cls_extra, wnd_extra, inst, icon, cursor, brush, menu, icon_sm)
    m.classes.append(cls)
    wine.trace[-1] += f" {cname!r} -> {atom:#x}"
    return atom


@api("USER", "RegisterClass")
def register_class(wine, arg, ptr):
    """window.c RegisterClass16: RegisterClassEx16 with hIconSm 0."""
    return register(wine, gdi16.read(wine, ptr, 26), False)


@api("USER", "RegisterClassEx")
def register_class_ex(wine, arg, ptr):
    return register(wine, gdi16.read(wine, ptr, 32), True)


def _class_info(wine, inst, name_ptr):
    name = class_name_arg(wine, name_ptr)
    if name is None:
        return None, None
    cls = find_class(wine, name, inst)
    if cls is None and isinstance(name, str) and name.lower() in SYSTEM_CLASSES:
        return None, f"GetClassInfo({name!r}): a Wine system class, and neww has no built-in {name.upper()} control"
    return cls, None


@api("USER", "GetClassInfo")
def get_class_info(wine, arg, inst, name_ptr, ptr):
    """window.c GetClassInfo16 through GetClassInfoEx16. lpszClassName is 0, as Wine leaves it."""
    cls, why = _class_info(wine, inst, name_ptr)
    if why:
        return 0, 0, f"USER.404 {why}"
    if cls is None:
        return 0
    gdi16.write(wine, ptr, struct.pack("<HIhhHHHHII", cls.style, cls.proc or 0, cls.cls_extra, cls.wnd_extra,
                                       cls.inst, cls.icon, cls.cursor, cls.brush, cls.menu, 0))
    return 1


@api("USER", "GetClassInfoEx")
def get_class_info_ex(wine, arg, inst, name_ptr, ptr):
    cls, why = _class_info(wine, inst, name_ptr)
    if why:
        return 0, 0, f"USER.398 {why}"
    if cls is None:
        return 0
    gdi16.write(wine, ptr + 4, struct.pack("<HIhhHHHHIIH", cls.style, cls.proc or 0, cls.cls_extra, cls.wnd_extra,
                                           cls.inst, cls.icon, cls.cursor, cls.brush, cls.menu, 0, cls.icon_sm))
    return 1


@api("USER", "UnregisterClass")
def unregister_class(wine, arg, name_ptr, inst):
    m = wm(wine)
    name = class_name_arg(wine, name_ptr)
    cls = find_class(wine, name, inst) if name is not None else None
    if cls is None:
        return 0
    if any(w.cls is cls and not w.destroyed for w in m.windows.values()):
        return 0
    m.classes.remove(cls)
    return 1


@api("USER", "GetClassName")
def get_class_name(wine, arg, hwnd, ptr, count):
    w = wm(wine).get(hwnd)
    if w is None or count <= 0:
        return 0
    name = (w.cls.name if w.cls else "#32769").encode("cp1252", "replace")[:count - 1]
    gdi16.write(wine, ptr, name + b"\x00")
    return len(name)


# Class and window long/word offsets.
GCL_MENUNAME, GCW_HBRBACKGROUND, GCW_HCURSOR, GCW_HICON, GCW_HMODULE = -8, -10, -12, -14, -16
GCW_CBWNDEXTRA, GCW_CBCLSEXTRA, GCL_WNDPROC, GCW_STYLE, GCW_ATOM, GCW_HICONSM = -18, -20, -24, -26, -32, -34
GWL_WNDPROC, GWW_HINSTANCE, GWW_HWNDPARENT, GWL_STYLE, GWL_EXSTYLE, GWW_ID = -4, -6, -8, -16, -20, -12


def _class_field(wine, cls, index, size):
    if index >= 0:
        if index + size > len(cls.extra):
            return None
        return int.from_bytes(cls.extra[index:index + size], "little")
    return {GCL_MENUNAME: cls.menu, GCW_HBRBACKGROUND: cls.brush, GCW_HCURSOR: cls.cursor, GCW_HICON: cls.icon,
            GCW_HMODULE: cls.module, GCW_CBWNDEXTRA: cls.wnd_extra, GCW_CBCLSEXTRA: cls.cls_extra,
            GCL_WNDPROC: cls.proc or 0, GCW_STYLE: cls.style, GCW_ATOM: cls.atom, GCW_HICONSM: cls.icon_sm}.get(index)


@api("USER", "GetClassWord")
def get_class_word(wine, arg, hwnd, index):
    w = wm(wine).get(hwnd)
    if w is None or w.cls is None:
        return 0
    v = _class_field(wine, w.cls, index, 2)
    return (v or 0) & 0xFFFF


@api("USER", "GetClassLong")
def get_class_long(wine, arg, hwnd, index):
    w = wm(wine).get(hwnd)
    if w is None or w.cls is None:
        return 0
    v = _class_field(wine, w.cls, index, 4)
    return v or 0


def _set_class(wine, hwnd, index, value, size):
    w = wm(wine).get(hwnd)
    if w is None or w.cls is None:
        return 0
    cls = w.cls
    if index >= 0:
        if index + size > len(cls.extra):
            return 0
        old = int.from_bytes(cls.extra[index:index + size], "little")
        cls.extra[index:index + size] = (value & ((1 << 8 * size) - 1)).to_bytes(size, "little")
        return old
    attr = {GCL_MENUNAME: "menu", GCW_HBRBACKGROUND: "brush", GCW_HCURSOR: "cursor", GCW_HICON: "icon",
            GCW_STYLE: "style", GCL_WNDPROC: "proc", GCW_HICONSM: "icon_sm", GCW_CBWNDEXTRA: "wnd_extra"}.get(index)
    if attr is None:
        return 0
    old = getattr(cls, attr) or 0
    setattr(cls, attr, value)
    return old


@api("USER", "SetClassWord")
def set_class_word(wine, arg, hwnd, index, value):
    return _set_class(wine, hwnd, index, value, 2) & 0xFFFF


@api("USER", "SetClassLong")
def set_class_long(wine, arg, hwnd, index, value):
    return _set_class(wine, hwnd, index, value, 4)


# ------------------------------------------------------------------ window longs

def def_proc_stub(wine):
    stub = wine.gate_address("USER", 107) if wine.gate_address else None
    return stub[0] << 16 | stub[1] if stub else 0


def _window_field(wine, w, index, size):
    m = wm(wine)
    if index >= 0:
        if index + size > len(w.extra):
            return None
        return int.from_bytes(w.extra[index:index + size], "little")
    if index == GWL_WNDPROC:
        return w.proc if w.proc is not None else def_proc_stub(wine)
    if index == GWW_HINSTANCE:
        return w.inst
    if index == GWW_HWNDPARENT:
        if w.style & WS_CHILD:
            return w.parent
        return w.owner
    if index == GWL_STYLE:
        return w.style
    if index == GWL_EXSTYLE:
        return w.exstyle
    if index == GWW_ID:
        return w.id
    return None


@api("USER", "GetWindowWord")
def get_window_word(wine, arg, hwnd, index):
    w = wm(wine).get(hwnd)
    if w is None:
        return 0
    v = _window_field(wine, w, index, 2)
    if v is None:
        return 0
    return v & 0xFFFF


@api("USER", "GetWindowLong")
def get_window_long(wine, arg, hwnd, index):
    w = wm(wine).get(hwnd)
    if w is None:
        return 0
    v = _window_field(wine, w, index, 4)
    return v or 0


def fix_exstyle(style, ex):
    """win32u window.c fix_exstyle."""
    if (ex & WS_EX_DLGMODALFRAME) or (not ex & WS_EX_STATICEDGE and style & (WS_DLGFRAME | WS_THICKFRAME)):
        return ex | WS_EX_WINDOWEDGE
    return ex & ~WS_EX_WINDOWEDGE


def _set_style(wine, w, index, value):
    """win32u set_window_long for GWL_STYLE and GWL_EXSTYLE. WM_STYLECHANGING and
    WM_STYLECHANGED are not sent to a 16-bit procedure (user.exe16 message.c drops them in
    WINPROC_CallProc32ATo16), and DefWindowProc does nothing with them, so a guest or default
    procedure sees no message. Wine's own control procedures do get them; neww stops there."""
    from .user_controls import host_index
    m = wm(wine)
    if host_index(wine, w.proc) is not None:
        return 0, f"SetWindowLong({w.hwnd:#x}, {index}) on a Wine control: its procedure gets WM_STYLECHANGING and WM_STYLECHANGED"
    if index == GWL_STYLE:
        old = w.style
        if w.parent == m.desktop:
            value |= WS_CLIPSIBLINGS      # WS_CLIPSIBLINGS can't be reset on top-level windows
        if old & WS_MINIMIZE:
            value |= WS_MINIMIZE          # WS_MINIMIZE can't be reset
        if (old ^ value) & WS_VISIBLE:
            return 0, (f"SetWindowLong({w.hwnd:#x}, GWL_STYLE) changes WS_VISIBLE: Wine invalidates the "
                       "window's DCs and updates its state, which neww does not yet")
        w.style = value
        w.exstyle = fix_exstyle(w.style, w.exstyle)
        return old, None
    old = w.exstyle
    w.exstyle = fix_exstyle(w.style, (value & ~WS_EX_TOPMOST) | (old & WS_EX_TOPMOST))
    return old, None


def _set_window(wine, hwnd, index, value, size):
    """SetWindowLong16 / SetWindowWord16, as win32u set_window_long."""
    w = wm(wine).get(hwnd)
    if w is None:
        return 0, None
    if index >= 0:
        if index + size > len(w.extra):
            return 0, None
        old = int.from_bytes(w.extra[index:index + size], "little")
        w.extra[index:index + size] = (value & ((1 << 8 * size) - 1)).to_bytes(size, "little")
        return old, None
    if index == GWL_WNDPROC:
        old = w.proc if w.proc is not None else def_proc_stub(wine)
        w.proc = None if proc_is_def(wine, value) else value
        return old, None
    if index == GWW_HINSTANCE:
        old, w.inst = w.inst, value & 0xFFFF
        return old, None
    if index == GWW_ID:
        old, w.id = w.id, value & 0xFFFF
        return old, None
    if index in (GWL_STYLE, GWL_EXSTYLE):
        return _set_style(wine, w, index, value & 0xFFFFFFFF)
    if index == GWW_HWNDPARENT:
        return 0, f"SetWindowWord({hwnd:#x}, GWW_HWNDPARENT): Wine changes the owner or the parent"
    return 0, None


@api("USER", "SetWindowWord")
def set_window_word(wine, arg, hwnd, index, value):
    old, why = _set_window(wine, hwnd, index, value, 2)
    return (0, 0, f"USER.134 {why}") if why else old & 0xFFFF


@api("USER", "SetWindowLong")
def set_window_long(wine, arg, hwnd, index, value):
    old, why = _set_window(wine, hwnd, index, value, 4)
    return (0, 0, f"USER.136 {why}") if why else old


# ------------------------------------------------------------------ creating

def create_window(wine, ex, cls_ptr, name_ptr, style, x, y, cx, cy, parent, menu, inst, data):
    """window.c CreateWindowEx16 -> win32u NtUserCreateWindowEx. Returns the HWND16."""
    m = wm(wine)
    cname = class_name_arg(wine, cls_ptr)
    if cname is None:
        return 0
    cls = find_class(wine, cname, inst)
    if cls is None:
        if isinstance(cname, str) and cname.lower() in SYSTEM_CLASSES:
            yield f"CreateWindow class {cname!r}: a Wine system class, and neww has no built-in {cname.upper()} control"
        wine.trace[-1] += f" class {cname!r} not found"
        return 0
    # Menu from the class, CreateWindowEx16 does it before create_window16.
    if not menu and (style & (WS_CHILD | WS_POPUP)) != WS_CHILD and cls.menu:
        from .user_res import load_menu
        menu, why = load_menu(wine, exe_ptr(wine, inst), cls.menu)
        if why:
            yield why
    owner = 0
    if parent:
        if m.get(parent) is None:
            return 0
        if (style & (WS_CHILD | WS_POPUP)) != WS_CHILD:
            owner, parent = parent, m.desktop
    else:
        if (style & (WS_CHILD | WS_POPUP)) == WS_CHILD:
            return 0
        parent = m.desktop
    # fix_cs_coordinates
    sw = 1  # SW_SHOW
    if style & (WS_CHILD | WS_POPUP):
        if x == CW_USEDEFAULT16:
            x = y = 0
        if cx == CW_USEDEFAULT16:
            cx = cy = 0
    elif x == CW_USEDEFAULT16 or cx == CW_USEDEFAULT16 or cy == CW_USEDEFAULT16:
        if x == CW_USEDEFAULT16:
            if y != CW_USEDEFAULT16:
                sw = y
            x, y = WORK[0], WORK[1]
        if cx == CW_USEDEFAULT16:
            cx = (WORK[2] - WORK[0]) * 3 // 4 - x
            cy = (WORK[3] - WORK[1]) * 3 // 4 - y
        elif cy == CW_USEDEFAULT16:
            cy = (WORK[3] - WORK[1]) * 3 // 4 - y
    if (ex & WS_EX_DLGMODALFRAME) or (not ex & WS_EX_STATICEDGE and style & (WS_DLGFRAME | WS_THICKFRAME)):
        ex |= WS_EX_WINDOWEDGE
    else:
        ex &= ~WS_EX_WINDOWEDGE
    hwnd = m._handle()
    w = Window(hwnd, cls, parent, owner)
    w.task = wine.htask
    w.inst = inst
    w.style = style & ~WS_VISIBLE
    w.exstyle = ex
    m.windows[hwnd] = w
    m.children.setdefault(parent, [])
    m.children.setdefault(hwnd, [])
    # Children go to the bottom of the z order, top-level windows to the top.
    if w.style & WS_CHILD:
        m.children[parent].append(hwnd)
    else:
        m.children[parent].insert(0, hwnd)
    if w.style & WS_SYSMENU:
        w.sysmenu = 0
    if WH_CBT_INDEX in wine.hooks:
        # win32u create_window: WH_CBT HCBT_CREATEWND before the styles are corrected.
        # hook.c call_WH_CBT passes a CBT_CREATEWND16 {lpcs, hwndInsertAfter = HWND_TOP}
        # and a CREATESTRUCT16 with MapLS copies of the name and class strings.
        mark = scratch_mark(wine)
        name = string_at(wine, name_ptr)
        name16 = scratch(wine, name.encode("cp1252", "replace") + b"\x00") if name is not None else (
            name_ptr if name_ptr and not name_ptr >> 16 else 0)
        class16 = scratch(wine, cls.name.encode("cp1252", "replace") + b"\x00")
        cs16 = scratch(wine, struct.pack("<IHHHhhhhIIII", data, inst, menu,
                                         owner or (parent if parent != m.desktop else 0), cy, cx, y, x,
                                         style, name16, class16, ex))
        cbt = scratch(wine, struct.pack("<IH", cs16, 0))
        refused = yield from call_hook(wine, WH_CBT_INDEX, HCBT_CREATEWND, hwnd, cbt)
        scratch_release(wine, mark)
        if refused:
            # free_window_handle: gone without a message.
            wine.trace.append(f"  {hwnd:#x}: refused by the WH_CBT hook")
            m.children[parent].remove(hwnd)
            del m.windows[hwnd]
            return 0
    if (w.style & (WS_CHILD | WS_POPUP)) != WS_CHILD:
        w.style |= WS_CLIPSIBLINGS
        if not w.style & WS_POPUP:
            w.style |= WS_CAPTION
    if (w.style & (WS_DLGFRAME | WS_THICKFRAME)) and not w.style & (WS_CHILD | WS_POPUP):
        w.exstyle |= WS_EX_WINDOWEDGE
    if not w.style & (WS_CHILD | WS_POPUP):
        w.need_size = True
    if (w.style & (WS_CHILD | WS_POPUP)) != WS_CHILD:
        w.menu = menu
    else:
        w.id = menu
    wine.trace[-1] += f" {cls.name!r} -> {hwnd:#x}"
    mark = scratch_mark(wine)
    if (style & WS_THICKFRAME) or not (style & (WS_POPUP | WS_CHILD)):
        info = yield from min_max_info(wine, hwnd)
        got = clamp_track(info, cx, cy)
        if isinstance(got, str):
            yield f"CreateWindow {cls.name!r}: {got}"
        cx, cy = got
    cx, cy = max(cx, 0), max(cy, 0)
    w.rect = (x, y, x + cx, y + cy)
    w.client = w.rect
    # WM_NCCREATE with a CREATESTRUCT16.
    class_text = scratch(wine, cls.name.encode("cp1252", "replace") + b"\x00")
    cs = scratch(wine, struct.pack("<IHHHhhhhIIII", data, inst, menu if (style & (WS_CHILD | WS_POPUP)) != WS_CHILD else menu,
                                   owner or (parent if parent != m.desktop else 0), cy, cx, y, x, style,
                                   name_ptr, class_text, ex))
    ok = yield from send(wine, hwnd, WM_NCCREATE, 0, cs)
    if not ok:
        wine.trace.append(f"  {hwnd:#x}: aborted by WM_NCCREATE")
        yield from destroy_window(wine, hwnd)
        scratch_release(wine, mark)
        return 0
    if m.get(hwnd) is None:
        scratch_release(wine, mark)
        return 0
    # WM_NCCALCSIZE with the window rectangle in screen coordinates.
    px, py = screen_origin(wine, parent)
    r = w.rect
    rp = scratch(wine, struct.pack("<hhhh", r[0] + px, r[1] + py, r[2] + px, r[3] + py))
    yield from send(wine, hwnd, WM_NCCALCSIZE, 0, rp)
    c = read_rect(wine, rp)
    w.client = (c[0] - px, c[1] - py, c[2] - px, c[3] - py)
    # WM_CREATE: -1 destroys the window.
    result = yield from send(wine, hwnd, WM_CREATE, 0, cs)
    if (result & 0xFFFFFFFF) == 0xFFFFFFFF:
        yield from destroy_window(wine, hwnd)
        scratch_release(wine, mark)
        return 0
    if m.get(hwnd) is None:
        scratch_release(wine, mark)
        return 0
    if not w.need_size:
        c = w.client
        yield from send(wine, hwnd, WM_SIZE, 0, ((c[2] - c[0]) & 0xFFFF) | ((c[3] - c[1]) & 0xFFFF) << 16)
        yield from send(wine, hwnd, WM_MOVE, 0, (c[0] & 0xFFFF) | (c[1] & 0xFFFF) << 16)
    if w.style & (WS_MINIMIZE | WS_MAXIMIZE):
        yield f"CreateWindow {cls.name!r} with WS_MINIMIZE or WS_MAXIMIZE: window_min_maximize is not in neww yet"
    # send_parent_notify
    if w.style & WS_CHILD and not w.exstyle & WS_EX_NOPARENTNOTIFY:
        yield from send(wine, parent, WM_PARENTNOTIFY, WM_CREATE, hwnd | w.id << 16)
    if m.get(hwnd) is None:
        scratch_release(wine, mark)
        return 0
    scratch_release(wine, mark)
    if style & WS_VISIBLE:
        if style & WS_MAXIMIZE:
            sw = 1
        elif style & WS_MINIMIZE:
            sw = 2
        yield from show_window(wine, hwnd, sw)
    return hwnd


@api("USER", "CreateWindow")
def create_window16(wine, arg, cls, name, style, x, y, cx, cy, parent, menu, inst, data):
    return create_window(wine, 0, cls, name, style, x, y, cx, cy, parent, menu, inst, data)


@api("USER", "CreateWindowEx")
def create_window_ex16(wine, arg, ex, cls, name, style, x, y, cx, cy, parent, menu, inst, data):
    return create_window(wine, ex, cls, name, style, x, y, cx, cy, parent, menu, inst, data)


# ------------------------------------------------------------------ destroying

def destroy_window(wine, hwnd):
    """win32u NtUserDestroyWindow: hide, WM_DESTROY to the window then its children, WM_NCDESTROY
    the other way round, and the handle freed."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None or hwnd == m.desktop:
        return 0
    if w.style & WS_CHILD and not w.exstyle & WS_EX_NOPARENTNOTIFY:
        yield from send(wine, w.parent, WM_PARENTNOTIFY, WM_DESTROY, hwnd | w.id << 16)
    if w.style & WS_VISIBLE:
        flags = SWP_HIDEWINDOW | SWP_NOACTIVATE | SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER
        if hwnd == m.active or not w.style & WS_CHILD:
            flags &= ~SWP_NOACTIVATE
        yield from set_window_pos(wine, hwnd, 0, 0, 0, 0, 0, flags | (0 if w.style & WS_CHILD else 0))
    if m.get(hwnd) is None:
        return 1
    # Owned windows are destroyed first.
    for other in list(m.windows.values()):
        if other.owner == hwnd and not other.destroyed:
            yield from destroy_window(wine, other.hwnd)
    yield from _send_destroy(wine, hwnd)
    _free(wine, hwnd)
    return 1


def _send_destroy(wine, hwnd):
    m = wm(wine)
    if m.get(hwnd) is None:
        return
    if m.capture == hwnd:
        m.capture = 0
    yield from send(wine, hwnd, WM_DESTROY, 0, 0)
    for child in list(m.children.get(hwnd, [])):
        yield from _send_destroy(wine, child)
    yield from send(wine, hwnd, WM_NCDESTROY, 0, 0)


def _free(wine, hwnd):
    m = wm(wine)
    w = m.windows.get(hwnd)
    if w is None:
        return
    for child in list(m.children.get(hwnd, [])):
        _free(wine, child)
    w.destroyed = True
    siblings = m.children.get(w.parent, [])
    if hwnd in siblings:
        siblings.remove(hwnd)
    q = m.queue_of(w.task)
    for key in [k for k in q.timers if k[0] == hwnd]:
        del q.timers[key]
    q.queue = [e for e in q.queue if e[0] != hwnd]
    if m.focus == hwnd:
        m.focus = 0
    if m.active == hwnd:
        m.active = 0
    del m.windows[hwnd]


@api("USER", "DestroyWindow")
def destroy_window16(wine, arg, hwnd):
    return destroy_window(wine, hwnd)


# ------------------------------------------------------------------ showing and moving

def show_window(wine, hwnd, cmd):
    """win32u window.c show_window. Minimize and maximize stop: window_min_maximize is not
    in neww yet."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    style = w.style
    was_visible = bool(style & WS_VISIBLE)
    show_flag = True
    swp = 0
    if cmd == 0:  # SW_HIDE
        if not was_visible:
            return 0
        show_flag = False
        swp |= SWP_HIDEWINDOW | SWP_NOSIZE | SWP_NOMOVE
        if style & WS_CHILD:
            swp |= SWP_NOACTIVATE | SWP_NOZORDER
    elif cmd in (2, 3, 6, 7, 11):
        yield f"ShowWindow({hwnd:#x}, {cmd}): minimize and maximize (window_min_maximize) are not in neww yet"
    elif cmd == 8:  # SW_SHOWNA
        swp |= SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
        if style & WS_CHILD:
            swp |= SWP_NOZORDER
    elif cmd == 5:  # SW_SHOW
        if was_visible:
            return 1
        swp |= SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
        if style & WS_CHILD:
            swp |= SWP_NOACTIVATE | SWP_NOZORDER
    elif cmd in (4, 9, 1, 10):  # SW_SHOWNOACTIVATE, SW_RESTORE, SW_SHOWNORMAL, SW_SHOWDEFAULT
        if cmd == 4:
            swp |= SWP_NOACTIVATE | SWP_NOZORDER
        if not was_visible:
            swp |= SWP_SHOWWINDOW
        if style & (WS_MINIMIZE | WS_MAXIMIZE):
            yield f"ShowWindow({hwnd:#x}, {cmd}) of a minimized or maximized window: window_min_maximize is not in neww yet"
        if was_visible:
            return 1
        swp |= SWP_NOSIZE | SWP_NOMOVE
        if style & WS_CHILD:
            swp |= SWP_NOACTIVATE | SWP_NOZORDER
    else:
        return 1 if was_visible else 0
    if show_flag != was_visible or cmd == 8:
        yield from send(wine, hwnd, WM_SHOWWINDOW, int(show_flag), 0)
        if m.get(hwnd) is None:
            return int(was_visible)
    parent = w.parent
    if parent and not is_visible(wine, parent):
        if show_flag:
            w.style |= WS_VISIBLE
        else:
            w.style &= ~WS_VISIBLE
    else:
        yield from set_window_pos(wine, hwnd, HWND_TOP, 0, 0, 0, 0, swp)
    if cmd == 0:
        if hwnd == m.active:
            yield from activate_other(wine, hwnd)
        if m.focus == hwnd:
            p = w.parent if w.parent != m.desktop else 0
            yield from set_focus(wine, p)
        return int(was_visible)
    w = m.get(hwnd)
    if w is None:
        return int(was_visible)
    if w.need_size:
        w.need_size = False
        c = w.client
        yield from send(wine, hwnd, WM_SIZE, 0, ((c[2] - c[0]) & 0xFFFF) | ((c[3] - c[1]) & 0xFFFF) << 16)
        yield from send(wine, hwnd, WM_MOVE, 0, (c[0] & 0xFFFF) | (c[1] & 0xFFFF) << 16)
    return int(was_visible)


def activate_other(wine, hwnd):
    """activate_other_window: the next visible, enabled top-level window, or none."""
    m = wm(wine)
    for other in m.children.get(m.desktop, []):
        o = m.get(other)
        if other != hwnd and o is not None and o.style & WS_VISIBLE and not o.style & WS_DISABLED:
            yield from set_active(wine, other)
            return
    yield from set_active(wine, 0)


@api("USER", "ShowWindow")
def show_window16(wine, arg, hwnd, cmd):
    return show_window(wine, hwnd, cmd)


def set_window_pos(wine, hwnd, after, x, y, cx, cy, flags):
    """win32u set_window_pos: WM_WINDOWPOSCHANGING, the new rectangles with WM_NCCALCSIZE,
    activation, the erase of a newly shown window, and WM_WINDOWPOSCHANGED."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    orig = flags
    if not flags & SWP_NOMOVE:
        x, y = max(-32768, min(32767, x)), max(-32768, min(32767, y))
    if not flags & SWP_NOSIZE:
        cx, cy = max(0, min(32767, cx)), max(0, min(32767, cy))
    mark = scratch_mark(wine)
    wp = scratch(wine, struct.pack("<HHhhhhH", hwnd, after & 0xFFFF, x, y, cx, cy, flags))
    if not flags & SWP_NOSENDCHANGING and not ((flags & SWP_AGG_NOCLIENTCHANGE) and (flags & SWP_SHOWWINDOW)):
        yield from send(wine, hwnd, WM_WINDOWPOSCHANGING, 0, wp)
        _h, after, x, y, cx, cy, flags = struct.unpack("<HHhhhhH", gdi16.read(wine, wp, 14))
    if m.get(hwnd) is None:
        scratch_release(wine, mark)
        return 0
    old_rect, old_client = w.rect, w.client
    new_rect = old_rect
    new_client = old_client
    if not flags & SWP_NOSIZE:
        new_rect = (new_rect[0], new_rect[1], new_rect[0] + cx, new_rect[1] + cy)
    if not flags & SWP_NOMOVE:
        dx, dy = x - old_rect[0], y - old_rect[1]
        new_rect = (x, y, new_rect[2] + dx, new_rect[3] + dy)
        new_client = (new_client[0] + dx, new_client[1] + dy, new_client[2] + dx, new_client[3] + dy)
    flags |= SWP_NOCLIENTMOVE | SWP_NOCLIENTSIZE
    # fixup_swp_flags
    if not is_visible(wine, w.parent):
        flags |= SWP_NOREDRAW
    if w.style & WS_VISIBLE:
        flags &= ~SWP_SHOWWINDOW
    else:
        flags &= ~SWP_HIDEWINDOW
        if not flags & SWP_SHOWWINDOW:
            flags |= SWP_NOREDRAW
    if old_rect[2] - old_rect[0] == cx and old_rect[3] - old_rect[1] == cy:
        flags |= SWP_NOSIZE
    if old_rect[0] == x and old_rect[1] == y:
        flags |= SWP_NOMOVE
    if (w.style & (WS_POPUP | WS_CHILD)) != WS_CHILD:
        if not flags & (SWP_NOACTIVATE | SWP_HIDEWINDOW):
            flags &= ~SWP_NOZORDER
            after = HWND_TOP
    siblings = m.children.get(w.parent, [])
    if not flags & SWP_NOZORDER:
        if after == HWND_TOP and siblings and siblings[0] == hwnd:
            flags |= SWP_NOZORDER
        elif after == HWND_BOTTOM and siblings and siblings[-1] == hwnd:
            flags |= SWP_NOZORDER
    # calc_ncsize
    if (flags & (SWP_FRAMECHANGED | SWP_NOSIZE)) != SWP_NOSIZE:
        px, py = 0, 0
        pos = scratch(wine, struct.pack("<HHhhhhH", hwnd, after & 0xFFFF,
                                        old_rect[0] if flags & SWP_NOMOVE else x, old_rect[1] if flags & SWP_NOMOVE else y,
                                        old_rect[2] - old_rect[0] if flags & SWP_NOSIZE else cx,
                                        old_rect[3] - old_rect[1] if flags & SWP_NOSIZE else cy, flags))
        params = scratch(wine, struct.pack("<hhhhhhhhhhhhI", *new_rect, *old_rect, *old_client, pos))
        yield from send(wine, hwnd, WM_NCCALCSIZE, 1, params)
        c = read_rect(wine, params)
        new_client = c
        if c[0] != old_client[0] - px or c[1] != old_client[1] - py:
            flags &= ~SWP_NOCLIENTMOVE
        if c[2] - c[0] != old_client[2] - old_client[0] or c[3] - c[1] != old_client[3] - old_client[1]:
            flags &= ~SWP_NOCLIENTSIZE
    elif not flags & SWP_NOMOVE and (new_client[0] != old_client[0] or new_client[1] != old_client[1]):
        flags &= ~SWP_NOCLIENTMOVE
    if m.get(hwnd) is None:
        scratch_release(wine, mark)
        return 0
    # apply_window_pos
    w.rect, w.client = new_rect, new_client
    if not flags & SWP_NOZORDER and hwnd in siblings:
        siblings.remove(hwnd)
        if after == HWND_BOTTOM:
            siblings.append(hwnd)
        elif after in (HWND_TOP, 0xFFFF, 0xFFFE):
            siblings.insert(0, hwnd)
        elif after in siblings:
            siblings.insert(siblings.index(after) + 1, hwnd)
        else:
            siblings.insert(0, hwnd)
    if flags & SWP_SHOWWINDOW:
        w.style |= WS_VISIBLE
        _invalidate_tree(wine, hwnd, erase=True, frame=True)
    elif flags & SWP_HIDEWINDOW:
        w.style &= ~WS_VISIBLE
        _expose(wine, w)
    elif not flags & SWP_NOREDRAW and (flags & SWP_AGG_STATUSFLAGS) != SWP_AGG_NOPOSCHANGE:
        _invalidate_tree(wine, hwnd, erase=True, frame=True)
        _expose(wine, w)
    if not flags & (SWP_NOACTIVATE | SWP_HIDEWINDOW):
        if (w.style & (WS_CHILD | WS_POPUP)) == WS_CHILD:
            yield from send(wine, hwnd, WM_CHILDACTIVATE, 0, 0)
        elif not w.style & WS_MINIMIZE:
            yield from set_foreground(wine, hwnd)
    if not orig & SWP_DEFERERASE:
        if orig & SWP_HIDEWINDOW or (not orig & SWP_SHOWWINDOW and (flags & SWP_AGG_STATUSFLAGS) != SWP_AGG_NOGEOMETRYCHANGE):
            parent = w.parent if w.parent and w.parent != m.desktop else hwnd
            yield from erase_now(wine, parent)
        if (flags & SWP_AGG_STATUSFLAGS) != SWP_AGG_NOPOSCHANGE and not orig & SWP_AGG_NOCLIENTCHANGE \
                and orig & SWP_SHOWWINDOW:
            yield from erase_now(wine, hwnd)
    if (flags & SWP_AGG_STATUSFLAGS) != SWP_AGG_NOPOSCHANGE and not ((orig & SWP_AGG_NOCLIENTCHANGE) and (orig & SWP_SHOWWINDOW)):
        if m.get(hwnd) is not None:
            gdi16.write(wine, wp, struct.pack("<HHhhhhH", hwnd, after & 0xFFFF, new_rect[0], new_rect[1],
                                              new_rect[2] - new_rect[0], new_rect[3] - new_rect[1], flags))
            yield from send(wine, hwnd, WM_WINDOWPOSCHANGED, 0, wp)
    scratch_release(wine, mark)
    return 1


def _expose(wine, w):
    """What a hidden or moved window uncovered: its parent repaints (neww invalidates the
    parent's whole client), or the desktop is filled with COLOR_BACKGROUND."""
    m = wm(wine)
    if w.parent and w.parent != m.desktop:
        _invalidate_tree(wine, w.parent, erase=True, frame=False)
    else:
        from PIL import ImageDraw
        ox, oy = window_origin(wine, w.hwnd) if w.hwnd in m.windows else (0, 0)


def _invalidate_tree(wine, hwnd, erase, frame):
    """RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN over the whole client."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return
    c = w.client
    w.update = (0, 0, c[2] - c[0], c[3] - c[1])
    w.erase = w.erase or erase
    w.ncpaint = w.ncpaint or frame
    for child in m.children.get(hwnd, []):
        if m.get(child) is not None and m.windows[child].style & WS_VISIBLE:
            _invalidate_tree(wine, child, erase, frame)


def erase_now(wine, hwnd):
    """painting.c erase_now: WM_NCPAINT and WM_ERASEBKGND now, for the window and its
    children that need them."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None or not is_visible(wine, hwnd):
        return
    if w.ncpaint:
        w.ncpaint = False
        yield from send(wine, hwnd, WM_NCPAINT, 1, 0)
    if w.erase and w.update is not None:
        w.erase = False
        hdc = get_dc(wine, hwnd)
        r = yield from send(wine, hwnd, WM_ERASEBKGND, hdc, 0)
        release_dc(wine, hwnd, hdc)
        if not r:
            w.erase = True
    for child in list(m.children.get(hwnd, [])):
        yield from erase_now(wine, child)


@api("USER", "SetWindowPos")
def set_window_pos16(wine, arg, hwnd, after, x, y, cx, cy, flags):
    return set_window_pos(wine, hwnd, after, signed(x), signed(y), signed(cx), signed(cy), flags)


@api("USER", "MoveWindow")
def move_window(wine, arg, hwnd, x, y, cx, cy, repaint):
    flags = SWP_NOZORDER | SWP_NOACTIVATE
    if not repaint:
        flags |= SWP_NOREDRAW
    return set_window_pos(wine, hwnd, 0, signed(x), signed(y), signed(cx), signed(cy), flags)


@api("USER", "BringWindowToTop")
def bring_window_to_top(wine, arg, hwnd):
    return set_window_pos(wine, hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE)


# ------------------------------------------------------------------ activation and focus

def set_foreground(wine, hwnd):
    m = wm(wine)
    previous = m.foreground
    m.foreground = hwnd
    if previous != hwnd:
        yield from set_active(wine, hwnd, focus=True)


def set_active(wine, hwnd, focus=True):
    """input.c set_active_window, one thread: WM_NCACTIVATE and WM_ACTIVATE to the old window,
    WM_QUERYNEWPALETTE, WM_ACTIVATEAPP when the task gains or loses the active window, then
    WM_NCACTIVATE and WM_ACTIVATE to the new one, and the focus."""
    m = wm(wine)
    previous = m.active
    if previous == hwnd:
        return previous
    if WH_CBT_INDEX in wine.hooks:
        # input.c set_active_window: HCBT_ACTIVATE with a CBTACTIVATESTRUCT16 {fMouse, hWndActive}.
        mark = scratch_mark(wine)
        cas = scratch(wine, struct.pack("<HH", 0, previous))
        refused = yield from call_hook(wine, WH_CBT_INDEX, HCBT_ACTIVATE, hwnd, cas)
        scratch_release(wine, mark)
        if refused:
            # set_active_window returns FALSE; NtUserSetActiveWindow then answers 0.
            return 0
    if m.get(previous) is not None:
        yield from send(wine, previous, WM_NCACTIVATE, 0, hwnd)
        yield from send(wine, previous, WM_ACTIVATE, 0, hwnd)
    m.active = hwnd
    if hwnd:
        yield from send(wine, hwnd, WM_QUERYNEWPALETTE, 0, 0)
        if m.get(hwnd) is None:
            return previous
    old_task = m.task_of(previous) if previous else 0
    new_task = m.task_of(hwnd) if hwnd else 0
    if old_task != new_task:
        # set_active_window: WM_ACTIVATEAPP (FALSE, the new thread) to the old thread's top-level
        # windows, then (TRUE, the old thread) to the new thread's. user.exe16 gives a 16-bit
        # procedure the thread as its HTASK16 (HTASK_16).
        tops = list(m.children.get(m.desktop, []))
        for task, active, other in ((old_task, 0, new_task), (new_task, 1, old_task)):
            if not task:
                continue
            for top in tops:
                if m.get(top) is not None and m.task_of(top) == task:
                    yield from send(wine, top, WM_ACTIVATEAPP, active, other)
    if m.get(hwnd) is not None:
        yield from send(wine, hwnd, WM_NCACTIVATE, int(hwnd == m.foreground), previous)
        yield from send(wine, hwnd, WM_ACTIVATE, 1, previous)
    if focus and hwnd and m.active == hwnd:
        f = m.focus
        if not f or root_of(wine, f) != hwnd:
            yield from set_focus_window(wine, hwnd)
    return previous


def root_of(wine, hwnd):
    m = wm(wine)
    w = m.get(hwnd)
    while w is not None and w.style & WS_CHILD and w.parent != m.desktop:
        w = m.get(w.parent)
    return w.hwnd if w is not None else 0


def set_focus_window(wine, hwnd):
    m = wm(wine)
    previous = m.focus
    if previous == hwnd:
        return previous
    m.focus = hwnd
    if m.get(previous) is not None:
        yield from send(wine, previous, WM_KILLFOCUS, hwnd, 0)
        if m.focus != hwnd:
            return previous
    if m.get(hwnd) is not None:
        yield from send(wine, hwnd, WM_SETFOCUS, previous, 0)
    return previous


def set_focus(wine, hwnd):
    """NtUserSetFocus: activates the top-level window first if needed."""
    m = wm(wine)
    previous = m.focus
    if hwnd:
        if m.get(hwnd) is None:
            return 0
        if hwnd == previous:
            return previous
        top = hwnd
        while True:
            t = m.windows[top]
            if t.style & (WS_MINIMIZE | WS_DISABLED):
                return 0
            if not t.style & WS_CHILD:
                break
            parent = t.parent
            if not parent or parent == m.desktop:
                if (t.style & (WS_POPUP | WS_CHILD)) == WS_CHILD:
                    return 0
                break
            top = parent
        # HCBT_SETFOCUS goes through call_hooks, but hook.c call_WH_CBT has no case for it:
        # the 16-bit hook is not called and the answer is 0.
        if not m.active:
            yield from set_foreground(wine, top)
        if top != m.active:
            yield from set_active(wine, top, focus=False)
            if m.get(hwnd) is None or top != m.active:
                return 0
    elif not previous:
        return 0
    result = yield from set_focus_window(wine, hwnd)
    return result


@api("USER", "SetFocus")
def set_focus16(wine, arg, hwnd):
    return set_focus(wine, hwnd)


@api("USER", "GetFocus")
def get_focus(wine, arg):
    return wm(wine).focus


@api("USER", "GetActiveWindow")
def get_active_window(wine, arg):
    return wm(wine).active


@api("USER", "SetActiveWindow")
def set_active_window(wine, arg, hwnd):
    m = wm(wine)
    if hwnd:
        w = m.get(hwnd)
        if w is None:
            return 0
        if (w.style & (WS_POPUP | WS_CHILD)) == WS_CHILD:
            return m.active
    previous = yield from set_active(wine, hwnd, focus=True)
    return previous


@api("USER", "GetCapture")
def get_capture(wine, arg):
    return wm(wine).capture


@api("USER", "SetCapture")
def set_capture(wine, arg, hwnd):
    m = wm(wine)
    previous, m.capture = m.capture, hwnd
    if previous and previous != hwnd and m.get(previous) is not None:
        yield from send(wine, previous, 0x215, 0, hwnd)  # WM_CAPTURECHANGED
    return previous


@api("USER", "ReleaseCapture")
def release_capture(wine, arg):
    m = wm(wine)
    previous, m.capture = m.capture, 0
    if previous and m.get(previous) is not None:
        yield from send(wine, previous, 0x215, 0, 0)
    return 1


# ------------------------------------------------------------------ queries

@api("USER", "IsWindow")
def is_window(wine, arg, hwnd):
    return 1 if wm(wine).get(hwnd) is not None else 0


@api("USER", "IsWindowVisible")
def is_window_visible(wine, arg, hwnd):
    return 1 if is_visible(wine, hwnd) else 0


@api("USER", "IsWindowEnabled")
def is_window_enabled(wine, arg, hwnd):
    w = wm(wine).get(hwnd)
    return 1 if w is not None and not w.style & WS_DISABLED else 0


@api("USER", "EnableWindow")
def enable_window(wine, arg, hwnd, enable):
    """NtUserEnableWindow: WM_ENABLE when the state changes; disabling the focus window takes the
    focus away. Returns TRUE if the window was disabled."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    was_disabled = bool(w.style & WS_DISABLED)
    if enable and was_disabled:
        w.style &= ~WS_DISABLED
        yield from send(wine, hwnd, WM_ENABLE, 1, 0)
    elif not enable and not was_disabled:
        yield from send(wine, hwnd, WM_CANCELMODE, 0, 0)
        w.style |= WS_DISABLED
        if hwnd == m.focus or root_of(wine, m.focus) == hwnd:
            yield from set_focus(wine, 0)
        yield from send(wine, hwnd, WM_ENABLE, 0, 0)
    return 1 if was_disabled else 0


@api("USER", "IsChild")
def is_child(wine, arg, parent, hwnd):
    m = wm(wine)
    w = m.get(hwnd)
    while w is not None and w.style & WS_CHILD:
        if w.parent == parent:
            return 1
        w = m.get(w.parent)
    return 0


@api("USER", "IsIconic")
def is_iconic(wine, arg, hwnd):
    w = wm(wine).get(hwnd)
    return 1 if w is not None and w.style & WS_MINIMIZE else 0


@api("USER", "IsZoomed")
def is_zoomed(wine, arg, hwnd):
    w = wm(wine).get(hwnd)
    return 1 if w is not None and w.style & WS_MAXIMIZE else 0


@api("USER", "GetDesktopWindow")
def get_desktop_window(wine, arg):
    return wm(wine).desktop


@api("USER", "GetParent")
def get_parent(wine, arg, hwnd):
    """NtUserGetParent: the parent of a child, the owner of a popup or top-level window."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    if w.style & WS_CHILD:
        return w.parent if w.parent != m.desktop else 0
    if w.style & WS_POPUP:
        return w.owner
    return 0


@api("USER", "SetParent")
def set_parent(wine, arg, hwnd, parent):
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    yield f"SetParent({hwnd:#x}, {parent:#x}): Wine hides, reparents and shows the window, which neww does not yet"


@api("USER", "GetWindow")
def get_window(wine, arg, hwnd, rel):
    """GetWindow: GW_HWNDFIRST 0, LAST 1, NEXT 2, PREV 3, OWNER 4, CHILD 5."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    siblings = [h for h in m.children.get(w.parent, []) if m.get(h) is not None]
    if rel == 0:
        return siblings[0] if siblings else 0
    if rel == 1:
        return siblings[-1] if siblings else 0
    if rel in (2, 3):
        if hwnd not in siblings:
            return 0
        i = siblings.index(hwnd) + (1 if rel == 2 else -1)
        return siblings[i] if 0 <= i < len(siblings) else 0
    if rel == 4:
        return w.owner
    if rel == 5:
        kids = [h for h in m.children.get(hwnd, []) if m.get(h) is not None]
        return kids[0] if kids else 0
    return 0


@api("USER", "GetTopWindow")
def get_top_window(wine, arg, hwnd):
    m = wm(wine)
    kids = [h for h in m.children.get(hwnd or m.desktop, []) if m.get(h) is not None]
    return kids[0] if kids else 0


@api("USER", "GetNextWindow")
def get_next_window(wine, arg, hwnd, flag):
    if flag not in (2, 3):
        return 0
    return get_window(wine, arg, hwnd, flag)


@api("USER", "GetLastActivePopup")
def get_last_active_popup(wine, arg, hwnd):
    return hwnd


@api("USER", "GetWindowTask")
def get_window_task(wine, arg, hwnd):
    """GetWindowTask16: the task of the window's thread."""
    w = wm(wine).get(hwnd)
    return w.task if w is not None else 0


@api("USER", "GetWindowRect")
def get_window_rect(wine, arg, hwnd, ptr):
    """In screen coordinates. Void."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is not None:
        px, py = screen_origin(wine, w.parent) if w.parent else (0, 0)
        r = w.rect
        write_rect(wine, ptr, (r[0] + px, r[1] + py, r[2] + px, r[3] + py))
    return arg.regs("ax"), 0


@api("USER", "GetClientRect")
def get_client_rect(wine, arg, hwnd, ptr):
    w = wm(wine).get(hwnd)
    if w is not None:
        c = w.client
        write_rect(wine, ptr, (0, 0, c[2] - c[0], c[3] - c[1]))
    return arg.regs("ax"), 0


@api("USER", "ClientToScreen")
def client_to_screen(wine, arg, hwnd, ptr):
    if wm(wine).get(hwnd) is not None:
        x, y = struct.unpack("<hh", gdi16.read(wine, ptr, 4))
        ox, oy = screen_origin(wine, hwnd)
        gdi16.write(wine, ptr, struct.pack("<hh", x + ox, y + oy))
    return arg.regs("ax"), 0


@api("USER", "ScreenToClient")
def screen_to_client(wine, arg, hwnd, ptr):
    if wm(wine).get(hwnd) is not None:
        x, y = struct.unpack("<hh", gdi16.read(wine, ptr, 4))
        ox, oy = screen_origin(wine, hwnd)
        gdi16.write(wine, ptr, struct.pack("<hh", x - ox, y - oy))
    return arg.regs("ax"), 0


@api("USER", "GetWindowText")
def get_window_text(wine, arg, hwnd, ptr, count):
    """GetWindowText16 is WM_GETTEXT to the window."""
    if wm(wine).get(hwnd) is None:
        return 0
    result = yield from send(wine, hwnd, WM_GETTEXT, count, ptr)
    return result & 0xFFFF


@api("USER", "GetWindowTextLength")
def get_window_text_length(wine, arg, hwnd):
    if wm(wine).get(hwnd) is None:
        return 0
    result = yield from send(wine, hwnd, WM_GETTEXTLENGTH, 0, 0)
    return result & 0xFFFF


@api("USER", "SetWindowText")
def set_window_text(wine, arg, hwnd, ptr):
    if wm(wine).get(hwnd) is None:
        return 0
    result = yield from send(wine, hwnd, WM_SETTEXT, 0, ptr)
    return result & 0xFFFF


@api("USER", "FindWindow")
def find_window(wine, arg, cls_ptr, title_ptr):
    m = wm(wine)
    cname = class_name_arg(wine, cls_ptr) if cls_ptr else None
    title = string_at(wine, title_ptr) if title_ptr else None
    for h in m.children.get(m.desktop, []):
        w = m.get(h)
        if w is None:
            continue
        if cname is not None:
            if isinstance(cname, int):
                if w.cls is None or w.cls.atom != cname:
                    continue
            elif w.cls is None or w.cls.name.lower() != cname.lower():
                continue
        if title is not None and (w.text or "") != title:
            continue
        return h
    return 0


@api("USER", "SetProp")
def set_prop(wine, arg, hwnd, name_ptr, value):
    w = wm(wine).get(hwnd)
    if w is None:
        return 0
    key = name_ptr & 0xFFFF if not name_ptr >> 16 else (string_at(wine, name_ptr) or "").lower()
    w.props[key] = value
    return 1


@api("USER", "GetProp")
def get_prop(wine, arg, hwnd, name_ptr):
    w = wm(wine).get(hwnd)
    if w is None:
        return 0
    key = name_ptr & 0xFFFF if not name_ptr >> 16 else (string_at(wine, name_ptr) or "").lower()
    return w.props.get(key, 0)


@api("USER", "RemoveProp")
def remove_prop(wine, arg, hwnd, name_ptr):
    w = wm(wine).get(hwnd)
    if w is None:
        return 0
    key = name_ptr & 0xFFFF if not name_ptr >> 16 else (string_at(wine, name_ptr) or "").lower()
    return w.props.pop(key, 0)


# ------------------------------------------------------------------ DCs for windows

def get_dc(wine, hwnd, window=False):
    """NtUserGetDCEx for a cache DC: the newest released one, or a new one, reset to the
    defaults and set to the window's client (or whole window) on the screen."""
    m = wm(wine)
    g = gdi16.gdi(wine)
    free = [hdc for hdc, used in wine.dcs.items() if not used and hdc in g.objects]
    if free:
        hdc = max(free)
        old = g.objects[hdc]
        g.objects[hdc] = gdi16.DC(hdc)
        del old
    else:
        hdc = gdi16.new_dc(wine)
    wine.dcs[hdc] = True
    dc = g.objects[hdc]
    if hwnd and m.get(hwnd) is not None:
        if window:
            ox, oy = window_origin(wine, hwnd)
            w = m.windows[hwnd]
            dc.origin = (ox, oy)
            dc.clip = (ox, oy, ox + w.rect[2] - w.rect[0], oy + w.rect[3] - w.rect[1])
        else:
            dc.origin = screen_origin(wine, hwnd)
            dc.clip = visible_client(wine, hwnd)
        dc.hwnd = hwnd
    else:
        dc.origin = (0, 0)
        dc.clip = (0, 0, SCREEN_W, SCREEN_H)
    return hdc


def release_dc(wine, hwnd, hdc):
    if not wine.dcs.get(hdc):
        return 0
    wine.dcs[hdc] = False
    return 1


@api("USER", "GetDC")
def get_dc16(wine, arg, hwnd):
    if hwnd and wm(wine).get(hwnd) is None:
        return 0
    return get_dc(wine, hwnd)


@api("USER", "GetWindowDC")
def get_window_dc(wine, arg, hwnd):
    if hwnd and wm(wine).get(hwnd) is None:
        return 0
    return get_dc(wine, hwnd, window=True)


@api("USER", "ReleaseDC")
def release_dc16(wine, arg, hwnd, hdc):
    return release_dc(wine, hwnd, hdc)


# ------------------------------------------------------------------ painting

def begin_paint(wine, hwnd, ps_ptr):
    """NtUserBeginPaint: WM_NCPAINT if the frame is due, a DC clipped to the update
    rectangle, WM_ERASEBKGND if the background is due, and the window validated."""
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    if w.ncpaint:
        w.ncpaint = False
        yield from send(wine, hwnd, WM_NCPAINT, 1, 0)
    w = m.get(hwnd)
    if w is None:
        return 0
    update = w.update or (0, 0, 0, 0)
    w.update = None
    hdc = get_dc(wine, hwnd)
    dc = gdi16.gdi(wine).objects[hdc]
    ox, oy = dc.origin
    dc.clip = gdi16._intersect(dc.clip, (update[0] + ox, update[1] + oy, update[2] + ox, update[3] + oy))
    erase = w.erase
    w.erase = False
    f_erase = 0
    if erase:
        r = yield from send(wine, hwnd, WM_ERASEBKGND, hdc, 0)
        f_erase = 0 if r else 1
    gdi16.write(wine, ps_ptr, struct.pack("<HHhhhhHH", hdc, f_erase, *update, 0, 0) + bytes(16))
    return hdc


def end_paint(wine, hwnd, ps_ptr):
    hdc = struct.unpack("<H", gdi16.read(wine, ps_ptr, 2))[0]
    release_dc(wine, hwnd, hdc)
    return 1


@api("USER", "BeginPaint")
def begin_paint16(wine, arg, hwnd, ptr):
    return begin_paint(wine, hwnd, ptr)


@api("USER", "EndPaint")
def end_paint16(wine, arg, hwnd, ptr):
    return end_paint(wine, hwnd, ptr)


def _union(a, b):
    if a is None:
        return b
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def invalidate(wine, hwnd, rect, erase):
    """RDW_INVALIDATE over rect (client coordinates) or the whole client, and RDW_ERASE when
    asked. neww keeps one bounding rectangle per window."""
    m = wm(wine)
    w = m.get(hwnd) if hwnd else None
    if w is None:
        if not hwnd:
            for top in m.children.get(m.desktop, []):
                _invalidate_tree(wine, top, erase, True)
        return
    c = w.client
    full = (0, 0, c[2] - c[0], c[3] - c[1])
    r = full if rect is None else gdi16._intersect(full, rect)
    if gdi16._empty(r):
        return
    w.update = _union(w.update, r)
    w.erase = w.erase or erase
    for child in m.children.get(hwnd, []):
        cw = m.get(child)
        if cw is not None and cw.style & WS_VISIBLE and not w.style & WS_CLIPCHILDREN:
            cr = (cw.rect[0], cw.rect[1], cw.rect[2], cw.rect[3])
            if not gdi16._empty(gdi16._intersect(cr, r)):
                invalidate(wine, child, None, erase)


@api("USER", "InvalidateRect")
def invalidate_rect(wine, arg, hwnd, ptr, erase):
    invalidate(wine, hwnd, read_rect(wine, ptr) if ptr else None, bool(erase))
    return arg.regs("ax"), 0


@api("USER", "InvalidateRgn")
def invalidate_rgn(wine, arg, hwnd, hrgn, erase):
    rgn = gdi16.gdi(wine).get(hrgn, gdi16.OBJ_REGION) if hrgn else None
    invalidate(wine, hwnd, rgn.rect if rgn is not None else None, bool(erase))
    return arg.regs("ax"), 0


@api("USER", "ValidateRect")
def validate_rect(wine, arg, hwnd, ptr):
    w = wm(wine).get(hwnd)
    if w is not None and w.update is not None:
        if not ptr:
            w.update = None
        else:
            r = read_rect(wine, ptr)
            if gdi16._contains(r, w.update):
                w.update = None
    return arg.regs("ax"), 0


@api("USER", "ValidateRgn")
def validate_rgn(wine, arg, hwnd, hrgn):
    w = wm(wine).get(hwnd)
    if w is not None:
        rgn = gdi16.gdi(wine).get(hrgn, gdi16.OBJ_REGION) if hrgn else None
        if rgn is None or (w.update is not None and gdi16._contains(rgn.rect, w.update)):
            w.update = None
    return arg.regs("ax"), 0


@api("USER", "GetUpdateRect")
def get_update_rect(wine, arg, hwnd, ptr, erase):
    m = wm(wine)
    w = m.get(hwnd)
    if w is None:
        return 0
    r = w.update or (0, 0, 0, 0)
    if ptr:
        write_rect(wine, ptr, r)
    if erase and w.update is not None and w.erase:
        yield from erase_now(wine, hwnd)
    return 0 if w.update is None else 1


@api("USER", "UpdateWindow")
def update_window(wine, arg, hwnd):
    """RDW_UPDATENOW | RDW_ALLCHILDREN: WM_PAINT now for the window and its children with
    something to paint."""
    yield from update_now(wine, hwnd)
    return arg.regs("ax"), 0


def update_now(wine, hwnd):
    m = wm(wine)
    w = m.get(hwnd)
    if w is None or not is_visible(wine, hwnd):
        return
    if w.update is not None or w.ncpaint:
        yield from send(wine, hwnd, WM_PAINT, 0, 0)
        w = m.get(hwnd)
        if w is not None and w.update is not None:
            # A window procedure that does not validate gets one WM_PAINT here, as Wine
            # sends one per update.
            pass
    for child in list(m.children.get(hwnd, [])):
        yield from update_now(wine, child)


@api("USER", "RedrawWindow")
def redraw_window(wine, arg, hwnd, rect_ptr, hrgn, flags):
    """RDW_INVALIDATE 1, INTERNALPAINT 2, ERASE 4, VALIDATE 8, FRAME 0x400, UPDATENOW 0x100,
    ERASENOW 0x200, ALLCHILDREN 0x80."""
    m = wm(wine)
    hwnd = hwnd or m.desktop
    rect = read_rect(wine, rect_ptr) if rect_ptr else None
    if hrgn:
        rgn = gdi16.gdi(wine).get(hrgn, gdi16.OBJ_REGION)
        rect = rgn.rect if rgn is not None else rect
    w = m.get(hwnd)
    if w is None:
        return 0
    if flags & 1:
        if hwnd == m.desktop:
            invalidate(wine, 0, None, bool(flags & 4))
        else:
            invalidate(wine, hwnd, rect, bool(flags & 4))
        if flags & 0x400:
            w.ncpaint = True
    if flags & 8:
        w.update = None
    if flags & 0x200:
        yield from erase_now(wine, hwnd)
    if flags & 0x100:
        yield from erase_now(wine, hwnd)
        yield from update_now(wine, hwnd)
    return 1


@api("USER", "FillRect")
def fill_rect(wine, arg, hdc, ptr, brush):
    dc = gdi16.gdi(wine).get(hdc, gdi16.OBJ_DC)
    if dc is None:
        return 0
    gdi16.fill(wine, dc, read_rect(wine, ptr), brush)
    return 1


@api("USER", "GetSysColor")
def get_sys_color(wine, arg, index):
    if index >= len(gdi16.SYS_COLORS):
        return 0
    return _colorref(gdi16.SYS_COLORS[index])


@api("USER", "GetSysColorBrush")
def get_sys_color_brush(wine, arg, index):
    if index >= len(gdi16.SYS_COLORS):
        return 0
    return sys_color_brush(wine, index)


# ------------------------------------------------------------------ messages

@api("USER", "SendMessage")
def send_message16(wine, arg, hwnd, msg, wp, lp):
    """SendMessage16: HWND_BROADCAST (0xFFFF) goes to every top-level window."""
    m = wm(wine)
    if hwnd == 0xFFFF:
        for top in list(m.children.get(m.desktop, [])):
            if m.get(top) is not None:
                yield from send(wine, top, msg, wp, lp)
        return 1
    w = m.get(hwnd)
    if w is not None and w.task and w.task != wine.htask and wine.tasks:
        return inter_task_send(wine, w, msg, wp, lp)
    result = yield from send(wine, hwnd, msg, wp, lp)
    return result


def inter_task_send(wine, w, msg, wp, lp):
    """SendMessage16 to a window of another task. The sender waits for the reply; the window's
    task runs the window procedure, on its own stack, from where it waits; then the sender gets
    the result, as Win16's task switch for a sent message does, and the other task waits again
    where it was. Returns (ax, dx) for the gate, with the switch request set."""
    from .tasks import by_handle, Switch
    receiver = by_handle(wine, w.task)
    if receiver is None or receiver.context is None:
        return 0, 0
    name = MESSAGE_NAMES.get(msg, hex(msg))
    wine.trace.append(f"  -> {w.hwnd:#x} {name} {wp:#x} {lp:#x} (task {receiver.exe_name})")
    if proc_is_def(wine, w.proc):
        return 0, 0, (f"SendMessage {name} to {w.hwnd:#x} of task {receiver.exe_name}: its procedure is "
                      "DefWindowProc, and neww runs that only in the sender's task")
    ss = receiver.context["ss"]
    inst = w.inst or ss
    call = Call(w.proc >> 16, w.proc & 0xFFFF, regs={"ds": ss, "es": ss, "ax": inst},
                words=[w.hwnd, msg & 0xFFFF, wp & 0xFFFF, (lp >> 16) & 0xFFFF, lp & 0xFFFF])
    sender = wine.current
    reply = {}

    def done(ax, dx):
        reply["value"] = (ax, dx)
        return sender

    switch = Switch("answer", receiver, wait="reply", answer=lambda: reply["value"])
    switch.call, switch.done = call, done
    wine.registers = {"switch": switch}
    return 0, 0


@api("USER", "DefWindowProc")
def def_window_proc16(wine, arg, hwnd, msg, wp, lp):
    result = yield from def_window_proc(wine, hwnd, msg, wp, lp)
    return result


@api("USER", "CallWindowProc")
def call_window_proc16(wine, arg, proc, hwnd, msg, wp, lp):
    if not proc:
        return 0
    if proc_is_def(wine, proc):
        result = yield from def_window_proc(wine, hwnd, msg, wp, lp)
        return result
    from .user_controls import host_index, call_host
    index = host_index(wine, proc)
    if index is not None:
        result = yield from call_host(wine, index, hwnd, msg, wp, lp)
        return result
    ax, dx = yield from call_proc(wine, proc, hwnd, msg, wp, lp)
    return ax | dx << 16


@api("USER", "PostMessage")
def post_message(wine, arg, hwnd, msg, wp, lp):
    """PostMessage16: to the queue of the window's task. HWND_BROADCAST posts to every
    top-level window."""
    m = wm(wine)
    if hwnd == 0xFFFF:
        for top in m.children.get(m.desktop, []):
            m.queue_of(m.task_of(top)).queue.append((top, msg, wp, lp))
        return 1
    if hwnd and m.get(hwnd) is None:
        return 0
    m.queue_of(m.task_of(hwnd) if hwnd else wine.htask).queue.append((hwnd, msg, wp, lp))
    return 1


@api("USER", "PostAppMessage")
def post_app_message(wine, arg, task, msg, wp, lp):
    """PostAppMessage16 -> PostThreadMessage to the task's thread: FALSE for no such task."""
    from .tasks import by_handle
    if wine.tasks and by_handle(wine, task) is None:
        return 0
    wm(wine).queue_of(task if wine.tasks else wine.htask).queue.append((0, msg, wp, lp))
    return 1


@api("USER", "PostQuitMessage")
def post_quit_message(wine, arg, code):
    """PostQuitMessage: the queue's quit flag; GetMessage returns WM_QUIT once nothing else
    is posted. Void."""
    wm(wine).quit = code
    wine.trace[-1] += f" {code}"
    return arg.regs("ax"), 0


def _matches(m, entry, hwnd, first, last):
    h, msg = entry[0], entry[1]
    if hwnd and h != hwnd and not is_child_of(m, h, hwnd):
        return False
    if first or last:
        return first <= msg <= last
    return True


def is_child_of(m, hwnd, parent):
    w = m.get(hwnd)
    while w is not None:
        if w.parent == parent:
            return True
        w = m.get(w.parent)
    return False


def _paint_window(wine, hwnd_filter, task=None):
    """The first visible window of the task, in z order from the top, that has something to paint."""
    m = wm(wine)
    task = wine.htask if task is None else task

    def walk(h):
        for child in m.children.get(h, []):
            w = m.get(child)
            if w is None or not w.style & WS_VISIBLE:
                continue
            if (w.update is not None or w.ncpaint) and w.task == task:
                if not hwnd_filter or child == hwnd_filter or is_child_of(m, child, hwnd_filter):
                    return child
            found = walk(child)
            if found:
                return found
        return 0
    return walk(m.desktop)


def next_message(wine, hwnd, first, last, remove, task=None, advance=True):
    """get_message's order: posted messages, the quit message, (no input), WM_PAINT, then
    timers. With advance, and nothing else, the clock moves to the task's next timer; without,
    only a timer already due counts. Returns the message as (hwnd, msg, wp, lp) or None."""
    m = wm(wine)
    q = m.queue_of(wine.htask if task is None else task)
    for i, entry in enumerate(q.queue):
        if _matches(m, entry, hwnd, first, last):
            if remove:
                del q.queue[i]
            return entry
    if q.quit is not None and (not first and not last or first <= WM_QUIT <= last):
        code = q.quit
        if remove:
            q.quit = None
        return (0, WM_QUIT, code, 0)
    if not first and not last or first <= WM_PAINT <= last:
        h = _paint_window(wine, hwnd, task)
        if h:
            return (h, WM_PAINT, 0, 0)
    if q.timers and (not first and not last or first <= WM_TIMER <= last):
        key, timer = min(q.timers.items(), key=lambda kv: kv[1][2])
        if hwnd and key[0] != hwnd:
            return None
        if not advance and timer[2] > m.clock:
            return None
        m.clock = max(m.clock, timer[2])
        if remove:
            timer[2] = m.clock + timer[0]
        return (key[0], WM_TIMER, key[1], timer[1])
    return None


def message_waiting(wine, task):
    """A message the task's GetMessage would return now, without moving the clock."""
    return next_message(wine, 0, 0, 0, False, task=task, advance=False) is not None


def write_msg(wine, ptr, msg):
    h, message, wp, lp = msg
    gdi16.write(wine, ptr, struct.pack("<HHHIIhh", h, message, wp & 0xFFFF, lp & 0xFFFFFFFF, m_time(wine), 0, 0))


def m_time(wine):
    return wm(wine).clock & 0xFFFFFFFF


def _next_or_wait(wine, hwnd, first, last, remove):
    """The task's next message, or the task to run while it waits: (msg, None) or (None, task).

    A message already there comes first. Then another task that can run. When none can, the
    clock moves to the first timer of any waiting task: this task's own, and it gets the
    WM_TIMER, or another's, which runs. (None, None) when nothing will come.
    """
    msg = next_message(wine, hwnd, first, last, remove, advance=False)
    if msg is not None:
        return msg, None
    if sum(t.alive for t in wine.tasks) > 1:
        from .tasks import wait_for_message
        nxt = wait_for_message(wine)
        if nxt is None:
            return None, None
        if nxt is not wine.current:
            return None, nxt
    return next_message(wine, hwnd, first, last, remove), None


def _mm_callback(wine, hwnd, first, last, polling=False):
    """mmsystem16.callback_due for a task in GetMessage, PeekMessage or WaitMessage. The task
    would wait when it has no message and no other task can run; a poll never waits."""
    from .mmsystem16 import callback_due
    from .tasks import next_ready
    waiting = (not polling and next_message(wine, hwnd, first, last, False, advance=False) is None
               and next_ready(wine) is None)
    return callback_due(wine, waiting)


NO_INPUT = ("the queue is empty, no window needs painting and no timer is set; "
            "the task waits for input, and neww has none")


@api("USER", "GetMessage")
def get_message(wine, arg, ptr, hwnd, first, last):
    """GetMessage16: the next message, FALSE for WM_QUIT. With none, the task waits and another
    task runs; it resumes at the call, and GetMessage looks again. When no task can run, the
    clock moves to the first timer. With no message, no timer and nothing to paint in any task,
    they would wait for input forever, and the run stops there. A multimedia timer callback
    that is due runs first, and GetMessage looks again (mmsystem16.callback_due)."""
    from .tasks import Switch
    calls = _mm_callback(wine, hwnd, first, last)
    if calls is not None:
        return calls
    msg, nxt = _next_or_wait(wine, hwnd, first, last, True)
    if nxt is not None:
        wine.trace[-1] += f" (waits) -> {nxt.exe_name}"
        wine.registers = {"switch": Switch("retry", nxt, wait="message")}
        return 0, 0
    if msg is None:
        return 0, 0, f"GetMessage: {NO_INPUT}"
    write_msg(wine, ptr, msg)
    wine.trace[-1] += f" {msg[0]:#x} {MESSAGE_NAMES.get(msg[1], hex(msg[1]))}"
    return 0 if msg[1] == WM_QUIT else 1


PM_REMOVE, PM_NOYIELD = 0x1, 0x2


@api("USER", "PeekMessage")
def peek_message(wine, arg, ptr, hwnd, first, last, flags):
    """PeekMessage16: PM_REMOVE is 1. With no message the answer is FALSE and the clock moves
    one millisecond, so a polling loop sees time pass. Without PM_NOYIELD, another task that
    can run runs first, and this one gets its FALSE when it runs again. A multimedia timer
    callback that is due runs first, and PeekMessage looks again."""
    from .tasks import Switch
    m = wm(wine)
    calls = _mm_callback(wine, hwnd, first, last, polling=True)
    if calls is not None:
        return calls
    msg, nxt = _next_or_wait(wine, hwnd, first, last, bool(flags & PM_REMOVE))
    if msg is None:
        m.clock += 1
        if nxt is not None and not flags & PM_NOYIELD:
            wine.trace[-1] += f" (yields) -> {nxt.exe_name}"
            wine.registers = {"switch": Switch("answer", nxt, answer=(0, 0))}
        return 0
    write_msg(wine, ptr, msg)
    return 1


@api("USER", "WaitMessage")
def wait_message(wine, arg):
    """WaitMessage16: returns when the task has a message. Until then another task runs, or
    the clock moves to the first timer. Void. A multimedia timer callback that is due runs
    first, and WaitMessage looks again."""
    from .tasks import Switch
    calls = _mm_callback(wine, 0, 0, 0)
    if calls is not None:
        return calls
    msg, nxt = _next_or_wait(wine, 0, 0, 0, False)
    if nxt is not None:
        wine.trace[-1] += f" (waits) -> {nxt.exe_name}"
        wine.registers = {"switch": Switch("retry", nxt, wait="message")}
        return arg.regs("ax"), 0
    if msg is None:
        return 0, 0, f"WaitMessage: {NO_INPUT}"
    return arg.regs("ax"), 0


@api("USER", "GetQueueStatus")
def get_queue_status(wine, arg, flags):
    m = wm(wine)
    status = 0
    if m.queue:
        status |= 0x08  # QS_POSTMESSAGE
    if _paint_window(wine, 0):
        status |= 0x20  # QS_PAINT
    if m.timers:
        status |= 0x10  # QS_TIMER
    return (status & flags) << 16 | (status & flags)


@api("USER", "GetInputState")
def get_input_state(wine, arg):
    return 0


@api("USER", "TranslateMessage")
def translate_message(wine, arg, ptr):
    """TranslateMessage16: only key messages are translated, and neww has no input."""
    msg = struct.unpack("<H", gdi16.read(wine, ptr + 2, 2))[0]
    return 1 if 0x100 <= msg <= 0x108 else 0


@api("USER", "DispatchMessage")
def dispatch_message(wine, arg, ptr):
    """DispatchMessage16: a WM_TIMER with a callback calls it (hwnd, msg, id, time); a WM_PAINT
    for a window that does not validate is validated afterwards, as Wine does."""
    m = wm(wine)
    h, msg, wp, lp, time_ = struct.unpack("<HHHII", gdi16.read(wine, ptr, 14))
    if msg in (WM_TIMER, WM_SYSTIMER) and lp:
        ax, dx = yield from call_proc(wine, lp, h, msg, wp, time_)
        return ax | dx << 16
    w = m.get(h)
    if w is None:
        return 0
    result = yield from send(wine, h, msg, wp, lp)
    if msg == WM_PAINT:
        w = m.get(h)
        if w is not None and w.update is not None:
            w.update = None
            w.ncpaint = False
    return result


@api("USER", "SetTimer")
def set_timer(wine, arg, hwnd, ident, elapse, proc):
    """SetTimer16: the timer's due time is on neww's clock. Returns the id."""
    m = wm(wine)
    if hwnd and m.get(hwnd) is None:
        return 0
    timers = m.queue_of(m.task_of(hwnd) if hwnd else wine.htask).timers
    if not hwnd:
        ident = 0x7FFF - len(timers)
    timers[(hwnd, ident)] = [max(elapse, 10), proc, m.clock + max(elapse, 10)]
    return ident or 1


@api("USER", "KillTimer")
def kill_timer(wine, arg, hwnd, ident):
    m = wm(wine)
    timers = m.queue_of(m.task_of(hwnd) if hwnd else wine.htask).timers
    return 1 if timers.pop((hwnd, ident), None) is not None else 0


@api("USER", "InSendMessage")
def in_send_message(wine, arg):
    return 0


@api("USER", "GetTickCount", "GetCurrentTime")
def get_tick_count(wine, arg):
    return m_time(wine)


@api("USER", "GetCursorPos")
def get_cursor_pos(wine, arg, ptr):
    x, y = getattr(wm(wine), "cursor_pos", (SCREEN_W // 2, SCREEN_H // 2))
    gdi16.write(wine, ptr, struct.pack("<hh", x, y))
    return 1


@api("USER", "SetCursor")
def set_cursor(wine, arg, hcursor):
    m = wm(wine)
    old, m.cursor = m.cursor, hcursor
    m.cursor_set = True
    return old


@api("USER", "GetCursor")
def get_cursor(wine, arg):
    """GetCursor16 -> NtUserGetCursor: the cursor SetCursor set; before any SetCursor in the
    process, the shared IDC_WAIT cursor (LoadImageW LR_SHARED)."""
    m = wm(wine)
    if not getattr(m, "cursor_set", False):
        from .user_controls import system_cursor
        return system_cursor(wine, 32514)
    return m.cursor or 0


@api("USER", "SetCursorPos")
def set_cursor_pos(wine, arg, x, y):
    """SetCursorPos16 -> NtUserSetCursorPos: the desktop's cursor moves (clipped to the screen),
    and GetCursorPos answers the new position. Void.

    Not yet done: the server's set_cursor_pos also queues a WM_MOUSEMOVE hardware message for
    the window under the cursor, whether or not the position changes. neww has no hardware
    input queue yet; the trace line says so each time, so the gap is never silent."""
    m = wm(wine)
    m.cursor_pos = (max(0, min(x, SCREEN_W - 1)), max(0, min(y, SCREEN_H - 1)))
    wine.trace[-1] += f" ({x}, {y}); no WM_MOUSEMOVE queued: neww has no hardware input queue yet"
    return arg.regs("ax"), 0


@api("USER", "GetKeyState", "GetAsyncKeyState")
def get_key_state(wine, arg, key):
    return 0


@api("USER", "MessageBeep")
def message_beep(wine, arg, kind):
    return arg.regs("ax"), 0


@api("USER", "EnumWindows")
def enum_windows(wine, arg, proc, lparam):
    m = wm(wine)
    for h in list(m.children.get(m.desktop, [])):
        if m.get(h) is None:
            continue
        ax, dx = yield Call(proc >> 16, proc & 0xFFFF, regs={"ds": wine.ss, "es": wine.ss},
                            words=[h, lparam >> 16, lparam & 0xFFFF])
        if not ax:
            break
    return 1


@api("USER", "EnumTaskWindows")
def enum_task_windows(wine, arg, task, proc, lparam):
    result = yield from enum_windows(wine, arg, proc, lparam)
    return result


@api("USER", "EnumChildWindows")
def enum_child_windows(wine, arg, parent, proc, lparam):
    m = wm(wine)

    def all_children(h):
        for c in list(m.children.get(h, [])):
            if m.get(c) is not None:
                yield c
                yield from all_children(c)
    for h in list(all_children(parent)):
        if m.get(h) is None:
            continue
        ax, dx = yield Call(proc >> 16, proc & 0xFFFF, regs={"ds": wine.ss, "es": wine.ss},
                            words=[h, lparam >> 16, lparam & 0xFFFF])
        if not ax:
            break
    return 1


# ------------------------------------------------------------------ hooks

@api("USER", "UnhookWindowsHook")
def unhook_windows_hook(wine, arg, id_, proc):
    """hook.c UnhookWindowsHook16: the task's hook of that kind, if its procedure matches."""
    from .wine import WH_MINHOOK, WH_MAXHOOK16
    if id_ < WH_MINHOOK or id_ > WH_MAXHOOK16:
        return 0
    hook = wine.hooks.get(id_ - WH_MINHOOK)
    if hook is None or hook[1] != proc:
        return 0
    del wine.hooks[id_ - WH_MINHOOK]
    return 1


@api("USER", "UnhookWindowsHookEx")
def unhook_windows_hook_ex(wine, arg, hhook):
    """hook.c UnhookWindowsHookEx16: the hook with that handle, FALSE if there is none."""
    for index, hook in list(wine.hooks.items()):
        if hook[0] == hhook:
            del wine.hooks[index]
            return 1
    return 0


def _windows_from_point(wine, parent, x, y, out):
    """server window.c get_window_children_from_point: each child (top of the z order first)
    that the point is in, its own children first, then itself. x, y are in parent's client
    coordinates."""
    m = wm(wine)
    for hwnd in m.children.get(parent, []):
        w = m.get(hwnd)
        if w is None or not _point_in_window(w, x, y):
            continue
        cl, ct, cr, cb = w.client
        if not w.style & (WS_MINIMIZE | WS_DISABLED) and cl <= x < cr and ct <= y < cb:
            _windows_from_point(wine, hwnd, x - cl, y - ct, out)
        out.append(hwnd)


def _point_in_window(w, x, y):
    """server is_point_in_window: visible, not a disabled child, not layered and transparent,
    and in the window's rectangle (neww keeps no window regions)."""
    WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
    if not w.style & WS_VISIBLE:
        return False
    if w.style & (WS_POPUP | WS_CHILD | WS_DISABLED) == WS_CHILD | WS_DISABLED:
        return False
    if w.exstyle & (WS_EX_LAYERED | WS_EX_TRANSPARENT) == WS_EX_LAYERED | WS_EX_TRANSPARENT:
        return False
    l, t, r, b = w.rect
    return l <= x < r and t <= y < b


@api("USER", "WindowFromPoint")
def window_from_point16(wine, arg, point):
    """WindowFromPoint16 -> NtUserWindowFromPoint -> window_from_point(desktop, pt, TRUE): the
    server's list of windows under the point (all_windows_from_point, the desktop last); the
    first that is disabled, or of another thread, or whose WM_NCHITTEST is not HTTRANSPARENT."""
    m = wm(wine)
    x, y = signed(point & 0xFFFF), signed(point >> 16 & 0xFFFF)
    found = []
    _windows_from_point(wine, m.desktop, x, y, found)
    found.append(m.desktop)
    for hwnd in found:
        w = m.get(hwnd)
        if w.style & WS_DISABLED:
            return hwnd
        if hwnd == m.desktop or m.task_of(hwnd) != wine.htask:
            return hwnd
        hit = yield from send(wine, hwnd, WM_NCHITTEST, 0, (y & 0xFFFF) << 16 | (x & 0xFFFF))
        if hit & 0xFFFF != HTTRANSPARENT:
            return hwnd
    return 0
