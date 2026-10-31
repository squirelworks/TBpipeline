"""tbpipeline_bf starts without --b and without a book.

--help is the path that already exits. It exits 0 and prints the usage,
and it does not need unicorn, because asking for usage is not a run.
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Run a module with unicorn made unimportable, so a top-level import of it
# shows up as a traceback instead of passing on a machine that has it.
NO_UNICORN = (
    "import runpy, sys\n"
    "sys.modules['unicorn'] = None\n"
    "sys.argv = [sys.argv[1]] + sys.argv[2:]\n"
    "runpy.run_module(sys.argv[0], run_name='__main__', alter_sys=True)\n"
)


def run(*argv, unicorn=True):
    cmd = [sys.executable, "-m", *argv] if unicorn else [sys.executable, "-c", NO_UNICORN, *argv]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)


class BfStarts(unittest.TestCase):
    def test_imports(self):
        import tbpipeline_bf
        import tbpipeline_bf.runtime
        self.assertTrue(tbpipeline_bf.__doc__)

    def test_help_exits_0(self):
        done = run("tbpipeline_bf", "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("python3 -m tbpipeline_bf", done.stdout)
        self.assertNotIn("Traceback", done.stderr)

    def test_help_without_unicorn(self):
        done = run("tbpipeline_bf", "--help", unicorn=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_no_book_is_a_sentence(self):
        done = run("tbpipeline_bf", "--open", str(ROOT / "no-such-book.tbk"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("not a book", done.stderr)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
