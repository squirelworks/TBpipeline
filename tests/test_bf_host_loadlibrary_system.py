"""Item 27: LoadLibrary("KERNEL") returns KERNEL's handle.

TB80W16 segment 8 0x7C0 loads KERNEL to look up the generic thunk calls.
A module Windows already has loaded is found, not read from disk, so the
host returning 2 (file not found) sent TB80W16 into its error report,
which asked for KERNEL again: 2,778 calls to the instruction cap. There is
no file behind the handle, so it has no exports and GetProcAddress on it
returns 0.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call

NAME = 0x100


def load(host, name):
    host.arena.write(host.data, NAME, name + b"\x00")
    far_call(host, "KERNEL", 95, [NAME, host.data], pop=4)
    return host.uc.reg_read(UC_X86_REG_AX)


class SystemModule(unittest.TestCase):
    def test_kernel_has_a_handle(self):
        host = fake_host()
        handle = load(host, b"KERNEL")
        self.assertGreaterEqual(handle, 32, "LoadLibrary failed for a module Windows has loaded")
        self.assertEqual(load(host, b"kernel.exe"), handle, "a second load is the same module")
        self.assertNotEqual(load(host, b"USER"), handle)
        self.assertEqual(host.ax1, [])

    def test_it_exports_nothing(self):
        host = fake_host()
        handle = load(host, b"KERNEL")
        # GetProcAddress(handle, MAKEINTRESOURCE(513)), LoadLibraryEx32W.
        far_call(host, "KERNEL", 50, [513, 0, handle], pop=6)
        self.assertEqual((host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)), (0, 0))

    def test_a_missing_dll_is_still_file_not_found(self):
        host = fake_host()
        self.assertEqual(load(host, b"NOSUCH.DLL"), 2)


if __name__ == "__main__":
    unittest.main()
