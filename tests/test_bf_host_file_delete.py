"""OpenFile with OF_DELETE removes a file the guest created.

TB80NET deletes its temp file with OpenFile(name, &ofs, OF_DELETE). The
answer is 1 when the file was there. A file that is not there gives
HFILE_ERROR and error 2 in the OFSTRUCT. The book is never deleted.
"""

import struct
import unittest

from tests.bf_host_fake import fake_host
from tests.test_bf_host_file_create import OF_CREATE, OF_READ, OF_READWRITE, OFS, TEMP, open_file

OF_DELETE = 0x0200


class DeleteFile(unittest.TestCase):
    def test_delete_removes_the_file(self):
        host = fake_host(book=b"the book")
        open_file(host, TEMP, OF_CREATE | OF_READWRITE)
        self.assertEqual(open_file(host, TEMP, OF_DELETE), 1)
        self.assertEqual(open_file(host, TEMP, OF_READ), 0xFFFF, "the file is still there")

    def test_deleting_a_missing_file_fails(self):
        host = fake_host(book=b"the book")
        self.assertEqual(open_file(host, TEMP, OF_DELETE), 0xFFFF)
        self.assertEqual(struct.unpack("<H", host.arena.read(host.data, OFS + 2, 2))[0], 2)

    def test_the_book_is_not_deleted(self):
        host = fake_host(book=b"the book")
        book = b"C:\\TOOLBOOK\\fixture.tbk"
        self.assertEqual(open_file(host, book, OF_DELETE), 0xFFFF)
        self.assertNotEqual(open_file(host, book, OF_READ), 0xFFFF)


if __name__ == "__main__":
    unittest.main()
