"""KERNEL.518 CallProcEx32W runs a 32-bit procedure and returns its EAX.

Wine's spec line (dlls/krnl386.exe16/krnl386.exe16.spec:426, Wine
commit 2528aff2) is
`518 varargs _CallProcEx32W(long long long) CallProcEx32W16`:
cdecl, so the callee pops nothing and the caller adds to SP. CallProcEx32W16 (dlls/krnl386.exe16/thunk.c:2609) takes nParams,
fAddressConvert and lpProc32, then reads the parameters p1 to pn left to
right. When bit i of fAddressConvert is set, p(i+1) is a 16:16 pointer
and is passed through MapSL. It calls lpProc32 and returns EAX in DX:AX.
The top bit of nParams, CPEX_DEST_CDECL, says the target is cdecl.
WOW_CallProc32W16 returns 0 for a NULL lpProc32 without calling it.

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

CALLPROCEX32W = 518
TEXT = 0x300
ADD = [bytes([0x8B, 0x44, 0x24, 0x04, 0x03, 0x44, 0x24, 0x08, 0xC2, 0x08, 0x00])]   # stdcall Add(a, b)
# stdcall Peek(p): the byte at linear address p.
PEEK = [bytes([0x8B, 0x44, 0x24, 0x04, 0x0F, 0xB6, 0x00, 0xC2, 0x04, 0x00])]
# cdecl Sub(a, b): a - b, and the caller pops.
SUB = [bytes([0x8B, 0x44, 0x24, 0x04, 0x2B, 0x44, 0x24, 0x08, 0xC3])]


def call_ex(h, proc, params, convert=0, cdecl=False):
    """CallProcEx32W(n, convert, proc, p1..pn), add sp, then DX:AX and SP to OUT."""
    n = len(params) | (0x80000000 if cdecl else 0)
    code = b""
    for value in [*reversed(params), proc, convert, n]:
        code += bytes([0x68]) + struct.pack("<H", value >> 16) + bytes([0x68]) + struct.pack("<H", value & 0xFFFF)
    gate_off = CALLPROCEX32W * 8 - 0x1000
    h.arena.write(h.gate, 0x1000 + gate_off, bytes([0xBA, CALLPROCEX32W & 0xFF, CALLPROCEX32W >> 8, 0xE6, 0xE0, 0xCA, 0, 0]))
    code += bytes([0x9A]) + struct.pack("<HH", CALLPROCEX32W * 8, h.gate)
    h.sites[(h.flat, GUEST + len(code))] = ("KERNEL", CALLPROCEX32W, POP["KERNEL"][CALLPROCEX32W])
    h.callers[(h.flat, GUEST + len(code))] = ("KERNEL", CALLPROCEX32W)
    code += bytes([0x83, 0xC4, 4 * (3 + len(params))])
    code += bytes([0xA3, OUT & 0xFF, OUT >> 8, 0x89, 0x16, (OUT + 2) & 0xFF, (OUT + 2) >> 8])
    code += bytes([0x89, 0x26, (OUT + 4) & 0xFF, (OUT + 4) >> 8, 0xF4])
    return run(h, code)


class CallProcEx32W(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()
        write(self.dir.name, "TESTW32.DLL", build([(None, ATTACH), ("Add", ADD), ("Peek", PEEK), ("Sub", SUB)]))
        self.h = host()
        hinst, _ = run(self.h)
        self.assertEqual(hinst, BASE)

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_runs_the_procedure_and_returns_eax(self):
        result, sp = call_ex(self.h, BASE + 0x1010, [5, 7])
        self.assertEqual(result, 12)
        self.assertEqual(self.h.ax1, [], "CallProcEx32W fell through to AX = 1")
        self.assertEqual(sp, STACK_TOP, "CallProcEx32W popped: it is cdecl")

    def test_a_marked_parameter_is_mapped_to_linear(self):
        self.h.arena.write(self.h.data, TEXT, b"Z")
        result, _ = call_ex(self.h, BASE + 0x1020, [(self.h.data << 16) | TEXT], convert=1)
        self.assertEqual(result, ord("Z"))

    def test_a_cdecl_target(self):
        result, sp = call_ex(self.h, BASE + 0x1030, [9, 4], cdecl=True)
        self.assertEqual(result, 5)
        self.assertEqual(sp, STACK_TOP)

    def test_a_null_procedure_returns_zero(self):
        result, sp = call_ex(self.h, 0, [5, 7])
        self.assertEqual(result, 0)
        self.assertEqual(sp, STACK_TOP)


if __name__ == "__main__":
    unittest.main()
