"""Item 69. neww does not draw the page. No binary needed."""

import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "tbpipeline_neww"


class NoRenderWriter(unittest.TestCase):
    def test_no_render_html_in_the_package(self):
        for path in PACKAGE.rglob("*.py"):
            text = path.read_text()
            self.assertNotIn("render.html", text, path.name)
            self.assertNotIn("runtime.debug", text, path.name)

    def test_a_run_writes_no_html(self):
        import tempfile
        from tests import neww_ne
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program(d)
            before = set(Path(d).rglob("*"))
            Machine(d).run()
            after = set(Path(d).rglob("*"))
        self.assertEqual([p for p in after - before if p.suffix.lower() in (".html", ".htm")], [])


if __name__ == "__main__":
    unittest.main()
