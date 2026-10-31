"""Item 27: the Windows 95/NT generic thunks run a 32-bit DLL.

TB80W16 reaches TB80W32.DLL, a PE DLL, with GetProcAddress(KERNEL, 513..518)
and calls through the pointers: LoadLibraryEx32W, GetProcAddress32W and
CallProcEx32W. GetProcAddress by ordinal on a system module now hands
out a stub whose selector names the module, so the host knows the call.
LoadLibraryEx32W maps the PE at its image base and runs its entry point
as 32-bit code; CallProcEx32W runs an export and returns EAX in DX:AX.
A Win32 import with no answer stops the run and is named.

The DLL here is a tiny original PE, not TB80W32.
"""

import struct
import tempfile
import unittest

from unicorn import UC_HOOK_INSN, UC_HOOK_INTR
from unicorn.x86_const import UC_X86_INS_OUT, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_IP, UC_X86_REG_SS

from tbpipeline_bf.nedllhost import pass06
from tests.bf_host_fake import STACK_TOP, fake_host
from tests.pe32 import BASE, build, call_import, write

NAME = 0x100
PROC = 0x120
OUT = 0x200
GUEST = 0xF020 + 13

ENTRY = [bytes([0xB8, 1, 0, 0, 0, 0xC2, 0x0C, 0x00])]                 # mov eax, 1; ret 12
ADD = [bytes([0x8B, 0x44, 0x24, 0x04, 0x03, 0x44, 0x24, 0x08, 0xC2, 0x08, 0x00])]


def host_with(directory):
    host = fake_host()
    host.dlls, host.dll_segs, host.dll_calls = {}, {}, []
    host.dll_ready, host.dll_busy, host.dll_group = set(), set(), {}
    host.file, host.ne, host.nseg, host.shift, host.segoff = b"", 0, 0, 0, 0
    host._thunks()
    host.uc.hook_add(UC_HOOK_INSN, host._on_out, None, 1, 0, UC_X86_INS_OUT)
    host.uc.hook_add(UC_HOOK_INTR, host._on_intr)
    return host


def far(stub):
    off, sel = stub
    return bytes([0x9A, off & 0xFF, off >> 8, sel & 0xFF, sel >> 8])


def guest(host):
    """LoadLibraryEx32W, GetProcAddress32W, then CallProcEx32W(Add, 5, 7)."""
    kernel = host._load_library("KERNEL")
    stubs = {n: host._module_stub("KERNEL", n) for n in (513, 515, 518)}
    for n, stub in stubs.items():
        assert stub, n
    code = bytes([0x1E, 0x68, NAME & 0xFF, NAME >> 8, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0]) + far(stubs[513])
    code += bytes([0xA3, OUT & 0xFF, OUT >> 8, 0x89, 0x16, (OUT + 2) & 0xFF, (OUT + 2) >> 8])
    code += bytes([0x52, 0x50, 0x1E, 0x68, PROC & 0xFF, PROC >> 8]) + far(stubs[515])
    code += bytes([0xA3, (OUT + 4) & 0xFF, (OUT + 4) >> 8, 0x89, 0x16, (OUT + 6) & 0xFF, (OUT + 6) >> 8])
    # cdecl, right to left: p2, p1, lpProc, fAddressConvert, nParams.
    code += bytes([0x6A, 0, 0x6A, 7, 0x6A, 0, 0x6A, 5, 0x52, 0x50, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 2])
    code += far(stubs[518]) + bytes([0x83, 0xC4, 0x14])
    code += bytes([0xA3, (OUT + 8) & 0xFF, (OUT + 8) >> 8, 0x89, 0x16, (OUT + 10) & 0xFF, (OUT + 10) >> 8, 0xCC])
    return kernel, code


def run(host, code):
    gdtr_at = 0xF0E0
    host.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
    host.uc.mem_write(0xF000, bytes([
        0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
        0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
        0xEA, 0x20, 0xF0, host.flat & 0xFF, (host.flat >> 8) & 0xFF,
    ]))
    host.uc.mem_write(0xF020, bytes([
        0xB8, host.data & 0xFF, host.data >> 8, 0x8E, 0xD8,
        0xB8, host.stack & 0xFF, host.stack >> 8, 0x8E, 0xD0,
        0xBC, STACK_TOP & 0xFF, STACK_TOP >> 8,
    ]) + code)
    for reg in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_SS):
        host.uc.reg_write(reg, 0)
    host.uc.reg_write(UC_X86_REG_IP, 0xF000)
    host._run_tasks(0xF000)


class GenericThunk(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = pass06.UNPACKED
        pass06.UNPACKED = self.dir.name

    def tearDown(self):
        pass06.UNPACKED = self.saved
        self.dir.cleanup()

    def dwords(self, host):
        return struct.unpack("<III", host.arena.read(host.data, OUT, 12))

    def test_load_lookup_and_call(self):
        write(self.dir.name, "TESTW32.DLL", build([(None, ENTRY), ("Add", ADD)]))
        host = host_with(self.dir.name)
        host.arena.write(host.data, NAME, b"TESTW32.DLL\x00")
        host.arena.write(host.data, PROC, b"Add\x00")
        _, code = guest(host)
        run(host, code)
        self.assertEqual(host.fault, "returned", host.task_log)
        self.assertEqual(host.ax1, [], "a generic thunk fell through to AX = 1")
        hinst, proc, result = self.dwords(host)
        self.assertEqual(hinst, BASE, "LoadLibraryEx32W did not return the image base")
        self.assertEqual(proc, BASE + 0x1010, "GetProcAddress32W did not find Add")
        self.assertEqual(result, 12, "CallProcEx32W did not run Add(5, 7)")
        self.assertEqual(host.uc.reg_read(pass06.UC_X86_REG_SP), STACK_TOP, "the 16-bit stack is not balanced")

    def test_an_unanswered_import_is_the_stop(self):
        entry = [call_import(0)] + ENTRY
        write(self.dir.name, "TESTW32.DLL", build([(None, entry), ("Add", ADD)],
                                                  imports=[("KERNEL32.dll", "NoSuchCall")]))
        host = host_with(self.dir.name)
        host.arena.write(host.data, NAME, b"TESTW32.DLL\x00")
        host.arena.write(host.data, PROC, b"Add\x00")
        _, code = guest(host)
        run(host, code)
        self.assertEqual(host.fault, "win32 KERNEL32.NoSuchCall")

    def test_a_dll_that_is_not_there_is_the_stop(self):
        host = host_with(self.dir.name)
        host.arena.write(host.data, NAME, b"TESTW32.DLL\x00")
        host.arena.write(host.data, PROC, b"Add\x00")
        _, code = guest(host)
        run(host, code)
        self.assertEqual(host.fault, "LoadLibraryEx32W 'TESTW32.DLL'")
        self.assertEqual(host.ax1, [])


if __name__ == "__main__":
    unittest.main()
