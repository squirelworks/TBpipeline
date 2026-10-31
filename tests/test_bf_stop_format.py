"""bf's line for an ordinal it does not know.

bf is allowed to answer an unknown far call with AX = 1. It is not
allowed to do that silently: the log line names the ordinal, and the
module when a reloc named the site. A fake gate, not a DLL.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import far_call, fake_host

ORDINAL = 999


class BfStopFormat(unittest.TestCase):
    def test_named_site(self):
        for module in ("KERNEL", "USER"):
            host = far_call(fake_host(), module, ORDINAL, [1, 2, 3, 4])
            self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1)
            self.assertEqual(host.uc.reg_read(UC_X86_REG_DX), 0)
            self.assertEqual(len(host.ax1), 1)
            self.assertIn(f"{module}.{ORDINAL}", host.ax1[0])

    def test_unnamed_site_still_names_the_ordinal(self):
        host = far_call(fake_host(), None, ORDINAL, [0, 0, 0, 0])
        self.assertEqual(host.uc.reg_read(UC_X86_REG_AX), 1)
        self.assertEqual(len(host.ax1), 1)
        self.assertIn(f".{ORDINAL}", host.ax1[0])

    def test_every_call_is_logged_not_only_the_first(self):
        host = fake_host()
        for _ in range(20):
            far_call(host, "USER", ORDINAL, [0, 0, 0, 0])
        self.assertEqual(len(host.ax1), 20)


if __name__ == "__main__":
    unittest.main()
