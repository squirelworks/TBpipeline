"""Item 38: the instruction caps stay. Pass 04 is 2,000,000 and 20 s.
Pass 06 is 4,000,000 and 30 s.

run() is called on a fake host with build() skipped, and the arguments
it hands to emu_start are read, so the test checks the numbers the CPU
gets, not a comment.
"""

import unittest
from unittest import mock

from tbpipeline_bf.nedllhost.pass06 import Pass06
from tbpipeline_bf.nehost.pass04 import Pass04
from tests.bf_host_fake import fake_host


def caps(cls):
    host = fake_host(cls)
    host.stack_top = 0x4000
    host.segs[2] = host.code
    host.dll_ready = set()
    seen = {}

    def emu_start(begin, until, timeout=0, count=0):
        seen.update(timeout=timeout, count=count)

    with mock.patch.object(cls, "build", lambda self: None):
        host.uc.emu_start = emu_start
        host.run()
    return seen


class Caps(unittest.TestCase):
    def test_pass04(self):
        self.assertEqual(caps(Pass04), {"count": 2_000_000, "timeout": 20_000_000})

    def test_pass06(self):
        self.assertEqual(caps(Pass06), {"count": 4_000_000, "timeout": 30_000_000})


if __name__ == "__main__":
    unittest.main()
