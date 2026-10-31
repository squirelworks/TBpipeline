"""USER.68 ReleaseDC is Wine user.exe16/window.c ReleaseDC16.

Spec: `68 pascal -ret16 ReleaseDC(word word) ReleaseDC16`, pop 4. win32u
dce.c release_dc returns 1 for a DC in use, without looking at hwnd, and
puts a cache DC back. NtUserGetDCEx then takes the first released DC of
the desktop window in dce_list, newest first. A DC not in use is 0.
No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


class Program:
    """Calls in order, each result stored at DS:0x40 + 2 * n."""

    def __init__(self):
        self.code = bytearray()
        self.fixups = []
        self.results = 0

    def call(self, module, ordinal, *args):
        for value in args:
            self.code += push(value) if isinstance(value, int) else value
        self.fixups.append((3, 1, len(self.code) + 1, module, ordinal))
        at = 0x40 + 2 * self.results
        self.results += 1
        self.code += neww_ne.call_far() + bytes([0xA3, at & 0xFF, at >> 8])

    def run(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, bytes(self.code), self.fixups, modules=("USER", "KERNEL"))
            host = Machine(d).run(limit=5000)
        ds = host.uc.reg_read(UC_X86_REG_DS)
        return host, [host.word(ds, 0x40 + 2 * i) for i in range(self.results)]


def get_dc(p):
    p.call(1, 66, 0)


def release_dc(p, hdc, hwnd=0):
    p.call(1, 68, hwnd, hdc)


class ReleaseDC(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import USER
        row = USER[68]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("ReleaseDC", (2, 2), 4, "word"))

    def test_released_dc_is_taken_again(self):
        p = Program()
        get_dc(p)
        release_dc(p, 0x1004, hwnd=0x1234)
        get_dc(p)
        host, results = p.run()
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(results, [0x1004, 1, 0x1004])

    def test_newest_released_dc_first(self):
        p = Program()
        get_dc(p)
        get_dc(p)
        release_dc(p, 0x1004)
        release_dc(p, 0x1008)
        get_dc(p)
        _host, results = p.run()
        self.assertEqual(results, [0x1004, 0x1008, 1, 1, 0x1008])

    def test_dc_not_in_use_is_zero(self):
        p = Program()
        get_dc(p)
        release_dc(p, 0x1004)
        release_dc(p, 0x1004)
        release_dc(p, 0x2000)
        _host, results = p.run()
        self.assertEqual(results, [0x1004, 1, 0, 0])


if __name__ == "__main__":
    unittest.main()
