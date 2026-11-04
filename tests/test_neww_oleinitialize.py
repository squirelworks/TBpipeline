"""OLE2.2 OleInitialize is S_OK the first time in a task and S_FALSE after that.

Roadmap #201 T3. Spec (ole2.dll16.spec:2): `2 pascal OleInitialize(ptr) OleInitialize16`, a long.
At Wine 2528aff2, ole2.dll16/ole2.c:71-74 OleInitialize16 returns ole32 OleInitialize.
ole32/ole2.c:171-183 calls CoInitializeEx(COINIT_APARTMENTTHREADED), then answers S_OK while
the thread's ole_inits is 0 and S_FALSE once it is not, and 193 counts the call. A 16-bit task
is a thread there, so each task keeps its own count. Before this handler, the call was answered
by a loaded spec row with no handler (0 every time). No binary needed.
"""

import unittest

from tests.test_neww_batch2 import by_name, window_wine

S_OK, S_FALSE = 0, 1


def ole_initialize(w):
    ax, dx, stop, _calls = by_name(w, "OLE2", "OleInitialize", (0, 0))
    return ax, dx, stop


class OleInitialize(unittest.TestCase):
    def setUp(self):
        self.w = window_wine()

    def test_first_call_is_s_ok_then_s_false(self):
        self.assertEqual(ole_initialize(self.w), (S_OK, 0, None))
        self.assertEqual(ole_initialize(self.w), (S_FALSE, 0, None))
        self.assertEqual(ole_initialize(self.w), (S_FALSE, 0, None))

    def test_each_task_has_its_own_count(self):
        ole_initialize(self.w)
        first = self.w.htask
        self.w.htask = first + 0x10
        self.assertEqual(ole_initialize(self.w), (S_OK, 0, None))
        self.w.htask = first
        self.assertEqual(ole_initialize(self.w), (S_FALSE, 0, None))

    def test_no_spec_row_default(self):
        ole_initialize(self.w)
        self.assertEqual([d for d in self.w.defaults if d[:2] == ("OLE2", 2)], [])


if __name__ == "__main__":
    unittest.main()
