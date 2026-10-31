"""KERNEL.29 Yield returns and pops nothing.

TBWIN.DLL's yieldApp (TBWIN.16), which tb80axf.sbk links in
_AXF_RunExternalProgramAndWait, is a far call to KERNEL.29 and nothing
else. The runtime also calls it once before the WinExec wall.

Wine's Yield16 (krnl386.exe16/task.c) is void. With a message queue it
peeks once, and otherwise OldYield16 releases and retakes the Win16 lock.
This host runs one task, so the call returns. The spec line is
`29 pascal -ret16 Yield() Yield16`, so nothing is popped. The call fell
through to AX = 1, which named it as an unanswered call.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call


class Yield(unittest.TestCase):
    def test_answered(self):
        host = fake_host()
        far_call(host, "KERNEL", 29, [], pop=0)
        self.assertEqual(host.ax1, [], "Yield fell through to AX = 1")

    def test_pops_nothing(self):
        host = fake_host()
        far_call(host, "KERNEL", 29, [], pop=0)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4)


if __name__ == "__main__":
    unittest.main()
