"""KERNEL.4 LocalInit is Wine local.c LocalInit16, written into the guest.

Spec: krnl386.exe16.spec `4 pascal -ret16 LocalInit(word word word)`,
pop 6. The heap is a first arena, the heap info arena, one large free
block and a last arena, and INSTANCEDATA.heap points at the info. The
result is in AX and also in CX, as Wine sets it. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, value >> 8])


# mov [0xF8], ax; mov [0xFA], cx
STORE = bytes([0xA3, 0xF8, 0x00, 0x89, 0x0E, 0xFA, 0x00])


class LocalInit(unittest.TestCase):
    def run_init(self, selector, start, end):
        from tbpipeline_neww.machine import Machine
        before = push(selector) + push(start) + push(end) + neww_ne.call_far() + STORE
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 10, 1, 4)])
            return Machine(d).run(limit=5000)

    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[4]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("LocalInit", (2, 2, 2), 6, "word"))

    def test_heap_layout(self):
        host = self.run_init(0, 0x20, 0xF0)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual((host.word(ds, 0xF8), host.word(ds, 0xFA)), (1, 1))
        # start 0x20, info arena 0x2C, free arena 0x5C, last arena 0xE4.
        self.assertEqual([host.word(ds, 0x20 + o) for o in (0, 2, 4, 6, 8)], [0x21, 0x2C, 0x0C, 0x20, 0x5C])
        self.assertEqual([host.word(ds, 0x2C + o) for o in (0, 2)], [0x21, 0x5C])
        self.assertEqual(host.word(ds, 0x06), 0x30)
        self.assertEqual([host.word(ds, 0x30 + o) for o in (0x04, 0x06, 0x0A, 0x18, 0x24, 0x26, 0x28)],
                         [4, 0x20, 0xE4, 0x20, 0x200, 0x88, 0x484C])
        self.assertEqual([host.word(ds, 0x5C + o) for o in (0, 2, 4, 6, 8)], [0x2C, 0xE4, 0x88, 0x20, 0xE4])
        self.assertEqual([host.word(ds, 0xE4 + o) for o in (0, 2, 4, 6, 8)], [0x5C, 0xE4, 0x0C, 0x5C, 0xE4])

    def test_too_small_returns_false_and_writes_nothing(self):
        host = self.run_init(0, 0x20, 0x60)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual((host.word(ds, 0xF8), host.word(ds, 0xFA)), (0, 0))
        self.assertEqual(host.word(ds, 0x06), 0)
        self.assertEqual(host.word(ds, 0x20), 0)


if __name__ == "__main__":
    unittest.main()
