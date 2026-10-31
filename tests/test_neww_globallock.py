"""KERNEL.18 GlobalLock is Wine global.c WIN16_GlobalLock16: (selector, 0) in DX:AX.

Spec: `18 pascal GlobalLock(word) WIN16_GlobalLock16`, pop 2, a long.
K32WOWGlobalLock16 returns MAKESEGPTR(sel, 0), and WIN16_GlobalLock16
puts the selector in CX too. -1 is CURRENT_DS. An invalid handle is
selector 0. neww used to return the handle in AX with DX 0. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


# mov [0x40], ax ; mov [0x42], dx ; mov [0x44], cx
STORE = bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00, 0x89, 0x0E, 0x44, 0x00])


def run(flags=None, handle=None):
    """GlobalAlloc(flags, 0x100) then GlobalLock of it, or GlobalLock(handle)."""
    from tbpipeline_neww.machine import Machine
    code = bytearray()
    fixups = []
    if handle is None:
        code += push(flags) + push(0) + push(0x100)
        fixups.append((3, 1, len(code) + 1, 1, 15))
        # call GlobalAlloc ; mov [0x46], ax ; push ax
        code += neww_ne.call_far() + bytes([0xA3, 0x46, 0x00, 0x50])
    else:
        code += push(handle)
    fixups.append((3, 1, len(code) + 1, 1, 18))
    code += neww_ne.call_far() + STORE
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups)
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, [host.word(ds, o) for o in (0x40, 0x42, 0x44, 0x46)]


class GlobalLock(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[18]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GlobalLock", (2,), 2, "long"))

    def test_moveable_block_is_its_selector(self):
        host, (ax, dx, cx, handle) = run(flags=0x0002)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(handle & 7, 4)
        self.assertEqual((ax, dx, cx), (0, handle & ~7, handle & ~7))
        self.assertEqual(host.box.wine.locks[handle & ~7], 1)

    def test_fixed_block_is_its_selector(self):
        _host, (ax, dx, cx, handle) = run(flags=0x0000)
        self.assertEqual((ax, dx, cx), (0, handle, handle))

    def test_minus_one_is_current_ds(self):
        host, (ax, dx, cx, _) = run(handle=0xFFFF)
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual((ax, dx, cx), (0, ds, ds))

    def test_invalid_handle_is_null(self):
        host, (ax, dx, cx, _) = run(handle=0x7770)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((ax, dx, cx), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
