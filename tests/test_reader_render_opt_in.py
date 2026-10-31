"""render.html is still opt-in.

Runs the reader launchers without --dbgrender on a book built here and
checks no new render.html appeared. --open and the runtime debug route
need no binary. They import the package's launcher, which needs unicorn
from requirements.txt; the CPU is not started.
"""

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

ROOT = Path(__file__).resolve().parent.parent
DEBUG = ROOT / "tbpipeline_bf" / "_debug"


def one_page_book() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + MARK + b"\x00" * 4 + b"P1\x00"


def debug_runs() -> set[Path]:
    return set(DEBUG.glob("db-*")) if DEBUG.is_dir() else set()


def renders() -> set[Path]:
    return set(DEBUG.rglob("render.html")) if DEBUG.is_dir() else set()


class RenderOptIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "one.tbk"
        self.book.write_bytes(one_page_book())
        self.runs = debug_runs()

    def tearDown(self):
        for path in debug_runs() - self.runs:
            shutil.rmtree(path)
        self.tmp.cleanup()

    def launch(self, *argv):
        before = renders()
        done = subprocess.run(
            [sys.executable, "-m", *argv], cwd=ROOT, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(renders() - before, set())
        return done

    def test_stage_2_without_dbgrender(self):
        out = Path(self.tmp.name) / "db"
        lines, prompt = run(str(self.book), out, dbgrender=False)
        self.assertEqual(lines, ["stage 2a not reached (pass --dbgrender)"])
        self.assertEqual(prompt, "")
        self.assertFalse((out / "render.html").exists())

    def test_open_writes_no_render(self):
        done = self.launch("tbpipeline_bf", "--open", str(self.book))
        self.assertIn("opened one.tbk", done.stdout)

    def test_runtime_route_without_dbgrender_writes_no_render(self):
        done = self.launch("tbpipeline_bf.runtime", "--c", str(self.book))
        self.assertIn("stage 2a not reached (pass --dbgrender)", done.stdout)


if __name__ == "__main__":
    unittest.main()
