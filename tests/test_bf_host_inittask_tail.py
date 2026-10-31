"""Item 27: InitTask hands WinMain an ASCIIZ command line.

The fake PSP's tail ends in a carriage return, the way DOS lays it down.
TB80RTM's C startup passes ES:BX from InitTask straight to WinMain, and its
book-name parser (00c0:13f6) stops only at space, tab or NUL. With the CR
still there the runtime opened 'fixture.tbk\\r' and said "Not a valid file
name." Windows' InitTask terminates the tail with a NUL.
"""

import unittest

from tests.bf_host_fake import fake_host, far_call
from tbpipeline_bf.nehost.pass04 import INITTASK


class InitTaskTail(unittest.TestCase):
    def test_tail_is_asciiz_after_inittask(self):
        host = fake_host()
        host.book = "/somewhere/fixture.tbk"
        host._make_psp()
        host.startup = 0
        far_call(host, "KERNEL", INITTASK, [], pop=0)
        tail = host.arena.read(host.psp, 0x80, 0x20)
        self.assertEqual(tail[0], len(b" fixture.tbk"))
        self.assertEqual(tail[1:].split(b"\x00", 1)[0], b" fixture.tbk")
        self.assertNotIn(b"\r", tail)

    def test_psp_before_inittask_is_still_dos_shaped(self):
        host = fake_host()
        host.book = "fixture.tbk"
        host._make_psp()
        self.assertEqual(host.arena.read(host.psp, 0x81, 13), b" fixture.tbk\r")


if __name__ == "__main__":
    unittest.main()
