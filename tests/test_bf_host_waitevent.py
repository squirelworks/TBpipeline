"""KERNEL.30 WaitEvent takes the task's start event and returns FALSE.

Wine's NE_CreateThread (krnl386.exe16/ne_module.c) does
`/* Post event to start the task */ PostEvent16( hTask );`, and
WaitEvent16 (krnl386.exe16/task.c) does `if (pTask->nEvents > 0)
{ pTask->nEvents--; return FALSE; }`. With no event pending it waits for
another task to post one. This host runs one task, so a second wait stops
the run instead of hanging. TB80RTM's C start-up calls WaitEvent(0) once,
between InitTask and InitApp. The AX = 1 default said TRUE.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call


class WaitEvent(unittest.TestCase):
    def test_start_event_returns_false(self):
        host = fake_host()
        far_call(host, "KERNEL", 30, [0], pop=2)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0)
        self.assertEqual(host.ax1, [], "WaitEvent fell through to AX = 1")
        self.assertFalse(host.fault)

    def test_second_wait_stops_the_run(self):
        host = fake_host()
        far_call(host, "KERNEL", 30, [0], pop=2)
        far_call(host, "KERNEL", 30, [0], pop=2)
        self.assertIn("WaitEvent", host.fault or "")


if __name__ == "__main__":
    unittest.main()
