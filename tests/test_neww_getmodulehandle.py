"""KERNEL.47 GetModuleHandle is Wine ne_module.c WIN16_GetModuleHandle.

Spec: `47 pascal GetModuleHandle(segstr) WIN16_GetModuleHandle`, pop 4,
a long. A selector of 0 is a handle, given to GetExePtr. A name is
GetModuleHandle16: the module name, then the base name of the loaded
file. DX is hFirstModule either way. A system module name stops, since
Wine's answer is its builtin and neww's system modules are gates. The
handle is a block with nothing in it, so reading it stops. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS

# call ; mov [0x40], ax ; mov [0x42], dx
AFTER = neww_ne.call_far() + bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00])


def run(name=None, after=b""):
    from tbpipeline_neww.machine import Machine
    data = bytearray(256)
    if name is None:
        # push 0 ; push ds: a handle, DGROUP's selector.
        code = bytes([0x6A, 0x00, 0x1E])
    else:
        data[0x80:0x80 + len(name) + 1] = name + b"\x00"
        # push ds ; push 0x80
        code = bytes([0x1E, 0x68, 0x80, 0x00])
    at = len(code) + 1
    code += AFTER + after
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, code, [(3, 1, at, 1, 47)], data=bytes(data))
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, host.word(ds, 0x40), host.word(ds, 0x42)


class GetModuleHandle(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[47]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetModuleHandle", (4,), 4, "long"))

    def test_module_name_without_case(self):
        host, ax, dx = run(b"tb80rtm")
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(ax, host.box.wine.modules["TB80RTM"])
        self.assertNotEqual(ax, 0)
        self.assertEqual(dx, host.box.wine.first_module)

    def test_path_matches_by_base_name(self):
        host, ax, _dx = run(b"C:\\TBK\\TB80RTM.EXE")
        self.assertEqual(ax, host.box.wine.modules["TB80RTM"])

    def test_unknown_name_is_zero(self):
        host, ax, dx = run(b"TB80XYZ")
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((ax, dx), (0, host.box.wine.first_module))

    def test_handle_goes_through_getexeptr(self):
        host, ax, _dx = run()
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(ax, host.box.wine.modules["TB80RTM"])

    def test_system_module_is_its_gate_module(self):
        # Wine returns its builtin USER. neww's USER is its gate module, which has a handle.
        host, ax, _dx = run(b"USER.EXE")
        self.assertTrue(host.stop.startswith("dos exit"), host.stop)
        self.assertEqual(ax, host.box.wine.system_modules["USER"])
        self.assertNotEqual(ax, 0)

    def test_reading_the_module_block_stops(self):
        # mov es, ax ; mov ax, es:[0x0A]
        host, _ax, _dx = run(b"TB80RTM", bytes([0x8E, 0xC0, 0x26, 0xA1, 0x0A, 0x00]))
        self.assertTrue(host.stop.startswith("module database of TB80RTM read at +0xa "), host.stop)
        self.assertTrue(host.stop.endswith("neww has only the handle"), host.stop)


if __name__ == "__main__":
    unittest.main()
