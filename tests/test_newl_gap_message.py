"""A newl Gap names the module, the ordinal, the name when there is one, and the far call."""

import tempfile
import unittest
from pathlib import Path

from tbpipeline_newl.layer import Gap, Layer
from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None


def _rtm(root, ordinals):
    """Segment 1 makes one far call per ordinal into KERNEL, then hlt."""
    code = bytearray()
    relocs = []
    for ordinal in ordinals:
        relocs.append((FAR, BY_ORDINAL, len(code) + 1, 1, ordinal))
        code += b"\x9a\xff\xff\x00\x00"
    code += b"\xf4"
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(bytes(code), relocs), Seg(b"\x00" * 0x2000, flags=1)],
          modules=["KERNEL"], entry=(1, 0), auto=2, stack=0x200)


class GapText(unittest.TestCase):
    def test_layer_gap_without_site(self):
        with self.assertRaises(Gap) as got:
            Layer().call("KERNEL", 999)
        self.assertEqual(str(got.exception), "gap KERNEL.999")

    def test_layer_gap_with_name_and_site(self):
        layer = Layer()
        layer.events = 0
        with self.assertRaises(Gap) as got:
            layer.call("KERNEL", 30, [0], at=(0x1F, 0x12, "call"))
        self.assertEqual(str(got.exception), "gap KERNEL.30 WaitEvent far call at 0x1f:0x12")


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class GapFromFixture(unittest.TestCase):
    def _run(self, ordinals, events=1):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp), ordinals)
            host = Cpu(tmp)
            host.layer.events = events
            host.run(limit=1000)
        code_sel = host.exe["segments"][0]["selector"]
        return host.stop, code_sel

    def test_unknown_ordinal_names_the_call(self):
        stop, cs = self._run([3, 999])
        self.assertEqual(stop, f"gap KERNEL.999 far call at {cs:#x}:0x5")

    def test_named_ordinal_names_the_call(self):
        stop, cs = self._run([30, 30], events=1)
        self.assertEqual(stop, f"gap KERNEL.30 WaitEvent far call at {cs:#x}:0x5")


if __name__ == "__main__":
    unittest.main()
