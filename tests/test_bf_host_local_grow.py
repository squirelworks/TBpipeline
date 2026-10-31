"""Item 27: LocalAlloc grows a full DGROUP, the way Windows does.

The real pass 06 run filled TB80BAS's local heap (its NE header asks for a
small one). LocalAlloc returned 0 for 0xC8 and 0xDA bytes, TB80BAS fell back
to allocating in the task's DS, wrote its record there, then read the record
back through its own DS as zeros. The open asserted at TB80BAS line 629.
Windows grows the automatic data segment up to 64K before it fails.
"""

import struct
import unittest

from unicorn import UC_HOOK_INSN
from unicorn.x86_const import UC_X86_INS_OUT, UC_X86_REG_AX, UC_X86_REG_DS, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call, run_guest

LMEM_ZEROINIT = 0x40
GUEST = 0xF020 + 13   # run_guest's code starts after its 13-byte prefix


class LocalGrow(unittest.TestCase):
    def host_with_small_heap(self):
        host = fake_host()
        host.dgroup = host.arena.alloc_selector(0x400, 0x92, b"S" * 0x300)
        host.uc.reg_write(UC_X86_REG_DS, host.dgroup)
        # LocalInit(ds, 0, 0x100): the heap is the top 0x100 bytes.
        far_call(host, "KERNEL", 4, [0x100, 0, host.dgroup], pop=6)
        return host

    def alloc(self, host, size):
        far_call(host, "KERNEL", 5, [size, LMEM_ZEROINIT], pop=4)
        return host.uc.reg_read(UC_X86_REG_AX)

    def test_alloc_past_the_initial_heap_grows(self):
        host = self.host_with_small_heap()
        self.assertTrue(self.alloc(host, 0x80))
        at = self.alloc(host, 0xDA)
        self.assertNotEqual(at, 0, "LocalAlloc failed instead of growing DGROUP")
        self.assertGreaterEqual(host.arena.segs[host.dgroup]["limit"], at + 0xDA - 1)

    def test_grown_segment_keeps_its_bytes_and_selector(self):
        host = self.host_with_small_heap()
        at = self.alloc(host, 0x400)
        self.assertTrue(at)
        self.assertEqual(host.arena.read(host.dgroup, 0, 0x300), b"S" * 0x300)
        host.arena.write(host.dgroup, at, b"rec")
        self.assertEqual(host.arena.read(host.dgroup, at, 3), b"rec")
        self.assertEqual(host.arena.read(host.dgroup, at + 3, 0x10), bytes(0x10))

    def test_guest_ds_sees_the_grown_segment(self):
        """The grow happens inside a real thunk call. After it returns, a
        write through the caller's DS must land in the grown segment."""
        host = self.host_with_small_heap()
        host.uc.hook_add(UC_HOOK_INSN, host._on_out, None, 1, 0, UC_X86_INS_OUT)
        # The thunk: mov dx, 5; out 0xE0, al; retf 0.
        host.arena.write(host.thunk, 0, bytes([0xBA, 0x05, 0x00, 0xE6, 0xE0, 0xCA, 0x00, 0x00]))
        sel, thunk = host.dgroup, host.thunk
        code = bytes([
            0xB8, sel & 0xFF, sel >> 8, 0x8E, 0xD8,        # mov ds, dgroup
            0x6A, LMEM_ZEROINIT, 0x68, 0x00, 0x08,          # push flags; push 0x800
            0x9A, 0x00, 0x00, thunk & 0xFF, thunk >> 8,     # call far thunk:0
        ])
        ret_ip = GUEST + len(code)
        host.sites[(host.flat, ret_ip)] = ("KERNEL", 5, 4)
        host.callers[(host.flat, ret_ip)] = ("KERNEL", 5)
        code += bytes([0x89, 0x06, 0x00, 0x01,              # mov [0x100], ax
                       0xC7, 0x06, 0x00, 0x09, 0x34, 0x12])  # mov word [0x900], 0x1234
        run_guest(host, code)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP, "the stack is not balanced")
        self.assertEqual(host.arena.read(sel, 0x900, 2), b"\x34\x12", "DS still points at the old memory")
        self.assertEqual(struct.unpack("<H", host.arena.read(sel, 0x100, 2))[0], 0x300)

    def test_64k_is_still_the_ceiling(self):
        host = self.host_with_small_heap()
        self.assertEqual(self.alloc(host, 0xFFF0), 0)


if __name__ == "__main__":
    unittest.main()
