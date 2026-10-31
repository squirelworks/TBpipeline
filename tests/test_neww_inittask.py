"""KERNEL.91 InitTask is Wine's register contract, or a stop that names what it needs.

Wine dlls/krnl386.exe16/task.c InitTask16 calls LocalInit16 when CX
is not 0, then the DLL entry points (ne_segment.c NE_InitializeDLLs),
then fills INSTANCEDATA and answers in registers: AX 1, BX the command
line in the PSP, CX the stack top, DX nCmdShow, SI the previous
instance, DI this instance, ES the PSP, and one zero word pushed.
neww has no local heap and does not run LibMain, so those two stop.
No binary needed.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DI, UC_X86_REG_DS, UC_X86_REG_ES,
    UC_X86_REG_SI, UC_X86_REG_SP,
)

# call InitTask; mov [0x20], ax; mov [0x22], dx; mov [0x24], sp; pop word [0x26]
AFTER = bytes([0xA3, 0x20, 0x00, 0x89, 0x16, 0x22, 0x00, 0x89, 0x26, 0x24, 0x00, 0x8F, 0x06, 0x26, 0x00])


def program(directory, heap=0, stack=0x40, modules=("KERNEL",), before=b""):
    code = bytearray(before)
    at_init = len(code)
    code += neww_ne.call_far() + AFTER
    code += neww_ne.mov_ax(0x4C00)
    at_exit = len(code)
    code += neww_ne.call_far() + bytes([0xF4])
    kernel = modules.index("KERNEL") + 1
    fixups = [(3, 1, at_init + 1, kernel, 91), (3, 1, at_exit + 1, kernel, 102)]
    blob = neww_ne.build(
        "TB80RTM",
        [(0x0000, bytes(code), fixups), (0x0001, b"\x00" * 256, [])],
        modules=modules, entry=(1, 0), auto=2, heap=heap, stack=stack,
    )
    neww_ne.write(directory, "TB80RTM.EXE", blob)


class InitTask(unittest.TestCase):
    def run_program(self, book=None, **kw):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, **kw)
            if book:
                book = Path(d) / book
                book.write_bytes(b"")
            for name in kw.get("modules", ()):
                if name != "KERNEL":
                    dll = neww_ne.build(name, [(0x0000, b"\xCB", [])], entry=(1, 0), exe=False)
                    neww_ne.write(d, f"{name}.DLL", dll)
            return Machine(d, book).run(limit=5000)

    def test_row_is_the_spec_register_entry(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[91]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("InitTask", (), 0, "register"))
        self.assertIn("-register InitTask()", row.spec[1])

    def test_registers_and_instancedata(self):
        host = self.run_program(book="nida81.tbk")
        self.assertEqual(host.stop, "dos exit 0x0")
        uc = host.uc
        ds = uc.reg_read(UC_X86_REG_DS)
        es = uc.reg_read(UC_X86_REG_ES)
        # SP starts at DGROUP's minsize plus the NE stack, as Wine NE_StartTask sets it.
        sp0 = 256 + 0x40
        # SP at the call is sp0 - 4. stackmin is the caller's SP, stacktop is stackmin - BX + 150.
        stacktop = sp0 - 0x40 + 150
        self.assertEqual(host.word(ds, 0x20), 1)
        self.assertEqual(host.word(ds, 0x22), 1)  # DX nCmdShow, SW_SHOWNORMAL
        self.assertEqual(uc.reg_read(UC_X86_REG_BX), 0x81)
        self.assertEqual(uc.reg_read(UC_X86_REG_CX), stacktop)
        self.assertEqual(uc.reg_read(UC_X86_REG_SI), 0)
        self.assertEqual(uc.reg_read(UC_X86_REG_DI), ds)
        self.assertEqual(host.word(es, 0), 0x20CD)
        self.assertEqual([host.word(ds, o) for o in (0x0A, 0x0C, 0x0E)], [stacktop, sp0, sp0])
        # One zero word pushed: after the return SP is sp0 - 2 and holds 0.
        self.assertEqual(host.word(ds, 0x24), sp0 - 2)
        self.assertEqual(host.word(ds, 0x26), 0)
        # The pop took the word back; the DOS3Call far call is still on the stack.
        self.assertEqual(uc.reg_read(UC_X86_REG_SP), sp0 - 4)

    def test_empty_command_line_is_0x80(self):
        host = self.run_program()
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_BX), 0x80)

    def test_heap_size_stops_on_localinit_and_writes_nothing(self):
        # mov ax, 0x5555 before the call: a stop leaves it.
        host = self.run_program(heap=0x100, before=neww_ne.mov_ax(0x5555))
        uc = host.uc
        ds = uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(
            host.stop,
            f"KERNEL.91 InitTask calls LocalInit16(DS={ds:#x}, 0, CX=0x100) first (Wine task.c InitTask16). "
            "neww has no local heap, KERNEL.4 LocalInit has no contract",
        )
        self.assertEqual(uc.reg_read(UC_X86_REG_AX), 0x5555)
        self.assertEqual(uc.reg_read(UC_X86_REG_SP), 256 + 0x40 - 4)
        self.assertEqual([host.word(ds, o) for o in (0x0A, 0x0C, 0x0E)], [0, 0, 0])

    def test_dll_with_init_code_stops(self):
        host = self.run_program(modules=("KERNEL", "TB80BAS"))
        self.assertEqual(
            host.stop,
            "KERNEL.91 InitTask runs the DLL entry points next (Wine ne_segment.c NE_InitializeDLLs): "
            "TB80BAS. neww does not call a DLL's LibMain",
        )


if __name__ == "__main__":
    unittest.main()
