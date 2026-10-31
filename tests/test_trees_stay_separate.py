"""The three trees do not import each other.

newl and neww do not import tbpipeline_bf. bf does not import newl or
neww. newl and neww do not import each other either: a shared Windows
table is how a lie in one tree looks like a fix in another.

The check reads every .py file with ast. It sees import statements and
importlib.import_module / __import__ calls with a literal name.
"""

import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREES = ("tbpipeline_bf", "tbpipeline_newl", "tbpipeline_neww")


def imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                names.add(node.args[0].value)
    return names


def crossings(root: Path, tree: str) -> list[str]:
    others = [t for t in TREES if t != tree]
    out = []
    for path in sorted((root / tree).rglob("*.py")):
        for name in sorted(imported(path)):
            top = name.split(".")[0]
            if top in others:
                out.append(f"{path.relative_to(root)} imports {name}")
    return out


class TreesStaySeparate(unittest.TestCase):
    def test_bf_imports_neither_host_tree(self):
        self.assertEqual(crossings(ROOT, "tbpipeline_bf"), [])

    def test_newl_does_not_import_another_tree(self):
        self.assertEqual(crossings(ROOT, "tbpipeline_newl"), [])

    def test_neww_does_not_import_another_tree(self):
        self.assertEqual(crossings(ROOT, "tbpipeline_neww"), [])

    def test_check_sees_a_crossing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "tbpipeline_neww"
            pkg.mkdir()
            (pkg / "a.py").write_text("from tbpipeline_bf.nedllhost import pass06\n")
            (pkg / "b.py").write_text("import importlib\nimportlib.import_module('tbpipeline_newl.layer')\n")
            (pkg / "c.py").write_text("from . import machine\nimport unicorn\n")
            self.assertEqual(crossings(Path(tmp), "tbpipeline_neww"), [
                "tbpipeline_neww/a.py imports tbpipeline_bf.nedllhost",
                "tbpipeline_neww/b.py imports tbpipeline_newl.layer",
            ])


if __name__ == "__main__":
    unittest.main()
