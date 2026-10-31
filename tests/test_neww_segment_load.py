"""A segment register a contract sets is loaded by the guest, not written by Unicorn.

Unicorn's register write for ES or DS in 16-bit mode keeps the old
descriptor base, so InitTask's ES = PSP pointed the guest at the wrong
memory: ES:[0] read 0, not Wine's int 20h. A register contract's stub
now ends in a tail that loads ES and DS from two words the gate fills.
No binary needed.
"""

import tempfile
import unittest

from tests import test_neww_inittask as inittask
from unicorn.x86_const import UC_X86_REG_DS

# mov ax, es:[0] ; mov [0x30], ax ; mov ax, ds ; mov [0x32], ax
READ_ES = bytes([0x26, 0xA1, 0x00, 0x00, 0xA3, 0x30, 0x00, 0x8C, 0xD8, 0xA3, 0x32, 0x00])


class SegmentLoad(unittest.TestCase):
    def test_es_from_inittask_reads_the_psp(self):
        from tbpipeline_neww.machine import Machine
        saved = inittask.AFTER
        inittask.AFTER = saved + READ_ES
        try:
            with tempfile.TemporaryDirectory() as d:
                inittask.program(d)
                host = Machine(d).run(limit=5000)
        finally:
            inittask.AFTER = saved
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.word(ds, 0x30), 0x20CD)
        # DS is not set by InitTask, so the tail loads it back unchanged.
        self.assertEqual(host.word(ds, 0x32), ds)

    def test_register_stub_jumps_to_its_tail(self):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            inittask.program(d)
            host = Machine(d)
        gate = host.box.images["KERNEL"].segments[0].data
        stub = gate[91 * 8:92 * 8]
        self.assertEqual(stub[:6], bytes([0xBA, 91, 0, 0xE6, 0xE4, 0xE9]))
        slot = host.box.slots[("KERNEL", 91)]
        tail = slot - 13
        self.assertEqual(91 * 8 + 8 + int.from_bytes(stub[6:8], "little"), tail)
        self.assertEqual(gate[tail:tail + 13], bytes([
            0x2E, 0x8E, 0x06, slot & 0xFF, slot >> 8, 0x2E, 0x8E, 0x1E, (slot + 2) & 0xFF, (slot + 2) >> 8,
            0xCA, 0, 0,
        ]))


if __name__ == "__main__":
    unittest.main()
