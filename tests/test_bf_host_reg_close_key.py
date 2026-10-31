"""SHELL.3 RegCloseKey with no registry hive behind it.

TBREG.DLL's RegistryGetKey (TBREG.5), which tb80axf.sbk links, closes
its key with SHELL.3.

Wine's RegCloseKey16 (shell.dll16/shell.c) maps the Win16 roots 0 and 1
to HKEY_CLASSES_ROOT and calls RegCloseKey (kernelbase/registry.c): a
predefined key, 0x80000000 and up, is ERROR_SUCCESS without a close, and
any other key goes to NtClose. This host hands out no other key (SHELL.1
only ever gives back a root), so that is ERROR_INVALID_HANDLE (6). The
result is a DWORD in DX:AX. The spec line is
`3 pascal RegCloseKey(long) RegCloseKey16`, so it pops 4.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call


def close_key(host, hkey):
    far_call(host, "SHELL", 3, [hkey & 0xFFFF, hkey >> 16], pop=4)
    return host.uc.reg_read(UC_X86_REG_AX) | (host.uc.reg_read(UC_X86_REG_DX) << 16)


class RegCloseKey(unittest.TestCase):
    def test_root(self):
        host = fake_host()
        self.assertEqual(close_key(host, 0x80000002), 0)
        self.assertEqual(host.ax1, [], "RegCloseKey fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4, "4 popped")

    def test_win16_roots(self):
        host = fake_host()
        self.assertEqual(close_key(host, 0), 0)
        self.assertEqual(close_key(host, 1), 0)

    def test_not_a_root(self):
        host = fake_host()
        self.assertEqual(close_key(host, 0x1234), 6)


if __name__ == "__main__":
    unittest.main()
