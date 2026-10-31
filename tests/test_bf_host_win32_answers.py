"""Item 27: the Win32 calls TB80W32.DLL's start-up makes are answered.

Each one is called the way 32-bit code calls it: through its import stub,
from a stdcall frame. The answer is checked, and so is the stack the stub
leaves: the return address, slid past the arguments the call pops.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP

from tbpipeline_bf.nedllhost.win32 import STACK32, STACK32_SIZE
from tests.bf_host_fake import fake_host

RET = 0x12345678


def call(host, dll, name, *args):
    host._win32_setup()
    host.task_log = []
    ident = host._api32_stub(dll, name)
    ident = (ident - 0x0F000000) // 8
    esp = STACK32 + STACK32_SIZE - 0x100
    host.uc.mem_write(esp, struct.pack("<I", RET) + b"".join(struct.pack("<I", a) for a in args) + bytes(32))
    host.uc.reg_write(UC_X86_REG_ESP, esp)
    host.fault = ""
    host._api32(ident)
    sp = host.uc.reg_read(UC_X86_REG_ESP)
    assert struct.unpack("<I", bytes(host.uc.mem_read(sp, 4)))[0] == RET, "return address lost"
    return host.uc.reg_read(UC_X86_REG_EAX), sp - esp


def scratch(host, data=b""):
    from tbpipeline_bf.nedllhost.win32api import _alloc
    at = _alloc(host, 0x200)
    host.uc.mem_write(at, data)
    return at


class Win32Answers(unittest.TestCase):
    def test_get_version_is_windows_98(self):
        host = fake_host()
        self.assertEqual(call(host, "KERNEL32", "GetVersion"), (0xC0000A04, 0))
        self.assertEqual(host.fault, "")

    def test_heap_alloc_and_size(self):
        host = fake_host()
        heap, pop = call(host, "KERNEL32", "HeapCreate", 0, 0x1000, 0)
        self.assertEqual(pop, 12)
        block, _ = call(host, "KERNEL32", "HeapAlloc", heap, 8, 0x30)
        self.assertNotEqual(block, 0)
        self.assertEqual(call(host, "KERNEL32", "HeapSize", heap, 0, block)[0], 0x30)

    def test_locale_ansi_code_page(self):
        host = fake_host()
        buf = scratch(host)
        n, pop = call(host, "KERNEL32", "GetLocaleInfoA", 0x409, 0x1004, buf, 16)
        self.assertEqual((n, pop), (5, 16))
        self.assertEqual(bytes(host.uc.mem_read(buf, 5)), b"1252\x00")

    def test_unknown_locale_type_stops(self):
        host = fake_host()
        host.uc.emu_stop = lambda: None
        call(host, "KERNEL32", "GetLocaleInfoA", 0x409, 0x5A, scratch(host), 16)
        self.assertEqual(host.fault, "win32 KERNEL32.GetLocaleInfoA lcid 0x409 type 0x5a")

    def test_lstrcmpi(self):
        host = fake_host()
        one, two = scratch(host, b"ToolBook\x00"), scratch(host, b"TOOLBOOK\x00")
        self.assertEqual(call(host, "KERNEL32", "lstrcmpiA", one, two), (0, 8))

    def test_wow_pointer_is_linear(self):
        host = fake_host()
        base = host.arena.segs[host.data]["base"]
        self.assertEqual(call(host, "WOW32", "WOWGetVDMPointerFix", (host.data << 16) | 0x20, 0x10, 1),
                         (base + 0x20, 12))


if __name__ == "__main__":
    unittest.main()
