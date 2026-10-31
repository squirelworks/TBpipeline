"""OpenFile with OF_REOPEN opens the path the OFSTRUCT holds.

TB80W32 hands TB80NET an OFSTRUCT whose szPathName is the book, and
TB80NET opens it with OpenFile(NULL, &ofs, OF_REOPEN | ...). The host
read the NULL name, qualified it, and wrote C:\\TOOLBOOK\\ over
szPathName, so the book's path was lost and the runtime said "This
network book cannot be opened".
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

OFS = 0x200
OF_REOPEN = 0x8000
OF_READWRITE = 0x0002
OF_SHARE_EXCLUSIVE = 0x0010
PATH = b"C:\\TOOLBOOK\\fixture.tbk"


class OpenFileReopen(unittest.TestCase):
    def test_reopen_uses_szpathname(self):
        host = fake_host(book=b"the book")
        host.arena.write(host.data, OFS, struct.pack("<BBHI", 136, 1, 0, 0) + PATH + b"\x00")
        style = OF_REOPEN | OF_SHARE_EXCLUSIVE | OF_READWRITE
        far_call(host, "KERNEL", 74, [style, OFS, host.data, 0, 0], pop=10)
        handle = host.uc.reg_read(UC_X86_REG_AX)
        self.assertNotEqual(handle, 0xFFFF, "the reopen failed")
        self.assertEqual(host.files[handle], b"the book")
        raw = host.arena.read(host.data, OFS, 136)
        self.assertEqual(raw[8:].split(b"\x00", 1)[0], PATH, "szPathName was overwritten")
        self.assertEqual(struct.unpack_from("<H", raw, 2)[0], 0)
        self.assertEqual(host.opens[-1], PATH.decode())


if __name__ == "__main__":
    unittest.main()
