"""Item 27: USER.420 wsprintf formats into the caller's buffer.

wsprintf is cdecl: the caller pops (TB80UTL's error box does
`add sp, 0xE` after the call). The pop table had 8, the Pascal size of
its two fixed pointers. AX = 1 left the buffer as it was, so the box
the runtime raised during the book open read as garbage.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SP

from tests.bf_host_fake import fake_host, far_call, STACK_TOP
from tbpipeline_bf.nehost.win16stack import POP

OUT = 0x100
FMT = 0x300
NAME = 0x380


class Wsprintf(unittest.TestCase):
    def call(self, fmt, args, name=b""):
        host = fake_host()
        host.arena.write(host.data, FMT, fmt + b"\x00")
        host.arena.write(host.data, NAME, name + b"\x00")
        host.arena.write(host.data, OUT, b"\xAA" * 0x100)
        # None in args stands for the data selector, the segment of a far pointer.
        args = [host.data if a is None else a for a in args]
        far_call(host, "USER", 420, [OUT, host.data, FMT, host.data] + args, pop=POP["USER"][420])
        text = host.arena.read(host.data, OUT, 0x100).split(b"\x00", 1)[0]
        return host, text

    def test_cdecl_pops_nothing(self):
        self.assertEqual(POP["USER"][420], 0)

    def test_error_box_text(self):
        host, text = self.call(b"File '%s' line %d.", [NAME, None, 0x275], name=b"Unknown")
        self.assertEqual(text, b"File 'Unknown' line 629.")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), len(text))
        self.assertEqual(host.ax1, [], "wsprintf fell through to AX = 1")

    def test_stack_is_left_for_the_caller(self):
        host = fake_host()
        host.arena.write(host.data, FMT, b"x\x00")
        sp_before = STACK_TOP - 4 - 8
        far_call(host, "USER", 420, [OUT, host.data, FMT, host.data], pop=0)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), sp_before)

    def test_numbers_and_flags(self):
        _, text = self.call(b"%u %x %04X %-3d| %c %ld %lx %%", [65535, 0xBEEF, 0x1F, 7, ord("Z"), 1, 0, 0x5678, 0x1234])
        self.assertEqual(text, b"65535 beef 001F 7  | Z 1 12345678 %")


if __name__ == "__main__":
    unittest.main()
