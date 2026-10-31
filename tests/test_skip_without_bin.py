"""bin_or_skip() is the one way a test asks for TB80RTM.EXE.

It reads TBK_BIN. It does not look in /Toolbook/, and it does not fall
back to bin/ beside tbpipeline_bf. A test that needs a binary skips
with a sentence when TBK_BIN is unset or the file is not there.
"""

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import binpath
from tests.binpath import bin_or_skip


class BinOrSkip(unittest.TestCase):
    def test_unset_skips_with_a_sentence(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(unittest.SkipTest) as hit:
                bin_or_skip()
        self.assertIn("TBK_BIN", str(hit.exception))

    def test_missing_file_skips_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TBK_BIN": tmp}):
                with self.assertRaises(unittest.SkipTest) as hit:
                    bin_or_skip()
        self.assertIn("TB80RTM.EXE", str(hit.exception))

    def test_present_returns_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "TB80RTM.EXE").write_bytes(b"MZ")
            with mock.patch.dict(os.environ, {"TBK_BIN": tmp}):
                self.assertEqual(bin_or_skip(), Path(tmp))

    def test_other_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "TB80RTM.EXE").write_bytes(b"MZ")
            with mock.patch.dict(os.environ, {"TBK_BIN": tmp}):
                with self.assertRaises(unittest.SkipTest) as hit:
                    bin_or_skip("TB80RTM.EXE", "TB80BMP.DLL")
        self.assertIn("TB80BMP.DLL", str(hit.exception))

    def test_ignores_tbk_unpacked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "TB80RTM.EXE").write_bytes(b"MZ")
            with mock.patch.dict(os.environ, {"TBK_UNPACKED": tmp}, clear=True):
                with self.assertRaises(unittest.SkipTest):
                    bin_or_skip()

    def test_never_reads_toolbook_archive(self):
        self.assertNotIn("/Toolbook", inspect.getsource(binpath))


if __name__ == "__main__":
    unittest.main()
