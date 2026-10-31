"""Item 34: DOS3Call with AH = 4Ch is the DOS exit.

The guest calls KERNEL.102 through the real thunk slot with AX = 4C03h.
The host records "dos exit 0x3" and the CPU stops there: the instruction
after the call does not run.
"""

import unittest

from unicorn import UC_HOOK_INSN
from unicorn.x86_const import UC_X86_INS_OUT, UC_X86_REG_BX

from tests.bf_host_fake import fake_host, run_guest

PREFIX = 13   # run_guest's DS/SS/SP setup


class DosExit(unittest.TestCase):
    def run_exit(self, code):
        host = fake_host()
        host._thunks()
        host.uc.hook_add(UC_HOOK_INSN, host._on_out, None, 1, 0, UC_X86_INS_OUT)
        slot = 102 * 8
        body = bytes([0xB8, code & 0xFF, 0x4C,
                      0x9A, slot & 0xFF, slot >> 8, host.thunk & 0xFF, host.thunk >> 8])
        ret = 0xF020 + PREFIX + len(body)
        host.sites[(host.flat, ret)] = ("KERNEL", 102, 0)
        host.callers[(host.flat, ret)] = ("KERNEL", 102)
        run_guest(host, body + bytes([0xBB, 0xEF, 0xBE]))   # mov bx, 0xBEEF
        return host

    def test_exit_code_is_recorded(self):
        host = self.run_exit(3)
        self.assertEqual(host.fault, "dos exit 0x3")

    def test_cpu_does_not_continue_after_exit(self):
        host = self.run_exit(0)
        self.assertEqual(host.fault, "dos exit 0x0")
        self.assertNotEqual(host.uc.reg_read(UC_X86_REG_BX), 0xBEEF, "ran past the exit")
        self.assertEqual(host.ax1, [])


if __name__ == "__main__":
    unittest.main()
