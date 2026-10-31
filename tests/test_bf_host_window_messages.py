"""Item 27: windows have procedures, and SendMessage calls them.

TB80BAS and TB80W32 talk to the book file manager by sending a registered
message to TB80NET's window. RegisterClass, CreateWindow,
RegisterWindowMessage and SendMessage all fell through to AX = 1, so the
window was hwnd 1, the message was 1, and nothing ran. Now a class keeps
its procedure and instance, CreateWindow sends WM_NCCREATE and WM_CREATE,
a registered message is an atom from 0xC000, and a send calls the
procedure with DS = the window's instance and returns its DX:AX.
"""

import struct
import unittest

from unicorn import UC_HOOK_INSN, UC_HOOK_INTR
from unicorn.x86_const import UC_X86_INS_OUT, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS

from tests.bf_host_fake import STACK_TOP, fake_host

GUEST = 0xF020 + 13
WNDCLASS = 0x100
CLASSNAME = 0x140
MSGNAME = 0x160
OUT = 0x200

# wParam + msg in AX, DS kept at DS:0x10, retf 10.
PROC = bytes([
    0x55, 0x8B, 0xEC, 0x8B, 0x46, 0x0A, 0x03, 0x46, 0x0C,
    0x8C, 0x1E, 0x10, 0x00, 0x33, 0xD2, 0x5D, 0xCA, 0x0A, 0x00,
])


def host_with_proc():
    host = fake_host()
    host.dlls, host.dll_segs, host.dll_calls = {}, {}, []
    host.dll_ready, host.dll_busy, host.dll_group = set(), set(), {}
    host._thunks()
    host.uc.hook_add(UC_HOOK_INSN, host._on_out, None, 1, 0, UC_X86_INS_OUT)
    host.uc.hook_add(UC_HOOK_INTR, host._on_intr)
    host.proc = host.arena.alloc_selector(0x100, 0x9A, PROC)
    host.inst = host.arena.alloc_selector(0x100, 0x92, bytes(0x100))
    host.arena.write(host.data, WNDCLASS, struct.pack(
        "<HHHHHHHHHII", 0, 0, host.proc, 0, 0, host.inst, 0, 0, 0, 0, (host.data << 16) | CLASSNAME))
    host.arena.write(host.data, CLASSNAME, b"TestClass\x00")
    host.arena.write(host.data, MSGNAME, b"TestMessage\x00")
    return host


def api(host, code, module, ordinal, pop, pushes):
    slot = ordinal * 8
    code += pushes + bytes([0x9A, slot & 0xFF, slot >> 8, host.thunk & 0xFF, host.thunk >> 8])
    host.callers[(host.flat, GUEST + len(code))] = (module, ordinal)
    host.sites[(host.flat, GUEST + len(code))] = (module, ordinal, pop)
    return code


def store(code, at):
    return code + bytes([0xA3, at & 0xFF, at >> 8, 0x89, 0x16, (at + 2) & 0xFF, (at + 2) >> 8])


def guest(host):
    d = [0x1E]  # push ds
    code = api(host, b"", "USER", 118, 4, bytes(d + [0x68, MSGNAME & 0xFF, MSGNAME >> 8]))
    code = store(code, OUT)
    code += bytes([0x50])                                   # keep the message number
    code = api(host, code, "USER", 57, 4, bytes(d + [0x68, WNDCLASS & 0xFF, WNDCLASS >> 8]))
    create = bytes(d + [0x68, CLASSNAME & 0xFF, CLASSNAME >> 8, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0,
                        0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0, 0x6A, 0])
    code = api(host, code, "USER", 41, 30, create)
    code = store(code, OUT + 4)
    code += bytes([0x5B])                                   # pop bx: the message
    send = bytes([0x50, 0x53, 0x6A, 0x05, 0x6A, 0x07, 0x6A, 0x00])  # hwnd, msg, 5, MAKELONG(0, 7)
    code = api(host, code, "USER", 111, 10, send)
    code = store(code, OUT + 8)
    return code + bytes([0xCC])


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


class WindowMessages(unittest.TestCase):
    def test_register_create_and_send(self):
        host = host_with_proc()
        run(host, guest(host))
        self.assertEqual(host.fault, "returned", host.task_log)
        self.assertEqual(host.ax1, [], "a window call fell through to AX = 1")
        msg, hwnd, result = struct.unpack("<III", host.arena.read(host.data, OUT, 12))
        self.assertGreaterEqual(msg, 0xC000, "RegisterWindowMessage is not an atom")
        self.assertNotIn(hwnd, (0, 1), "CreateWindow did not make a window")
        self.assertEqual(result, 5 + msg, "SendMessage did not return the procedure's DX:AX")
        self.assertEqual(struct.unpack("<H", host.arena.read(host.inst, 0x10, 2))[0], host.inst,
                         "the procedure did not run with DS = the window's instance")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP, "the stack is not balanced")

    def test_the_same_name_is_the_same_message(self):
        host = fake_host()
        host.task_log = []
        self.assertEqual(host._atom("msg:TestMessage"), host._atom("msg:testmessage"))


if __name__ == "__main__":
    unittest.main()
