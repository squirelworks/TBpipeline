"""Item 68. A stop inside TB80BAS names the segment and export, and nothing is reimplemented.

Original fixtures. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne

MODULES = ("KERNEL", "TB80BAS")


def run():
    from tbpipeline_neww.machine import Machine
    d = tempfile.mkdtemp()
    # Segment 2 holds two exports. The second runs two nops and then an invalid opcode.
    seg2 = bytes([0xCB, 0xCB, 0xCB, 0xCB, 0x90, 0x90, 0x0F, 0x0B])
    blob = neww_ne.build(
        "TB80BAS", [(0x0000, b"\xCB", []), (0x0000, seg2, [])],
        entries=[(1, 1, 0, "BASFIRST"), (2, 2, 0, "BASSTART"), (3, 2, 4, "BASFAULT")], exe=False,
    )
    neww_ne.write(d, "TB80BAS.DLL", blob)
    fixups = [(3, 1, 1, 2, 3)]
    neww_ne.exit_program_with(d, neww_ne.call_far(), fixups, modules=MODULES)
    return Machine(d).run()


class BasFaultIsMapped(unittest.TestCase):
    def test_stop_names_segment_and_export(self):
        host = run()
        self.assertIn("in TB80BAS segment 2 +0x6, BASFAULT+0x2 (ordinal 3)", host.stop)
        self.assertEqual(host.box.wine.trace, [])

    def test_where_outside_any_export(self):
        host = run()
        sel = host.box.images["TB80BAS"].segments[1].selector
        self.assertEqual(host.where(sel, 2), f"at {sel:#x}:0x2 in TB80BAS segment 2 +0x2, BASSTART+0x2 (ordinal 2)")


if __name__ == "__main__":
    unittest.main()
