"""Item 57. InitTask stops, by name, until neww can fill Wine's register contract.

No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne


class InitTaskStops(unittest.TestCase):
    def test_row_is_the_spec_register_entry(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[91]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("InitTask", (), 0, "register"))
        self.assertIn("-register InitTask()", row.spec[1])

    def test_guest_stops_on_inittask_and_keeps_its_registers(self):
        from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SP
        from tbpipeline_neww.machine import Machine
        before = neww_ne.mov_ax(0x5555) + neww_ne.call_far()
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 4, 1, 91)])
            host = Machine(d)
            sp0 = len(host.box.exe.segments[host.box.exe.auto - 1].data) - 2
            host.run()
            ax = host.uc.reg_read(UC_X86_REG_AX)
            sp = host.uc.reg_read(UC_X86_REG_SP)
        self.assertTrue(host.stop.startswith("KERNEL.91 InitTask"), host.stop)
        self.assertIn("ES:BX", host.stop)
        self.assertIn("nothing guessed", host.stop)
        self.assertEqual(host.box.wine.exit, None)
        self.assertEqual(ax, 0x5555)
        self.assertEqual(sp, sp0 - 4)


if __name__ == "__main__":
    unittest.main()
