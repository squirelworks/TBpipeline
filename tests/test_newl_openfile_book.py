"""newl OpenFile of a .tbk is a handle whose bytes are the book on the command line."""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_newl.layer import Layer, Refused
from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None

MAGIC = 0x22222222


def _book(path):
    """An original stand-in: the locator magic at 0xC00 and nothing else."""
    raw = bytearray(0xC10)
    struct.pack_into("<I", raw, 0xC00, MAGIC)
    path.write_bytes(bytes(raw))
    return path


def _push(word):
    return b"\x68" + struct.pack("<H", word)


def _rtm(root, name):
    """OpenFile(name, &ofs, 0); _llseek(h, 0xC00, 0); _lread(h, buf, 4); hlt.
    DGROUP holds the name at 0x100, the OFSTRUCT at 0x200, the buffer at 0x300."""
    code = bytearray()
    relocs = []

    def far(ordinal):
        relocs.append((FAR, BY_ORDINAL, len(code) + 1, 1, ordinal))
        code.extend(b"\x9a\xff\xff\x00\x00")

    code += b"\x1e" + _push(0x100) + b"\x1e" + _push(0x200) + _push(0)  # push ds; ...
    far(74)
    code += b"\x89\xc3"  # mov bx, ax
    code += b"\x53" + _push(0x0000) + _push(0x0C00) + _push(0)  # push bx; long 0xC00; origin 0
    far(84)
    code += b"\x53\x1e" + _push(0x300) + _push(4)  # push bx; push ds; buf; count
    far(82)
    code += b"\xf4"
    data = bytearray(0x2000)
    raw = name.encode("latin1") + b"\x00"
    data[0x100:0x100 + len(raw)] = raw
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(bytes(code), relocs), Seg(bytes(data), flags=1)],
          modules=["KERNEL"], auto=2, stack=0x200)


class OpenBookLayer(unittest.TestCase):
    def test_tbk_without_book_is_refused_by_name(self):
        with self.assertRaises(Refused) as got:
            Layer().call("KERNEL", 74, [0] * 8, path="C:\\NIDA\\LESSON.TBK")
        self.assertEqual(str(got.exception), "OpenFile C:\\NIDA\\LESSON.TBK: no book on the command line (--c)")

    def test_tbk_handle_reads_the_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _book(Path(tmp) / "fixture.tbk")
            layer = Layer(book)
            handle = layer.call("KERNEL", 74, [0] * 8, path="LESSON.TBK")
            self.assertEqual(layer.call("KERNEL", 84, [0, 0x0C00, 0, handle]), 0xC00)
            self.assertEqual(layer.call("KERNEL", 82, [4, 0, 0, handle]), 4)
            self.assertEqual(struct.unpack("<I", layer.last_read)[0], MAGIC)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class OpenBookFromGuest(unittest.TestCase):
    def test_guest_reads_the_magic_through_the_handle(self):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = _book(root / "fixture.tbk")
            _rtm(root, "C:\\BOOKS\\LESSON.TBK")
            host = Cpu(root, book=book)
            host.run(limit=1000)
        self.assertTrue(host.stop.startswith("hlt at "), host.stop)
        dgroup = host.selectors[host.dgroup]
        got = host.uc.mem_read(dgroup["base"] + 0x300, 4)
        self.assertEqual(struct.unpack("<I", got)[0], MAGIC)
        names = [row[2] for row in host.layer.trace]
        self.assertEqual(names, ["OpenFile", "_llseek", "_lread"])


if __name__ == "__main__":
    unittest.main()
