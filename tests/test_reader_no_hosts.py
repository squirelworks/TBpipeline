"""The reader does not call pass06, newl, or neww.

Reads every import in tbpipeline_bf/runtime with ast, then runs the
runtime route with unicorn made unimportable. No binary, no CPU.
"""

import ast
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "tbpipeline_bf" / "runtime"
DEBUG = ROOT / "tbpipeline_bf" / "_debug"
HOSTS = (
    "unicorn",
    "tbpipeline_newl",
    "tbpipeline_neww",
    "tbpipeline_bf.run",
    "tbpipeline_bf.nehost",
    "tbpipeline_bf.nedllhost",
)
NO_UNICORN = (
    "import runpy, sys\n"
    "sys.modules['unicorn'] = None\n"
    "sys.argv = [sys.argv[1]] + sys.argv[2:]\n"
    "runpy.run_module(sys.argv[0], run_name='__main__', alter_sys=True)\n"
)


def absolute(path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    if node.level > 1:
        package = package[:-(node.level - 1)]
    return ".".join(package + ([node.module] if node.module else []))


def imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = absolute(path, node)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def is_host(name: str) -> bool:
    return any(name == host or name.startswith(host + ".") for host in HOSTS)


class ReaderCallsNoHost(unittest.TestCase):
    def test_runtime_imports_no_host(self):
        found = {
            str(path.relative_to(ROOT)): sorted(n for n in imports(path) if is_host(n))
            for path in RUNTIME.rglob("*.py")
        }
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_runtime_route_runs_without_unicorn(self):
        before = set(DEBUG.glob("db-*")) if DEBUG.is_dir() else set()
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "one.tbk"
            book.write_bytes(
                bytes(STUB) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + MARK + b"\x00" * 4 + b"P1\x00"
            )
            try:
                done = subprocess.run(
                    [sys.executable, "-c", NO_UNICORN, "tbpipeline_bf.runtime", "--dbgrender", "--c", str(book)],
                    cwd=ROOT, capture_output=True, text=True, timeout=60,
                )
            finally:
                for path in (set(DEBUG.glob("db-*")) if DEBUG.is_dir() else set()) - before:
                    shutil.rmtree(path)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("stage 2b render", done.stdout)


if __name__ == "__main__":
    unittest.main()
