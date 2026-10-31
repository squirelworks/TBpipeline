"""Item 53. A contract is a row, and the row sets the pop. No binary needed."""

import tempfile
import unittest

from tests import neww_ne


def push_word(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


class ContractRow(unittest.TestCase):
    def test_row_fields_and_pop(self):
        from tbpipeline_neww.wine import Contract
        row = Contract("KERNEL", 74, "OpenFile", (4, 4, 2), "word")
        self.assertEqual((row.module, row.ordinal, row.name, row.args, row.ret),
                         ("KERNEL", 74, "OpenFile", (4, 4, 2), "word"))
        self.assertEqual(row.pop, 10)

    def test_table_rows_are_contracts(self):
        from tbpipeline_neww.wine import KERNEL, USER, Contract, Wine
        for table in (KERNEL, USER):
            for ordinal, row in table.items():
                self.assertIsInstance(row, Contract)
                self.assertEqual(row.ordinal, ordinal)
        self.assertIs(Wine(".").contract("kernel", 17), KERNEL[17])

    def test_gate_retf_pops_the_row(self):
        from unicorn.x86_const import UC_X86_REG_SP
        from tbpipeline_neww.machine import Machine
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[17]
        before = push_word(1) + neww_ne.call_far()
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 4, 1, row.ordinal)])
            host = Machine(d)
            sp0 = len(host.box.exe.segments[host.box.exe.auto - 1].data) - 2
            stub = host.box.images["KERNEL"].segments[0].data[row.ordinal * 8:row.ordinal * 8 + 8]
            host.run()
            sp = host.uc.reg_read(UC_X86_REG_SP)
        self.assertEqual(bytes(stub[5:8]), bytes([0xCA, row.pop, 0]))
        # GlobalFree popped its word. The stop is the DOS exit, with only that far return on the stack.
        self.assertTrue(host.stop.startswith("dos exit"), host.stop)
        self.assertEqual(sp, sp0 - 4)


if __name__ == "__main__":
    unittest.main()
