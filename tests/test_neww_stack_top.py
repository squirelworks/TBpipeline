"""SP at entry is Wine NE_StartTask's, below the local heap.

Wine ne_module.c NE_StartTask takes SP from the NE header's SS:SP, or,
when its offset is 0, from the stack segment's minsize plus the NE stack
size, made even. DGROUP is minsize + stack + heap, so the heap is above
the stack. neww used to start SP at the end of DGROUP, inside the heap
that LocalInit16 builds at the end of the segment.
"""

import struct
import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS

# mov [0], sp
STORE_SP = bytes([0x89, 0x26, 0x00, 0x00])


def program(directory, sssp=0, heap=0x100, stack=0x40):
    code = STORE_SP + neww_ne.mov_ax(0x4C00)
    at = len(code)
    code += neww_ne.call_far() + bytes([0xF4])
    blob = bytearray(neww_ne.build(
        "TB80RTM",
        [(0x0000, code, [(3, 1, at + 1, 1, 102)]), (0x0001, b"\x00" * 256, [])],
        modules=("KERNEL",), entry=(1, 0), auto=2, heap=heap, stack=stack,
    ))
    struct.pack_into("<I", blob, 0x40 + 0x18, sssp)
    neww_ne.write(directory, "TB80RTM.EXE", bytes(blob))


class StackTop(unittest.TestCase):
    def run_program(self, **kw):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, **kw)
            return Machine(d).run(limit=5000)

    def test_sp_is_minsize_plus_stack(self):
        host = self.run_program(sssp=2 << 16)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.word(ds, 0), 256 + 0x40)

    def test_header_sp_wins(self):
        host = self.run_program(sssp=(2 << 16) | 0x121)
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.word(ds, 0), 0x120)

    def test_sp_outside_dgroup_stops(self):
        host = self.run_program(sssp=(2 << 16) | 0x8000)
        self.assertEqual(host.stop, "stack top 0x8000 is outside DGROUP (0x240 bytes)")
        self.assertEqual(host.calls, 0)


if __name__ == "__main__":
    unittest.main()
