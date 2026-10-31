"""Item 27: LocalAlloc grows a full DGROUP, the way Windows does.

The real pass 06 run filled TB80BAS's local heap (its NE header asks for a
small one). LocalAlloc returned 0 for 0xC8 and 0xDA bytes, TB80BAS fell back
to allocating in the task's DS, wrote its record there, then read the record
back through its own DS as zeros. The open asserted at TB80BAS line 629.
Windows grows the automatic data segment up to 64K before it fails.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DS

from tests.bf_host_fake import fake_host, far_call, run_guest

LMEM_ZEROINIT = 0x40


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

    def test_ds_sees_the_grown_segment(self):
        host = self.host_with_small_heap()
        at = self.alloc(host, 0x800)
        # A guest read through DS after the grow lands in the new memory.
        host.arena.write(host.dgroup, at, b"\x34\x12")
        sel = host.dgroup
        code = bytes([0xB8, sel & 0xFF, sel >> 8, 0x8E, 0xD8,   # mov ds, dgroup
                      0xA1, at & 0xFF, at >> 8])                 # mov ax, [at]
        run_guest(host, code)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0x1234)

    def test_64k_is_still_the_ceiling(self):
        host = self.host_with_small_heap()
        self.assertEqual(self.alloc(host, 0xFFF0), 0)


if __name__ == "__main__":
    unittest.main()
