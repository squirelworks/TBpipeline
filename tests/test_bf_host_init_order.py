"""Item 30: the DLL entry order stays RCR, LNL, OLE, W16, UTL, BAS.

A change to pass06.INIT_ORDER fails here unless WHY.md says the new order
in the same change. The startup blob is also built from a fake host and
the far calls in it are read back, so the order the CPU sees is checked,
not only the list.
"""

import re
import struct
import unittest
from pathlib import Path

from tbpipeline_bf.nedllhost import pass06
from tests.bf_host_fake import fake_host

ORDER = ["TB80RCR", "TB80LNL", "TB80OLE", "TB80W16", "TB80UTL", "TB80BAS"]
WHY = Path(pass06.__file__).resolve().parent.parent / "WHY.md"


def fake_dll(ip, seg, heap):
    blob = bytearray(0x80)
    struct.pack_into("<H", blob, 0x3C, 0x40)
    struct.pack_into("<H", blob, 0x40 + 0x10, heap)
    struct.pack_into("<HH", blob, 0x40 + 0x14, ip, seg)
    return bytes(blob)


class InitOrder(unittest.TestCase):
    def test_list(self):
        self.assertEqual(pass06.INIT_ORDER, ORDER)

    def test_why_names_the_same_order(self):
        text = WHY.read_text(encoding="utf-8")
        short = ", ".join(name[4:] for name in pass06.INIT_ORDER[:-1]) + ", then " + pass06.INIT_ORDER[-1][4:]
        self.assertIn(short, text, "INIT_ORDER changed without the order in WHY.md")

    def test_startup_calls_entries_in_that_order(self):
        host = fake_host()
        host.stack_top = 0x4000
        host.dlls, host.dll_segs, host.dll_group = {}, {}, {}
        # Mark them ready in reverse, so the blob's order comes from INIT_ORDER.
        host.dll_ready = set()
        sels = {}
        for n, name in enumerate(reversed(ORDER)):
            sel = 0x100 + 8 * n
            sels[sel] = name
            host.dlls[name] = ({}, fake_dll(0x10 + n, 1, 0x200))
            host.dll_segs[(name, 1)] = sel
            host.dll_group[name] = sel
            host.dll_ready.add(name)
        blob = host._startup(host.data, 0x200)
        calls = [m.start() for m in re.finditer(rb"\x9a", blob)]
        seen = [sels[struct.unpack_from("<H", blob, at + 3)[0]] for at in calls]
        self.assertEqual(seen, ORDER)
        self.assertEqual(blob[-5:], bytes([0xEA, 0x5A, 0x03, 0x00, 0x02]))


if __name__ == "__main__":
    unittest.main()
