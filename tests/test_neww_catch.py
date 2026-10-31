"""KERNEL.55 Catch is Wine thunk.c Catch16, a register contract.

Spec: `55 pascal -register Catch(ptr) Catch16`, pop 4. Catch16 writes
the caller's state into the 9-word CATCHBUF: IP, CS, the SP at the far
return (Esp in winebuild's register relay) less 4 words, BP, SI, DI, DS, 0, SS. AX is 0. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS, UC_X86_REG_SS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(seg=None):
    from tbpipeline_neww.machine import Machine
    # mov bp, 0x1111 ; mov si, 0x2222 ; mov di, 0x3333 ; mov ax, 0x5555 ; push seg|ds ; push 0x80 ;
    # call Catch ; here: mov [0x40], ax ; mov [0x42], sp
    code = bytearray(bytes([0xBD, 0x11, 0x11, 0xBE, 0x22, 0x22, 0xBF, 0x33, 0x33]) + neww_ne.mov_ax(0x5555))
    code += push(seg) if seg is not None else bytes([0x1E])
    code += push(0x80)
    at = len(code) + 1
    code += neww_ne.call_far()
    here = len(code)
    code += bytes([0xA3, 0x40, 0x00, 0x89, 0x26, 0x42, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), [(3, 1, at, 1, 55)])
        host = Machine(d).run(limit=5000)
    return host, here


class Catch(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[55]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("Catch", (4,), 4, "register"))

    def test_catchbuf(self):
        host, here = run()
        self.assertEqual(host.stop, "dos exit 0x0")
        uc = host.uc
        ds, ss = uc.reg_read(UC_X86_REG_DS), uc.reg_read(UC_X86_REG_SS)
        cs = host.box.exe.segments[0].selector
        buf = tuple(host.word(ds, 0x80 + 2 * i) for i in range(9))
        sp_after = host.word(ds, 0x42)
        self.assertEqual(host.word(ds, 0x40), 0)
        # Esp is the SP at the far return, 8 below SP after the retf 4. Catch saves it 4 words lower.
        self.assertEqual(buf, (here, cs, sp_after - 8 - 8, 0x1111, 0x2222, 0x3333, ds, 0, ss))

    def test_buffer_outside_any_block_stops(self):
        host, _here = run(seg=0x7770)
        self.assertEqual(host.stop, "KERNEL.55 Catch(0x7770:0x80): the CATCHBUF is not in a block neww has")


if __name__ == "__main__":
    unittest.main()
