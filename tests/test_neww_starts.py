"""tbpipeline_neww starts without --b.

A missing --b exits with a sentence, not a traceback, even where
unicorn is not installed. --help exits 0. Neither starts the sandbox.
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NO_UNICORN = (
    "import runpy, sys\n"
    "sys.modules['unicorn'] = None\n"
    "sys.argv = [sys.argv[1]] + sys.argv[2:]\n"
    "runpy.run_module(sys.argv[0], run_name='__main__', alter_sys=True)\n"
)


def run(*argv, unicorn=True):
    cmd = [sys.executable, "-m", *argv] if unicorn else [sys.executable, "-c", NO_UNICORN, *argv]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)


class NewwStarts(unittest.TestCase):
    def test_imports(self):
        import tbpipeline_neww
        self.assertTrue(tbpipeline_neww.__doc__)

    def test_no_bin_is_a_sentence(self):
        done = run("tbpipeline_neww")
        self.assertEqual(done.returncode, 2)
        self.assertIn("usage: python3 -m tbpipeline_neww", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_no_bin_without_unicorn(self):
        done = run("tbpipeline_neww", unicorn=False)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("usage: python3 -m tbpipeline_neww", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_help_exits_0(self):
        done = run("tbpipeline_neww", "--help", unicorn=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("python3 -m tbpipeline_neww", done.stdout)


if __name__ == "__main__":
    unittest.main()
