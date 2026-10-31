"""KERNEL32.VirtualAlloc, called from a 32-bit DLL, answers as Wine does.

Wine (commit 2528aff2): kernelbase VirtualAlloc (dlls/kernelbase/memory.c:421)
is NtAllocateVirtualMemory on the current process. That refuses a size of
0 (dlls/ntdll/unix/virtual.c:4859), and allocate_virtual_memory
(virtual.c:4712) refuses a type with none of MEM_COMMIT, MEM_RESERVE or
MEM_RESET: STATUS_INVALID_PARAMETER, ERROR_INVALID_PARAMETER (87). With no
address it reserves at 64K granularity. MEM_COMMIT alone on an address
rounds it down to a page and needs a view that holds the range, or it is
STATUS_NOT_MAPPED_VIEW, ERROR_INVALID_ADDRESS (487).

The DLL is a tiny original PE built by tests/pe32.py. Its DllMain calls
VirtualAlloc twice: the second call's address is the first call's result
plus an offset, and both results are kept.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tbpipeline_bf.nedllhost.win32 import TEB
from tests.pe32 import BASE, build, call_import, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, host, run

FIRST, SECOND = BASE + 0x2F04, BASE + 0x2F08
MEM_COMMIT, MEM_RESERVE = 0x1000, 0x2000
PAGE_NOACCESS, PAGE_READWRITE = 1, 4


def push(*values):
    return b"".join(bytes([0x68]) + struct.pack("<I", v) for v in reversed(values))


def entry(first, second=None):
    """first: (addr, size, type, protect). second: (offset from first's result, size, type, protect)."""
    code = [push(*first), call_import(0), bytes([0xA3]) + struct.pack("<I", FIRST)]
    if second:
        offset, size, kind, protect = second
        # push protect, type and size, then EAX + offset as the address
        code += [push(protect) + push(kind) + push(size),
                 bytes([0x05]) + struct.pack("<I", offset), bytes([0x50]),
                 call_import(0), bytes([0xA3]) + struct.pack("<I", SECOND)]
    return code + ATTACH


class VirtualAlloc(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def call(self, first, second=None):
        write(self.dir.name, "TESTW32.DLL", build([(None, entry(first, second))], imports=[("KERNEL32.dll", "VirtualAlloc")]))
        self.h = host()
        self.hinst, _ = run(self.h)
        return struct.unpack("<II", bytes(self.h.uc.mem_read(FIRST, 8)))

    def last_error(self):
        return struct.unpack("<I", bytes(self.h.uc.mem_read(TEB + 0x34, 4)))[0]

    def test_reserve_then_commit_inside(self):
        base, page = self.call((0, 0x100000, MEM_RESERVE, PAGE_NOACCESS),
                               (0x10010, 0x10000, MEM_COMMIT, PAGE_READWRITE))
        self.assertFalse(self.h.fault.startswith("win32"), self.h.fault)
        self.assertEqual(self.hinst, BASE, "VirtualAlloc pops 16")
        self.assertEqual(base & 0xFFFF, 0, "a reservation starts on a 64K boundary")
        self.assertEqual(self.h.regions32[base], 0x100000)
        self.assertEqual(page, base + 0x10000, "the commit address is rounded down to a page")

    def test_reserve_and_commit_without_an_address_rounds_to_a_page(self):
        base, _ = self.call((0, 0x1801, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE))
        self.assertNotEqual(base, 0)
        self.h.uc.mem_write(base + 0x1FFC, b"\xAA\xBB\xCC\xDD")
        self.assertEqual(bytes(self.h.uc.mem_read(base + 0x1FFC, 4)), b"\xAA\xBB\xCC\xDD")

    def test_a_commit_past_the_reservation_is_invalid_address(self):
        base, page = self.call((0, 0x10000, MEM_RESERVE, PAGE_NOACCESS),
                               (0xF000, 0x2000, MEM_COMMIT, PAGE_READWRITE))
        self.assertNotEqual(base, 0)
        self.assertEqual(page, 0)
        self.assertEqual(self.last_error(), 487)

    def test_size_zero_is_invalid_parameter(self):
        base, _ = self.call((0, 0, MEM_RESERVE, PAGE_NOACCESS))
        self.assertEqual(base, 0)
        self.assertEqual(self.last_error(), 87)

    def test_no_allocation_type_is_invalid_parameter(self):
        base, _ = self.call((0, 0x1000, 0, PAGE_READWRITE))
        self.assertEqual(base, 0)
        self.assertEqual(self.last_error(), 87)

    def test_reserving_at_an_address_stops_the_run(self):
        self.call((0x30000000, 0x10000, MEM_RESERVE, PAGE_NOACCESS))
        self.assertEqual(self.h.fault, "win32 KERNEL32.VirtualAlloc MEM_RESERVE at 0x30000000")


if __name__ == "__main__":
    unittest.main()
