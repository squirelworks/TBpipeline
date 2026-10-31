"""When newl hits the cap it can show the last 20 basic blocks, as CS:IP offsets."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


def _rtm(root):
    """Three blocks in a loop: 0x0 jmp 0x10, 0x10 jmp 0x20, 0x20 jmp 0x0."""
    code = bytearray(b"\x90" * 0x30)
    code[0x00:0x02] = b"\xeb\x0e"
    code[0x10:0x12] = b"\xeb\x0e"
    code[0x20:0x22] = b"\xeb\xde"
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(bytes(code)), Seg(b"\x00" * 0x2000, flags=1)], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class LastBlocks(unittest.TestCase):
    def test_last_twenty_blocks(self):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp))
            host = Cpu(tmp)
            host.run(limit=300)
        cs = host.exe["segments"][0]["selector"]
        self.assertTrue(host.stop.startswith("instruction cap 300"), host.stop)
        self.assertEqual(len(host.recent), 20)
        self.assertEqual({off for sel, off in host.recent if sel == cs}, {0x00, 0x10, 0x20})
        offsets = [off for _sel, off in host.recent]
        for a, b in zip(offsets, offsets[1:]):
            self.assertEqual(b, {0x00: 0x10, 0x10: 0x20, 0x20: 0x00}[a])

    def test_cli_prints_them_on_a_cap(self):
        from tbpipeline_newl import __main__ as cli
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp))
            run = Cpu.run
            out = io.StringIO()
            try:
                Cpu.run = lambda self, limit=300: run(self, limit)
                with contextlib.redirect_stdout(out):
                    cli.main(["--b", tmp])
            finally:
                Cpu.run = run
        line = next(l for l in out.getvalue().splitlines() if "last blocks" in l)
        self.assertEqual(len(line.split()) - 2, 20)


if __name__ == "__main__":
    unittest.main()
