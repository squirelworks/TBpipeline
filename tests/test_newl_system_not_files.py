"""A KERNEL.EXE, USER.EXE or GDI.EXE in --b is not loaded. System calls stay the layer."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX
except ImportError:
    unicorn = None


def _fake(root, name):
    """An original NE named like a system module: ordinal 1 and 3 return 0x1234."""
    build(root / f"{name}.EXE", name, [Seg(b"\xb8\x34\x12\xcb")], entries=[(1, 0), (1, 0), (1, 0)], exe=False)


def _rtm(root, module, ordinal):
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(b"\x9a\xff\xff\x00\x00\xf4", [(FAR, BY_ORDINAL, 1, 1, ordinal)]), Seg(b"\x00" * 0x2000, flags=1)],
          modules=[module], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class SystemNotFiles(unittest.TestCase):
    def _run(self, module, ordinal):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("KERNEL", "USER", "GDI"):
                _fake(root, name)
            _rtm(root, module, ordinal)
            host = Cpu(root)
            host.run(limit=100)
        return host

    def test_kernel_file_is_not_used(self):
        host = self._run("KERNEL", 3)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0x0A03)
        self.assertEqual(host.layer.trace[-1][:3], ("KERNEL", 3, "GetVersion"))
        self.assertNotIn("KERNEL", [img["name"] for img in host.images.values() if not img.get("synthetic")])

    def test_user_file_is_not_used(self):
        host = self._run("USER", 5)
        self.assertEqual(host.layer.trace[-1][:3], ("USER", 5, "InitApp"))

    def test_gdi_file_is_a_gap_not_code(self):
        host = self._run("GDI", 1)
        cs = host.exe["segments"][0]["selector"]
        self.assertEqual(host.stop, f"gap GDI.1 far call at {cs:#x}:0x0")
        self.assertEqual(sorted(Path(p).name for p in host.ignored), ["GDI.EXE", "KERNEL.EXE", "USER.EXE"])


if __name__ == "__main__":
    unittest.main()
