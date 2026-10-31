"""Item 56. GetWinFlags is a contract row that answers 0x0C25. No binary needed."""

import tempfile
import unittest

from tests import neww_ne


class GetWinFlagsContract(unittest.TestCase):
    def test_row_holds_the_answer(self):
        from tbpipeline_neww.wine import EQUATES, KERNEL, KERNEL_SPEC
        row = KERNEL[132]
        self.assertEqual((row.name, row.pop, row.ret, row.value), ("GetWinFlags", 0, "long", (0x0C25, 0)))
        self.assertEqual(row.spec[0], KERNEL_SPEC)
        self.assertEqual(row.value[0], EQUATES["KERNEL"][178][1])

    def test_answer_is_the_row(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine(".").answer("KERNEL", 132, None), (0x0C25, 0, None))

    def test_guest_reads_0c25(self):
        from unicorn.x86_const import UC_X86_REG_AX
        from tbpipeline_neww.machine import Machine
        before = neww_ne.call_far() + neww_ne.call_far()
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 1, 1, 132), (3, 1, 6, 1, 999)])
            host = Machine(d)
            host.run()
            ax = host.uc.reg_read(UC_X86_REG_AX)
        self.assertEqual(host.box.wine.trace[0], "KERNEL.132 GetWinFlags")
        self.assertIn("KERNEL.999", host.stop)
        self.assertEqual(ax, 0x0C25)


if __name__ == "__main__":
    unittest.main()
