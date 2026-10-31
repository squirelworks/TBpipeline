"""KERNEL.56 Throw is Wine thunk.c Throw16, back to the Catch.

Spec: `56 pascal -register Throw(ptr word) Throw16`, pop 6. AX is the
return value. CS:IP, BP, SI, DI and DS come from the CATCHBUF. Esp, the
SP at the far return, is lpbuf[2] + 4 words - 1 word, so after Throw's
retf 6 the SP is what it was after Catch's retf 4. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def program(throw_ss=None):
    # mov bp, 0x1111 ; push ds ; push 0x80 ; call Catch
    code = bytearray([0xBD, 0x11, 0x11, 0x1E]) + push(0x80)
    fixups = [(3, 1, len(code) + 1, 1, 55)]
    code += neww_ne.call_far()
    # here: mov [0x40], ax ; mov [0x42], sp ; mov [0x44], bp ; test ax, ax ; jnz done
    code += bytes([0xA3, 0x40, 0x00, 0x89, 0x26, 0x42, 0x00, 0x89, 0x2E, 0x44, 0x00, 0x85, 0xC0, 0x75, 0x00])
    jnz = len(code) - 1
    # first pass: mov [0x46], sp ; mov bp, 0x9999 ; (break the saved SS) ; push ds ; push 0x80 ; push 7 ; call Throw ; hlt
    code += bytes([0x89, 0x26, 0x46, 0x00, 0xBD, 0x99, 0x99])
    if throw_ss is not None:
        code += bytes([0xC7, 0x06, 0x90, 0x00, throw_ss & 0xFF, throw_ss >> 8])  # mov word [0x80 + 16], ss
    code += bytes([0x1E]) + push(0x80) + push(7)
    fixups.append((3, 1, len(code) + 1, 1, 56))
    code += neww_ne.call_far() + bytes([0xF4])
    code[jnz] = len(code) - (jnz + 1)
    return bytes(code), fixups


def run(throw_ss=None):
    from tbpipeline_neww.machine import Machine
    code, fixups = program(throw_ss)
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, code, fixups)
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, [host.word(ds, o) for o in (0x40, 0x42, 0x44, 0x46)]


class Throw(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[56]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("Throw", (4, 2), 6, "register"))

    def test_lands_after_the_catch(self):
        host, (ax, sp, bp, sp_first) = run()
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(ax, 7)
        self.assertEqual(sp, sp_first)
        self.assertEqual(bp, 0x1111)

    def test_other_stack_segment_stops(self):
        host, _ = run(throw_ss=0x7770)
        self.assertTrue(host.stop.startswith("KERNEL.56 Throw: the CATCHBUF's SS 0x7770"), host.stop)


if __name__ == "__main__":
    unittest.main()
