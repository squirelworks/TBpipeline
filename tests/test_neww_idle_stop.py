"""Roadmap #201 T1: a task that has had all of its input script and would only wait for a
later timer ends the run on a named idle stop, instead of running timers to the call limit.

Wine's NtUserGetMessage (dlls/win32u/message.c:3640-3643, at 2528aff2) loops on peek_message
and blocks in wait_objects while nothing is there. No ToolBook bytes: handlers run on fake
memory (tests/test_neww_batch2.py's harness).
"""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name
from tests.test_neww_batch6 import control_wine, top_window
from tests.test_neww_input import HTCLIENT, answer, origin, settle

MSG = (DATA, 0x400)
# GetMessage's return address on the fake stack, as the guest's far call leaves it.
STACK = {"ss": DATA, "sp": 0x500}
CALLER = (0x1478, 0x0BB7)


def get(w, reply):
    """GetMessage with the caller's CS:IP on the stack: (ax, stop, msg)."""
    w.memory.write(DATA, STACK["sp"], struct.pack("<HH", CALLER[1], CALLER[0]))
    for _ in range(20):
        ax, _dx, stop, _calls = by_name(w, "USER", "GetMessage", MSG, 0, 0, 0, reply=reply, regs=STACK)
        request = (w.registers or {}).get("guest")
        if request is not None and request.retry and not stop:
            continue
        msg = struct.unpack("<HHHIIhh", w.memory.read(DATA, 0x400, 18))
        return ax, stop, msg
    raise AssertionError("GetMessage kept cooking")


class IdleStop(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()
        self.hwnd = top_window(self.w)
        settle(self.w)
        self.ox, self.oy = origin(self.w, self.hwnd)
        self.reply = answer(HTCLIENT)

    def click(self):
        from tbpipeline_neww.input16 import queue_script
        queue_script(self.w, f"click {self.ox + 5},{self.oy + 5}")
        got = [get(self.w, self.reply)[2][1] for _ in range(3)]
        self.assertEqual(got, [0x200, 0x201, 0x202])

    def test_script_done_and_a_later_timer_is_a_named_idle_stop(self):
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        self.click()
        start = m.clock
        ax, stop, _msg = get(self.w, self.reply)
        self.assertEqual(ax, 0)
        self.assertEqual(stop, "idle: input script done, task waiting in GetMessage at "
                               "0x1478:0xbb7, next timer in 100 ms")
        # The clock did not move to the timer.
        self.assertEqual(m.clock, start)

    def test_script_done_and_a_timer_due_now_still_gets_wm_timer(self):
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        self.click()
        m.clock += 100
        ax, stop, msg = get(self.w, self.reply)
        self.assertEqual((ax, stop, msg[1]), (1, None, 0x113))

    def test_script_done_and_a_posted_message_is_returned(self):
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        self.click()
        by_name(self.w, "USER", "PostMessage", self.hwnd, 0x400, 7, (0, 0))
        ax, stop, msg = get(self.w, self.reply)
        self.assertEqual((ax, stop, msg[1], msg[2]), (1, None, 0x400, 7))

    def test_without_an_input_script_the_clock_moves_to_the_timer(self):
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        start = m.clock
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        ax, stop, msg = get(self.w, self.reply)
        self.assertEqual((ax, stop, msg[1], m.clock), (1, None, 0x113, start + 100))

    def test_idle_stop_without_an_input_script_waits_for_the_first_tick(self):
        # Roadmap #201 T2: a run that asks for the idle stop (the command line's default) and
        # has no input script still gets its first timer tick, then ends at the next idle point.
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        self.w.idle_stop = True
        start = m.clock
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        ax, stop, msg = get(self.w, self.reply)
        self.assertEqual((ax, stop, msg[1], m.clock), (1, None, 0x113, start + 100))
        ax, stop, _msg = get(self.w, self.reply)
        self.assertEqual(ax, 0)
        self.assertEqual(stop, "idle: no input script, task waiting in GetMessage at "
                               "0x1478:0xbb7, next timer in 100 ms")
        self.assertEqual(m.clock, start + 100)

    def test_a_multimedia_timer_callback_is_a_tick_too(self):
        from tbpipeline_neww.user_wnd import wm
        m = wm(self.w)
        self.w.idle_stop = True
        self.w.mm_ticks = 1
        start = m.clock
        by_name(self.w, "USER", "SetTimer", self.hwnd, 5, 100, (0, 0))
        _ax, stop, _msg = get(self.w, self.reply)
        self.assertEqual(stop, "idle: no input script, task waiting in GetMessage at "
                               "0x1478:0xbb7, next timer in 100 ms")
        self.assertEqual(m.clock, start)

    def test_no_timer_and_no_input_left_is_the_same_named_stop(self):
        self.click()
        _ax, stop, _msg = get(self.w, self.reply)
        self.assertEqual(stop, "idle: input script done, task waiting in GetMessage at "
                               "0x1478:0xbb7, no timer set")


if __name__ == "__main__":
    unittest.main()
