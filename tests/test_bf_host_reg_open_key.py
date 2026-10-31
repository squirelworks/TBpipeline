"""SHELL.1 RegOpenKey with no registry hive behind it.

TBREG.DLL's RegistryGetKey (TBREG.5), which tb80axf.sbk links in
AXF_AbleToExport, opens its key with SHELL.1. The runtime calls it once
before the WinExec wall.

Wine's RegOpenKey16 (shell.dll16/shell.c) maps the Win16 roots 0 and 1 to
HKEY_CLASSES_ROOT and calls RegOpenKeyA (advapi32/registry.c): a null
retkey is ERROR_INVALID_PARAMETER (87), a null or empty name gives back
hkey with ERROR_SUCCESS, and otherwise RegOpenKeyExA's open_key clears
*retkey first. This host has no hive, so a named subkey of a root is
ERROR_FILE_NOT_FOUND (2), and a key that is not a root is
ERROR_INVALID_HANDLE (6). The result is a DWORD in DX:AX. The spec line
is `1 pascal RegOpenKey(long str ptr) RegOpenKey16`, so it pops 12.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call

NAME, RET = 0x100, 0x200
HKCR, HKLM = 0x80000000, 0x80000002


def open_key(host, hkey, name, ret=True):
    host.arena.write(host.data, RET, b"\xAA" * 4)
    name_ptr = [0, 0]
    if name is not None:
        host.arena.write(host.data, NAME, name + b"\x00")
        name_ptr = [NAME, host.data]
    ret_ptr = [RET, host.data] if ret else [0, 0]
    far_call(host, "SHELL", 1, ret_ptr + name_ptr + [hkey & 0xFFFF, hkey >> 16], pop=12)
    result = host.uc.reg_read(UC_X86_REG_AX) | (host.uc.reg_read(UC_X86_REG_DX) << 16)
    return result, struct.unpack("<I", host.arena.read(host.data, RET, 4))[0]


class RegOpenKey(unittest.TestCase):
    def test_subkey_not_found(self):
        host = fake_host()
        self.assertEqual(open_key(host, HKLM, b"Software\\Asymetrix"), (2, 0))
        self.assertEqual(host.ax1, [], "RegOpenKey fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4, "12 popped")

    def test_empty_name_is_the_key(self):
        host = fake_host()
        self.assertEqual(open_key(host, HKLM, b""), (0, HKLM))
        self.assertEqual(open_key(host, HKLM, None), (0, HKLM))

    def test_win16_root(self):
        host = fake_host()
        self.assertEqual(open_key(host, 1, b""), (0, HKCR))
        self.assertEqual(open_key(host, 0, b".tbk"), (2, 0))

    def test_not_a_root(self):
        host = fake_host()
        self.assertEqual(open_key(host, 0x1234, b"x"), (6, 0))

    def test_no_retkey(self):
        host = fake_host()
        self.assertEqual(open_key(host, HKLM, b"x", ret=False)[0], 87)


if __name__ == "__main__":
    unittest.main()
