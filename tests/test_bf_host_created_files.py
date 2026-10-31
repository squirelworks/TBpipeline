"""Item 27: a file the guest creates can be opened, written and read back.

TB80W32 asks GetTempFileNameA for a name with uUnique 0, which on Windows
creates the file, and TB80NET then opens it with OpenFile, writes it with
_lwrite, reads it, and deletes it with OF_DELETE. The host only had the
book and the INI files, so the open of OBJ1.TMP failed. Created files live
in the host, never on disk, and the book stays read-only.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call
from tests.test_bf_host_win32_answers import call, scratch

OFS = 0x200
NAME = 0x300
BUF = 0x400
OF_READ = 0x0000
OF_READWRITE = 0x0002
OF_DELETE = 0x0200
OF_CREATE = 0x1000
TEMP = b"C:\\WINDOWS\\TEMP\\OBJ1.TMP"


def open_file(host, name, style):
    host.arena.write(host.data, NAME, name + b"\x00")
    far_call(host, "KERNEL", 74, [style, OFS, host.data, NAME, host.data], pop=10)
    return host.uc.reg_read(UC_X86_REG_AX)


def lwrite(host, handle, data):
    host.arena.write(host.data, BUF, data)
    far_call(host, "KERNEL", 86, [len(data), BUF, host.data, handle], pop=8)
    return host.uc.reg_read(UC_X86_REG_AX)


def lread(host, handle, count):
    far_call(host, "KERNEL", 82, [count, BUF, host.data, handle], pop=8)
    got = host.uc.reg_read(UC_X86_REG_AX)
    return host.arena.read(host.data, BUF, got)


class CreatedFiles(unittest.TestCase):
    def test_temp_file_name_creates_the_file(self):
        host = fake_host(book=b"the book")
        out = scratch(host)
        unique, _ = call(host, "KERNEL32", "GetTempFileNameA",
                         scratch(host, b"C:\\WINDOWS\\TEMP\\\x00"), scratch(host, b"OBJ\x00"), 0, out)
        self.assertEqual(unique, 1)
        self.assertEqual(bytes(host.uc.mem_read(out, len(TEMP))), TEMP)
        handle = open_file(host, TEMP, OF_READWRITE)
        self.assertNotEqual(handle, 0xFFFF, "the temp file GetTempFileNameA made cannot be opened")

    def test_write_then_read_back_through_another_handle(self):
        host = fake_host(book=b"the book")
        one = open_file(host, TEMP, OF_CREATE | OF_READWRITE)
        self.assertNotEqual(one, 0xFFFF, "OF_CREATE failed")
        self.assertEqual(lwrite(host, one, b"object data"), 11)
        two = open_file(host, TEMP, OF_READ)
        self.assertEqual(lread(host, two, 64), b"object data")

    def test_delete_removes_the_file(self):
        host = fake_host(book=b"the book")
        open_file(host, TEMP, OF_CREATE | OF_READWRITE)
        self.assertEqual(open_file(host, TEMP, OF_DELETE), 1)
        self.assertEqual(open_file(host, TEMP, OF_READ), 0xFFFF)
        self.assertEqual(struct.unpack("<H", host.arena.read(host.data, OFS + 2, 2))[0], 2)

    def test_the_book_is_not_written(self):
        host = fake_host(book=b"the book")
        handle = open_file(host, b"C:\\TOOLBOOK\\fixture.tbk", OF_READWRITE)
        self.assertEqual(lwrite(host, handle, b"xx"), 0xFFFF)
        self.assertEqual(host.book_bytes, b"the book")


if __name__ == "__main__":
    unittest.main()
