"""newl reads LocalAlloc and GetModuleFileName in the order Wine's spec pushes them.

`5 pascal -ret16 LocalAlloc(word word)`: the flags are pushed first, so the
size is the word on top of the stack. `49 pascal -ret16
GetModuleFileName(word ptr s_word)`: nSize is pushed last, so it is on top,
then the buffer's offset and selector, then hModule. newl used to read the
flags as the size and hModule as the count. neww reads both this way.
"""

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


def _call(code, ordinal, relocs):
    relocs.append((FAR, BY_ORDINAL, len(code) + 1, 1, ordinal))
    return code + b"\x9a\xff\xff\x00\x00"


def _run(code, relocs):
    from tbpipeline_newl.cpu import Cpu

    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(code + b"\xf4", relocs), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["KERNEL"], auto=2, heap=0x400, stack=0x200)
    host = Cpu(tmp.name)
    host.run(limit=200)
    tmp.cleanup()
    return host


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class SpecArgOrder(unittest.TestCase):
    def test_localalloc_size_is_the_top_word(self):
        relocs = []
        code = _call(_push(0x0040) + _push(0x0100), 5, relocs)
        code += b"\x50"  # push ax: the first block
        code = _call(code + _push(0x0040) + _push(0x0010), 5, relocs)
        host = _run(code, relocs)
        calls = [row[:3] for row in host.layer.trace]
        self.assertEqual(calls[-2:], [("KERNEL", 5, "LocalAlloc")] * 2)
        second = host.uc.reg_read(UC_X86_REG_AX)
        # The local heap starts at 0x2000, past the fixture's data. The first
        # block is 0x100 bytes, not the 0x40 the flags word says.
        self.assertEqual(second, 0x2100)
        self.assertEqual(host.layer.heap_brk, 0x2110)

    def test_getmodulefilename_count_is_the_top_word(self):
        relocs = []
        # GetModuleFileName(hModule 0, DS:0x100, nSize 5), with DS the fixture's data segment.
        code = _push(0) + b"\x1e" + _push(0x0100) + _push(5)
        code = _call(code, 49, relocs)
        host = _run(code, relocs)
        self.assertEqual(host.layer.trace[-1][:3], ("KERNEL", 49, "GetModuleFileName"))
        # lstrcpyn semantics: nSize - 1 characters and a NUL.
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 4)
        ds = host.uc.reg_read(unicorn.x86_const.UC_X86_REG_DS)
        seg = host.selectors[ds]
        self.assertEqual(bytes(host.uc.mem_read(seg["base"] + 0x100, 6)), b"TB80\x00\x00")


if __name__ == "__main__":
    unittest.main()
