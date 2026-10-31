"""KERNEL.517 CallProc32W runs a 32-bit procedure and returns its EAX.

Wine's spec line (dlls/krnl386.exe16/krnl386.exe16.spec:425, Wine commit
2528aff2) is `517 varargs CallProc32W(long long long) CallProc32W16`.
CallProc32W16 (dlls/krnl386.exe16/thunk.c:2574) takes nParams,
fAddressConvert and lpProc32, then the parameters, which the caller
pushed p1 first. It reads them from pn upwards, maps the i-th one with
MapSL when bit i of fAddressConvert is set, and puts them back in p1..pn
order. It pops (3 + nParams) * 4 bytes for the caller. WOW_CallProc32W16
returns 0 for a NULL lpProc32, or calls it and returns EAX in DX:AX.

The DLL is loaded with LoadLibraryEx32W (#144) and is a tiny original PE
built by tests/pe32.py.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from tbpipeline_bf.nehost.win16stack import POP
from tests.bf_host_fake import STACK_TOP
from tests.pe32 import BASE, build, write
from tests.test_bf_host_loadlibraryex32w import ATTACH, GUEST, OUT, host, run

CALLPROC32W = 517
TEXT = 0x300
# stdcall Sub(a, b): a - b. The order shows p1 comes first.
SUB = [bytes([0x8B, 0x44, 0x24, 0x04, 0x2B, 0x44, 0x24, 0x08, 0xC2, 0x08, 0x00])]
# stdcall Peek(p): the byte at linear address p.
PEEK = [bytes([0x8B, 0x44, 0x24, 0x04, 0x0F, 0xB6, 0x00, 0xC2, 0x04, 0x00])]
# stdcall AddPeek(n, p): n + the byte at p.
ADDPEEK = [bytes([0x8B, 0x44, 0x24, 0x08, 0x0F, 0xB6, 0x00, 0x03, 0x44, 0x24, 0x04, 0xC2, 0x08, 0x00])]


def call(h, proc, params, convert=0):
    """push p1..pn, proc, convert, n; CallProc32W; then DX:AX and SP to OUT. No add sp."""
    code = b""
    for value in [*params, proc, convert, len(params)]:
        code += bytes([0x68]) + struct.pack("<H", value >> 16) + bytes([0x68]) + struct.pack("<H", value & 0xFFFF)
    gate_off = CALLPROC32W * 8 - 0x1000
    h.arena.write(h.gate, 0x1000 + gate_off, bytes([0xBA, CALLPROC32W & 0xFF, CALLPROC32W >> 8, 0xE6, 0xE0, 0xCA, 0, 0]))
    code += bytes([0x9A]) + struct.pack("<HH", CALLPROC32W * 8, h.gate)
    h.sites[(h.flat, GUEST + len(code))] = ("KERNEL", CALLPROC32W, POP["KERNEL"][CALLPROC32W])
    h.callers[(h.flat, GUEST + len(code))] = ("KERNEL", CALLPROC32W)
    code += bytes([0xA3, OUT & 0xFF, OUT >> 8, 0x89, 0x16, (OUT + 2) & 0xFF, (OUT + 2) >> 8])
    code += bytes([0x89, 0x26, (OUT + 4) & 0xFF, (OUT + 4) >> 8, 0xF4])
    return run(h, code)


class CallProc32W(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()
        write(self.dir.name, "TESTW32.DLL", build([(None, ATTACH), ("Sub", SUB), ("Peek", PEEK), ("AddPeek", ADDPEEK)]))
        self.h = host()
        hinst, _ = run(self.h)
        self.assertEqual(hinst, BASE)

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_runs_the_procedure_in_pascal_order_and_pops(self):
        result, sp = call(self.h, BASE + 0x1010, [9, 4])
        self.assertEqual(self.h.ax1, [], "CallProc32W fell through to AX = 1")
        self.assertEqual(result, 5, "Sub(9, 4): p1 is the first parameter")
        self.assertEqual(sp, STACK_TOP, "CallProc32W pops 12 + 4 * nParams for the caller")

    def test_a_marked_parameter_is_mapped_to_linear(self):
        self.h.arena.write(self.h.data, TEXT, b"Z")
        result, sp = call(self.h, BASE + 0x1020, [(self.h.data << 16) | TEXT], convert=1)
        self.assertEqual(result, ord("Z"))
        self.assertEqual(sp, STACK_TOP)

    def test_mask_bit_0_is_the_last_parameter(self):
        self.h.arena.write(self.h.data, TEXT, b"\x07")
        result, sp = call(self.h, BASE + 0x1030, [100, (self.h.data << 16) | TEXT], convert=1)
        self.assertEqual(result, 107)
        self.assertEqual(sp, STACK_TOP)

    def test_a_null_procedure_returns_zero_and_still_pops(self):
        result, sp = call(self.h, 0, [5, 7])
        self.assertEqual(result, 0)
        self.assertEqual(sp, STACK_TOP)


if __name__ == "__main__":
    unittest.main()
