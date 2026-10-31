"""A moveable block's handle loads as its selector, as in Wine.

Wine's moveable handle is the selector - 1: the same LDT entry at RPL 2,
so Win16 code can put the handle in DS or ES. TB80LNL calls
LocalInit(handle, ...) and then loads the handle into DS. neww's handle
used to be selector - 1 in the GDT, which set the table bit with no LDT
behind it, and the load faulted. Now the handle is the selector with the
table bit set, and every GDT entry has a copy in the LDT. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run(after):
    from tbpipeline_neww.machine import Machine
    # GlobalAlloc(GMEM_MOVEABLE, 0x100) ; after ; KERNEL.999 stops
    code = bytearray(push(0x0002) + push(0) + push(0x100))
    fixups = [(3, 1, len(code) + 1, 1, 15)]
    code += neww_ne.call_far() + after
    fixups.append((3, 1, len(code) + 1, 1, 999))
    code += neww_ne.call_far()
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups)
        return Machine(d).run(limit=5000)


class MoveableHandle(unittest.TestCase):
    def test_handle_in_es_writes_the_block(self):
        # mov es, ax ; mov byte es:[2], 0x77
        host = run(bytes([0x8E, 0xC0, 0x26, 0xC6, 0x06, 0x02, 0x00, 0x77]))
        self.assertIn("KERNEL.999", host.stop)
        (handle, (sel, _size, _flags)), = host.box.wine.heap.items()
        self.assertEqual(host.uc.mem_read(host.box.selectors[sel].base + 2, 1), b"\x77")

    def test_handle_in_ds_and_ss(self):
        # mov dx, ss ; mov ds, ax ; mov byte [3], 0x55 ; mov ss, ax ; mov ss, dx
        host = run(bytes([0x8C, 0xD2, 0x8E, 0xD8, 0xC6, 0x06, 0x03, 0x00, 0x55, 0x8E, 0xD0, 0x8E, 0xD2]))
        self.assertIn("KERNEL.999", host.stop)
        (_handle, (sel, _size, _flags)), = host.box.wine.heap.items()
        self.assertEqual(host.uc.mem_read(host.box.selectors[sel].base + 3, 1), b"\x55")


if __name__ == "__main__":
    unittest.main()
