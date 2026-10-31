"""USER.66 GetDC is Wine user.exe16/window.c GetDC16.

Spec: `66 pascal -ret16 GetDC(word) GetDC16`, pop 2. hwnd 0 is the
screen. Wine takes a free DCE from its cache, so two GetDC calls with no
ReleaseDC are two DCs. Wine's HDC is a win32u GDI handle. neww numbers
its own from 0x1004 by 4, which is never a selector or a moveable handle.
A window's DC stops, because neww has no windows. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(hwnd):
    from tbpipeline_neww.machine import Machine
    # push hwnd ; call ; mov [0x40], ax ; push hwnd ; call ; mov [0x42], ax
    one = push(hwnd) + neww_ne.call_far()
    code = one + bytes([0xA3, 0x40, 0x00]) + one + bytes([0xA3, 0x42, 0x00])
    second = len(one) + 3
    fixups = [(3, 1, 4, 1, 66), (3, 1, second + 4, 1, 66)]
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, code, fixups, modules=("USER", "KERNEL"))
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, host.word(ds, 0x40), host.word(ds, 0x42)


class GetDC(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import USER
        row = USER[66]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetDC", (2,), 2, "word"))

    def test_screen_dcs_are_new_each_time(self):
        host, first, second = run(0)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((first, second), (0x1004, 0x1008))
        self.assertEqual(host.box.wine.dcs, {0x1004: 0, 0x1008: 0})

    def test_window_dc_stops(self):
        host, _first, _second = run(0x2000)
        self.assertEqual(host.stop, "USER.66 GetDC(0x2000): Wine gets a DC for that window, and neww has no windows")


if __name__ == "__main__":
    unittest.main()
