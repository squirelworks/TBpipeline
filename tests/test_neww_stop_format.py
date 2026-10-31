"""neww's stop for an ordinal with no contract.

A fake gate, not a DLL: a sandbox with one gate for KERNEL.999 and no
contract for it. The stop names the module, the ordinal, and says the
pop size was not guessed.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_SP, UC_X86_REG_SS

from tbpipeline_neww.machine import Machine
from tbpipeline_neww.wine import KERNEL, Wine

GATE_CS = 0x4F
ORDINAL = 999


class FakeUc:
    def __init__(self, regs):
        self.regs = dict(regs)
        self.stopped = False

    def reg_read(self, reg):
        return self.regs.get(reg, 0)

    def reg_write(self, reg, value):
        self.regs[reg] = value

    def emu_stop(self):
        self.stopped = True


class FakeBox:
    def __init__(self):
        self.gates = {(GATE_CS, ORDINAL): "KERNEL"}
        self.wine = Wine(None)
        self.selectors = {}


def fake_machine():
    host = Machine.__new__(Machine)
    host.box = FakeBox()
    host.stop = ""
    host.calls = 0
    host.uc = FakeUc({UC_X86_REG_CS: GATE_CS, UC_X86_REG_DX: ORDINAL, UC_X86_REG_SP: 0x1F0, UC_X86_REG_SS: 0x57})
    return host


class NewwStopFormat(unittest.TestCase):
    def test_ordinal_has_no_contract(self):
        self.assertNotIn(ORDINAL, KERNEL)

    def test_stop_names_module_ordinal_and_pop(self):
        host = fake_machine()
        host._out(host.uc, 0xE4, 1, 0, None)
        self.assertTrue(host.uc.stopped)
        self.assertIn("KERNEL", host.stop)
        self.assertIn(str(ORDINAL), host.stop)
        self.assertIn("pop size not guessed", host.stop)

    def test_wine_answer_says_the_same(self):
        ax, dx, stop = Wine(None).answer("USER", ORDINAL, lambda n: 0)
        self.assertEqual((ax, dx), (0, 0))
        self.assertIn(f"USER.{ORDINAL}", stop)
        self.assertIn("pop size not guessed", stop)


if __name__ == "__main__":
    unittest.main()
