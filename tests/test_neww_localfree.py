"""KERNEL.7 LocalFree is Wine local.c LocalFree16, in CURRENT_DS.

Spec: `7 pascal -ret16 LocalFree(word) LocalFree16`, pop 2. It returns 0
when the block is freed and the handle when it is not. A fixed handle is
its arena + 4, given to LOCAL_FreeArena. A moveable handle frees the
block it points at, then LOCAL_FreeHandleEntry marks the entry free and
frees the handle table once all its entries are free. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, value >> 8])


def run(ops, end=0x3E0):
    """LocalInit(0, 0x20, end), then each op. Result n is at 0x3F0 + 2n.

    An op is ("alloc", flags, size), ("free", n) for result n, or ("free", "#", word).
    """
    from tbpipeline_neww.machine import Machine
    code = bytearray(push(0) + push(0x20) + push(end))
    fixups = [(3, 1, len(code) + 1, 1, 4)]
    code += neww_ne.call_far()
    for i, op in enumerate(ops):
        if op[0] == "alloc":
            code += push(op[1]) + push(op[2])
            ordinal = 5
        else:
            if op[1] == "#":
                code += push(op[2])
            else:
                at = 0x3F0 + 2 * op[1]
                # push word [at]
                code += bytes([0xFF, 0x36, at & 0xFF, at >> 8])
            ordinal = 7
        fixups.append((3, 1, len(code) + 1, 1, ordinal))
        code += neww_ne.call_far()
        at = 0x3F0 + 2 * i
        code += bytes([0xA3, at & 0xFF, at >> 8])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups, data=0x400)
        host = Machine(d).run(limit=20000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, ds, [host.word(ds, 0x3F0 + 2 * i) for i in range(len(ops))]


class LocalFree(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[7]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("LocalFree", (2,), 2, "word"))

    def test_fixed_block_is_freed_once(self):
        host, ds, results = run([("alloc", 0, 8), ("free", 0), ("free", 0), ("alloc", 0, 8)])
        self.assertEqual(host.stop, "dos exit 0x0")
        block = results[0]
        self.assertNotEqual(block, 0)
        # Freed, then already free: the handle back. The same block is found again.
        self.assertEqual(results[1:], [0, block, block])

    def test_zero_is_zero(self):
        _host, _ds, results = run([("free", "#", 0)])
        self.assertEqual(results, [0])

    def test_moveable_frees_its_entry_and_table(self):
        _host, ds, _results = run([("alloc", 0x0002, 8)])
        info = _host.word(ds, 0x06)
        self.assertNotEqual(_host.word(ds, info + 0x14), 0)
        host, ds, results = run([("alloc", 0x0002, 8), ("free", 0)])
        self.assertEqual(host.stop, "dos exit 0x0")
        handle = results[0]
        self.assertEqual(handle & 3, 2)
        self.assertEqual(results[1], 0)
        # The only entry was freed, so the table went too: the heap info's htable is 0.
        info = host.word(ds, 0x06)
        self.assertEqual(host.word(ds, info + 0x14), 0)
        self.assertEqual((host.word(ds, handle), host.word(ds, handle + 2)), (0, 0xFFFF))


if __name__ == "__main__":
    unittest.main()
