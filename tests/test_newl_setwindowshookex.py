"""newl USER.291 SetWindowsHookEx: the Wine spec's 10-byte pop, a nonzero HHOOK in DX:AX, and a record."""

import tempfile
import unittest
from pathlib import Path

from tbpipeline_newl.layer import USER, Layer
from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_SP
except ImportError:
    unicorn = None


class Contract(unittest.TestCase):
    def test_row(self):
        # user.exe16.spec: 291 pascal SetWindowsHookEx(s_word segptr word word)
        self.assertEqual(USER[291], ("SetWindowsHookEx", 10))

    def test_records_the_hook(self):
        layer = Layer()
        hhook = layer.call("USER", 291, [0x0077, 0x0101, 0x0020, 0x0158, 0xFFFF])
        self.assertEqual(hhook, 0x00010001)
        self.assertEqual(layer.hooks, [(-1, 0x0158, 0x0020, 0x0101, 0x0077)])


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class FromGuest(unittest.TestCase):
    def test_pop_and_dx_ax(self):
        from tbpipeline_newl.cpu import Cpu

        # push idHook=-1 (WH_MSGFILTER); push seg; push off; push hinst; push htask; call far USER.291; hlt
        code = b"\x68\xff\xff\x68\x58\x01\x68\x20\x00\x68\x01\x01\x68\x77\x00" + b"\x9a\xff\xff\x00\x00\xf4"
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / "TB80RTM.EXE", "TB80RTM",
                  [Seg(code, [(FAR, BY_ORDINAL, 16, 1, 291)]), Seg(b"\x00" * 0x2000, flags=1)],
                  modules=["USER"], auto=2, stack=0x200)
            host = Cpu(tmp)
            sp0 = len(host.exe["segments"][1]["data"]) - 2
            host.run(limit=100)
        self.assertTrue(host.stop.startswith("hlt at "), host.stop)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_DX), 0x0001)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0x0001)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), sp0)  # five words pushed, ten bytes popped
        self.assertEqual(host.layer.hooks, [(-1, 0x0158, 0x0020, 0x0101, 0x0077)])


if __name__ == "__main__":
    unittest.main()
