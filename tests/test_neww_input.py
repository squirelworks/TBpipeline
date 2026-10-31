"""Hardware input: the input script, the system queue and the cooking of mouse and key messages.

Each test checks against the Wine function its comment names (win32u message.c
process_mouse_message, process_keyboard_message, the server's queue_hardware_message and
set_cursor_pos, user32 TranslateMessage). No ToolBook bytes: handlers run on fake memory
(tests/test_neww_batch2.py's harness), and the window procedure is a guest call whose answer
the test gives.
"""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name
from tests.test_neww_batch6 import control_wine, top_window

HTCLIENT, HTCAPTION = 1, 2
MSG = (DATA, 0x400)


def settle(w):
    """Nothing left to paint: the windows are as a book leaves them once drawn."""
    from tbpipeline_neww.user_wnd import wm
    for win in wm(w).windows.values():
        win.update = None
        win.ncpaint = False


def answer(hits):
    """A window procedure: WM_NCHITTEST answers hits (one code, or a dict hwnd -> code),
    WM_MOUSEACTIVATE MA_ACTIVATE, the rest 0. Records each (hwnd, msg, wp, lp)."""
    seen = []

    def reply(call):
        hwnd, msg, wp = call.words[0], call.words[1], call.words[2]
        lp = call.words[3] << 16 | call.words[4]
        seen.append((hwnd, msg, wp, lp))
        if msg == 0x84:
            return (hits.get(hwnd, HTCLIENT) if isinstance(hits, dict) else hits), 0
        if msg == 0x21:
            return 1, 0
        if msg == 0x81:
            return 1, 0
        return 0, 0
    reply.seen = seen
    return reply


def get(w, reply=None, name="GetMessage", *extra):
    """GetMessage (or PeekMessage) as the gate makes it: a call that cooks input runs its guest
    calls and then runs again. Returns (ax, stop, (hwnd, msg, wp, lp, time, x, y))."""
    for _ in range(20):
        ax, _dx, stop, _calls = by_name(w, "USER", name, MSG, 0, 0, 0, *extra, reply=reply)
        request = (w.registers or {}).get("guest")
        if request is not None and request.retry and not stop:
            continue
        msg = struct.unpack("<HHHIIhh", w.memory.read(DATA, 0x400, 18))
        return ax, stop, (msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], msg[6])
    raise AssertionError("GetMessage kept cooking")


def origin(w, hwnd):
    from tbpipeline_neww.user_wnd import screen_origin
    return screen_origin(w, hwnd)


class Script(unittest.TestCase):
    """input16.parse: each step's raw messages; the first waits for the task to be idle."""

    def test_click_is_a_move_then_the_button(self):
        from tbpipeline_neww.input16 import parse
        (step,) = parse("click 400,300")
        self.assertEqual([(r.msg, r.x, r.y) for r in step],
                         [(0x200, 400, 300), (0x201, 400, 300), (0x202, 400, 300)])
        self.assertEqual([r.idle for r in step], [True, False, False])
        self.assertEqual([r.due for r in step], [None, 0, 0])

    def test_keys_modifiers_and_typing(self):
        from tbpipeline_neww.input16 import parse
        (ctrl_right,) = parse("key ctrl+right")
        self.assertEqual([(r.msg, r.vk) for r in ctrl_right],
                         [(0x100, 0x11), (0x100, 0x27), (0x101, 0x27), (0x101, 0x11)])
        (alt_f,) = parse("key alt+f")
        self.assertEqual([r.msg for r in alt_f], [0x104, 0x104, 0x105, 0x105])
        (typed,) = parse("type Hi")
        self.assertEqual([(r.msg, r.vk) for r in typed],
                         [(0x100, 0x10), (0x100, 0x48), (0x101, 0x48), (0x101, 0x10), (0x100, 0x49), (0x101, 0x49)])

    def test_wait_delays_the_next_step(self):
        from tbpipeline_neww.input16 import parse
        a, b = parse("move 1,2; wait 250; wait 250\nkey enter")
        self.assertEqual((a[0].delay, b[0].delay), (0, 500))

    def test_unknown_steps_and_keys_are_refused(self):
        from tbpipeline_neww.input16 import parse
        with self.assertRaises(ValueError):
            parse("jump 1,2")
        with self.assertRaises(ValueError):
            parse("key hyper")


class Mouse(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()
        self.hwnd = top_window(self.w)
        settle(self.w)
        self.ox, self.oy = origin(self.w, self.hwnd)

    def test_a_click_in_the_client(self):
        # process_mouse_message: WM_NCHITTEST picks HTCLIENT, the point goes to client
        # coordinates, wParam is the MK_ state after the event; WM_SETCURSOR (hwnd, MAKELONG(hit,
        # raw message)) goes to the window before each message is returned.
        from tbpipeline_neww.input16 import queue_script
        x, y = self.ox + 30, self.oy + 40
        queue_script(self.w, f"click {x},{y}")
        reply = answer(HTCLIENT)
        got = [get(self.w, reply)[2] for _ in range(3)]
        lp = 40 << 16 | 30
        self.assertEqual([g[:4] for g in got], [(self.hwnd, 0x200, 0, lp), (self.hwnd, 0x201, 1, lp),
                                                (self.hwnd, 0x202, 0, lp)])
        # MSG.pt is the cursor on the screen.
        self.assertEqual(got[1][5:], (x, y))
        sent = [(s[1], s[2], s[3]) for s in reply.seen]
        self.assertEqual(sent[:2], [(0x84, 0, y << 16 | x), (0x20, self.hwnd, 0x200 << 16 | HTCLIENT)])
        self.assertIn((0x20, self.hwnd, 0x201 << 16 | HTCLIENT), sent)
        # The window was active already: no WM_MOUSEACTIVATE.
        self.assertNotIn(0x21, [s[0] for s in sent])
        ax, _dx, _stop, _ = by_name(self.w, "USER", "GetMessagePos")
        self.assertEqual(ax | _dx << 16, y << 16 | x)

    def test_a_click_on_the_frame_is_a_non_client_message(self):
        # A hit other than HTCLIENT: WM_NC... with the hit code and screen coordinates. The
        # window procedure's WM_NCHITTEST answer decides, wherever the point is.
        from tbpipeline_neww.input16 import queue_script
        x, y = self.ox + 5, self.oy + 5
        queue_script(self.w, f"click {x},{y}")
        got = [get(self.w, answer(HTCAPTION))[2][:4] for _ in range(3)]
        self.assertEqual([g[1] for g in got], [0xA0, 0xA1, 0xA2])
        self.assertEqual({(g[2], g[3]) for g in got}, {(HTCAPTION, y << 16 | x)})

    def test_key_state_follows_the_button(self):
        from tbpipeline_neww.input16 import queue_script
        queue_script(self.w, f"click {self.ox + 1},{self.oy + 1}")
        get(self.w, answer(HTCLIENT))
        get(self.w, answer(HTCLIENT))
        # NtUserGetKeyState: (signed char)(state & 0x81) while down, plus the toggle.
        self.assertEqual(by_name(self.w, "USER", "GetKeyState", 1)[0], 0xFF81)
        self.assertEqual(by_name(self.w, "USER", "GetAsyncKeyState", 1)[0], 0x8001)
        self.assertEqual(by_name(self.w, "USER", "GetAsyncKeyState", 1)[0], 0x8000)
        get(self.w, answer(HTCLIENT))
        self.assertEqual(by_name(self.w, "USER", "GetKeyState", 1)[0], 0x0001)

    def test_input_waits_for_posted_messages_and_paint(self):
        # A step waits until its task is idle; within the step, input comes after posted
        # messages and before WM_PAINT (get_message's order).
        from tbpipeline_neww.input16 import queue_script
        from tbpipeline_neww.user_wnd import wm
        by_name(self.w, "USER", "PostMessage", self.hwnd, 0x400, 7, (0, 0))
        wm(self.w).get(self.hwnd).update = (0, 0, 10, 10)
        queue_script(self.w, f"click {self.ox + 1},{self.oy + 1}")
        reply = answer(HTCLIENT)
        first = get(self.w, reply)[2]
        self.assertEqual(first[1], 0x400)
        self.assertEqual(get(self.w, reply)[2][1], 0x0F)       # WM_PAINT: still not idle
        wm(self.w).get(self.hwnd).update = None
        self.assertEqual(get(self.w, reply)[2][1], 0x200)
        # The button follows at once, ahead of a new WM_PAINT.
        wm(self.w).get(self.hwnd).update = (0, 0, 10, 10)
        self.assertEqual(get(self.w, reply)[2][1], 0x201)
        self.assertEqual(get(self.w, reply)[2][1], 0x202)
        self.assertEqual(get(self.w, reply)[2][1], 0x0F)

    def test_capture_takes_the_mouse_without_a_hit_test(self):
        # A capture window gets the mouse wherever it is, with HTCLIENT and no WM_NCHITTEST.
        from tbpipeline_neww.input16 import queue_script
        by_name(self.w, "USER", "SetCapture", self.hwnd)
        queue_script(self.w, "move 1000,700")
        reply = answer(HTCAPTION)
        hwnd, msg, wp, lp = get(self.w, reply)[2][:4]
        self.assertEqual((hwnd, msg), (self.hwnd, 0x200))
        self.assertEqual(lp, ((700 - self.oy) & 0xFFFF) << 16 | ((1000 - self.ox) & 0xFFFF))
        self.assertNotIn(0x84, [s[1] for s in reply.seen])

    def test_a_press_on_an_inactive_window_activates_it(self):
        # process_mouse_message: a button down on a top-level window that is not the active one
        # sends WM_MOUSEACTIVATE (top, MAKELONG(hit, message)); MA_ACTIVATE activates it.
        from tbpipeline_neww.input16 import queue_script
        from tbpipeline_neww.user_wnd import wm
        other = top_window(self.w, style=(0x10CF, 0))
        settle(self.w)
        m = wm(self.w)
        self.assertEqual(m.active, other)
        queue_script(self.w, f"click {self.ox + 2},{self.oy + 2}")
        reply = answer({other: 0xFFFF, self.hwnd: HTCLIENT})
        for _ in range(3):
            get(self.w, reply)
        self.assertIn((self.hwnd, 0x21, self.hwnd, 0x201 << 16 | HTCLIENT), reply.seen)
        self.assertEqual(m.active, self.hwnd)

    def test_double_click_needs_cs_dblclks(self):
        # A second press within GetDoubleClickTime and SM_CXDOUBLECLK is WM_LBUTTONDBLCLK when the
        # class has CS_DBLCLKS; without it, two WM_LBUTTONDOWN.
        from tbpipeline_neww.input16 import queue_script
        x, y = self.ox + 3, self.oy + 3
        queue_script(self.w, f"dblclick {x},{y}")
        msgs = [get(self.w, answer(HTCLIENT))[2][1] for _ in range(5)]
        self.assertEqual(msgs, [0x200, 0x201, 0x202, 0x201, 0x202])
        from tbpipeline_neww.user_wnd import wm
        wm(self.w).get(self.hwnd).cls.style |= 0x8
        queue_script(self.w, f"dblclick {x + 50},{y}")
        msgs = [get(self.w, answer(HTCLIENT))[2][1] for _ in range(5)]
        self.assertEqual(msgs, [0x200, 0x201, 0x202, 0x203, 0x202])
        self.assertEqual(by_name(self.w, "USER", "GetDoubleClickTime")[0], 500)

    def test_set_cursor_pos_queues_a_move(self):
        # The server's set_cursor_pos queues WM_MOUSEMOVE for the window under the cursor.
        by_name(self.w, "USER", "SetCursorPos", self.ox + 7, self.oy + 9)
        hwnd, msg, wp, lp = get(self.w, answer(HTCLIENT))[2][:4]
        self.assertEqual((hwnd, msg, lp), (self.hwnd, 0x200, 9 << 16 | 7))

    def test_queue_status_and_input_state(self):
        from tbpipeline_neww.input16 import queue_script
        self.assertEqual(by_name(self.w, "USER", "GetInputState")[0], 0)
        queue_script(self.w, f"click {self.ox + 1},{self.oy + 1}")
        # The move is due: QS_MOUSEMOVE, and GetInputState counts only buttons and keys.
        self.assertEqual(by_name(self.w, "USER", "GetQueueStatus", 0x07)[0], 0x02)
        self.assertEqual(by_name(self.w, "USER", "GetInputState")[0], 0)
        get(self.w, answer(HTCLIENT))
        self.assertEqual(by_name(self.w, "USER", "GetInputState")[0], 1)

    def test_wait_moves_the_clock_when_the_task_has_nothing_else(self):
        from tbpipeline_neww.input16 import queue_script
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        start = m.clock
        queue_script(self.w, f"wait 750; move {self.ox + 1},{self.oy + 1}")
        _ax, _stop, msg = get(self.w, answer(HTCLIENT))
        self.assertEqual(msg[1], 0x200)
        self.assertEqual(m.clock, start + 750)
        self.assertEqual(msg[4], start + 750)

    def test_a_timer_before_the_input_comes_first(self):
        from tbpipeline_neww.input16 import queue_script
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        start = m.clock
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        queue_script(self.w, f"wait 750; move {self.ox + 1},{self.oy + 1}")
        msg = get(self.w, answer(HTCLIENT))[2]
        self.assertEqual((msg[1], m.clock), (0x113, start + 100))

    def test_a_point_on_no_window_is_dropped_and_the_next_comes(self):
        from tbpipeline_neww.input16 import queue_script
        queue_script(self.w, f"move 1020,760; move {self.ox + 1},{self.oy + 1}")
        msg = get(self.w, answer(HTCLIENT))[2]
        self.assertEqual((msg[0], msg[1]), (self.hwnd, 0x200))
        self.assertIn("  input WM_MOUSEMOVE (1020, 760): no window", self.w.trace)

    def test_no_input_left_stops_as_before(self):
        _ax, stop, _msg = get(self.w, answer(HTCLIENT))
        self.assertIn("the input script has no more for it", stop)


class MouseAsWineDoes(unittest.TestCase):
    """process_mouse_message details: WM_PARENTNOTIFY, WM_MOUSEACTIVATE to a child of the active
    window, capture and PM_NOREMOVE returning before activation, and the double click bounds."""

    def setUp(self):
        from tbpipeline_neww.user_wnd import wm
        from tests.test_neww_batch1_handlers import NUL, put
        from tests.test_neww_batch2 import INST
        self.w = control_wine()
        self.hwnd = top_window(self.w)
        cls = put(self.w, 0x20, "TBKMain")
        self.child = by_name(self.w, "USER", "CreateWindow", cls, NUL, (0x5000, 0), 10, 10, 100, 50,
                             self.hwnd, 7, INST, NUL, reply=answer(HTCLIENT))[0]
        settle(self.w)
        self.m = wm(self.w)
        self.cx, self.cy = origin(self.w, self.child)
        self.px, self.py = origin(self.w, self.hwnd)

    def test_a_press_on_a_child_notifies_and_mouse_activates(self):
        # send_parent_notify: WM_PARENTNOTIFY (WM_LBUTTONDOWN, 0) with the point in the parent's
        # client coordinates. msg->hwnd != hwndActive, and its root is a top-level window, so
        # the child gets WM_MOUSEACTIVATE (root, MAKELONG(hit, message)) though its root is
        # active. Then WM_SETCURSOR.
        from tbpipeline_neww.input16 import queue_script
        self.assertEqual(self.m.active, self.hwnd)
        x, y = self.cx + 5, self.cy + 6
        queue_script(self.w, f"click {x},{y}")
        reply = answer(HTCLIENT)
        got = [get(self.w, reply)[2][:2] for _ in range(3)]
        self.assertEqual(got, [(self.child, 0x200), (self.child, 0x201), (self.child, 0x202)])
        down = reply.seen[[i for i, s in enumerate(reply.seen) if s[1] == 0x84][1]:]
        self.assertEqual([(s[0], s[1]) for s in down[:4]],
                         [(self.child, 0x84), (self.hwnd, 0x210), (self.child, 0x21), (self.child, 0x20)])
        self.assertEqual(down[1][2:], (0x201, (y - self.py) << 16 | (x - self.px)))
        self.assertEqual(down[2][2:], (self.hwnd, 0x201 << 16 | HTCLIENT))
        # The button up sends neither.
        self.assertEqual([s[1] for s in down[4:]], [0x84, 0x20])

    def test_no_parent_notify_with_ws_ex_noparentnotify(self):
        from tbpipeline_neww.input16 import queue_script
        self.m.get(self.child).exstyle |= 0x4
        queue_script(self.w, f"click {self.cx + 1},{self.cy + 1}")
        reply = answer(HTCLIENT)
        for _ in range(3):
            get(self.w, reply)
        self.assertNotIn(0x210, [s[1] for s in reply.seen])

    def test_capture_returns_before_activation_and_set_cursor(self):
        from tbpipeline_neww.input16 import queue_script
        by_name(self.w, "USER", "SetCapture", self.child)
        queue_script(self.w, f"click {self.cx + 1},{self.cy + 1}")
        reply = answer(HTCLIENT)
        got = [get(self.w, reply)[2][:2] for _ in range(3)]
        self.assertEqual(got, [(self.child, 0x200), (self.child, 0x201), (self.child, 0x202)])
        self.assertEqual(reply.seen, [])

    def test_peek_without_remove_leaves_it_queued(self):
        # !remove: the message comes back after the hook, with no WM_SETCURSOR, and stays in
        # the queue; PM_REMOVE then processes it in full.
        from tbpipeline_neww.input16 import queue_script, state
        queue_script(self.w, f"move {self.cx + 1},{self.cy + 1}")
        reply = answer(HTCLIENT)
        ax, _stop, msg = get(self.w, reply, "PeekMessage", 0)
        self.assertEqual((ax, msg[0], msg[1]), (1, self.child, 0x200))
        self.assertEqual([s[1] for s in reply.seen], [0x84])
        self.assertEqual(len(state(self.w).raw), 1)
        ax, _stop, msg = get(self.w, reply, "PeekMessage", 1)
        self.assertEqual((ax, msg[1]), (1, 0x200))
        self.assertEqual([s[1] for s in reply.seen], [0x84, 0x84, 0x20])
        self.assertEqual(state(self.w).raw, [])

    def test_a_message_dropped_on_a_peek_leaves_the_queue(self):
        # accept_hardware_message: when WH_MOUSE eats the message, it leaves the queue even
        # without PM_REMOVE; the next look does not call the hook for it again.
        from tbpipeline_neww.input16 import queue_script, state
        self.w.hooks[8] = (0x00010001, 0x0130_0010)
        hooked = []

        def reply(call):
            if (call.cs, call.ip) == (0x0130, 0x0010):
                hooked.append((call.words[0], call.words[1]))
                return 1, 0
            return (HTCLIENT, 0) if call.words[1] == 0x84 else (0, 0)
        queue_script(self.w, f"move {self.cx + 1},{self.cy + 1}")
        ax, _stop, _msg = get(self.w, reply, "PeekMessage", 0)
        self.assertEqual(ax, 0)
        self.assertEqual(hooked, [(3, 0x200)])      # HC_NOREMOVE
        self.assertEqual(state(self.w).raw, [])
        get(self.w, reply, "PeekMessage", 0)
        self.assertEqual(hooked, [(3, 0x200)])

    def test_non_client_double_click_needs_no_class_style(self):
        from tbpipeline_neww.input16 import queue_script
        queue_script(self.w, f"dblclick {self.px + 3},{self.py + 3}")
        msgs = [get(self.w, answer({self.hwnd: HTCAPTION, self.child: HTCAPTION}))[2][1] for _ in range(5)]
        self.assertEqual(msgs, [0xA0, 0xA1, 0xA2, 0xA3, 0xA2])

    def test_double_click_bounds_are_strict(self):
        # time - clk.time < GetDoubleClickTime(), abs(dx) < SM_CXDOUBLECLK / 2.
        from tbpipeline_neww.input16 import queue_script
        self.m.get(self.child).cls.style |= 0x8
        x, y = self.cx + 5, self.cy + 5
        queue_script(self.w, f"click {x},{y}; wait 500; click {x},{y}")
        msgs = [get(self.w, answer(HTCLIENT))[2][1] for _ in range(6)]
        self.assertEqual(msgs[3:5], [0x200, 0x201])
        queue_script(self.w, f"click {x + 2},{y}")
        msgs = [get(self.w, answer(HTCLIENT))[2][1] for _ in range(3)]
        self.assertEqual(msgs[1], 0x201)
        queue_script(self.w, f"click {x + 3},{y}")
        msgs = [get(self.w, answer(HTCLIENT))[2][1] for _ in range(3)]
        self.assertEqual(msgs[1], 0x203)


class Keyboard(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()
        self.hwnd = top_window(self.w)
        settle(self.w)

    def test_keys_go_to_the_focus_and_translate_to_characters(self):
        # process_keyboard_message: the focus window; lParam is repeat 1, the scan code, bit 30
        # the previous state and bit 31 the transition. TranslateMessage posts WM_CHAR.
        from tbpipeline_neww.input16 import queue_script
        from tbpipeline_neww.user_wnd import wm
        self.assertEqual(wm(self.w).focus, self.hwnd)
        queue_script(self.w, "type A")
        got = []
        for _ in range(5):
            msg = get(self.w)[2]
            got.append(msg[:4])
            self.w.memory.write(DATA, 0x400, struct.pack("<HHHI", *msg[:4]))
            by_name(self.w, "USER", "TranslateMessage", MSG)
        self.assertEqual(got, [
            (self.hwnd, 0x100, 0x10, 0x002A0001),
            (self.hwnd, 0x100, 0x41, 0x001E0001),
            (self.hwnd, 0x102, ord("A"), 0x001E0001),
            (self.hwnd, 0x101, 0x41, 0xC01E0001),
            (self.hwnd, 0x101, 0x10, 0xC02A0001),
        ])

    def test_extended_keys_and_key_state(self):
        from tbpipeline_neww.input16 import queue_script
        queue_script(self.w, "key ctrl+right")
        get(self.w)
        msg = get(self.w)[2]
        self.assertEqual((msg[1], msg[2], msg[3]), (0x100, 0x27, 0x014D0001))
        self.assertEqual(by_name(self.w, "USER", "GetKeyState", 0x11)[0], 0xFF81)
        by_name(self.w, "USER", "GetKeyboardState", (DATA, 0x500))
        self.assertEqual(self.w.memory.read(DATA, 0x500 + 0x27, 1), b"\x81")

    def test_f1_posts_wm_keyf1(self):
        # process_keyboard_message: a removed WM_KEYDOWN of VK_F1 posts WM_KEYF1.
        from tbpipeline_neww.input16 import queue_script
        queue_script(self.w, "key f1")
        self.assertEqual(get(self.w)[2][1:3], (0x100, 0x70))
        self.assertEqual(get(self.w)[2][:2], (self.hwnd, 0x4D))
        self.assertEqual(get(self.w)[2][1], 0x101)

    def test_f1_is_posted_before_the_keyboard_hook_eats_it(self):
        # WM_KEYF1 goes out before WH_KEYBOARD runs (process_keyboard_message), so a hook that
        # eats F1 still leaves it.
        from tbpipeline_neww.input16 import queue_script
        self.w.hooks[3] = (0x00010001, 0x0130_0010)
        hooked = []

        def reply(call):
            if (call.cs, call.ip) == (0x0130, 0x0010):
                hooked.append(call.words[1])
                return 1, 0          # eaten
            return 0, 0
        queue_script(self.w, "key f1")
        msg = get(self.w, reply)[2]
        self.assertEqual(msg[:2], (self.hwnd, 0x4D))
        self.assertEqual(hooked, [0x70, 0x70])     # the down and the up, both eaten

    def test_without_a_focus_the_active_window_gets_sys_keys(self):
        from tbpipeline_neww.input16 import queue_script
        from tbpipeline_neww.user_wnd import wm
        wm(self.w).focus = 0
        queue_script(self.w, "key esc")
        msg = get(self.w)[2]
        self.assertEqual((msg[0], msg[1], msg[2]), (self.hwnd, 0x104, 0x1B))


class MenuBar(unittest.TestCase):
    """A menu with no items has no bar (user_wnd.menu_bar_height), so a window sized for its
    page alone keeps the whole page; a menu with items has its bar."""

    def setUp(self):
        self.w = control_wine()
        self.hwnd = top_window(self.w)

    def client_top(self):
        # handle_nc_calc_size on the window's own rectangle (the test's window procedure is a
        # guest stand-in that leaves WM_NCCALCSIZE alone).
        from tbpipeline_neww.user_wnd import wm, nc_calc_size
        w = wm(self.w).get(self.hwnd)
        return nc_calc_size(self.w, w, w.rect)[1]

    def test_empty_menu_takes_no_room(self):
        before = self.client_top()
        menu = by_name(self.w, "USER", "CreateMenu")[0]
        self.assertEqual(by_name(self.w, "USER", "SetMenu", self.hwnd, menu)[0], 1)
        self.assertEqual(self.client_top(), before)

    def test_a_menu_with_items_has_its_bar(self):
        from tbpipeline_neww.user_wnd import MENU_HEIGHT
        from tests.test_neww_batch1_handlers import put
        before = self.client_top()
        menu = by_name(self.w, "USER", "CreateMenu")[0]
        by_name(self.w, "USER", "AppendMenu", menu, 0, 1, put(self.w, 0x80, "&File"))
        by_name(self.w, "USER", "SetMenu", self.hwnd, menu)
        self.assertEqual(self.client_top(), before + MENU_HEIGHT + 1)


class Rop2(unittest.TestCase):
    """Binary raster ops for pens and Rectangle's brush: R2 - 1 is the truth table, bit
    (P << 1 | D), as the dib driver's get_rop_codes reads it."""

    def test_rop3_of_each_named_rop2(self):
        from tbpipeline_neww.gdi16 import rop2_rop3
        # R2_COPYPEN is PATCOPY, R2_XORPEN PATINVERT, R2_NOT DSTINVERT, R2_NOP leaves D,
        # R2_BLACK BLACKNESS, R2_WHITE WHITENESS, R2_MASKPEN 0xA0 (P and D).
        self.assertEqual([rop2_rop3(r) >> 16 for r in (13, 7, 6, 11, 1, 16, 9)],
                         [0xF0, 0x5A, 0x55, 0xAA, 0x00, 0xFF, 0xA0])

    def test_xor_rectangle_outline_on_a_color_bitmap(self):
        call = lambda name, *a: by_name(self.w, "GDI", name, *a)[0]
        self.w = control_wine()
        screen = by_name(self.w, "USER", "GetDC", 0)[0]
        dc = call("CreateCompatibleDC", screen)
        call("SelectObject", dc, call("CreateCompatibleBitmap", screen, 8, 8))
        call("PatBlt", dc, 0, 0, 8, 8, (0x00FF, 0x0062))           # WHITENESS
        call("SelectObject", dc, call("GetStockObject", 6))        # WHITE_PEN
        call("SelectObject", dc, call("GetStockObject", 5))        # NULL_BRUSH
        call("SetROP2", dc, 7)                                     # R2_XORPEN
        self.assertEqual(by_name(self.w, "GDI", "Rectangle", dc, 0, 0, 6, 6)[2], None)
        pixel = lambda x, y: (lambda r: r[0] | r[1] << 16)(by_name(self.w, "GDI", "GetPixel", dc, x, y))
        self.assertEqual((pixel(0, 0), pixel(5, 3), pixel(3, 3), pixel(7, 7)), (0, 0, 0xFFFFFF, 0xFFFFFF))


class LogicFamiliesClicks(unittest.TestCase):
    def test_title_click_next_and_back(self):
        # TBK_BIN, and TBK_BOOK2: Logic Families with nida81.tbk beside it. A click on the title
        # page goes to P10; its right arrow sends Next and shows P100 (OBJECTIVES); the left
        # arrow there sends Previous and P10 comes back. No error box.
        import os
        from pathlib import Path
        from tests.binpath import bin_or_skip
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80F32L.dll", "TB80RMT.DLL")
        book = os.environ.get("TBK_BOOK2")
        if not book or not (Path(book).parent / "nida81.tbk").exists():
            raise unittest.SkipTest("TBK_BOOK2 is not set, or has no nida81.tbk beside it")
        from tbpipeline_neww.machine import Machine
        host = Machine(str(root), book, input_script="click 512,420; click 808,600; click 215,600")
        host.call_limit = 300000
        host.timeout_us = 600_000_000
        host.run(limit=300000 * 1000)
        trace = host.box.wine.trace
        print(f"\nneww stop: {host.stop} after {len(trace)} trace lines")
        self.assertEqual(host.box.wine.input.raw, [])
        self.assertEqual([t for t in trace if t.startswith("USER.1 MessageBox")], [])
        downs = [i for i, t in enumerate(trace) if t.startswith("  input WM_LBUTTONDOWN")]
        self.assertEqual(len(downs), 3)
        after = lambda i: [t for t in trace[downs[i]:downs[i + 1] if i + 1 < len(downs) else None]]
        self.assertTrue(any("'P10'" in t for t in after(0)))
        self.assertTrue(any("'Next'" in t for t in after(1)))
        self.assertTrue(any("'OBJECTIVES'" in t for t in after(1)))
        self.assertTrue(any("'Previous'" in t for t in after(2)))
        self.assertTrue(any("'P10'" in t for t in after(2)))


class Command(unittest.TestCase):
    def test_help_names_the_input_option(self):
        import io
        from contextlib import redirect_stdout
        from tbpipeline_neww.__main__ import main
        out = io.StringIO()
        with redirect_stdout(out):
            main(["--help"])
        self.assertIn("--input", out.getvalue())


if __name__ == "__main__":
    unittest.main()
