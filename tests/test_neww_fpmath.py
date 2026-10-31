"""WIN87EM.1 __fpMath is Wine win87em.c, by the sub-function in BX.

Spec: win87em.dll16.spec `1 pascal -register __fpMath()`, pop 0. BX 0
installs: WIN87_Init (fninit, control word 0x1332 & ~0xC3, fclex) and
AX 0. Wine's fninit/fldcw run on the real x87. Here they set Unicorn's
FPU control, status and tag words. DX is the guest's. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def run(bx, ax=0x9876):
    from tbpipeline_neww.machine import Machine
    # mov dx, 0x5555 ; mov bx, bx ; mov ax, ax ; call __fpMath ; mov [0x40], ax ; mov [0x42], dx ;
    # fnstcw [0x44] ; fnstsw [0x46]
    before = bytes([0xBA, 0x55, 0x55, 0xBB, bx & 0xFF, bx >> 8]) + neww_ne.mov_ax(ax) + neww_ne.call_far()
    before += bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00, 0xD9, 0x3E, 0x44, 0x00, 0xDD, 0x3E, 0x46, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, before, [(3, 1, 10, 2, 1)], modules=("KERNEL", "WIN87EM"))
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, [host.word(ds, o) for o in (0x40, 0x42, 0x44, 0x46)]


class FpMath(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import WIN87EM
        row = WIN87EM[1]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("__fpMath", (), 0, "register"))

    def test_install_inits_the_x87(self):
        host, (ax, dx, cw, sw) = run(0)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((ax, dx, cw, sw), (0, 0x5555, 0x1330, 0))

    def test_set_and_get_control_word(self):
        host, (ax, dx, cw, _sw) = run(4, ax=0x13F3)
        self.assertEqual((ax, dx, cw), (0x1330, 0x5555, 0x1330))
        host, (ax, _dx, _cw, _sw) = run(5)
        self.assertEqual(ax, 0)

    def test_host_x87_round_stops(self):
        host, _ = run(6)
        self.assertTrue(host.stop.startswith("WIN87EM.1 __fpMath BX=6: Wine win87em.c rounds"), host.stop)

    def test_pop_as_integer_is_wines_zero(self):
        # Wine's fistp is commented out, so DX:AX is 0 whatever the x87 holds.
        host, _ = run(7)
        self.assertTrue(host.stop.startswith("dos exit"), host.stop)


if __name__ == "__main__":
    unittest.main()
