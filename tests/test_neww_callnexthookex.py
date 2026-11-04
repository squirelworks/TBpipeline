"""USER.293 CallNextHookEx finds no next hook for a 16-bit task, so it is 0 and calls nothing.

Roadmap #201 T3. Spec (user.exe16.spec:293): `293 pascal CallNextHookEx(segptr s_word word long)
CallNextHookEx16`, a long. At Wine 2528aff2, user.exe16/hook.c:523-528 CallNextHookEx16 is 0
when the thread has no 16-bit hook info. Otherwise it maps the lParam for the running hook's
kind and calls user32 CallNextHookEx (hook.c:530-...). win32u/hook.c:362-393
NtUserCallNextHookEx asks the server for the hook after the thread's running hook
(get_next = 1), and server/hook.c:242-270 get_next_hook walks the rest of that hook's chain in
the thread's table, then the global table. win32u call_hook (hook.c:206-239) calls nothing and
returns 0 when no hook is found.

A 16-bit task can put nothing after its own hook. hook.c:407-432 SetWindowsHookEx16 sets a
thread hook (SetWindowsHookExA with GetCurrentThreadId()), refuses a second hook of the same
kind ("Multiple hooks ... not supported yet", 429), and refuses another task's hook, and a
system-global one is "broken in Win16" (419). neww keeps the same one-per-kind table
(wine.hooks), so the chain after a task's hook is empty, and the answer is 0 with no guest
call. Before this handler, the call was answered by a loaded spec row with no handler.
No binary needed.
"""

import unittest

from tests.test_neww_batch2 import by_name, window_wine

WH_KEYBOARD, WH_CBT = 2, 5
PROC = (0x5678, 0x1234)


class CallNextHookEx(unittest.TestCase):
    def setUp(self):
        self.w = window_wine()

    def next_hook(self, hhook, code=0, wp=0x41, lp=(0x0001, 0xC01E)):
        ax, dx, stop, calls = by_name(self.w, "USER", "CallNextHookEx",
                                      (hhook & 0xFFFF, hhook >> 16), code, wp, lp)
        return ax, dx, stop, calls

    def test_after_the_tasks_own_hook_there_is_none(self):
        ax, dx, _stop, _calls = by_name(self.w, "USER", "SetWindowsHookEx", WH_KEYBOARD, PROC,
                                        0x10, 0)
        hhook = ax | dx << 16
        self.assertTrue(hhook)
        self.assertEqual(self.next_hook(hhook), (0, 0, None, []))

    def test_two_kinds_do_not_chain(self):
        by_name(self.w, "USER", "SetWindowsHookEx", WH_CBT, (0x1111, 0x2222), 0x10, 0)
        ax, dx, _stop, _calls = by_name(self.w, "USER", "SetWindowsHookEx", WH_KEYBOARD, PROC,
                                        0x10, 0)
        self.assertEqual(self.next_hook(ax | dx << 16), (0, 0, None, []))

    def test_no_hook_set_is_zero(self):
        self.assertEqual(self.next_hook(0), (0, 0, None, []))

    def test_no_spec_row_default(self):
        self.next_hook(0)
        self.assertEqual([d for d in self.w.defaults if d[:2] == ("USER", 293)], [])


if __name__ == "__main__":
    unittest.main()
