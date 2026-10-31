"""Item 51. TB80BAS exports stay in the DLL. No binary needed."""

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne

PACKAGE = Path(__file__).resolve().parent.parent / "tbpipeline_neww"


def _bas(directory):
    code = bytes([0xCB, 0xCB])
    blob = neww_ne.build(
        "TB80BAS", [(0x0000, code, [])],
        entries=[(1, 1, 0, "CDBFILEOPEN"), (2, 1, 1, "HEAPALLOC")], exe=False,
    )
    return neww_ne.write(directory, "TB80BAS.DLL", blob)


class BasStaysInDll(unittest.TestCase):
    def run_main(self, directory):
        from tbpipeline_neww.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--b", str(directory)])
        return code, out.getvalue()

    def test_line_when_bas_is_in_bin(self):
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program(d)
            _bas(d)
            code, text = self.run_main(d)
        self.assertEqual(code, 0)
        self.assertIn("TB80BAS 2 exports stay in the DLL. neww does not answer them in Python.", text)

    def test_no_line_without_bas(self):
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program(d)
            _code, text = self.run_main(d)
        self.assertNotIn("TB80BAS", text)

    def test_no_python_bas_export(self):
        pattern = re.compile(r"^\s*(def|class)\s+_*(CDB|OBJ|HEAP|STACK|RESMGR)", re.I | re.M)
        for path in PACKAGE.glob("*.py"):
            self.assertIsNone(pattern.search(path.read_text()), path.name)


if __name__ == "__main__":
    unittest.main()
