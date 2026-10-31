"""KERNEL.198 GlobalUnfix is Wine global.c GlobalUnfix16.

Spec: `198 pascal -ret16 GlobalUnfix(word) GlobalUnfix16`, pop 2. The
function is void: a valid handle's lockCount goes down, and AX is left
as the call found it. Unlike UnlockSegment16, -1 is not CURRENT_DS.
No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(handle):
    from tbpipeline_neww.machine import Machine
    # push handle ; mov ax, 0x1234 ; call ; mov [0x40], ax
    code = push(handle) + neww_ne.mov_ax(0x1234)
    at = len(code) + 1
    code += neww_ne.call_far() + bytes([0xA3, 0x40, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, code, [(3, 1, at, 1, 198)])
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, ds, host.word(ds, 0x40)


class GlobalUnfix(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[198]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GlobalUnfix", (2,), 2, "word"))

    def test_dgroup_lock_goes_down_and_ax_stays(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, b"", [])
            ds = Machine(d).run(limit=5000).uc.reg_read(UC_X86_REG_DS)
        host, ds2, ax = run(ds)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(ds2, ds)
        self.assertEqual(ax, 0x1234)
        self.assertEqual(host.box.wine.locks[ds], -1)

    def test_minus_one_is_not_current_ds(self):
        host, ds, ax = run(0xFFFF)
        self.assertEqual((host.stop, ax), ("dos exit 0x0", 0x1234))
        self.assertNotIn(ds, host.box.wine.locks)


if __name__ == "__main__":
    unittest.main()
