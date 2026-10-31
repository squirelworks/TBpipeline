"""newl --list counts named TB80BAS imports by layer, and the CPU never starts."""

import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tbpipeline_newl.__main__ import main
from tests.newl_fixture import BY_NAME, BY_ORDINAL, FAR, Seg, build, name_offsets


def _rtm(root):
    code = bytearray(b"\x90" * 32)
    for at in range(0, 32, 4):
        code[at:at + 4] = b"\xff\xff\x00\x00"
    names = ["HEAPNEWBLOCK", "CDBREADPAGE", "OBJFINDCHILD"]
    offsets = name_offsets(["TB80BAS"], names)
    relocs = [(FAR, BY_NAME, 4 * i, 1, offsets[name]) for i, name in enumerate(names)]
    relocs.append((FAR, BY_ORDINAL, 12, 1, 77))
    build(root / "TB80RTM.EXE", "TB80RTM", [Seg(bytes(code), relocs)], modules=["TB80BAS"], imports=names)


class ListBasLayers(unittest.TestCase):
    def test_counts_by_layer_without_cpu(self):
        fake = types.ModuleType("tbpipeline_newl.cpu")

        class Cpu:
            def __init__(self, *a, **k):
                raise AssertionError("--list started the CPU")

        fake.Cpu = Cpu
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"tbpipeline_newl.cpu": fake}):
            root = Path(tmp)
            _rtm(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--b", str(root), "--list"])
        self.assertEqual(code, 0)
        line = next(l for l in out.getvalue().splitlines() if l.startswith("TB80BAS by layer"))
        self.assertIn("HEAP 1", line)
        self.assertIn("STACK 0", line)
        self.assertIn("RESMGR 0", line)
        self.assertIn("CDB 1", line)
        self.assertIn("OBJ 1", line)
        self.assertIn("other 0", line)
        self.assertIn("unnamed 1", line)


if __name__ == "__main__":
    unittest.main()
