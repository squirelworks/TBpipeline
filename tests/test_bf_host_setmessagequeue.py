"""USER.266 SetMessageQueue is answered: TRUE, as Wine returns.

Wine's SetMessageQueue16 (user.exe16/message.c) is
`return SetMessageQueue( size );`, and SetMessageQueue (user32/message.c)
returns TRUE for any size, because the queue is expanded as necessary. The
spec line is `266 pascal -ret16 SetMessageQueue(word)`. TB80RTM calls it
once, with 0x60 messages. The AX = 1 default happened to be TRUE, but the
call was logged as unanswered.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call


class SetMessageQueue(unittest.TestCase):
    def test_true_and_answered(self):
        for size in (0x60, 8, 0):
            host = fake_host()
            far_call(host, "USER", 266, [size], pop=2)
            self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1, size)
            self.assertEqual(host.ax1, [], "SetMessageQueue fell through to AX = 1")


if __name__ == "__main__":
    unittest.main()
