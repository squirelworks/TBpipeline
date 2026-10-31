"""KERNEL.513 LoadLibraryEx32W maps a 32-bit DLL and runs its DllMain.

Wine's LoadLibraryEx32W16 (dlls/krnl386.exe16/wowthunk.c) returns
LoadLibraryExA's HMODULE: the image base once DllMain(hinst,
DLL_PROCESS_ATTACH, 0) has returned TRUE, or 0 when the file is missing
or DllMain says FALSE. The spec line is
`513 pascal LoadLibraryEx32W(ptr long long) LoadLibraryEx32W16`, so it
pops 12. A Win32 system DLL is already mapped and needs no file. A Win32
import with no answer stops the run and is named.

The DLL here is a tiny original PE built by tests/pe32.py, not TB80W32.
"""

import os
import struct
import tempfile
import unittest
from unittest import mock

from unicorn import UC_HOOK_INSN
from unicorn.x86_const import (
    UC_X86_INS_OUT, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

from tests.bf_host_fake import STACK_TOP, fake_host
from tests.pe32 import BASE, build, call_import, write

NAME = 0x100
OUT = 0x200
GUEST = 0xF020 + 13       # after run()'s 13-byte prefix
LOADLIBRARYEX32W = 513

# DllMain returns fdwReason, so TRUE only for DLL_PROCESS_ATTACH. It also
# keeps hinstDLL at BASE + 0x2F00 for the test to read.
ATTACH = [bytes([0x8B, 0x44, 0x24, 0x04, 0xA3]) + struct.pack("<I", BASE + 0x2F00)
          + bytes([0x8B, 0x44, 0x24, 0x08, 0xC2, 0x0C, 0x00])]
REFUSE = [bytes([0x31, 0xC0, 0xC2, 0x0C, 0x00])]                      # xor eax, eax; ret 12


def host():
    h = fake_host()
    h.dlls, h.dll_segs, h.dll_calls = {}, {}, []
    h.dll_ready, h.dll_busy, h.dll_group = set(), set(), {}
    # A selector laid out like the thunk, reaching past ordinal 511.
    blob = bytearray(0x1000)
    at = LOADLIBRARYEX32W * 8 - 0x1000
    blob[at:at + 8] = bytes([0xBA, LOADLIBRARYEX32W & 0xFF, LOADLIBRARYEX32W >> 8, 0xE6, 0xE0, 0xCA, 0, 0])
    h.gate = h.arena.alloc_selector(0x2000, 0x9A, bytes(0x1000) + bytes(blob))
    h.uc.hook_add(UC_HOOK_INSN, h._on_out, None, 1, 0, UC_X86_INS_OUT)
    h.arena.write(h.data, NAME, b"TESTW32.DLL\x00")
    return h


def guest(h):
    """LoadLibraryEx32W(NAME, 0, 0), then DX:AX to OUT, then hlt."""
    code = bytes([0x1E, 0x68, NAME & 0xFF, NAME >> 8, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0])
    code += bytes([0x9A]) + struct.pack("<HH", LOADLIBRARYEX32W * 8, h.gate)
    h.sites[(h.flat, GUEST + len(code))] = ("KERNEL", LOADLIBRARYEX32W, 12)
    h.callers[(h.flat, GUEST + len(code))] = ("KERNEL", LOADLIBRARYEX32W)
    code += bytes([0xA3, OUT & 0xFF, OUT >> 8, 0x89, 0x16, (OUT + 2) & 0xFF, (OUT + 2) >> 8])
    code += bytes([0x89, 0x26, (OUT + 4) & 0xFF, (OUT + 4) >> 8, 0xF4])
    return code


def run(h, code=None):
    """Run code (the LoadLibraryEx32W guest by default); return OUT's dword and word."""
    gdtr_at = 0xF0E0
    h.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
    h.uc.mem_write(0xF000, bytes([
        0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
        0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
        0xEA, 0x20, 0xF0, h.flat & 0xFF, (h.flat >> 8) & 0xFF,
    ]))
    h.uc.mem_write(0xF020, bytes([
        0xB8, h.data & 0xFF, h.data >> 8, 0x8E, 0xD8,
        0xB8, h.stack & 0xFF, h.stack >> 8, 0x8E, 0xD0,
        0xBC, STACK_TOP & 0xFF, STACK_TOP >> 8,
    ]) + (guest(h) if code is None else code))
    for reg in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_SS):
        h.uc.reg_write(reg, 0)
    h.uc.reg_write(UC_X86_REG_IP, 0xF000)
    # A second run writes new code where the first ran; drop what the CPU
    # translated from the old bytes.
    h.uc.ctl_flush_tb()
    h.fault = ""
    h._run_from(0xF000)
    hinst, sp = struct.unpack("<IH", h.arena.read(h.data, OUT, 6))
    return hinst, sp


class LoadLibraryEx32W(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TBK_UNPACKED": self.dir.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_returns_the_image_base_after_dllmain_attaches(self):
        write(self.dir.name, "TESTW32.DLL", build([(None, ATTACH)]))
        h = host()
        hinst, sp = run(h)
        self.assertEqual(h.ax1, [], "LoadLibraryEx32W fell through to AX = 1")
        self.assertEqual(hinst, BASE, "LoadLibraryEx32W did not return the image base")
        self.assertEqual(struct.unpack("<I", bytes(h.uc.mem_read(BASE + 0x2F00, 4)))[0], BASE,
                         "DllMain did not get hinstDLL")
        self.assertEqual(sp, STACK_TOP, "LoadLibraryEx32W did not pop its 12 bytes")

    def test_a_second_load_does_not_run_dllmain_again(self):
        write(self.dir.name, "TESTW32.DLL", build([(None, ATTACH)]))
        h = host()
        run(h)
        h.uc.mem_write(BASE + 0x2F00, bytes(4))
        hinst, _ = run(h)
        self.assertEqual(hinst, BASE)
        self.assertEqual(bytes(h.uc.mem_read(BASE + 0x2F00, 4)), bytes(4), "DllMain ran twice")

    def test_dllmain_false_returns_zero(self):
        write(self.dir.name, "TESTW32.DLL", build([(None, REFUSE)]))
        h = host()
        hinst, sp = run(h)
        self.assertEqual(hinst, 0)
        self.assertEqual(sp, STACK_TOP)

    def test_a_missing_dll_returns_zero(self):
        h = host()
        hinst, sp = run(h)
        self.assertEqual(hinst, 0)
        self.assertEqual(h.ax1, [])
        self.assertEqual(sp, STACK_TOP)

    def test_a_win32_system_dll_needs_no_file(self):
        h = host()
        h.arena.write(h.data, NAME, b"KERNEL32.DLL\x00")
        hinst, _ = run(h)
        self.assertEqual(hinst, 0x7FE00000)

    def test_an_unanswered_import_is_the_stop(self):
        entry = [call_import(0)] + ATTACH
        write(self.dir.name, "TESTW32.DLL", build([(None, entry)], imports=[("KERNEL32.dll", "NoSuchCall")]))
        h = host()
        run(h)
        self.assertEqual(h.fault, "win32 KERNEL32.NoSuchCall")


if __name__ == "__main__":
    unittest.main()
