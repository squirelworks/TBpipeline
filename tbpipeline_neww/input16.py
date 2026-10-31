"""Hardware input: mouse and keyboard, from a script, as the device would give it.

Win16 USER keeps one system queue of raw hardware messages, and Wine's server
keeps one per desktop. A raw message goes to the task that owns the window
under the point (or the capture window) for the mouse, and the focus window
(or the active window) for the keyboard. That task's GetMessage or
PeekMessage takes it after its posted messages and the quit message, and
before WM_PAINT and timers, and cooks it as win32u message.c
process_mouse_message and process_keyboard_message do: WM_NCHITTEST picks the
window and the hit code, a hit outside the client makes it a WM_NC... message,
a button press on an inactive top-level window sends WM_MOUSEACTIVATE, and
WM_SETCURSOR goes to the window. The cooked message is what GetMessage returns.

Cooking sends messages, so it runs as guest calls inside the waiting call,
which then looks again (GuestCalls retry), as the multimedia timer callbacks do.

neww has no device. The input is a script (Machine.input or --input):

    click 400,300; dblclick 400,300; rclick 10,10; move 5,5
    key right; key ctrl+right; key pgdn; type hello
    wait 500

Coordinates are on the screen. Each step's first raw message waits until the
task it goes to is idle: no posted message and nothing to paint. The rest of
the step follows at once, as a button's up follows its down. wait N moves the
next step N milliseconds of neww's clock past the moment the task is idle.
"""

import re
import struct

from .handlers import signed

WM_KEYDOWN, WM_KEYUP, WM_CHAR, WM_SYSKEYDOWN, WM_SYSKEYUP, WM_SYSCHAR = 0x100, 0x101, 0x102, 0x104, 0x105, 0x106
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK = 0x204, 0x205, 0x206
WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK = 0x207, 0x208, 0x209
WM_NCMOUSEMOVE = 0xA0
WM_MOUSEACTIVATE, WM_SETCURSOR, WM_NCHITTEST = 0x21, 0x20, 0x84
MOUSE_FIRST, MOUSE_LAST = WM_MOUSEMOVE, WM_MBUTTONDBLCLK
KEY_FIRST, KEY_LAST = 0x100, 0x108

HTERROR, HTNOWHERE, HTCLIENT, HTTRANSPARENT = 0xFFFE, 0, 1, 0xFFFF
MA_ACTIVATE, MA_ACTIVATEANDEAT, MA_NOACTIVATE, MA_NOACTIVATEANDEAT = 1, 2, 3, 4
MK_LBUTTON, MK_RBUTTON, MK_SHIFT, MK_CONTROL, MK_MBUTTON = 0x1, 0x2, 0x4, 0x8, 0x10
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
CS_DBLCLKS = 0x8
WH_KEYBOARD, WH_MOUSE, HC_ACTION = 2, 7, 0
DOUBLE_CLICK_TIME = 500        # GetDoubleClickTime's default
DOUBLE_CLICK_SIZE = 4          # SM_CXDOUBLECLK, SM_CYDOUBLECLK

BUTTONS = {WM_LBUTTONDOWN: VK_LBUTTON, WM_LBUTTONUP: VK_LBUTTON, WM_RBUTTONDOWN: VK_RBUTTON,
           WM_RBUTTONUP: VK_RBUTTON, WM_MBUTTONDOWN: VK_MBUTTON, WM_MBUTTONUP: VK_MBUTTON}
DOWNS = (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN)

# Virtual keys by name, and their set-1 scan codes (extended keys marked 0x100), as the
# keyboard driver's MapVirtualKey table has them for a US layout.
KEYS = {
    "backspace": (0x08, 0x0E), "tab": (0x09, 0x0F), "enter": (0x0D, 0x1C), "return": (0x0D, 0x1C),
    "shift": (VK_SHIFT, 0x2A), "ctrl": (VK_CONTROL, 0x1D), "alt": (VK_MENU, 0x38),
    "esc": (0x1B, 0x01), "escape": (0x1B, 0x01), "space": (0x20, 0x39),
    "pgup": (0x21, 0x149), "pageup": (0x21, 0x149), "pgdn": (0x22, 0x151), "pagedown": (0x22, 0x151),
    "end": (0x23, 0x14F), "home": (0x24, 0x147), "left": (0x25, 0x14B), "up": (0x26, 0x148),
    "right": (0x27, 0x14D), "down": (0x28, 0x150), "insert": (0x2D, 0x152), "delete": (0x2E, 0x153),
}
KEYS.update({f"f{n}": (0x6F + n, 0x3A + n) for n in range(1, 11)})
KEYS.update({"f11": (0x7A, 0x57), "f12": (0x7B, 0x58)})
_ROWS = ("1234567890", 0x02), ("qwertyuiop", 0x10), ("asdfghjkl", 0x1E), ("zxcvbnm", 0x2C)
for _chars, _scan in _ROWS:
    for _i, _c in enumerate(_chars):
        KEYS[_c] = (ord(_c.upper()), _scan + _i)
SCANS = {vk: scan for vk, scan in KEYS.values()}


class Raw:
    """One raw hardware message in the system queue. Mouse: msg, x, y on the screen. Keyboard:
    msg, vk. idle: it waits until its task is idle; delay: then that many milliseconds more."""

    def __init__(self, msg, x=0, y=0, vk=0, idle=False, delay=0):
        self.msg, self.x, self.y, self.vk = msg, x, y, vk
        self.idle, self.delay = idle, delay
        self.due = None if idle else 0
        self.alt_down = set()

    @property
    def mouse(self):
        return MOUSE_FIRST <= self.msg <= MOUSE_LAST

    def __repr__(self):
        where = f"({self.x}, {self.y})" if self.mouse else f"vk {self.vk:#x}"
        return f"Raw({self.msg:#x} {where})"


class Input:
    """The system queue and the key state. down is the device's (GetAsyncKeyState, and the MK_
    flags a mouse message carries); keys and toggled are the thread's, as of the last input
    message the task read (GetKeyState, GetKeyboardState, TranslateMessage)."""

    def __init__(self):
        self.raw = []
        self.down = set()
        self.keys = set()
        self.toggled = set()
        self.pressed = set()       # GetAsyncKeyState's "pressed since the last call"
        self.last_click = None     # (msg, hwnd, time, x, y) of the last button down


def state(wine):
    if getattr(wine, "input", None) is None:
        wine.input = Input()
    return wine.input


# ------------------------------------------------------------------ the script

def _point(text):
    x, y = (int(v) for v in text.replace(" ", "").split(","))
    return x, y


def _key_steps(spec):
    """'ctrl+shift+right' -> the raw messages: modifiers down, the key down and up, modifiers up."""
    names = [n for n in spec.lower().split("+") if n]
    for name in names:
        if name not in KEYS:
            raise ValueError(f"unknown key {name!r}")
    vks = [KEYS[n][0] for n in names]
    alt = VK_MENU in vks[:-1]
    down, up = (WM_SYSKEYDOWN, WM_SYSKEYUP) if alt or vks[-1] == VK_MENU else (WM_KEYDOWN, WM_KEYUP)
    out = [Raw(WM_SYSKEYDOWN if vk == VK_MENU else down, vk=vk) for vk in vks]
    out += [Raw(WM_SYSKEYUP if vk == VK_MENU else up, vk=vk) for vk in reversed(vks)]
    return out


def parse(script):
    """The script's steps, each a list of Raw messages; the first of each waits for idle."""
    steps = []
    delay = 0
    for part in re.split(r"[;\n]", script or ""):
        part = part.strip()
        if not part:
            continue
        verb, _, rest = part.partition(" ")
        verb, rest = verb.lower(), rest.strip()
        if verb == "wait":
            delay += int(rest)
            continue
        if verb == "move":
            x, y = _point(rest)
            raws = [Raw(WM_MOUSEMOVE, x, y)]
        elif verb in ("click", "rclick", "mclick", "dblclick"):
            x, y = _point(rest)
            down, up = {"rclick": (WM_RBUTTONDOWN, WM_RBUTTONUP),
                        "mclick": (WM_MBUTTONDOWN, WM_MBUTTONUP)}.get(verb, (WM_LBUTTONDOWN, WM_LBUTTONUP))
            raws = [Raw(WM_MOUSEMOVE, x, y), Raw(down, x, y), Raw(up, x, y)]
            if verb == "dblclick":
                raws += [Raw(down, x, y), Raw(up, x, y)]
        elif verb == "key":
            raws = _key_steps(rest)
        elif verb == "type":
            raws = []
            for ch in rest:
                if ch == " ":
                    raws += _key_steps("space")
                elif ch.isupper():
                    raws += _key_steps("shift+" + ch.lower())
                else:
                    raws += _key_steps(ch)
        else:
            raise ValueError(f"unknown input step {part!r}")
        raws[0].idle, raws[0].due, raws[0].delay = True, None, delay
        delay = 0
        steps.append(raws)
    return steps


def queue_script(wine, script):
    """Put a script's raw messages at the end of the system queue."""
    st = state(wine)
    for raws in parse(script):
        st.raw.extend(raws)


def queue_raw(wine, raw):
    state(wine).raw.append(raw)


# ------------------------------------------------------------------ routing

def _top_window_at(wine, x, y):
    """The server's window_from_point: the deepest window under the point, no WM_NCHITTEST."""
    from .user_wnd import wm, _windows_from_point
    m = wm(wine)
    found = []
    _windows_from_point(wine, m.desktop, x, y, found)
    return found[0] if found else m.desktop


def target_window(wine, raw):
    """The window the server gives a raw message to: the capture window or the window under the
    point for the mouse; the focus window, else the active window, for the keyboard."""
    from .user_wnd import wm
    m = wm(wine)
    if raw.mouse:
        if m.capture and m.get(m.capture) is not None:
            return m.capture
        return _top_window_at(wine, raw.x, raw.y)
    if m.focus and m.get(m.focus) is not None:
        return m.focus
    return m.active if m.get(m.active) is not None else 0


def target_task(wine, raw):
    from .user_wnd import wm
    m = wm(wine)
    hwnd = target_window(wine, raw)
    if not hwnd or hwnd == m.desktop:
        # Nobody's window: the desktop's input goes to the active window's task, or none.
        return m.task_of(m.active) if m.get(m.active) is not None else 0
    return m.task_of(hwnd)


def task_idle(wine, task):
    """No posted message, no quit, nothing to paint in the task."""
    from .user_wnd import wm, _paint_window
    q = wm(wine).queue_of(task)
    return not q.queue and q.quit is None and not q.input and not _paint_window(wine, 0, task)


def head_for(wine, task):
    """The system queue's first raw message when it is the task's, with its due time set once
    the task is idle; else None. Win16 has one system queue: what is first goes first."""
    st = state(wine)
    if not st.raw:
        return None
    raw = st.raw[0]
    if target_task(wine, raw) != task:
        return None
    if raw.due is None:
        if not task_idle(wine, task):
            return None
        from .user_wnd import wm
        raw.due = wm(wine).clock + raw.delay
    return raw


def ready(wine, task):
    """A raw message for the task is due now."""
    from .user_wnd import wm
    raw = head_for(wine, task)
    return raw is not None and raw.due <= wm(wine).clock


def due_time(wine, task):
    """When the task's next raw message is due, or None."""
    raw = head_for(wine, task)
    return None if raw is None else raw.due


def filter_takes(first, last, raw):
    if not first and not last:
        return True
    if raw.mouse:
        return first <= MOUSE_LAST and last >= WM_NCMOUSEMOVE
    return first <= KEY_LAST and last >= KEY_FIRST


# ------------------------------------------------------------------ cooking

def _apply_device(wine, raw):
    """What the server does when the device reports: the cursor moves, keys go down or up."""
    from .user_wnd import wm, SCREEN_W, SCREEN_H
    st = state(wine)
    if raw.mouse:
        wm(wine).cursor_pos = (max(0, min(raw.x, SCREEN_W - 1)), max(0, min(raw.y, SCREEN_H - 1)))
        vk = BUTTONS.get(raw.msg)
    else:
        vk = raw.vk
    if vk is None:
        return
    if raw.msg in DOWNS or raw.msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
        if vk not in st.down:
            st.pressed.add(vk)
        st.down.add(vk)
    else:
        st.down.discard(vk)


def retrieved(wine, msg):
    """A task read an input message: the thread's key state follows it (the server's
    update_input_key_state on the thread's queue)."""
    st = state(wine)
    message = msg[1]
    if message in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
        vk, down = msg[2] & 0xFF, message in (WM_KEYDOWN, WM_SYSKEYDOWN)
    else:
        base = message - (WM_NCMOUSEMOVE - WM_MOUSEMOVE) if 0xA0 <= message <= 0xA9 else message
        if base in (WM_LBUTTONDBLCLK, WM_RBUTTONDBLCLK, WM_MBUTTONDBLCLK):
            base -= 2
        vk = BUTTONS.get(base)
        down = base in DOWNS
        if vk is None:
            return
    if down:
        if vk not in st.keys:
            st.toggled ^= {vk}
        st.keys.add(vk)
    else:
        st.keys.discard(vk)


def mk_flags(wine):
    down = state(wine).down
    flags = 0
    for vk, mk in ((VK_LBUTTON, MK_LBUTTON), (VK_RBUTTON, MK_RBUTTON), (VK_SHIFT, MK_SHIFT),
                   (VK_CONTROL, MK_CONTROL), (VK_MBUTTON, MK_MBUTTON)):
        if vk in down:
            flags |= mk
    return flags


def window_from_point_hit(wine, x, y):
    """win32u WINPOS_WindowFromPoint: (hwnd, hit). The windows under the point, deepest first;
    the first that is disabled (HTERROR), of another task (HTCLIENT), or whose WM_NCHITTEST is
    not HTTRANSPARENT."""
    from .user_wnd import wm, _windows_from_point, send, WS_DISABLED
    m = wm(wine)
    found = []
    _windows_from_point(wine, m.desktop, x, y, found)
    for hwnd in found:
        w = m.get(hwnd)
        if w is None:
            continue
        if w.style & WS_DISABLED:
            return hwnd, HTERROR
        if m.task_of(hwnd) != wine.htask:
            return hwnd, HTCLIENT
        hit = yield from send(wine, hwnd, WM_NCHITTEST, 0, (y & 0xFFFF) << 16 | (x & 0xFFFF))
        if hit & 0xFFFF != HTTRANSPARENT:
            return hwnd, hit & 0xFFFF
    return 0, HTNOWHERE


def _double_click(wine, raw, hwnd, msg):
    """process_mouse_message: a second press of the same button on the same window, soon
    enough and near enough, is a double click when the class has CS_DBLCLKS."""
    from .user_wnd import wm
    m = wm(wine)
    st = state(wine)
    if raw.msg not in DOWNS:
        return msg
    last = st.last_click
    w = m.get(hwnd)
    dbl = (last is not None and last[0] == raw.msg and last[1] == hwnd
           and m.clock - last[2] <= DOUBLE_CLICK_TIME
           and abs(raw.x - last[3]) <= DOUBLE_CLICK_SIZE // 2 and abs(raw.y - last[4]) <= DOUBLE_CLICK_SIZE // 2)
    if dbl and w is not None and w.cls is not None and w.cls.style & CS_DBLCLKS:
        st.last_click = None
        return msg + (WM_LBUTTONDBLCLK - WM_LBUTTONDOWN)
    st.last_click = (raw.msg, hwnd, m.clock, raw.x, raw.y)
    return msg


def cook_mouse(wine, raw):
    """process_mouse_message for one raw message. Returns the message (hwnd, msg, wp, lp), or
    None when it is eaten."""
    from .user_wnd import wm, send, scratch, scratch_mark, scratch_release, call_hook, \
        screen_origin, root_of, set_active, MESSAGE_NAMES
    m = wm(wine)
    _apply_device(wine, raw)
    x, y = m.cursor_pos
    if m.capture and m.get(m.capture) is not None:
        hwnd, hit = m.capture, HTCLIENT
    else:
        hwnd, hit = yield from window_from_point_hit(wine, x, y)
    if not hwnd:
        wine.trace.append(f"  input {MESSAGE_NAMES.get(raw.msg, hex(raw.msg))} ({x}, {y}): no window")
        return None
    msg = _double_click(wine, raw, hwnd, raw.msg) if hit == HTCLIENT else raw.msg
    if hit != HTCLIENT:
        msg += WM_NCMOUSEMOVE - WM_MOUSEMOVE
        wp, lp = hit, (y & 0xFFFF) << 16 | (x & 0xFFFF)
    else:
        ox, oy = screen_origin(wine, hwnd)
        wp, lp = mk_flags(wine), ((y - oy) & 0xFFFF) << 16 | ((x - ox) & 0xFFFF)
    wine.trace.append(f"  input {MESSAGE_NAMES.get(msg, hex(msg))} ({x}, {y}) -> {hwnd:#x} hit {signed(hit)}")
    if m.task_of(hwnd) != wine.htask:
        return hwnd, msg, wp, lp
    # WH_MOUSE: MOUSEHOOKSTRUCT16 {POINT16 pt; HWND16 hwnd; UINT16 wHitTestCode; DWORD dwExtraInfo}.
    if WH_MOUSE + 1 in wine.hooks:
        mark = scratch_mark(wine)
        mhs = scratch(wine, struct.pack("<hhHHI", x, y, hwnd, hit, 0))
        eaten = yield from call_hook(wine, WH_MOUSE + 1, HC_ACTION, msg, mhs)
        scratch_release(wine, mark)
        if eaten:
            return None
    if hit in (HTERROR, HTNOWHERE):
        # process_mouse_message: WM_SETCURSOR, and the message goes no further.
        yield from send(wine, hwnd, WM_SETCURSOR, hwnd, raw.msg << 16 | hit)
        return None
    eat = False
    if raw.msg in DOWNS:
        top = root_of(wine, hwnd)
        if top and top != m.active:
            r = yield from send(wine, hwnd, WM_MOUSEACTIVATE, top, raw.msg << 16 | hit)
            r &= 0xFFFF
            eat = r in (MA_ACTIVATEANDEAT, MA_NOACTIVATEANDEAT)
            if r in (MA_ACTIVATE, MA_ACTIVATEANDEAT, 0) and m.get(top) is not None:
                m.foreground = top
                yield from set_active(wine, top)
    if m.get(hwnd) is not None:
        yield from send(wine, hwnd, WM_SETCURSOR, hwnd, raw.msg << 16 | hit)
    if eat or m.get(hwnd) is None:
        return None
    return hwnd, msg, wp, lp


def key_lparam(raw, previously_down):
    scan = SCANS.get(raw.vk, 0)
    lp = 1 | (scan & 0xFF) << 16
    if scan & 0x100:
        lp |= 1 << 24
    if raw.msg in (WM_SYSKEYDOWN, WM_SYSKEYUP) and raw.vk != VK_MENU or VK_MENU in raw.alt_down:
        lp |= 1 << 29
    if previously_down:
        lp |= 1 << 30
    if raw.msg in (WM_KEYUP, WM_SYSKEYUP):
        lp |= 1 << 31
    return lp


def cook_key(wine, raw):
    """process_keyboard_message: the focus window, or the active window with WM_SYS... when
    there is no focus; the WH_KEYBOARD hook may eat it."""
    from .user_wnd import wm, call_hook, MESSAGE_NAMES
    m = wm(wine)
    st = state(wine)
    previously = raw.vk in st.down
    raw.alt_down = set(st.down)
    _apply_device(wine, raw)
    hwnd, msg = m.focus, raw.msg
    if not hwnd or m.get(hwnd) is None:
        hwnd = m.active
        if msg in (WM_KEYDOWN, WM_KEYUP):
            msg += WM_SYSKEYDOWN - WM_KEYDOWN
    if not hwnd or m.get(hwnd) is None:
        return None
    lp = key_lparam(raw, previously)
    wine.trace.append(f"  input {MESSAGE_NAMES.get(msg, hex(msg))} vk {raw.vk:#x} -> {hwnd:#x}")
    if WH_KEYBOARD + 1 in wine.hooks and m.task_of(hwnd) == wine.htask:
        eaten = yield from call_hook(wine, WH_KEYBOARD + 1, HC_ACTION, raw.vk, lp)
        if eaten:
            return None
    return hwnd, msg, raw.vk, lp


def cook_calls(wine, first, last):
    """The current task's due raw message, cooked into its queue's input list. Returns None
    when there is nothing to cook, "cooked" when it took no guest call, a GuestCalls whose
    waiting call looks again afterwards, or (ax, dx, stop)."""
    from .guest import GuestCalls, drive
    from .user_wnd import wm
    raw = head_for(wine, wine.htask)
    m = wm(wine)
    if raw is None or raw.due > m.clock or not filter_takes(first, last, raw):
        return None
    state(wine).raw.pop(0)

    def cook():
        cooked = yield from (cook_mouse(wine, raw) if raw.mouse else cook_key(wine, raw))
        if cooked is not None:
            m.queue_of(m.task_of(cooked[0])).input.append(cooked)
        return 0

    res = drive(cook())
    if isinstance(res, GuestCalls):
        res.retry = True
        return res
    if res[2]:
        return res
    return "cooked"            # no guest call was needed; the caller looks again itself


# ------------------------------------------------------------------ TranslateMessage

def char_for(vk, down):
    """The character a key makes on a US layout (ToAscii), or None."""
    shift, ctrl = VK_SHIFT in down, VK_CONTROL in down
    if 0x41 <= vk <= 0x5A:
        if ctrl:
            return vk - 0x40
        return vk if shift else vk + 0x20
    if 0x30 <= vk <= 0x39 and not ctrl:
        return ")!@#$%^&*("[vk - 0x30] if shift else vk
    return {0x20: 0x20, 0x0D: 0x0D, 0x1B: 0x1B, 0x08: 0x08, 0x09: 0x09}.get(vk)
