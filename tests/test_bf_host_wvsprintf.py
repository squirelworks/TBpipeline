"""USER.421 wvsprintf formats with arguments from a far pointer.

Wine's wvsprintf16 (user.exe16/user.c) takes the output buffer, the format
and a VA_LIST16, a far pointer to the argument words, and returns the
length written. The runtime calls it twice before the WinExec wall. AX = 1
left the buffer as it was and said one character was written.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

OUT, FMT, ARGS, STR = 0x100, 0x200, 0x280, 0x300


def wvsprintf(fmt, args):
    """args are words; None stands for the data selector."""
    host = fake_host()
    d = host.data
    host.arena.write(d, FMT, fmt + b"\x00")
    host.arena.write(d, STR, b"TB80BAS\x00")
    host.arena.write(d, ARGS, b"".join(struct.pack("<H", d if w is None else w) for w in args))
    host.arena.write(d, OUT, b"\xEE" * 64)
    far_call(host, "USER", 421, [ARGS, d, FMT, d, OUT, d], pop=12)
    return host, host.uc.reg_read(UC_X86_REG_AX), host.arena.read(d, OUT, 64)


class Wvsprintf(unittest.TestCase):
    def test_words_and_a_far_string(self):
        host, n, out = wvsprintf(b"%s line %d, %04x", [STR, None, 629, 0xBEEF])
        text = b"TB80BAS line 629, beef"
        self.assertEqual((n, out[:len(text) + 1]), (len(text), text + b"\x00"))
        self.assertEqual(host.ax1, [], "wvsprintf fell through to AX = 1")

    def test_long_and_negative(self):
        _, n, out = wvsprintf(b"%ld %i", [0x4240, 0x000F, 0xFFFE])
        self.assertEqual(out[:n + 1], b"1000000 -2\x00")


if __name__ == "__main__":
    unittest.main()
