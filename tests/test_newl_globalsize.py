"""newl GlobalSize answers for the selector GlobalLock returned, in DX:AX."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX
except ImportError:
    unicorn = None


def _rtm(root, size, by_selector):
    """GlobalAlloc(0x2002, size); GlobalLock; GlobalSize(selector or handle); hlt.
    The same sequence TB80RCR runs at 0x1420:0xBDA3 before it uses a block."""
    code = bytearray()
    relocs = []

    def far(ordinal):
        relocs.append((FAR, BY_ORDINAL, len(code) + 1, 1, ordinal))
        code.extend(b"\x9a\xff\xff\x00\x00")

    code += b"\x68\x02\x20" + b"\x68" + (size >> 16).to_bytes(2, "little") + b"\x68" + (size & 0xFFFF).to_bytes(2, "little")
    far(15)
    code += b"\x89\xc3\x50"  # mov bx, ax; push ax
    far(18)
    code += b"\x52" if by_selector else b"\x53"  # push dx (selector) or push bx (handle)
    far(20)
    code += b"\xf4"
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(bytes(code), relocs), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["KERNEL"], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class GlobalSize(unittest.TestCase):
    def _size(self, size, by_selector):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp), size, by_selector)
            host = Cpu(tmp)
            host.run(limit=100)
        self.assertEqual(host.layer.trace[-1][:3], ("KERNEL", 20, "GlobalSize"))
        return host.uc.reg_read(UC_X86_REG_DX) << 16 | host.uc.reg_read(UC_X86_REG_AX)

    def test_selector(self):
        self.assertEqual(self._size(0x1000, by_selector=True), 0x1000)

    def test_handle(self):
        self.assertEqual(self._size(0x1000, by_selector=False), 0x1000)

    def test_64k_is_dx_ax(self):
        self.assertEqual(self._size(0x10000, by_selector=True), 0x10000)


if __name__ == "__main__":
    unittest.main()
