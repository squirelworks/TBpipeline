"""KERNEL.23 LockSegment and KERNEL.24 UnlockSegment are Wine global.c.

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


class UnlockSegment(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[24]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("UnlockSegment", (2,), 2, "word"))

    def test_lock_then_unlock_leaves_ax(self):
        from tbpipeline_neww.machine import Machine
        # push -1 ; call LockSegment ; push -1 ; mov ax, 0x4321 ; call UnlockSegment ; mov [0x40], ax
        before = bytes([0x68, 0xFF, 0xFF]) + neww_ne.call_far()
        before += bytes([0x68, 0xFF, 0xFF]) + neww_ne.mov_ax(0x4321) + neww_ne.call_far() + bytes([0xA3, 0x40, 0x00])
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 4, 1, 23), (3, 1, 15, 1, 24)])
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.word(ds, 0x40), 0x4321)
        self.assertEqual(host.box.wine.locks, {ds: 0})


if __name__ == "__main__":
    unittest.main()
