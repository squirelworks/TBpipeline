"""OpenFile with OF_CREATE creates an empty file the host keeps.

The host only had the book and the INI files, so a file the guest made
itself, like the book file manager's temp file C:\\WINDOWS\\TEMP\\OBJ1.TMP,
could not be opened. A created file lives in the host, never on disk,
and later opens of the same path find it.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

OFS = 0x200
NAME = 0x300
BUF = 0x400
OF_READ = 0x0000
OF_READWRITE = 0x0002
OF_CREATE = 0x1000
TEMP = b"C:\\WINDOWS\\TEMP\\OBJ1.TMP"


def open_file(host, name, style):
    host.arena.write(host.data, NAME, name + b"\x00")
    far_call(host, "KERNEL", 74, [style, OFS, host.data, NAME, host.data], pop=10)
    return host.uc.reg_read(UC_X86_REG_AX)


class CreateFile(unittest.TestCase):
    def test_create_then_reopen(self):
        host = fake_host(book=b"the book")
        self.assertNotEqual(open_file(host, TEMP, OF_CREATE | OF_READWRITE), 0xFFFF, "OF_CREATE failed")
        handle = open_file(host, TEMP, OF_READ)
        self.assertNotEqual(handle, 0xFFFF, "the created file cannot be opened again")
        self.assertEqual(host.files[handle], b"", "a new file is empty")

    def test_a_missing_file_still_fails(self):
        host = fake_host(book=b"the book")
        self.assertEqual(open_file(host, TEMP, OF_READ), 0xFFFF)


if __name__ == "__main__":
    unittest.main()
