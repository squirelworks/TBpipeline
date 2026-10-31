"""A register contract's gate keeps the guest's DX unless the contract sets it.

Ordinary stubs load the ordinal into DX before OUT 0E4h, which is fine
for a Pascal call that returns in DX:AX. A register contract (spec
-register) reads and sets registers, so its stub is OUT 0E7h first, and
the gate finds the ordinal from the stub's offset. DOS3Call used to come
back with DX = 0. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


class RegisterGateKeepsDx(unittest.TestCase):
    def test_dos3call_leaves_dx(self):
        from tbpipeline_neww.machine import Machine
        # mov dx, 0x1234 ; mov ax, 0x3000 ; call DOS3Call ; mov [0x40], dx
        before = bytes([0xBA, 0x34, 0x12]) + neww_ne.mov_ax(0x3000) + neww_ne.call_far()
        before += bytes([0x89, 0x16, 0x40, 0x00])
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, before, [(3, 1, 7, 1, 102)])
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.word(ds, 0x40), 0x1234)

    def test_register_stub_does_not_load_dx(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, b"", [])
            host = Machine(d)
        gate = host.box.images["KERNEL"].segments[0].data
        self.assertEqual(bytes(gate[102 * 8:102 * 8 + 2]), b"\xE6\xE7")
        # A Pascal-return contract still loads DX: GetVersion.
        self.assertEqual(bytes(gate[3 * 8:3 * 8 + 5]), bytes([0xBA, 3, 0, 0xE6, 0xE4]))


if __name__ == "__main__":
    unittest.main()
