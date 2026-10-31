"""USER.5 InitApp is answered: TRUE, as Wine's InitApp16 returns.

Wine's InitApp16 (user.exe16/user.c) creates the task's message queue and
returns InitThreadInput16(0, 0) != 0. TB80RTM calls it once from its C
start-up. The AX = 1 default happened to be TRUE, but the call was logged
as unanswered.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call


class InitApp(unittest.TestCase):
    def test_true_and_answered(self):
        host = fake_host()
        far_call(host, "USER", 5, [0x0468], pop=2)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1)
        self.assertEqual(host.ax1, [], "InitApp fell through to AX = 1")


if __name__ == "__main__":
    unittest.main()
