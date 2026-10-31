"""Item 60. GlobalAlloc takes the dword size, as Wine's GlobalAlloc16 does. No binary needed."""

import tempfile
import unittest

from tests import neww_ne


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def alloc_then(flags, size, after=b""):
    """GlobalAlloc(flags, size), then `after`, then KERNEL.999 to stop with registers intact."""
    from tbpipeline_neww.machine import Machine
    code = bytearray(push(flags) + push(size >> 16) + push(size & 0xFFFF))
    fixups = [(3, 1, len(code) + 1, 1, 15)]
    code += neww_ne.call_far()
    code += after
    fixups.append((3, 1, len(code) + 1, 1, 999))
    code += neww_ne.call_far()
    d = tempfile.mkdtemp()
    neww_ne.exit_program_with(d, bytes(code), fixups)
    return Machine(d).run()


class GlobalAllocDword(unittest.TestCase):
    def test_size_over_64k_keeps_the_high_word(self):
        host = alloc_then(0, 0x12345)
        self.assertIn("KERNEL.999", host.stop)
        (handle, (sel, size, flags)), = host.box.wine.heap.items()
        self.assertEqual((handle, size, flags), (sel, 0x12360, 0))
        first = host.box.selectors[sel]
        second = host.box.selectors[sel + 8]
        self.assertEqual(second.base, first.base + 0x10000)
        self.assertEqual(len(second.data), 0x2360)

    def test_guest_writes_through_the_handle(self):
        from unicorn.x86_const import UC_X86_REG_AX
        # mov es, ax ; mov byte es:[2], 0x77 ; mov ax, es
        after = bytes([0x8E, 0xC0, 0x26, 0xC6, 0x06, 0x02, 0x00, 0x77, 0x8C, 0xC0])
        host = alloc_then(0, 0x100, after)
        self.assertIn("KERNEL.999", host.stop)
        sel = host.uc.reg_read(UC_X86_REG_AX)
        seg = host.box.selectors[sel]
        self.assertEqual(host.uc.mem_read(seg.base + 2, 1), b"\x77")

    def test_moveable_handle_is_selector_minus_one(self):
        host = alloc_then(0x0002, 0x40)
        (handle, (sel, size, flags)), = host.box.wine.heap.items()
        self.assertEqual(handle, sel - 1)
        self.assertEqual(size, 0x40)

    def test_size_zero_and_over_1m_stop_by_name(self):
        self.assertIn("KERNEL.15 GlobalAlloc flags=0x0 size 0", alloc_then(0, 0).stop)
        self.assertIn("KERNEL.15 GlobalAlloc size 0x100001", alloc_then(0, 0x100001).stop)


if __name__ == "__main__":
    unittest.main()
