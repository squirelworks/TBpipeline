"""KERNEL.20 GlobalSize is Wine global.c GlobalSize16, the arena's size in DX:AX.

Spec: `20 pascal GlobalSize(word) GlobalSize16`, pop 2, a long. Handle 0
and an invalid handle are 0. GET_ARENA_PTR finds the arena from the
selector, so a moveable block's handle and selector both work.
GLOBAL_Alloc rounds the size up to 32 bytes. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(flags, size, which="handle"):
    """GlobalAlloc(flags, size), then GlobalSize of its handle, its selector, or a given word."""
    from tbpipeline_neww.machine import Machine
    code = bytearray(push(flags) + push(size >> 16) + push(size & 0xFFFF))
    fixups = [(3, 1, len(code) + 1, 1, 15)]
    code += neww_ne.call_far()
    if which == "handle":
        code += bytes([0x50])  # push ax
    elif which == "selector":
        code += bytes([0x40, 0x50])  # inc ax ; push ax
    else:
        code += push(which)
    fixups.append((3, 1, len(code) + 1, 1, 20))
    # call GlobalSize ; mov [0x40], ax ; mov [0x42], dx
    code += neww_ne.call_far() + bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups)
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, host.word(ds, 0x40) | (host.word(ds, 0x42) << 16)


class GlobalSize(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[20]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GlobalSize", (2,), 2, "long"))

    def test_rounded_to_32(self):
        host, size = run(0x0002, 0x101)
        self.assertEqual((host.stop, size), ("dos exit 0x0", 0x120))

    def test_moveable_selector_finds_the_arena(self):
        _host, size = run(0x0002, 0x40, which="selector")
        self.assertEqual(size, 0x40)

    def test_over_64k_is_the_whole_block(self):
        _host, size = run(0x0000, 0x18000)
        self.assertEqual(size, 0x18000)

    def test_zero_and_invalid_are_zero(self):
        for word in (0, 0x7770):
            host, size = run(0x0002, 0x40, which=word)
            self.assertEqual((host.stop, size), ("dos exit 0x0", 0), word)


if __name__ == "__main__":
    unittest.main()
