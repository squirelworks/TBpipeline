"""KERNEL.131 GetDOSEnvironment returns a far pointer to an environment block.

Wine's GetDOSEnvironment16 (krnl386.exe16/task.c) copies the environment
strings, ending in an empty string, then the WORD 1 and the program name
"C:\\WINDOWS\\SYSTEM\\KRNL386.EXE", into one fixed block, and returns it as a
SEGPTR. This host gives the guest no variables. TB80RTM and its DLLs call it
from their C start-up; the AX = 1 default handed them 0000:0001.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call

PROGRAM = b"C:\\WINDOWS\\SYSTEM\\KRNL386.EXE\x00"


def environment(host):
    far_call(host, "KERNEL", 131, [], pop=0)
    return host.uc.reg_read(UC_X86_REG_DX), host.uc.reg_read(UC_X86_REG_AX)


class GetDOSEnvironment(unittest.TestCase):
    def test_block_layout(self):
        host = fake_host()
        seg, off = environment(host)
        self.assertNotEqual(seg, 0)
        size = 3 + len(PROGRAM)
        block = bytes(host.arena.read(seg, off, size))
        self.assertEqual(block[0], 0, "no variables: the block starts with its terminator")
        self.assertEqual(struct.unpack_from("<H", block, 1)[0], 1)
        self.assertEqual(block[3:], PROGRAM)
        self.assertEqual(host.ax1, [], "GetDOSEnvironment fell through to AX = 1")

    def test_same_block_every_call(self):
        host = fake_host()
        self.assertEqual(environment(host), environment(host))


if __name__ == "__main__":
    unittest.main()
