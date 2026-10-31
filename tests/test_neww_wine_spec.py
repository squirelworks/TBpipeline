"""Item 54. Rows come from Wine Win16 spec lines. No binary needed.

Set WINE_SRC to a Wine checkout to also compare every row with the
spec file it cites.
"""

import os
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne


class RowsFromSpec(unittest.TestCase):
    def test_every_row_cites_file_and_ordinal(self):
        from tbpipeline_neww.wine import KERNEL, KERNEL_SPEC, USER, USER_SPEC
        for table, path in ((KERNEL, KERNEL_SPEC), (USER, USER_SPEC)):
            for ordinal, row in table.items():
                self.assertEqual(row.spec[0], path)
                self.assertEqual(int(row.spec[1].split()[0]), ordinal)
                self.assertIn(f" {row.name}(", row.spec[1])

    def test_sizes_come_from_the_argument_types(self):
        from tbpipeline_neww.wine import Contract
        row = Contract.from_spec("USER", "user.exe16.spec", "176 pascal -ret16 LoadString(word word ptr s_word) LoadString16")
        self.assertEqual((row.ordinal, row.name, row.args, row.pop, row.ret), (176, "LoadString", (2, 2, 4, 2), 10, "word"))
        row = Contract.from_spec("KERNEL", "k.spec", "91  pascal -register InitTask() InitTask16")
        self.assertEqual((row.pop, row.ret), (0, "register"))
        row = Contract.from_spec("KERNEL", "k.spec", "18  pascal GlobalLock(word) WIN16_GlobalLock16")
        self.assertEqual(row.ret, "long")

    def test_unknown_type_is_refused(self):
        from tbpipeline_neww.wine import Contract
        with self.assertRaises(KeyError):
            Contract.from_spec("KERNEL", "k.spec", "999 pascal Odd(double) Odd16")

    def test_against_wine_checkout(self):
        root = os.environ.get("WINE_SRC")
        if not root:
            raise unittest.SkipTest("WINE_SRC is not set, so the rows are not compared with a Wine checkout")
        from tbpipeline_neww.wine import KERNEL, USER
        for table in (KERNEL, USER):
            for row in table.values():
                lines = Path(root, row.spec[0]).read_text().splitlines()
                self.assertIn(row.spec[1], lines, f"{row.spec[0]}:{row.ordinal}")


class SpecAndBinaryDisagree(unittest.TestCase):
    def test_stop_records_both_sizes(self):
        from unicorn.x86_const import UC_X86_REG_SP
        from tbpipeline_neww import wine
        from tbpipeline_neww.machine import Machine
        real = wine.KERNEL[17]
        odd = wine.Contract.from_spec("KERNEL", real.spec[0], real.spec[1], binary=4)
        wine.KERNEL[17] = odd
        try:
            before = bytes([0x68, 1, 0]) + neww_ne.call_far()
            with tempfile.TemporaryDirectory() as d:
                neww_ne.exit_program_with(d, before, [(3, 1, 4, 1, 17)])
                host = Machine(d)
                sp0 = len(host.box.exe.segments[host.box.exe.auto - 1].data) - 2
                stub = host.box.images["KERNEL"].segments[0].data[17 * 8:17 * 8 + 8]
                host.run()
                sp = host.uc.reg_read(UC_X86_REG_SP)
        finally:
            wine.KERNEL[17] = real
        self.assertIn("dlls/krnl386.exe16/krnl386.exe16.spec:17 pops 2, binary pops 4", host.stop)
        self.assertNotEqual(stub[5], 0xCA)
        self.assertEqual(sp, sp0 - 2 - 4)


if __name__ == "__main__":
    unittest.main()
