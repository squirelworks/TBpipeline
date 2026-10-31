"""Item 27: OpenFile fills the OFSTRUCT and honours OF_PARSE.

The real run's two book opens are OpenFile(..., OF_PARSE). Windows does
not open the file for OF_PARSE: it returns 0 and writes the fully
qualified name into the OFSTRUCT. The host returned a book handle and
left the OFSTRUCT as stack garbage.

OFSTRUCT: cBytes, fFixedDisk, nErrCode (word), 4 reserved bytes, then
szPathName[128].
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

NAME = 0x100
OFS = 0x200
OF_READ = 0x0000
OF_PARSE = 0x0100
OF_EXIST = 0x4000


def open_file(host, name, style):
    host.arena.write(host.data, NAME, name + b"\x00")
    host.arena.write(host.data, OFS, b"\xAA" * 136)
    far_call(host, "KERNEL", 74, [style, OFS, host.data, NAME, host.data], pop=10)
    ax = host.uc.reg_read(UC_X86_REG_AX)
    raw = host.arena.read(host.data, OFS, 136)
    return ax, raw[0], struct.unpack_from("<H", raw, 2)[0], raw[8:].split(b"\x00", 1)[0]


class OpenFileOfstruct(unittest.TestCase):
    def test_parse_returns_zero_and_the_full_name(self):
        host = fake_host(book=b"book")
        ax, size, err, path = open_file(host, b"fixture.tbk", OF_PARSE)
        self.assertEqual(ax, 0)
        self.assertEqual(size, 136)
        self.assertEqual(err, 0)
        self.assertEqual(path, b"C:\\TOOLBOOK\\fixture.tbk")
        self.assertEqual(host.files, {}, "OF_PARSE opened a handle")

    def test_open_fills_the_struct_and_keeps_an_absolute_path(self):
        host = fake_host(book=b"book")
        ax, size, err, path = open_file(host, b"D:\\BOOKS\\fixture.tbk", OF_READ)
        self.assertNotEqual(ax, 0xFFFF)
        self.assertEqual(host.files[ax], b"book")
        self.assertEqual((size, err, path), (136, 0, b"D:\\BOOKS\\fixture.tbk"))

    def test_missing_file_sets_the_error_code(self):
        host = fake_host(book=b"book")
        ax, size, err, path = open_file(host, b"C:\\NOWHERE\\x.dat", OF_READ)
        self.assertEqual(ax, 0xFFFF)
        self.assertEqual(err, 2)

    def test_exist_does_not_leave_a_handle(self):
        host = fake_host(book=b"book")
        ax, _, err, path = open_file(host, b"fixture.tbk", OF_EXIST)
        self.assertNotEqual(ax, 0xFFFF)
        self.assertEqual(err, 0)
        self.assertNotIn(ax, host.files, "OF_EXIST left the file open")


if __name__ == "__main__":
    unittest.main()
