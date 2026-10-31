"""Item 25: an open of a path ending in .tbk or .sbk is the book on the command line.

Asked through the stub the way the guest would ask, then the magic at
0xC00 is read back through the same handle. A 0xFFFF for a book that
exists is a failure, not a skip.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_BX, UC_X86_REG_CX

from tests.bf_host_fake import fake_host, far_call
from tests.fixtures import book as fixture

REFUSED = 0xFFFF


def put(host, name):
    host.arena.write(host.data, 0x100, name.encode("ascii") + b"\x00")


def open_file(host, name):
    """KERNEL.74 OpenFile(lpFileName, lpReOpenBuff, uStyle)."""
    put(host, name)
    far_call(host, "KERNEL", 74, [0, 0x200, host.data, 0x100, host.data], pop=10)
    return host.uc.reg_read(UC_X86_REG_AX)


def lopen(host, name):
    """KERNEL.85 _lopen(lpPathName, iReadWrite)."""
    put(host, name)
    far_call(host, "KERNEL", 85, [0, 0x100, host.data], ret_ip=0x305, pop=6)
    return host.uc.reg_read(UC_X86_REG_AX)


def dos_open(host, name):
    put(host, name)
    host.uc.reg_write(UC_X86_REG_DX, 0x100)
    host.uc.reg_write(UC_X86_REG_AX, 0x3D00)
    host._dos()
    return host.uc.reg_read(UC_X86_REG_AX)


def magic_via_kernel(host, handle):
    """_llseek(h, 0xC00, 0) then _lread(h, buf, 4)."""
    far_call(host, "KERNEL", 84, [0, fixture.STUB, 0, handle], ret_ip=0x405, pop=8)
    far_call(host, "KERNEL", 82, [4, 0x400, host.data, handle], ret_ip=0x505, pop=8)
    n = host.uc.reg_read(UC_X86_REG_AX)
    return struct.unpack("<I", host.arena.read(host.data, 0x400, 4))[0] if n == 4 else None


def magic_via_dos(host, handle):
    host.uc.reg_write(UC_X86_REG_BX, handle)
    host.uc.reg_write(UC_X86_REG_CX, 0)
    host.uc.reg_write(UC_X86_REG_DX, fixture.STUB)
    host.uc.reg_write(UC_X86_REG_AX, 0x4200)
    host._dos()
    host.uc.reg_write(UC_X86_REG_BX, handle)
    host.uc.reg_write(UC_X86_REG_CX, 4)
    host.uc.reg_write(UC_X86_REG_DX, 0x400)
    host.uc.reg_write(UC_X86_REG_AX, 0x3F00)
    host._dos()
    return struct.unpack("<I", host.arena.read(host.data, 0x400, 4))[0]


class TbkOpenIsTheBook(unittest.TestCase):
    def setUp(self):
        self.book = fixture.build()
        self.host = fake_host(book=self.book)

    def assertBook(self, handle, path):
        self.assertNotEqual(handle, REFUSED, f"{path} exists and the stub refused it")
        self.assertIs(self.host.files[handle], self.host.book_bytes)

    def test_openfile_tbk(self):
        path = "C:\\COURSES\\fixture.tbk"
        handle = open_file(self.host, path)
        self.assertBook(handle, path)
        self.assertEqual(magic_via_kernel(self.host, handle), fixture.MAGIC)

    def test_openfile_sbk_and_upper_case(self):
        for path in ("C:\\TOOLBOOK\\SYSTEM.SBK", "C:\\COURSES\\FIXTURE.TBK"):
            handle = open_file(self.host, path)
            self.assertBook(handle, path)
            self.assertEqual(magic_via_kernel(self.host, handle), fixture.MAGIC)

    def test_lopen_tbk(self):
        handle = lopen(self.host, "fixture.tbk")
        self.assertBook(handle, "fixture.tbk")
        self.assertEqual(magic_via_kernel(self.host, handle), fixture.MAGIC)

    def test_dos_open_tbk(self):
        handle = dos_open(self.host, "fixture.tbk")
        self.assertBook(handle, "fixture.tbk")
        self.assertEqual(magic_via_dos(self.host, handle), fixture.MAGIC)

    def test_locator_is_in_the_handle(self):
        handle = open_file(self.host, "fixture.tbk")
        self.assertIn(fixture.LOCATOR, self.host.files[handle][:fixture.STUB])

    def test_ini_is_still_refused(self):
        self.assertEqual(open_file(self.host, "C:\\TOOLBOOK\\TB80.INI"), REFUSED)


if __name__ == "__main__":
    unittest.main()
