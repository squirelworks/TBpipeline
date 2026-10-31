"""KERNEL.5 LocalAlloc is Wine local.c LocalAlloc16, on the heap LocalInit16 built.

Spec: `5 pascal -ret16 LocalAlloc(word word)`, pop 4. A fixed block is
the first free arena that fits, split off by LOCAL_ShrinkArena. A
moveable block gets a handle entry from a handle table of hdelta
entries, made on first use. The handle is also in CX. A full heap is
compacted, then grown to 64K, as LOCAL_GetBlock does. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, value >> 8])


def program(directory, end, allocs):
    """LocalInit(0, 0x20, end), then LocalAlloc(flags, size) for each, AX and CX stored at 0x3F0 + 4i."""
    code = bytearray(push(0) + push(0x20) + push(end))
    fixups = [(3, 1, len(code) + 1, 1, 4)]
    code += neww_ne.call_far()
    for i, (flags, size) in enumerate(allocs):
        code += push(flags) + push(size)
        fixups.append((3, 1, len(code) + 1, 1, 5))
        code += neww_ne.call_far()
        at = 0x3F0 + 4 * i
        code += bytes([0xA3, at & 0xFF, at >> 8, 0x89, 0x0E, (at + 2) & 0xFF, (at + 2) >> 8])
    neww_ne.exit_program_with(directory, bytes(code), fixups, data=0x400)


class LocalAlloc(unittest.TestCase):
    def run_program(self, end, allocs):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, end, allocs)
            host = Machine(d).run(limit=20000)
        ds = host.uc.reg_read(UC_X86_REG_DS)
        return host, ds

    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[5]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("LocalAlloc", (2, 2), 4, "word"))

    def test_fixed_block_splits_the_free_arena(self):
        host, ds = self.run_program(0xF0, [(0x20, 1)])
        self.assertEqual(host.stop, "dos exit 0x0")
        # Heap: first 0x20, info 0x2C, free 0x5C, last 0xE4. Size 1 is 5, an arena of 12.
        self.assertEqual((host.word(ds, 0x3F0), host.word(ds, 0x3F2)), (0x60, 0x60))
        self.assertEqual([host.word(ds, 0x5C + o) for o in (0, 2)], [0x2D, 0x68])
        self.assertEqual([host.word(ds, 0x68 + o) for o in (0, 2, 4, 6, 8)], [0x5C, 0xE4, 0x7C, 0x20, 0xE4])
        self.assertEqual(host.word(ds, 0x20 + 8), 0x68)
        self.assertEqual(host.word(ds, 0x30 + 4), 5)

    def test_moveable_block_has_a_handle_entry(self):
        host, ds = self.run_program(0x3E0, [(0x0042, 8)])
        self.assertEqual(host.stop, "dos exit 0x0")
        handle, cx = host.word(ds, 0x3F0), host.word(ds, 0x3F2)
        self.assertEqual(handle, cx)
        self.assertEqual(handle & 3, 2)
        addr = host.word(ds, handle)
        self.assertEqual(host.word(ds, addr - 2), handle)
        self.assertEqual(host.word(ds, handle + 2), 0)
        self.assertEqual([host.word(ds, addr + i) for i in range(0, 8, 2)], [0, 0, 0, 0])
        table = host.word(ds, 0x30 + 0x14)
        self.assertEqual(host.word(ds, table), 0x20)
        self.assertEqual(handle, table + 2)

    def test_no_room_grows_the_segment_to_64k(self):
        # The handle table needs 0x88 bytes, more than the heap holds. LOCAL_GetBlock compacts,
        # then LOCAL_GrowHeap reallocates DGROUP to 64K and the last arena moves to its end.
        host, ds = self.run_program(0xF0, [(0x0002, 8)])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertNotEqual(host.word(ds, 0x3F0), 0)
        self.assertEqual(host.box.wine._global_size(ds), 0x10000)
        self.assertEqual(host.word(ds, 0x30 + 0x0A), 0xFFF4)


if __name__ == "__main__":
    unittest.main()
