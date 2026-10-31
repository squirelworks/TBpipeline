"""A newl run that ends without a gap says whether it was a hlt or the instruction cap."""

import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


def _rtm(root, code, relocs=()):
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(code, list(relocs)), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["KERNEL"], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class RunEnd(unittest.TestCase):
    def _run(self, code, relocs=(), limit=200):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp), code, relocs)
            host = Cpu(tmp)
            host.run(limit=limit)
        return host, host.exe["segments"][0]["selector"]

    def test_hlt(self):
        host, cs = self._run(b"\x90\x90\xf4")
        self.assertEqual(host.stop, f"hlt at {cs:#x}:0x2")

    def test_cap_with_no_windows_call(self):
        host, cs = self._run(b"\xeb\xfe")  # jmp $
        self.assertEqual(host.stop, f"instruction cap 200 reached at {cs:#x}:0x0, no Windows call taken")

    def test_cap_after_a_windows_call(self):
        code = b"\x9a\xff\xff\x00\x00\xeb\xfe"  # call far KERNEL.3; jmp $
        host, cs = self._run(code, [(FAR, BY_ORDINAL, 1, 1, 3)])
        self.assertEqual(
            host.stop, f"instruction cap 200 reached at {cs:#x}:0x5, 1 Windows calls taken, last KERNEL.3 GetVersion")



@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot be imported")
class CapStays(unittest.TestCase):
    def test_cap_values(self):
        from tbpipeline_newl import cpu

        self.assertEqual(cpu.Cpu.run.__defaults__, (1_000_000,))
        self.assertEqual(cpu.TIMEOUT_US, 15_000_000)


if __name__ == "__main__":
    unittest.main()
