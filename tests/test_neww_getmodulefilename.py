"""KERNEL.49 GetModuleFileName is Wine ne_module.c GetModuleFileName16.

Spec: `49 pascal -ret16 GetModuleFileName(word ptr s_word)`, pop 8.
hModule 0 is the current task's module. Any handle of a module's block
finds the module, as GetExePtr does. The path is copied with lstrcpynA
and its length returned. The directory is neww's guest name for --b,
C:\\TBK. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(handle, size):
    from tbpipeline_neww.machine import Machine
    # push handle ; push ds ; push 0x80 ; push size ; call ; mov [0x40], ax
    code = push(handle) + bytes([0x1E]) + push(0x80) + push(size) + neww_ne.call_far() + bytes([0xA3, 0x40, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, code, [(3, 1, 11, 1, 49)])
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    text = bytes(host.word(ds, 0x80 + i) & 0xFF for i in range(0x20)).split(b"\x00")[0]
    return host, host.word(ds, 0x40), text


class GetModuleFileName(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[49]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetModuleFileName", (2, 4, 2), 8, "word"))

    def test_zero_is_the_task_module(self):
        host, ax, text = run(0, 0x40)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((ax, text), (18, b"C:\\TBK\\TB80RTM.EXE"))

    def test_short_buffer_is_cut_as_lstrcpyn_cuts(self):
        _host, ax, text = run(0, 5)
        self.assertEqual((ax, text), (4, b"C:\\T"))

    def test_unknown_handle_is_zero(self):
        _host, ax, text = run(0x7770, 0x40)
        self.assertEqual((ax, text), (0, b""))


if __name__ == "__main__":
    unittest.main()
