"""KERNEL32.HeapCreate, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2): kernelbase HeapCreate (dlls/kernelbase/memory.c:740)
is RtlCreateHeap(flags, NULL, max_size, init_size), and NULL becomes
ERROR_NOT_ENOUGH_MEMORY. RtlCreateHeap (dlls/ntdll/heap.c:1499) rounds the
commit to 0x1000, makes a growable heap's size the commit + 1 rounded to
64K, and reserves that many bytes; the handle is the region's base.

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
HeapCreate and keeps EAX. The test then writes and reads the region's
last dword to show the whole reservation is mapped.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tbpipeline_bf.nedllhost import win32
from tbpipeline_bf.nedllhost.win32 import TEB
from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

KEPT = BASE + 0x2F04


def entry(flags, init, maximum):
    push = b"".join(bytes([0x68]) + struct.pack("<I", v) for v in (maximum, init, flags))
    return [push, call_import(0), bytes([0xA3]) + struct.pack("<I", KEPT)] + ATTACH


class HeapCreate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def call(self, flags, init, maximum):
        write(self.dir.name, "TESTW32.DLL", build([(None, entry(flags, init, maximum))], imports=[("KERNEL32.dll", "HeapCreate")]))
        self.h = host()
        self.hinst, _ = run(self.h)
        return struct.unpack("<I", bytes(self.h.uc.mem_read(KEPT, 4)))[0]

    def test_a_growable_heap_reserves_commit_plus_one_rounded_to_64k(self):
        heap = self.call(0, 0x1000, 0)
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(self.hinst, BASE, "HeapCreate pops 12")
        self.assertNotEqual(heap, 0)
        self.assertEqual(heap & 0xFFFF, 0, "a region starts on a 64K boundary")
        self.assertEqual(self.h.regions32[heap], 0x10000)
        self.h.uc.mem_write(heap + 0xFFFC, b"\x01\x02\x03\x04")
        self.assertEqual(bytes(self.h.uc.mem_read(heap + 0xFFFC, 4)), b"\x01\x02\x03\x04")

    def test_a_fixed_heap_reserves_its_maximum(self):
        heap = self.call(0, 0x1000, 0x30000)
        self.assertEqual(self.h.regions32[heap], 0x30000)

    def test_a_commit_of_a_full_region_rounds_up_to_two(self):
        heap = self.call(0, 0x10000, 0)
        self.assertEqual(self.h.regions32[heap], 0x20000)

    def test_no_room_is_null_with_not_enough_memory(self):
        with mock.patch.object(win32, "ARENA32_END", win32.ARENA32 + 0x10000):
            heap = self.call(0, 0x1000, 0x20000)
        self.assertEqual(heap, 0)
        self.assertEqual(struct.unpack("<I", bytes(self.h.uc.mem_read(TEB + 0x34, 4)))[0], 8)


if __name__ == "__main__":
    unittest.main()
