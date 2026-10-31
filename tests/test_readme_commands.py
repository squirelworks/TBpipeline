"""Every python3 line in a ```sh block of the root README runs.

Lines that name ~/TBK/bin need the ToolBook directory. They read it
from TBK_BIN through bin_or_skip() and skip without it. fixture.tbk is
written by the line that builds it, into a temp directory.
"""

import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.binpath import bin_or_skip

ROOT = Path(__file__).resolve().parent.parent
BIN = "~/TBK/bin"


def commands():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    out = []
    for block in re.findall(r"```sh\n(.*?)```", text, re.S):
        out.extend(line.strip() for line in block.splitlines() if line.strip().startswith("python3 "))
    return out


def run(line, tmp, root=None):
    argv = shlex.split(line)
    argv[0] = sys.executable
    argv = [str(Path(tmp) / a) if a == "fixture.tbk" else a for a in argv]
    if root is not None:
        argv = [str(root) if a == BIN else a for a in argv]
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)


class ReadmeCommands(unittest.TestCase):
    def test_readme_names_the_three_modules(self):
        lines = commands()
        for module in ("tbpipeline_bf", "tbpipeline_newl", "tbpipeline_neww"):
            self.assertTrue(any(f"-m {module} " in line for line in lines), module)

    def test_lines_without_a_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            for line in commands():
                if BIN in line:
                    continue
                with self.subTest(line=line):
                    done = run(line, tmp)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertNotIn("Traceback", done.stderr)

    def test_lines_with_a_binary(self):
        root = bin_or_skip()
        with tempfile.TemporaryDirectory() as tmp:
            for line in commands():
                if BIN not in line:
                    continue
                with self.subTest(line=line):
                    done = run(line, tmp, root)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
