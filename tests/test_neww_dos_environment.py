"""KERNEL.131 GetDOSEnvironment and PSP:0x2C are Wine's environment block.

Wine task.c GetDOSEnvironment16 copies the host's environment strings,
then a 0, WORD 1, and "C:\\WINDOWS\\SYSTEM\\KRNL386.EXE", into a fixed
block, and returns it as a SEGPTR. TASK_Create puts its selector in the
PSP at 0x2C. neww copies no host environment, so the list is empty: the
block starts with the 0 that ends it. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS, UC_X86_REG_ES

# call GetDOSEnvironment ; mov [0x40], ax ; mov [0x42], dx
AFTER = bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00])


class DosEnvironment(unittest.TestCase):
    def run_program(self):
        from tbpipeline_neww.machine import Machine
        before = neww_ne.call_far() + AFTER
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 1, 1, 131)])
            return Machine(d).run(limit=5000)

    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[131]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetDOSEnvironment", (), 0, "long"))

    def test_segptr_is_the_block_and_the_psp_names_it(self):
        host = self.run_program()
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        es = host.uc.reg_read(UC_X86_REG_ES)
        offset, sel = host.word(ds, 0x40), host.word(ds, 0x42)
        self.assertEqual(offset, 0)
        self.assertNotEqual(sel, 0)
        self.assertEqual(host.word(es, 0x2C), sel)
        block = bytes(host.word(sel, i) & 0xFF for i in range(33))
        self.assertEqual(block, b"\x00\x01\x00C:\\WINDOWS\\SYSTEM\\KRNL386.EXE\x00")


if __name__ == "__main__":
    unittest.main()
