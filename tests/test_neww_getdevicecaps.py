"""GDI.80 GetDeviceCaps of the screen DC is Wine's null display driver.

Spec: `80 pascal -ret16 GetDeviceCaps(word s_word) GetDeviceCaps16`,
pop 4. Wine gdi.c GetDeviceCaps16 calls GetDeviceCaps and turns a
NUMCOLORS of -1 into 2048. neww has no display driver, so the screen DC
is win32u driver.c nulldrv_GetDeviceCaps over Wine's default display,
1024x768 at 32 bits and 60 Hz, at 96 dpi. A DC neww did not make stops.
No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(cap, hdc=None):
    from tbpipeline_neww.machine import Machine
    code = bytearray()
    fixups = []
    if hdc is None:
        # push 0 ; call GetDC ; push ax
        code += push(0)
        fixups.append((3, 1, len(code) + 1, 1, 66))
        code += neww_ne.call_far() + bytes([0x50])
    else:
        code += push(hdc)
    code += push(cap)
    fixups.append((3, 1, len(code) + 1, 2, 80))
    # call GetDeviceCaps ; mov [0x40], ax
    code += neww_ne.call_far() + bytes([0xA3, 0x40, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups, modules=("USER", "GDI", "KERNEL"))
        host = Machine(d).run(limit=5000)
    return host, host.word(host.uc.reg_read(UC_X86_REG_DS), 0x40)


class GetDeviceCaps(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import GDI
        row = GDI[80]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetDeviceCaps", (2, 2), 4, "word"))

    def test_screen(self):
        # BITSPIXEL, HORZRES, VERTRES, LOGPIXELSY, HORZSIZE, RASTERCAPS, NUMCOLORS, NUMPENS, a cap with no case.
        for cap, value in ((12, 32), (8, 1024), (10, 768), (90, 96), (4, 271), (38, 0xBE99), (24, 2048), (18, 0xFFFF), (46, 0)):
            host, ax = run(cap)
            self.assertEqual((host.stop, ax), ("dos exit 0x0", value), cap)

    def test_unknown_dc_stops(self):
        host, _ax = run(12, hdc=0x2000)
        self.assertEqual(host.stop, "GDI.80 GetDeviceCaps(0x2000, 12): not a DC neww made")


if __name__ == "__main__":
    unittest.main()
