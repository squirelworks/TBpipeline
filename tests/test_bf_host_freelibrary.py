"""KERNEL.96 FreeLibrary returns nothing, and a system module stays loaded.

TB80W16 frees the KERNEL handle it got from LoadLibrary("KERNEL") after
looking up the generic thunks. Wine's FreeLibrary16 (krnl386.exe16/
ne_module.c) is void: it calls FreeModule16, which only drops a usage
count while other users remain, and KERNEL always has them. The call fell
through to AX = 1, which named it as an unanswered call.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

NAME = 0x100


def load(host, name):
    host.arena.write(host.data, NAME, name + b"\x00")
    far_call(host, "KERNEL", 95, [NAME, host.data], pop=4)
    return host.uc.reg_read(UC_X86_REG_AX)


class FreeLibrary(unittest.TestCase):
    def test_free_a_system_module(self):
        host = fake_host()
        kernel = load(host, b"KERNEL")
        far_call(host, "KERNEL", 96, [kernel], pop=2)
        self.assertEqual(host.ax1, [], "FreeLibrary fell through to AX = 1")
        self.assertEqual(load(host, b"KERNEL"), kernel, "KERNEL is still loaded")


if __name__ == "__main__":
    unittest.main()
