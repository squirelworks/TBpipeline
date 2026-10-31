"""Item 26: name the call that still refuses the book.

Every run keeps the last Windows call it made: module, ordinal, call
site, the four argument words, and the registers it got back. With
TBK_BIN, pass 06 runs with the cap on and that line is printed.
"""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.binpath import bin_or_skip
from tests.bf_host_fake import fake_host, far_call
from tests.fixtures import book as fixture
from tbpipeline_bf.nehost.pass04 import last_call_line

LINE = re.compile(
    r"^last call (\S+)\.(\d+) from 0x[0-9a-f]{4}:0x[0-9a-f]{4} stack( [0-9a-f]{4}){4} -> "
    r"ax=([0-9a-f]{4}) bx=[0-9a-f]{4} cx=[0-9a-f]{4} dx=([0-9a-f]{4}) "
    r"si=[0-9a-f]{4} di=[0-9a-f]{4} ds=[0-9a-f]{4} es=[0-9a-f]{4}( \(AX = 1 default\))?$"
)


class LastCall(unittest.TestCase):
    def test_none_before_any_call(self):
        self.assertEqual(last_call_line(fake_host().last_call), "last call none")

    def test_named_call_with_registers(self):
        host = fake_host()
        host.arena.write(host.data, 0x100, b"C:\\TOOLBOOK\\TB80.INI\x00")
        far_call(host, "KERNEL", 74, [0, 0x200, host.data, 0x100, host.data], pop=10)
        line = last_call_line(host.last_call)
        m = LINE.match(line)
        self.assertIsNotNone(m, line)
        self.assertEqual((m.group(1), m.group(2), m.group(4)), ("KERNEL", "74", "ffff"))
        self.assertIsNone(m.group(6), "OpenFile is answered, not the AX = 1 default")

    def test_default_is_tagged(self):
        host = fake_host()
        far_call(host, "USER", 300, [9, 8, 7, 6])
        far_call(host, "GDI", 301, [1, 2, 3, 4], ret_ip=0x205)
        line = last_call_line(host.last_call)
        m = LINE.match(line)
        self.assertIsNotNone(m, line)
        self.assertEqual((m.group(1), m.group(2), m.group(4)), ("GDI", "301", "0001"))
        self.assertTrue(line.endswith("(AX = 1 default)"))


class LastCallStartup(unittest.TestCase):
    """Pass 06 with the cap on, to its stop. Skips without TBK_BIN."""

    def test_pass06_names_its_last_call(self):
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80RCR.DLL", "TB80LNL.DLL",
                           "TB80OLE.DLL", "TB80UTL.DLL", "TB80W16.DLL")
        import tbpipeline_bf.nedllhost.pass06 as pass06
        with tempfile.TemporaryDirectory() as tmp:
            book = fixture.write(Path(tmp) / "fixture.tbk")
            with mock.patch.dict(os.environ, {"TBK_UNPACKED": str(root)}), \
                    mock.patch.object(pass06, "UNPACKED", str(root)):
                host = pass06.Pass06(str(root / "TB80RTM.EXE"), str(book))
                host.run()
        line = last_call_line(host.last_call)
        print(f"\n{line}\nstop {host.fault}; book handles "
              f"{[h for h, b in host.files.items() if b is host.book_bytes] or 'none'}")
        self.assertRegex(line, LINE)


if __name__ == "__main__":
    unittest.main()
