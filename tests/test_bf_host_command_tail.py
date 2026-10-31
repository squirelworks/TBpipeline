"""Item 24: the book path in the PSP command tail at 0x80.

The tail is read back out of guest memory. A guest read of it is
recorded. A real run, with TBK_BIN, says whether the entry ever read it
before it exited, and does not pretend the book was requested if not.
"""

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unicorn.x86_const import UC_X86_REG_AX

from tests.binpath import bin_or_skip
from tests.bf_host_fake import fake_host, run_guest


class CommandTail(unittest.TestCase):
    def test_tail_is_in_guest_memory(self):
        host = fake_host()
        host.book = "/tmp/somewhere/fixture.tbk"
        psp = host._make_psp()
        length = host.arena.read(psp, 0x80, 1)[0]
        tail = host.arena.read(psp, 0x81, length + 1)
        self.assertEqual(tail, b" fixture.tbk\r")
        self.assertEqual(length, len(" fixture.tbk"))

    def test_guest_read_of_tail_is_recorded(self):
        host = fake_host()
        psp = host._make_psp()
        # mov ax, psp ; mov es, ax ; mov al, es:[0x81]
        code = bytes([0xB8, psp & 0xFF, psp >> 8, 0x8E, 0xC0, 0x26, 0xA0, 0x81, 0x00])
        run_guest(host, code)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX) & 0xFF, ord(" "))
        self.assertEqual([r[2] for r in host.tail_reads], [0x81])

    def test_untouched_tail_records_nothing(self):
        host = fake_host()
        host._make_psp()
        run_guest(host, bytes([0x90]))
        self.assertEqual(host.tail_reads, [])


class CommandTailStartup(unittest.TestCase):
    """Pass 06 to its stop. Skips without TBK_BIN."""

    def test_entry_reads_the_tail(self):
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80RCR.DLL", "TB80LNL.DLL",
                           "TB80OLE.DLL", "TB80UTL.DLL", "TB80W16.DLL")
        import tbpipeline_bf.nedllhost.pass06 as pass06
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "fixture.tbk"
            book.write_bytes(b"\x00" * 0xC00 + struct.pack("<I", 0x22222222))
            with mock.patch.dict(os.environ, {"TBK_UNPACKED": str(root)}), \
                    mock.patch.object(pass06, "UNPACKED", str(root)):
                host = pass06.Pass06(str(root / "TB80RTM.EXE"), str(book))
                host.run()
        reads = ", ".join(f"{cs:#x}:{ip:#x} +{off:#x}" for cs, ip, off in host.tail_reads)
        print(f"\ncommand tail reads: {reads or 'none'}; stop {host.fault}")
        self.assertTrue(host.tail_reads, "the entry never read PSP:0x80; the book was not requested")


if __name__ == "__main__":
    unittest.main()
