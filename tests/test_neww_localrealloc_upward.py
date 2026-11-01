"""KERNEL.6 LocalReAlloc grows a fixed block into the free arena after it.

Wine local.c LocalReAlloc16: when the next arena is free and reaches the new end,
LOCAL_GrowArenaUpward removes that arena, LOCAL_ShrinkArena gives back what is left, and the
handle is returned unchanged. Logic Families stopped here on the way to P300.
"""

import tempfile
import unittest

from tests import neww_ne
from tests.test_neww_localalloc import push
from unicorn.x86_const import UC_X86_REG_DS


def program(directory, flags=0):
    code = bytearray(push(0) + push(0x20) + push(0x3E0))
    fixups = [(3, 1, len(code) + 1, 1, 4)]                       # LocalInit(0, 0x20, 0x3E0)
    code += neww_ne.call_far()

    def call(ordinal, *args, store=None):
        nonlocal code
        for a in args:
            code += push(a)
        fixups.append((3, 1, len(code) + 1, 1, ordinal))
        code += neww_ne.call_far()
        if store is not None:
            code += bytes([0xA3, store & 0xFF, store >> 8])        # mov [store], ax

    call(5, 0, 8, store=0x3F0)                                     # a = LocalAlloc(LMEM_FIXED, 8)
    call(5, 0, 8, store=0x3F2)                                     # b = LocalAlloc(LMEM_FIXED, 8)
    code += bytes([0x8B, 0x1E, 0xF2, 0x03, 0xC7, 0x47, 0x06, 0xCD, 0xAB])  # mov bx,[b]; mov [bx+6], 0xABCD
    code += bytes([0xFF, 0x36, 0xF2, 0x03])                        # push [b]
    fixups.append((3, 1, len(code) + 1, 1, 7))                     # LocalFree(b)
    code += neww_ne.call_far()
    code += bytes([0xFF, 0x36, 0xF0, 0x03]) + push(0x20) + push(flags)  # push [a], 0x20, flags
    fixups.append((3, 1, len(code) + 1, 1, 6))                     # LocalReAlloc(a, 0x20, 0)
    code += neww_ne.call_far()
    code += bytes([0xA3, 0xF4, 0x03])
    neww_ne.exit_program_with(directory, bytes(code), fixups, data=0x400)


class GrowUpward(unittest.TestCase):
    def run_program(self, flags=0):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, flags)
            host = Machine(d).run(limit=20000)
        return host, host.uc.reg_read(UC_X86_REG_DS)

    def test_zeroinit_clears_what_the_block_gained(self):
        # local.c LocalReAlloc16: memset from the old end to the arena's new next.
        host, ds = self.run_program(0x40)
        b = host.word(ds, 0x3F2)
        self.assertEqual(host.word(ds, b + 6), 0)

    def test_without_zeroinit_the_old_bytes_stay(self):
        host, ds = self.run_program(0)
        b = host.word(ds, 0x3F2)
        self.assertEqual(host.word(ds, b + 6), 0xABCD)

    def test_the_block_stays_put_and_takes_the_free_arena(self):
        host, ds = self.run_program()
        self.assertEqual(host.stop, "dos exit 0x0")
        a, b, got = host.word(ds, 0x3F0), host.word(ds, 0x3F2), host.word(ds, 0x3F4)
        self.assertEqual(b, a + 0x0C)                              # b's arena followed a's
        self.assertEqual(got, a)                                   # not moved
        arena = a - 4
        nxt = host.word(ds, arena + 2)
        self.assertEqual(nxt, (a + 0x20 + 3) & ~3)                 # a now ends at its new size
        self.assertEqual(host.word(ds, nxt) & 3, 0)                # and the rest is free again


if __name__ == "__main__":
    unittest.main()
