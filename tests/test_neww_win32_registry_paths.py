"""Win32 calls TB80F32L's file and registry helpers make (#227, group C): RegOpenKeyA,
RegOpenKeyExA and RegCloseKey (Wine 2528aff2 advapi32/registry.c:154, kernelbase/registry.c:688),
and GetShortPathNameA (kernelbase/file.c:2233, kernel32/path.c:76). INST80.SBK and an uploaded
NIDA course stopped on them."""

import struct
import unittest
from pathlib import Path

HKCU, HKLM = 0x80000001, 0x80000002


class Calls(unittest.TestCase):
    def setUp(self):
        from tests.test_neww_win32 import Kernel32
        from tbpipeline_neww.win32 import WIN32
        self.w = Kernel32().wine()
        self.call = lambda module, name, *a: WIN32[(module, name)](self.w, *a)

    def put(self, addr, raw):
        self.w.write_linear(addr, raw)
        return addr

    def dword(self, addr):
        return struct.unpack("<I", self.w.read_linear(addr, 4))[0]


class Registry(Calls):
    def test_a_key_an_empty_prefix_lacks_is_file_not_found(self):
        name = self.put(0x1000, b"Software\\Asymetrix\\ToolBook\0")
        self.assertEqual(self.call("ADVAPI32", "RegOpenKeyA", HKCU, name, 0x1100), 2)

    def test_no_name_is_the_key_itself(self):
        self.assertEqual(self.call("ADVAPI32", "RegOpenKeyA", HKLM, 0, 0x1100), 0)
        self.assertEqual(self.dword(0x1100), HKLM)

    def test_no_out_pointer_is_invalid_parameter(self):
        self.assertEqual(self.call("ADVAPI32", "RegOpenKeyA", HKCU, self.put(0x1000, b"X\0"), 0), 87)

    def test_hkey_0_is_not_classes_root_from_32_bits(self):
        self.assertEqual(self.call("ADVAPI32", "RegOpenKeyExA", 0, self.put(0x1000, b"X\0"), 0, 0, 0x1100), 6)

    def test_a_key_shell_made_opens_and_closes(self):
        # One registry: what SHELL.2 RegCreateKey made from 16 bits, advapi32 opens.
        from tbpipeline_neww.shell16 import _reg
        reg = _reg(self.w)
        reg.walk(reg.key(HKCU), "Software\\NIDA", create=True)
        self.assertEqual(self.call("ADVAPI32", "RegOpenKeyA", HKCU, self.put(0x1000, b"software\\nida\0"), 0x1100), 0)
        handle = self.dword(0x1100)
        self.assertEqual(self.call("ADVAPI32", "RegCloseKey", handle), 0)
        self.assertEqual(self.call("ADVAPI32", "RegCloseKey", handle), 6)
        self.assertEqual(self.call("ADVAPI32", "RegCloseKey", HKCU), 0)


class ShortPath(Calls):
    def setUp(self):
        super().setUp()
        Path(self.w.root, "tb80anm.sbk").write_bytes(b"")
        Path(self.w.root, "Preventing_Fraud.tbk").write_bytes(b"")

    def short(self, path, size=0x105):
        n = self.call("KERNEL32", "GetShortPathNameA", self.put(0x1000, path + b"\0"), 0x1200, size)
        return n, self.w.read_linear(0x1200, n) if n and n < size else None

    def test_an_8_3_name_is_itself_as_the_disk_has_it(self):
        self.assertEqual(self.short(b"C:\\TBK\\TB80ANM.SBK"), (18, b"C:\\TBK\\tb80anm.sbk"))

    def test_a_long_name_is_its_alias(self):
        self.assertEqual(self.short(b"C:\\TBK\\Preventing_Fraud.tbk"), (19, b"C:\\TBK\\PREVEN~1.TBK"))

    def test_a_missing_file_is_file_not_found(self):
        self.assertEqual(self.short(b"C:\\TBK\\NONE.TBK")[0], 0)
        self.assertEqual(self.w.w32.last_error, 2)

    def test_too_small_is_the_size_needed(self):
        self.assertEqual(self.short(b"C:\\TBK\\tb80anm.sbk", size=5), (19, None))

    def test_wildcards_are_invalid_name(self):
        self.assertEqual(self.short(b"C:\\TBK\\*.SBK")[0], 0)
        self.assertEqual(self.w.w32.last_error, 123)


if __name__ == "__main__":
    unittest.main()
