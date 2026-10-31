"""Item 70. Each newl/neww return-value disagreement has a sentence in layers.md.

Reads documentation only. Imports neither tree.
"""

import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "documentation" / "layers.md"

# ordinal -> name, for every ordinal the two trees answer differently today.
DISAGREE = {
    "KERNEL.91": "InitTask",
    "KERNEL.74": "OpenFile",
    "KERNEL.85": "_lopen",
    "KERNEL.15": "GlobalAlloc",
    "KERNEL.18": "GlobalLock",
    "KERNEL.20": "GlobalSize",
    "KERNEL.30": "WaitEvent",
    "KERNEL.102": "DOS3Call",
}


class LayersNamesDisagreements(unittest.TestCase):
    def test_each_disagreement_has_a_sentence(self):
        text = DOC.read_text()
        section = text.split("## Where newl and neww disagree", 1)[1]
        lines = [line for line in section.splitlines() if line.startswith("- ")]
        for ordinal, name in DISAGREE.items():
            hits = [line for line in lines if f"`{ordinal}` `{name}`" in line]
            self.assertTrue(hits, f"{ordinal} {name} is not named in layers.md")
            self.assertIn("`newl`", hits[0])
            self.assertIn("`neww`", hits[0])

    def test_readme_lists_the_file(self):
        readme = (DOC.parent / "README.md").read_text()
        self.assertIn("[layers.md](layers.md)", readme)


if __name__ == "__main__":
    unittest.main()
