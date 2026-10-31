"""KERNEL.55 Catch and KERNEL.56 Throw follow Wine's Catch16 and Throw16.

Wine's thunk.c Catch16 (spec `55 pascal -register Catch(ptr)`) writes the
caller's IP, CS, SP, BP, SI, DI, DS, 0 and SS into the 9-word CATCHBUF and
answers AX 0. The SP is winebuild's Esp, the SP at the far return address,
less 4 words. Throw16 (`56 pascal -register Throw(ptr word)`) answers AX =
retval at Catch's return address, with SP where Catch's own return left it.

Both fell through to AX = 1. From Catch that tells the caller a Throw has
come back. neww answers the pair the same way (tests/test_neww_catch.py).
"""

import struct
import unittest

from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BP, UC_X86_REG_DI, UC_X86_REG_DS, UC_X86_REG_SI, UC_X86_REG_SP,
    UC_X86_REG_SS,
)

from tests.bf_host_fake import STACK_TOP, fake_host, far_call

BUF = 0x40


class CatchThrow(unittest.TestCase):
    def setUp(self):
        self.host = fake_host()
        uc = self.host.uc
        uc.reg_write(UC_X86_REG_AX, 0x5A5A)
        uc.reg_write(UC_X86_REG_BP, 0x0E80)
        uc.reg_write(UC_X86_REG_SI, 0x1111)
        uc.reg_write(UC_X86_REG_DI, 0x2222)

    def catch(self):
        far_call(self.host, "KERNEL", 55, [BUF, self.host.data], ret_ip=0x105, pop=4)
        return struct.unpack("<9H", self.host.arena.read(self.host.data, BUF, 18))

    def test_catch_fills_the_buffer_and_answers_0(self):
        host = self.host
        buf = self.catch()
        esp = STACK_TOP - 4 - 4
        self.assertEqual(host.ax1, [], "Catch fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0)
        self.assertEqual(buf, (0x105, host.code, esp - 8, 0x0E80, 0x1111, 0x2222, host.data, 0, host.stack))

    def test_throw_returns_retval_at_the_catch(self):
        host = self.host
        buf = self.catch()
        after_catch = host.uc.reg_read(UC_X86_REG_SP) + 4
        uc = host.uc
        uc.reg_write(UC_X86_REG_BP, 0)
        uc.reg_write(UC_X86_REG_SI, 0)
        uc.reg_write(UC_X86_REG_DI, 0)
        far_call(host, "KERNEL", 56, [7, BUF, host.data], ret_ip=0x200, pop=6)
        self.assertEqual(host.ax1, [])
        self.assertEqual(host.fault, "")
        self.assertEqual(uc.reg_read(UC_X86_REG_AX), 7)
        sp = uc.reg_read(UC_X86_REG_SP)
        self.assertEqual(struct.unpack("<HH", host.arena.read(host.stack, sp, 4)), (0x105, host.code))
        # The thunk's retf 0 pops the return address: SP is then where Catch's return left it.
        self.assertEqual(sp + 4, after_catch)
        self.assertEqual((uc.reg_read(UC_X86_REG_BP), uc.reg_read(UC_X86_REG_SI), uc.reg_read(UC_X86_REG_DI)),
                         (0x0E80, 0x1111, 0x2222))
        self.assertEqual(buf[2] + 16, after_catch)

    def test_throw_from_another_data_segment_stops(self):
        host = self.host
        self.catch()
        host.arena.write(host.data, BUF + 12, struct.pack("<H", 0x1234))
        far_call(host, "KERNEL", 56, [1, BUF, host.data], ret_ip=0x200, pop=6)
        self.assertIn("KERNEL.56 Throw", host.fault)
        self.assertEqual(host.ax1, [])

    def test_catch_outside_any_block_stops(self):
        host = self.host
        far_call(host, "KERNEL", 55, [0xFFF0, host.data], pop=4)
        self.assertIn("KERNEL.55 Catch", host.fault)


if __name__ == "__main__":
    unittest.main()
