"""int 2Fh AX = 150Bh, the MSCDEX CD-ROM drive check, finds no MSCDEX.

TB80BAS segment 2 0x56B asks whether drive CX is a CD-ROM. BX = 0xADAD
back means MSCDEX is installed. With nothing on the multiplex, DOS
returns every register as it was, so BX stays 0 and TB80BAS says "not a
CD-ROM". The host had no int 2Fh at all and the run stopped there.
"""

import unittest

from unicorn import UC_HOOK_INTR
from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX

from tests.bf_host_fake import fake_host, run_guest


def drive_check(ax):
    host = fake_host()
    host.uc.hook_add(UC_HOOK_INTR, host._on_intr)
    code = bytes([
        0xB8, ax & 0xFF, ax >> 8,      # mov ax, ax
        0x31, 0xDB,                    # xor bx, bx
        0xB9, 0x03, 0x00,              # mov cx, 3 (drive D:)
        0xCD, 0x2F,                    # int 2Fh
    ])
    run_guest(host, code)
    return host


class MscdexDriveCheck(unittest.TestCase):
    def test_no_mscdex_leaves_the_registers(self):
        host = drive_check(0x150B)
        self.assertEqual(host.fault, "")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_BX), 0, "BX = 0xADAD would claim MSCDEX")
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 0x150B)
        self.assertEqual(host.uc.reg_read(UC_X86_REG_CX), 3)

    def test_other_multiplex_calls_still_stop(self):
        # Only AX = 150Bh is answered. Every other AX stops as before.
        for ax in (0x1500, 0x150A, 0x150C, 0x1600, 0x4300):
            with self.subTest(ax=hex(ax)):
                host = drive_check(ax)
                self.assertEqual(host.fault, "int 0x2f")


if __name__ == "__main__":
    unittest.main()
