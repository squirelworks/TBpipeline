"""newl GlobalAlloc reads its size as the dword Wine's spec names, low word on top."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX
except ImportError:
    unicorn = None


def _push(word):
    return b"\x68" + word.to_bytes(2, "little")


def _rtm(root, size, flags=0x0042):
    """GlobalAlloc(flags, size) the way a pascal caller pushes it, then hlt."""
    code = _push(flags) + _push(size >> 16) + _push(size & 0xFFFF)
    reloc = (FAR, BY_ORDINAL, len(code) + 1, 1, 15)
    code += b"\x9a\xff\xff\x00\x00\xf4"
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(code, [reloc]), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["KERNEL"], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class GlobalAllocSize(unittest.TestCase):
    def _alloc(self, size):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp), size)
            host = Cpu(tmp)
            host.run(limit=100)
        handle = host.uc.reg_read(UC_X86_REG_AX)
        self.assertEqual(host.layer.trace[-1][:3], ("KERNEL", 15, "GlobalAlloc"))
        return host, handle

    def test_small_size_is_the_low_word(self):
        host, handle = self._alloc(0x1800)
        self.assertEqual(host.layer.gsizes[handle], 0x2000)
        self.assertEqual(host.layer.capped, [])

    def test_size_over_64k_keeps_the_high_word(self):
        host, handle = self._alloc(0x18000)
        # Low word alone would be 0x8000. A 16-bit segment stops at 64K.
        self.assertEqual(host.layer.gsizes[handle], 0x10000)
        self.assertEqual(host.layer.capped, [(handle, 0x18000)])


if __name__ == "__main__":
    unittest.main()
