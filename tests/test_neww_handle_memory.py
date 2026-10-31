"""neww reads and writes a block through its moveable handle, as the CPU does.

Wine's MapSL of a moveable handle is the block, because the handle and
the selector are the same LDT entry. TB80LNL calls LocalInit(handle, ...)
and then LocalAlloc with the handle in DS. neww's helpers looked selectors
up exactly, so the heap went nowhere and LocalAlloc found none. Now a
lookup goes by descriptor index. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run():
    from tbpipeline_neww.machine import Machine
    # GlobalAlloc(GMEM_MOVEABLE, 0x200) ; mov bx, ax ; LocalInit(bx, 0x10, 0x1F0) ;
    # push ds ; mov ds, bx ; LocalAlloc(LMEM_FIXED, 6) ; pop ds ; mov [0x40], ax ; mov [0x42], bx
    code = bytearray(push(0x0002) + push(0) + push(0x200))
    fixups = [(3, 1, len(code) + 1, 1, 15)]
    code += neww_ne.call_far() + bytes([0x89, 0xC3, 0x53]) + push(0x10) + push(0x1F0)
    fixups.append((3, 1, len(code) + 1, 1, 4))
    code += neww_ne.call_far() + bytes([0x1E, 0x8E, 0xDB]) + push(0) + push(6)
    fixups.append((3, 1, len(code) + 1, 1, 5))
    code += neww_ne.call_far() + bytes([0x1F, 0xA3, 0x40, 0x00, 0x89, 0x1E, 0x42, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups)
        return Machine(d).run(limit=5000)


class HandleMemory(unittest.TestCase):
    def test_local_heap_behind_a_moveable_handle(self):
        from unicorn.x86_const import UC_X86_REG_DS
        host = run()
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        handle = host.word(ds, 0x42)
        self.assertEqual(handle & 7, 4)
        self.assertNotEqual(host.word(ds, 0x40), 0)
        # The heap is in the block: LocalInit's pointer at +6 reads the same through either name.
        self.assertEqual(host.word(handle, 6), host.word(handle & ~7, 6))
        self.assertNotEqual(host.word(handle & ~7, 6), 0)


if __name__ == "__main__":
    unittest.main()
