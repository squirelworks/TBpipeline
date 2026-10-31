"""The task starts with Wine's NE_StartTask registers and a PSP in ES.

Wine ne_module.c NE_StartTask enters a task with AX 0, BX the stack
size, CX the heap size, SI the previous instance, DI this instance,
BP 0, ES the PSP, and DS DGROUP. The PSP is task.c TASK_Create's PDB16.
neww used to enter with BX, CX, SI, DI and ES all 0 and no PSP.
"""

import tempfile
import unittest
from pathlib import Path

from tests import neww_ne
from unicorn.x86_const import (
    UC_X86_REG_BP, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DS, UC_X86_REG_DI, UC_X86_REG_ES,
    UC_X86_REG_SI,
)


def program(directory, before):
    code = bytearray(before)
    code += neww_ne.mov_ax(0x4C00)
    at = len(code)
    code += neww_ne.call_far() + bytes([0xF4])
    blob = neww_ne.build(
        "TB80RTM",
        [(0x0000, bytes(code), [(3, 1, at + 1, 1, 102)]), (0x0001, b"\x00" * 256, [])],
        modules=("KERNEL",), entry=(1, 0), auto=2, heap=0x100, stack=0x200,
    )
    neww_ne.write(directory, "TB80RTM.EXE", blob)


class TaskEntry(unittest.TestCase):
    def run_program(self, before, book=None):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, before)
            if book:
                book = Path(d) / book
                book.write_bytes(b"")
            return Machine(d, book).run(limit=5000)

    def test_registers_are_ne_starttask(self):
        # inc ax; mov [0], ax: DS:0 holds 1 only if AX was 0 at entry.
        host = self.run_program(bytes([0x40, 0xA3, 0x00, 0x00]))
        self.assertEqual(host.stop, "dos exit 0x0")
        uc = host.uc
        ds = uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.word(ds, 0), 1)
        self.assertEqual(uc.reg_read(UC_X86_REG_BX), 0x200)
        self.assertEqual(uc.reg_read(UC_X86_REG_CX), 0x100)
        self.assertEqual(uc.reg_read(UC_X86_REG_SI), 0)
        # DGROUP here is fixed, so the instance handle is its selector.
        self.assertEqual(uc.reg_read(UC_X86_REG_DI), ds)
        self.assertEqual(uc.reg_read(UC_X86_REG_BP), 0)

    def test_es_is_the_psp(self):
        host = self.run_program(b"", book="nida81.tbk")
        es = host.uc.reg_read(UC_X86_REG_ES)
        self.assertNotEqual(es, 0)
        self.assertEqual(host.word(es, 0x00), 0x20CD)
        self.assertEqual(host.word(es, 0x18), 0xFFFF)
        self.assertEqual(host.word(es, 0x32), 20)
        self.assertEqual((host.word(es, 0x34), host.word(es, 0x36)), (0x18, es))
        line = bytes(host.word(es, 0x80 + i) & 0xFF for i in range(11))
        self.assertEqual(line, b"\x0anida81.tbk")

    def test_no_book_is_an_empty_command_line(self):
        host = self.run_program(b"")
        es = host.uc.reg_read(UC_X86_REG_ES)
        self.assertEqual(host.word(es, 0x80) & 0xFF, 0)

    def test_reading_the_dispatcher_stops(self):
        # mov ax, es:[0x06]
        host = self.run_program(bytes([0x26, 0xA1, 0x06, 0x00]))
        self.assertTrue(host.stop.startswith("PSP dispatcher at 0x05, Wine's far call to KERNEL.DOS3Call, read at "), host.stop)
        self.assertTrue(host.stop.endswith(": neww has nothing to put there"), host.stop)
        self.assertEqual(host.calls, 0)


if __name__ == "__main__":
    unittest.main()
