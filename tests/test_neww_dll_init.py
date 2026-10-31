"""InitTask runs each ToolBook DLL's LibMain, as Wine NE_InitializeDLLs does.

Wine ne_segment.c NE_InitDLL calls a library's entry point with CX the
DLL's heap size, DI its instance, DS and ES its DGROUP, and the other
registers 0, in the order the DLLs were first loaded, a DLL's own DLLs
first. Then InitTask16 answers its caller. neww used to stop there.
No binary needed.
"""

import struct
import tempfile
import unittest

from tests import neww_ne
from tests.test_neww_inittask import program
from unicorn.x86_const import UC_X86_REG_DS

# mov [0], cx; mov [2], di; mov [4], ds; mov [6], es; mov [8], bp; mov [10], bx; mov ax, 1; retf
LIBMAIN = bytes([
    0x89, 0x0E, 0x00, 0x00, 0x89, 0x3E, 0x02, 0x00, 0x8C, 0x1E, 0x04, 0x00, 0x8C, 0x06, 0x06, 0x00,
    0x89, 0x2E, 0x08, 0x00, 0x89, 0x1E, 0x0A, 0x00, 0xB8, 0x01, 0x00, 0xCB,
])


def dll(directory, name, modules=(), heap=0x40):
    blob = bytearray(neww_ne.build(
        name, [(0x0000, LIBMAIN, []), (0x0001, b"\x00" * 64, [])],
        modules=modules, entry=(1, 0), auto=2, heap=heap, exe=False,
    ))
    # Library + SINGLEDATA, as ToolBook's DLLs are marked.
    struct.pack_into("<H", blob, 0x40 + 0x0C, 0x8001)
    neww_ne.write(directory, f"{name}.DLL", bytes(blob))


class DllInit(unittest.TestCase):
    def test_libmain_gets_wine_registers_and_inittask_answers(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, modules=("KERNEL", "TB80UTL"))
            dll(d, "TB80UTL")
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.stop, "dos exit 0x0")
        seg = host.box.images["TB80UTL"].segments[1]
        sel = seg.selector
        cx, di, ds, es, bp, bx = (host.word(sel, o) for o in range(0, 12, 2))
        self.assertEqual((cx, di, ds, es, bx), (0x40, sel, sel, sel, 0))
        self.assertNotEqual(bp, 0)
        # The DLL's DGROUP has room for its heap: 64 + 0x40, rounded to 32.
        self.assertEqual(len(seg.data), 0x80)
        # InitTask then answered the task: AX 1 was stored, DS is the task's again.
        exe_ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(exe_ds, host.box.exe.segments[1].selector)
        self.assertEqual(host.word(exe_ds, 0x20), 1)
        self.assertEqual(host.word(exe_ds, 0x26), 0)

    def test_order_is_a_dlls_own_dlls_first(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            program(d, modules=("KERNEL", "TB80W16", "TB80RCR"))
            dll(d, "TB80W16", modules=("TB80UTL",))
            dll(d, "TB80UTL", modules=("TB80W16", "TB80RCR"))
            dll(d, "TB80RCR")
            host = Machine(d)
            names = [row[0] for row in host.run(limit=5000).box.wine.task["dll_init"]]
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(names, ["TB80RCR", "TB80UTL", "TB80W16"])


if __name__ == "__main__":
    unittest.main()
