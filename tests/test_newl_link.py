"""ToolBook modules call each other by real fixups, by ordinal and by name. No gate."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_NAME, BY_ORDINAL, FAR, Seg, build, name_offsets

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_BX
except ImportError:
    unicorn = None


def _pair(root):
    # TB80UTL: ordinal 1 is mov ax, 0x4242; retf. UTLSECOND (ordinal 2) is mov bx, 0x77; retf.
    build(root / "TB80UTL.DLL", "TB80UTL", [Seg(b"\xb8\x42\x42\xcb\xbb\x77\x00\xcb")],
          entries=[(1, 0), (1, 4)], names=[("UTLSECOND", 2)], exe=False)
    offsets = name_offsets(["TB80UTL"], ["UTLSECOND"])
    code = b"\x9a\xff\xff\x00\x00" b"\x9a\xff\xff\x00\x00" b"\xf4"
    relocs = [(FAR, BY_ORDINAL, 1, 1, 1), (FAR, BY_NAME, 6, 1, offsets["UTLSECOND"])]
    build(root / "TB80RTM.EXE", "TB80RTM", [Seg(code, relocs), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["TB80UTL"], imports=["UTLSECOND"], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class ToolBookLink(unittest.TestCase):
    def test_far_calls_complete_without_the_layer(self):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _pair(Path(tmp))
            host = Cpu(tmp)
            utl = host.images["TB80UTL"]
            self.assertFalse(utl.get("synthetic"))
            host.run(limit=100)
        self.assertEqual(host.linked, 2)
        self.assertTrue(host.stop.startswith("hlt at "), host.stop)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0x4242)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_BX), 0x77)
        self.assertEqual(host.layer.trace, [])
        self.assertNotIn("TB80UTL", {module for (_cs, _o), module in host.gates.items()})


if __name__ == "__main__":
    unittest.main()
