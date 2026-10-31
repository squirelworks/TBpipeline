"""KERNEL.23 LockSegment is Wine global.c LockSegment16.

Spec: `23 pascal -ret16 LockSegment(word)`, pop 2. Handle -1 is the
current DS. A handle with no block returns 0. Otherwise the block's
lockCount goes up and the handle comes back. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def run(handle):
    from tbpipeline_neww.machine import Machine
    # push handle ; call LockSegment ; mov [0x40], ax
    before = bytes([0x68, handle & 0xFF, handle >> 8]) + neww_ne.call_far() + bytes([0xA3, 0x40, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, before, [(3, 1, 4, 1, 23)])
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, ds, host.word(ds, 0x40)


class LockSegment(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[23]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("LockSegment", (2,), 2, "word"))

    def test_minus_one_is_ds(self):
        host, ds, ax = run(0xFFFF)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(ax, ds)
        self.assertEqual(host.box.wine.locks, {ds: 1})

    def test_no_block_returns_zero(self):
        host, _ds, ax = run(0x7770)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(ax, 0)
        self.assertEqual(host.box.wine.locks, {})


if __name__ == "__main__":
    unittest.main()
