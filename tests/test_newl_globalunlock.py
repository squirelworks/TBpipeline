"""newl KERNEL.19 GlobalUnlock: the Wine spec's 2-byte pop and FALSE, because newl keeps no lock count."""

import tempfile
import unittest
from pathlib import Path

from tbpipeline_newl.layer import KERNEL, Layer
from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SP
except ImportError:
    unicorn = None


class Contract(unittest.TestCase):
    def test_row(self):
        # krnl386.exe16.spec: 19 pascal -ret16 GlobalUnlock(word)
        self.assertEqual(KERNEL[19], ("GlobalUnlock", 2))

    def test_answer(self):
        self.assertEqual(Layer().call("KERNEL", 19, [3]), 0)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class FromGuest(unittest.TestCase):
    def test_pop(self):
        from tbpipeline_newl.cpu import Cpu

        code = b"\xb8\x34\x12\x6a\x03" + b"\x9a\xff\xff\x00\x00\xf4"  # mov ax,0x1234; push 3; call far KERNEL.19
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / "TB80RTM.EXE", "TB80RTM",
                  [Seg(code, [(FAR, BY_ORDINAL, 6, 1, 19)]), Seg(b"\x00" * 0x2000, flags=1)],
                  modules=["KERNEL"], auto=2, stack=0x200)
            host = Cpu(tmp)
            sp0 = len(host.exe["segments"][1]["data"]) - 2
            host.run(limit=100)
        self.assertTrue(host.stop.startswith("hlt at "), host.stop)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), sp0)


if __name__ == "__main__":
    unittest.main()
