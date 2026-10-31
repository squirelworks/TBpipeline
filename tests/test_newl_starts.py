"""tbpipeline_newl starts without --b.

--help exits 0. A missing --b is a usage sentence. Neither needs
unicorn, because neither starts the CPU.
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


class NewlStarts(unittest.TestCase):
    def test_imports(self):
        import tbpipeline_newl
        self.assertTrue(tbpipeline_newl.__doc__)

    def test_help_exits_0(self):
        done = run("tbpipeline_newl", "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("python3 -m tbpipeline_newl", done.stdout)
        self.assertIn("--list", done.stdout)

    def test_help_without_unicorn(self):
        done = run("tbpipeline_newl", "--help", unicorn=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_list_without_bin_is_a_sentence(self):
        done = run("tbpipeline_newl", "--list", unicorn=False)
        self.assertEqual(done.returncode, 2)
        self.assertIn("usage: python3 -m tbpipeline_newl", done.stderr)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
