"""KERNEL.36 GetCurrentTask returns one task handle, the same every call.

Wine's WIN16_GetCurrentTask (dlls/krnl386.exe16/task.c) returns
MAKELONG(GetCurrentTask(), hFirstTask): the current task's handle in AX
and the first task's in DX. This host runs one task, so they are equal.
TB80UTL and TB80LNL key their per-task tables on it. AX = 1 is not a
selector.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call


def current_task(host):
    far_call(host, "KERNEL", 36, [], pop=0)
    return host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)


class GetCurrentTask(unittest.TestCase):
    def test_handle_is_a_selector(self):
        host = fake_host()
        ax, dx = current_task(host)
        self.assertIn(ax, host.arena.segs)
        self.assertEqual(dx, ax, "one task: the first task is the current one")
        self.assertEqual(host.ax1, [], "GetCurrentTask fell through to AX = 1")

    def test_same_handle_every_call(self):
        host = fake_host()
        self.assertEqual(current_task(host), current_task(host))


if __name__ == "__main__":
    unittest.main()
