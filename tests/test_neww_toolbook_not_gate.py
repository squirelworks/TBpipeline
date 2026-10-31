"""Item 65. A ToolBook-to-ToolBook fixup is never a gate. No binary needed."""

import tempfile
import unittest

from tests import neww_ne
from tests.test_neww_link import IMPORTS, MODULES, program, w16


class ToolBookIsNotAGate(unittest.TestCase):
    def test_linked_call_has_no_gate(self):
        from tbpipeline_neww.machine import Machine
        d = tempfile.mkdtemp()
        w16(d)
        program(d, by_name=False)
        host = Machine(d)
        self.assertNotIn("TB80W16", set(host.box.gates.values()))
        self.assertFalse(host.box.images["TB80W16"].synthetic)

    def test_missing_toolbook_dll_stops_by_name_without_wine(self):
        from tbpipeline_neww.machine import Machine
        d = tempfile.mkdtemp()
        code = bytearray()
        fixups = [(3, 1, 1, 2, 7)]
        code += neww_ne.call_far()
        fixups.append((3, 1, len(code) + 1, 1, 999))
        code += neww_ne.call_far()
        neww_ne.exit_program_with(d, bytes(code), fixups, modules=MODULES, imports=IMPORTS)
        host = Machine(d)
        self.assertNotIn("TB80W16", host.box.images)
        self.assertNotIn("TB80W16", set(host.box.gates.values()))
        host.run()
        self.assertEqual(host.stop, "not linked: TB80RTM -> TB80W16.7. A ToolBook call with no target is a stop, not a gate")
        self.assertEqual(host.box.wine.trace, [])
        self.assertEqual(host.calls, 0)

    def test_missing_export_stops_by_name(self):
        from tbpipeline_neww.machine import Machine
        d = tempfile.mkdtemp()
        w16(d)
        code = bytearray()
        fixups = [(3, 1, 1, 2, 9)]
        code += neww_ne.call_far()
        neww_ne.exit_program_with(d, bytes(code), fixups, modules=MODULES, imports=IMPORTS)
        host = Machine(d).run()
        self.assertTrue(host.stop.startswith("not linked: TB80RTM -> TB80W16.9"), host.stop)
        self.assertEqual(host.box.wine.trace, [])


if __name__ == "__main__":
    unittest.main()
