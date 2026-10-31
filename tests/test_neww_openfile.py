"""Item 63. OpenFile has a real file table. No binary needed.

A .tbk path opens the book from --c, and its bytes read back through
_llseek and _lread. A path not in --b returns HFILE_ERROR with
nErrCode 2 in the OFSTRUCT, which is what Wine's OpenFile16 does for a
missing file.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne

PATH, OFS, HANDLE, BUF = 0x00, 0x40, 0xD0, 0xE0


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


class Guest:
    def __init__(self):
        self.code = bytearray()
        self.fixups = []

    def call(self, ordinal):
        self.fixups.append((3, 1, len(self.code) + 1, 1, ordinal))
        self.code += neww_ne.call_far()

    def far(self, offset):
        self.code += bytes([0x1E]) + push(offset)  # push ds; push offset


def open_read(path, read=4, at=0xC00, mode=0):
    g = Guest()
    g.far(PATH)
    g.far(OFS)
    g.code += push(mode)
    g.call(74)
    g.code += bytes([0xA3, HANDLE, 0])            # mov [HANDLE], ax
    g.code += bytes([0x50]) + push(at >> 16) + push(at & 0xFFFF) + push(0)
    g.call(84)
    g.code += bytes([0xFF, 0x36, HANDLE, 0])      # push word [HANDLE]
    g.far(BUF)
    g.code += push(read)
    g.call(82)
    g.code += bytes([0x8B, 0x1E, HANDLE, 0])      # mov bx, [HANDLE]
    g.call(999)
    data = bytearray(512)
    raw = path.encode("latin1") + b"\x00"
    data[PATH:PATH + len(raw)] = raw
    return g, data


def fixture_book(directory):
    blob = bytearray(0xC00 + 16)
    struct.pack_into("<I", blob, 0xC00, 0x22222222)
    path = Path(directory) / "fixture.tbk"
    path.write_bytes(blob)
    return path


def run(path, files=None, book=True, mode=0):
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_BX
    from tbpipeline_neww.machine import Machine
    g, data = open_read(path, mode=mode)
    d = tempfile.mkdtemp()
    for name, raw in (files or {}).items():
        Path(d, name).write_bytes(raw)
    neww_ne.exit_program_with(d, bytes(g.code), g.fixups, data=data)
    host = Machine(d, fixture_book(tempfile.mkdtemp()) if book else None)
    host.run()
    dgroup = host.box.exe.segments[host.box.exe.auto - 1]
    mem = bytes(host.uc.mem_read(dgroup.base, 512))
    return host, mem, host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_BX)


class OpenFileTable(unittest.TestCase):
    def test_tbk_handle_is_the_book(self):
        host, mem, ax, bx = run("C:\\BOOKS\\LESSON.TBK")
        self.assertIn("KERNEL.999", host.stop)
        self.assertEqual(bx, 5)
        self.assertEqual(ax, 4)
        self.assertEqual(struct.unpack_from("<I", mem, BUF)[0], 0x22222222)
        self.assertEqual(mem[OFS], 136)
        self.assertEqual(struct.unpack_from("<H", mem, OFS + 2)[0], 0)
        self.assertEqual(mem[OFS + 8:OFS + 8 + 19], b"C:\\BOOKS\\LESSON.TBK")

    def test_missing_ini_is_hfile_error(self):
        host, mem, _ax, bx = run("C:\\WINDOWS\\TB80.INI")
        self.assertEqual(bx, 0xFFFF)
        self.assertEqual(struct.unpack_from("<H", mem, OFS + 2)[0], 2)
        self.assertEqual(host.box.wine.files, {})

    def test_ini_in_bin_opens(self):
        host, mem, ax, bx = run("TB80.INI", files={"tb80.ini": b"[x]\r\n" + b"\x00" * (0xC00 - 5) + b"INI!"})
        self.assertEqual(bx, 5)
        self.assertEqual(mem[BUF:BUF + 4], b"INI!")

    def test_tbk_without_c_is_hfile_error(self):
        _host, mem, _ax, bx = run("A.TBK", book=False)
        self.assertEqual(bx, 0xFFFF)
        self.assertEqual(struct.unpack_from("<H", mem, OFS + 2)[0], 2)

    def test_read_write_mode_opens_the_book(self):
        # OF_READWRITE opens as OF_READ does: TB80NET opens the book so. A write to it stops
        # (write_file), since neww never writes the host.
        host, mem, _ax, bx = run("A.TBK", mode=0x0002)
        self.assertNotEqual(bx, 0xFFFF)
        self.assertEqual(mem[BUF:BUF + 4], b"\x22\x22\x22\x22")

    def test_access_mode_3_stops(self):
        host, *_ = run("A.TBK", mode=0x0003)
        self.assertIn("KERNEL.74 OpenFile 'A.TBK' mode 0x0003", host.stop)


if __name__ == "__main__":
    unittest.main()
