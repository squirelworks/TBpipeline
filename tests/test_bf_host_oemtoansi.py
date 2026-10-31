"""Item 27: KEYBOARD.6 OemToAnsi copies the string.

The second half of TB80BAS's path conversion (seg 10, 0x2C3B). The
OpenFile at 0x2C53 reads the OemToAnsi buffer.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call
from tbpipeline_bf.nehost.win16stack import POP

SRC = 0x100
DST = 0x200


class OemToAnsi(unittest.TestCase):
    def convert(self, text):
        host = fake_host()
        host.arena.write(host.data, SRC, text + b"\x00")
        host.arena.write(host.data, DST, b"\xAA" * 0x40)
        far_call(host, "KEYBOARD", 6, [DST, host.data, SRC, host.data], pop=POP["KEYBOARD"][6])
        return host, host.arena.read(host.data, DST, 0x40).split(b"\x00", 1)[0]

    def test_pop_is_two_far_pointers(self):
        self.assertEqual(POP["KEYBOARD"][6], 8)

    def test_ascii_path_is_copied(self):
        host, out = self.convert(b"C:\\BOOKS\\fixture.tbk")
        self.assertEqual(out, b"C:\\BOOKS\\fixture.tbk")
        self.assertEqual(host.ax1, [], "OemToAnsi fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0xFFFF)

    def test_oem_letters_become_ansi(self):
        _, out = self.convert(b"caf\x82")
        self.assertEqual(out, b"caf\xe9")


if __name__ == "__main__":
    unittest.main()
