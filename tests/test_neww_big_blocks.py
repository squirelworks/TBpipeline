"""GlobalAlloc over 1M (#227): the Instructor Walkthrough sample allocates 0x12A000 bytes.
Wine 2528aff2 dlls/krnl386.exe16/global.c:209-211 rounds such a block to a page, and
selector.c:66 ldt_set_limit makes the limit page-granular."""

import tempfile
import unittest

from tests import neww_ne
from tests.test_neww_batch1_handlers import wine


class Sizes(unittest.TestCase):
    def setUp(self):
        self.w = wine()
        self.asked = []
        self.w.allocate = lambda size: self.asked.append(size) or 0x200

    def test_over_1m_rounds_to_a_page(self):
        handle, _dx, stop = self.w._global_alloc(0, 0x12A001)
        self.assertEqual((handle, stop, self.asked), (0x200, None, [0x12B000]))

    def test_under_1m_rounds_to_32(self):
        self.w._global_alloc(0, 0x1001)
        self.assertEqual(self.asked, [0x1020])

    def test_16m_less_64k_fails(self):
        # GLOBAL_MAX_ALLOC_SIZE (global.c:59): GlobalAlloc16 returns 0.
        self.assertEqual(self.w._global_alloc(0, 0xFF0000), (0, 0, None))
        self.assertEqual(self.asked, [])


class Descriptors(unittest.TestCase):
    def test_the_first_selector_is_page_granular_and_the_last_is_not(self):
        from tbpipeline_neww.machine import Machine, SelectorHooks
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, b"", [])
            m = Machine(d).run()
            sel = m._allocate(0x12A000)
            hooks = SelectorHooks(m)
            self.assertEqual(hooks.info(sel)[1], 0x129FFF)
            last = sel + 8 * 0x12
            self.assertEqual(hooks.info(last)[1], 0x12A000 - 0x120000 - 1)


if __name__ == "__main__":
    unittest.main()
