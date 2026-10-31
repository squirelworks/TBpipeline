"""newl's stop for an ordinal the layer does not know.

A fake gate, not a DLL: a Cpu whose only gate is KERNEL.999. The layer
raises Gap, the run stops, and the stop names the module and the
ordinal. No value is returned for it.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_SP, UC_X86_REG_SS

from tbpipeline_newl.cpu import Cpu
from tbpipeline_newl.layer import Gap, Layer

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


def fake_cpu(module):
    host = Cpu.__new__(Cpu)
    host.gates = {(GATE_CS, ORDINAL): module}
    host.layer = Layer()
    host.selectors = {}
    host.stop = ""
    host.uc = FakeUc({UC_X86_REG_CS: GATE_CS, UC_X86_REG_DX: ORDINAL, UC_X86_REG_AX: 0x1234,
                      UC_X86_REG_SP: 0x1F0, UC_X86_REG_SS: 0x57})
    host._word = lambda sel, off: 0
    return host


class NewlStopFormat(unittest.TestCase):
    def test_layer_raises_gap(self):
        for module in ("KERNEL", "USER"):
            with self.assertRaises(Gap) as hit:
                Layer().call(module, ORDINAL)
            self.assertEqual((hit.exception.module, hit.exception.ordinal), (module, ORDINAL))
            self.assertIn(f"{module}.{ORDINAL}", str(hit.exception))

    def test_gate_stops_and_names_it(self):
        for module in ("KERNEL", "USER"):
            host = fake_cpu(module)
            host._out(host.uc, 0xE4, 1, 0, None)
            self.assertTrue(host.uc.stopped)
            self.assertIn(f"{module}.{ORDINAL}", host.stop)
            self.assertEqual(host.uc.regs[UC_X86_REG_AX], 0x1234, "no AX for an unknown ordinal")


if __name__ == "__main__":
    unittest.main()
