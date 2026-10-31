"""Item 27: KEYBOARD.5 AnsiToOem copies the string.

TB80BAS builds the book's path with AnsiToOem then OemToAnsi (seg 10,
0x2C2B and 0x2C3B). AX = 1 copied nothing, so OpenFile got whatever the
stack buffer held ('P\\x07') and the runtime said "Not a valid file name."
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call
from tbpipeline_bf.nehost.win16stack import POP

SRC = 0x100
DST = 0x200


class AnsiToOem(unittest.TestCase):
    def convert(self, text):
        host = fake_host()
        host.arena.write(host.data, SRC, text + b"\x00")
        host.arena.write(host.data, DST, b"\xAA" * 0x40)
        # AnsiToOem(lpszWindowsStr, lpszOemStr): the destination is the last push.
        far_call(host, "KEYBOARD", 5, [DST, host.data, SRC, host.data], pop=POP["KEYBOARD"][5])
        return host, host.arena.read(host.data, DST, 0x40).split(b"\x00", 1)[0]

    def test_pop_is_two_far_pointers(self):
        self.assertEqual(POP["KEYBOARD"][5], 8)

    def test_ascii_path_is_copied(self):
        host, out = self.convert(b"C:\\BOOKS\\fixture.tbk")
        self.assertEqual(out, b"C:\\BOOKS\\fixture.tbk")
        self.assertEqual(host.ax1, [], "AnsiToOem fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0xFFFF)

    def test_ansi_letters_become_oem(self):
        _, out = self.convert(b"caf\xe9")      # e acute: 0xE9 in 1252, 0x82 in 437
        self.assertEqual(out, b"caf\x82")


if __name__ == "__main__":
    unittest.main()
