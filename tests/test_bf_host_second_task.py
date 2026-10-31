"""Item 27: WinExec starts an EXE from the bin directory as a second task.

TB80BAS starts the book file manager with WinExec("TB80NET.exe ToolBook")
and waits for that task to call back with its window. Stopping there was
the wall. The host now loads the EXE beside the runtime, runs its startup
in the same CPU, and returns its instance to the caller once the new task
blocks in GetMessage, the way Win16 WinExec returns.

The EXE here is a tiny original NE image, not TB80NET.
"""

import struct
import tempfile
import unittest

from unicorn import UC_HOOK_INSN, UC_HOOK_INTR
from unicorn.x86_const import UC_X86_INS_OUT, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_IP, UC_X86_REG_SS

from tbpipeline_bf.nedllhost import pass06
from tests.bf_host_fake import STACK_TOP, fake_host
from tests.neww_ne import build, call_far, write

CMD = 0x100
RESULT = 0x200
GUEST = 0xF020 + 13


def second_exe(directory):
    """InitTask, keep DI and the command line offset, then GetMessage."""
    code = bytearray()
    fixups = []
    at = len(code)
    code += call_far()
    fixups.append((3, 1, at + 1, 1, 91))
    code += bytes([0x89, 0x3E, 0x10, 0x00])          # mov [0x10], di
    code += bytes([0x89, 0x1E, 0x12, 0x00])          # mov [0x12], bx
    code += bytes([0x1E, 0x6A, 0x20, 0x6A, 0x00, 0x6A, 0x00, 0x6A, 0x00])
    at = len(code)
    code += call_far()
    fixups.append((3, 1, at + 1, 2, 108))
    code += bytes([0xC7, 0x06, 0x14, 0x00, 0x34, 0x12])  # mov word [0x14], 0x1234
    code += bytes([0xF4])
    blob = build(
        "TASKTWO",
        [(0x0000, bytes(code), fixups), (0x0001, bytes(0x40), [])],
        modules=("KERNEL", "USER"), entry=(1, 0), auto=2, stack=0x200,
    )
    return write(directory, "TASKTWO.EXE", blob)


def caller(host):
    """WinExec("TaskTwo.exe hello", 2), keep AX, then int 3."""
    slot = 166 * 8
    code = bytes([
        0x1E, 0x68, CMD & 0xFF, CMD >> 8, 0x6A, 0x02,
        0x9A, slot & 0xFF, slot >> 8, host.thunk & 0xFF, host.thunk >> 8,
    ])
    ret_ip = GUEST + len(code)
    host.callers[(host.flat, ret_ip)] = ("KERNEL", 166)
    host.sites[(host.flat, ret_ip)] = ("KERNEL", 166, 6)
    code += bytes([0xA3, RESULT & 0xFF, RESULT >> 8, 0xCC])
    return code


class SecondTask(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        second_exe(self.dir.name)
        self.saved = pass06.UNPACKED
        pass06.UNPACKED = self.dir.name

    def tearDown(self):
        pass06.UNPACKED = self.saved
        self.dir.cleanup()

    def run_caller(self):
        host = fake_host()
        host.dlls, host.dll_segs, host.dll_calls = {}, {}, []
        host.dll_ready, host.dll_busy, host.dll_group = set(), set(), {}
        host.file, host.ne, host.nseg, host.shift, host.segoff = b"", 0, 0, 0, 0
        host._thunks()
        host.uc.hook_add(UC_HOOK_INSN, host._on_out, None, 1, 0, UC_X86_INS_OUT)
        host.uc.hook_add(UC_HOOK_INTR, host._on_intr)
        host.arena.write(host.data, CMD, b"TaskTwo.exe hello\x00")
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
        ]) + caller(host))
        for reg in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_SS):
            host.uc.reg_write(reg, 0)
        host.uc.reg_write(UC_X86_REG_IP, 0xF000)
        host._run_tasks(0xF000)
        return host

    def test_winexec_runs_the_task_and_returns_its_instance(self):
        host = self.run_caller()
        self.assertEqual(host.fault, "returned", host.task_log)
        self.assertEqual(host.ax1, [], "a call fell through to AX = 1")
        self.assertEqual([t["name"] for t in host.tasks], ["TB80RTM", "TASKTWO"])
        task = host.tasks[1]
        inst = struct.unpack("<H", host.arena.read(host.data, RESULT, 2))[0]
        self.assertEqual(inst, task["inst"], "WinExec did not return the new instance")
        self.assertGreater(inst, 32)
        self.assertEqual(struct.unpack("<H", host.arena.read(inst, 0x10, 2))[0], inst, "InitTask DI")
        self.assertEqual(host.arena.read(task["psp"], 0x81, 7), b" hello\r")
        self.assertEqual(host.task_log[-1], "TASKTWO yielded at USER.108")

    def test_the_task_blocks_in_getmessage(self):
        host = self.run_caller()
        inst = host.tasks[1]["inst"]
        self.assertEqual(host.arena.read(inst, 0x14, 2), b"\x00\x00", "GetMessage returned with an empty queue")


if __name__ == "__main__":
    unittest.main()
