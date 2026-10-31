"""Item 52. A gate with no contract stops before any pop. No binary needed."""

import tempfile
import unittest

from tests import neww_ne

UNKNOWN = 999


class UnknownGateDoesNotPop(unittest.TestCase):
    def run_box(self, directory):
        from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SP
        from tbpipeline_neww.machine import Machine
        before = neww_ne.mov_ax(0x1234) + neww_ne.call_far()
        fixups = [(3, 1, 4, 1, UNKNOWN)]
        neww_ne.exit_program_with(directory, before, fixups)
        host = Machine(directory)
        sp0 = host.box.exe.segments[host.box.exe.auto - 1].minsize + host.box.exe.stack
        host.run()
        return host, sp0, host.uc.reg_read(UC_X86_REG_SP), host.uc.reg_read(UC_X86_REG_AX)

    def test_stop_names_ordinal_and_sp_holds_the_return(self):
        with tempfile.TemporaryDirectory() as d:
            host, sp0, sp, ax = self.run_box(d)
        self.assertIn(f"KERNEL.{UNKNOWN}", host.stop)
        # The far call pushed CS:IP. Nothing else moved SP.
        self.assertEqual(sp, sp0 - 4)
        self.assertEqual(ax, 0x1234)
        self.assertEqual(host.calls, 1)

    def test_stub_has_no_retf(self):
        with tempfile.TemporaryDirectory() as d:
            host, *_ = self.run_box(d)
        stub = host.box.images["KERNEL"].segments[0].data[UNKNOWN * 8:UNKNOWN * 8 + 8]
        self.assertEqual(stub[0], 0xBA)
        self.assertNotEqual(stub[5], 0xCA)


if __name__ == "__main__":
    unittest.main()
