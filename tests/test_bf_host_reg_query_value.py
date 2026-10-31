"""SHELL.6 RegQueryValue with no registry hive behind it.

TBREG.DLL's RegistryGetKey (TBREG.5), which tb80axf.sbk links, reads its
value with SHELL.6. The runtime calls it twice before the WinExec wall.

Wine's RegQueryValue16 (shell.dll16/shell.c) maps the Win16 roots 0 and
1 to HKEY_CLASSES_ROOT, masks *count to 16 bits, and calls
RegQueryValueA (advapi32/registry.c). A name opens that subkey first and
returns RegOpenKeyA's error, which with no hive is ERROR_FILE_NOT_FOUND
(2) under a root. With no name it reads hkey's default value, and a
default that is not there comes back as "" with *count 1 and
ERROR_SUCCESS. A key that is not a root was never opened here:
ERROR_INVALID_HANDLE (6). The spec line is
`6 pascal RegQueryValue(long str ptr ptr) RegQueryValue16`, so it pops 16.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_SP

from tests.bf_host_fake import STACK_TOP, fake_host, far_call

NAME, DATA, COUNT = 0x100, 0x200, 0x300
HKCR = 0x80000000


def query(host, hkey, name, count=0x00010040):
    host.arena.write(host.data, DATA, b"\xAA" * 4)
    host.arena.write(host.data, COUNT, struct.pack("<I", count))
    name_ptr = [0, 0]
    if name is not None:
        host.arena.write(host.data, NAME, name + b"\x00")
        name_ptr = [NAME, host.data]
    words = [COUNT, host.data, DATA, host.data] + name_ptr + [hkey & 0xFFFF, hkey >> 16]
    far_call(host, "SHELL", 6, words, pop=16)
    result = host.uc.reg_read(UC_X86_REG_AX) | (host.uc.reg_read(UC_X86_REG_DX) << 16)
    data = host.arena.read(host.data, DATA, 1)
    count = struct.unpack("<I", host.arena.read(host.data, COUNT, 4))[0]
    return result, data, count


class RegQueryValue(unittest.TestCase):
    def test_default_value_of_a_root(self):
        host = fake_host()
        self.assertEqual(query(host, HKCR, b""), (0, b"\x00", 1))
        self.assertEqual(host.ax1, [], "RegQueryValue fell through to AX = 1")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_SP), STACK_TOP - 4, "16 popped")

    def test_null_name_and_win16_root(self):
        host = fake_host()
        self.assertEqual(query(host, 1, None), (0, b"\x00", 1))

    def test_subkey_not_found(self):
        host = fake_host()
        self.assertEqual(query(host, HKCR, b".tbk"), (2, b"\xAA", 0x40), "count masked, data untouched")

    def test_not_a_root(self):
        host = fake_host()
        self.assertEqual(query(host, 0x1234, b"")[0], 6)


if __name__ == "__main__":
    unittest.main()
