"""_lwrite writes to a file the guest created, and _lread reads it back.

KERNEL.86 _lwrite had no answer. A created file now takes writes, and
another handle on the same path reads them. The book and the INI files
stay read-only: _lwrite to them returns HFILE_ERROR.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call
from tests.test_bf_host_file_create import OF_CREATE, OF_READ, OF_READWRITE, TEMP, open_file

BUF = 0x400


def lwrite(host, handle, data):
    host.arena.write(host.data, BUF, data)
    far_call(host, "KERNEL", 86, [len(data), BUF, host.data, handle], pop=8)
    return host.uc.reg_read(UC_X86_REG_AX)


def lread(host, handle, count):
    far_call(host, "KERNEL", 82, [count, BUF, host.data, handle], pop=8)
    got = host.uc.reg_read(UC_X86_REG_AX)
    return host.arena.read(host.data, BUF, got)


class WriteFile(unittest.TestCase):
    def test_write_then_read_back_through_another_handle(self):
        host = fake_host(book=b"the book")
        one = open_file(host, TEMP, OF_CREATE | OF_READWRITE)
        self.assertEqual(lwrite(host, one, b"object data"), 11)
        two = open_file(host, TEMP, OF_READ)
        self.assertEqual(lread(host, two, 64), b"object data")

    def test_the_book_is_not_written(self):
        host = fake_host(book=b"the book")
        handle = open_file(host, b"C:\\TOOLBOOK\\fixture.tbk", OF_READWRITE)
        self.assertEqual(lwrite(host, handle, b"xx"), 0xFFFF)
        self.assertEqual(host.book_bytes, b"the book")


if __name__ == "__main__":
    unittest.main()
