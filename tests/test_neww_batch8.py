"""Batch 8: what the Logic Families book needed. Handlers run on fake memory
(tests/test_neww_batch2.py's harness). No ToolBook bytes."""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine


class LoadMenuIndirect(unittest.TestCase):
    """user.c LoadMenuIndirect16: MENUITEMTEMPLATEHEADER, then parse_menu_resource."""

    def setUp(self):
        self.w = window_wine()

    def put(self, raw):
        self.w.memory.write(DATA, 0x100, raw)
        return (DATA, 0x100)

    def test_popup_with_one_item(self):
        # version 0, offset 0; "&File" popup (MF_POPUP | MF_END) holding "E&xit" id 1 (MF_END).
        raw = struct.pack("<HH", 0, 0) + struct.pack("<H", 0x0090) + b"&File\0" \
            + struct.pack("<HH", 0x0080, 1) + b"E&xit\0"
        hmenu, _dx, stop, _ = by_name(self.w, "USER", "LoadMenuIndirect", self.put(raw))
        self.assertIsNone(stop)
        self.assertNotEqual(hmenu, 0)
        self.assertEqual(by_name(self.w, "USER", "GetMenuItemCount", hmenu)[0], 1)
        sub = by_name(self.w, "USER", "GetSubMenu", hmenu, 0)[0]
        self.assertEqual(by_name(self.w, "USER", "GetMenuItemID", sub, 0)[0], 1)

    def test_version_not_zero_is_zero(self):
        raw = struct.pack("<HH", 1, 0) + b"\0" * 8
        self.assertEqual(by_name(self.w, "USER", "LoadMenuIndirect", self.put(raw))[:3], (0, 0, None))


if __name__ == "__main__":
    unittest.main()
