"""Item 55. GetVersion is a contract row that answers 0x0A03. No binary needed."""

import tempfile
import unittest

from tests import neww_ne


class GetVersionContract(unittest.TestCase):
    def test_row_holds_the_answer(self):
        from tbpipeline_neww.wine import KERNEL, KERNEL_SPEC
        row = KERNEL[3]
        self.assertEqual((row.name, row.pop, row.ret, row.value), ("GetVersion", 0, "long", (0x0A03, 0x0616)))
        self.assertEqual(row.spec[0], KERNEL_SPEC)

    def test_guest_reads_0a03(self):
        from unicorn.x86_const import UC_X86_REG_AX
        from tbpipeline_neww.machine import Machine
        # GetVersion, then an ordinal with no contract, which stops without touching AX or DX.
        before = neww_ne.call_far() + neww_ne.call_far()
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 1, 1, 3), (3, 1, 6, 1, 999)])
            host = Machine(d)
            host.run()
            ax = host.uc.reg_read(UC_X86_REG_AX)
        self.assertEqual(host.box.wine.trace[0], "KERNEL.3 GetVersion")
        self.assertIn("KERNEL.999", host.stop)
        # DX is the next stub's ordinal by now, so only AX is read from the guest.
        self.assertEqual(ax, 0x0A03)

    def test_answer_is_the_row(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine(".").answer("KERNEL", 3, None), (0x0A03, 0x0616, None))


if __name__ == "__main__":
    unittest.main()
