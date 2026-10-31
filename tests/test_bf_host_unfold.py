"""Item 37: unfold.py stays the unpacker. It does not become the book runtime.

It has no KERNEL OpenFile or _lopen: those ordinals are not in its table
and it has no handler for them, so an OpenFile there is the zero default.
"""

import unittest
from pathlib import Path

from tbpipeline_bf.nehost import unfold

OPENFILE, LOPEN = 74, 85


class UnfoldIsTheUnpacker(unittest.TestCase):
    def test_no_openfile_in_the_kernel_table(self):
        self.assertNotIn(OPENFILE, unfold.KERNEL_ORDINALS)
        self.assertNotIn(LOPEN, unfold.KERNEL_ORDINALS)
        names = {name.lower() for name in unfold.KERNEL_ORDINALS.values()}
        self.assertFalse(names & {"openfile", "_lopen", "lopen"})

    def test_no_handler_for_openfile(self):
        handlers = [name for name in dir(unfold) for obj in [getattr(unfold, name)]
                    if isinstance(obj, type) for name in dir(obj)]
        for name in handlers:
            self.assertNotIn("openfile", name.lower())
            self.assertNotIn("lopen", name.lower())

    def test_source_does_not_call_openfile(self):
        text = Path(unfold.__file__).read_text(encoding="utf-8")
        self.assertNotIn("OpenFile", text)
        self.assertNotIn("_take_file", text)


if __name__ == "__main__":
    unittest.main()
