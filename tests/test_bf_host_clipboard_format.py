"""USER.145 RegisterClipboardFormat shares RegisterWindowMessage's atoms.

Wine's RegisterClipboardFormat16 (dlls/user.exe16/user.c) is
RegisterClipboardFormatA, which calls NtUserRegisterWindowMessage
(dlls/user32/clipboard.c): the same string atoms from 0xC000, one per name,
compared without case. AX = 1 gave every format the same number.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

NAME = 0x100


def register(host, ordinal, name):
    host.arena.write(host.data, NAME, name + b"\x00")
    far_call(host, "USER", ordinal, [NAME, host.data], pop=4)
    return host.uc.reg_read(UC_X86_REG_AX)


class RegisterClipboardFormat(unittest.TestCase):
    def test_string_atom(self):
        host = fake_host()
        self.assertGreaterEqual(register(host, 145, b"Native"), 0xC000)
        self.assertEqual(host.ax1, [], "RegisterClipboardFormat fell through to AX = 1")

    def test_different_names_different_formats(self):
        host = fake_host()
        self.assertNotEqual(register(host, 145, b"Native"), register(host, 145, b"OwnerLink"))

    def test_same_table_as_register_window_message(self):
        host = fake_host()
        self.assertEqual(register(host, 118, b"Native"), register(host, 145, b"NATIVE"))


if __name__ == "__main__":
    unittest.main()
