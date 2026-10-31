"""MMSYSTEM, DDEML, OLE2DISP and VER are system modules, as Wine builds them.

Wine has a 16-bit spec file for each (dlls/mmsystem.dll16,
dlls/ddeml.dll16, dlls/ole2disp.dll16, dlls/ver.dll16). ToolBook DLLs
import them. neww named a call into one "not linked", as if it were a
ToolBook module that was missing. Now each is a gate, and an ordinal with
no contract stops as unimplemented. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne


class WineBuiltinModules(unittest.TestCase):
    def test_each_is_a_system_module(self):
        from tbpipeline_neww.wine import SYSTEM
        for name in ("MMSYSTEM", "DDEML", "OLE2DISP", "VER"):
            self.assertIn(name, SYSTEM)

    def test_call_with_no_contract_stops_as_unimplemented(self):
        from tbpipeline_neww.machine import Machine
        for name, ordinal in (("MMSYSTEM", 401), ("VER", 2)):
            with tempfile.TemporaryDirectory() as d:
                code = neww_ne.call_far()
                neww_ne.exit_program_with(d, code, [(3, 1, 1, 1, ordinal)], modules=(name, "KERNEL"))
                host = Machine(d).run(limit=5000)
            self.assertEqual(host.stop, f"unimplemented {name}.{ordinal}: no contract, pop size not guessed")


if __name__ == "__main__":
    unittest.main()
