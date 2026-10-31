"""USER.118 RegisterWindowMessage gives each message name its own atom.

Wine's RegisterWindowMessageA (dlls/user32/message.c) is GlobalAddAtomA:
string atoms from 0xC000, one per name, compared without case. AX = 1
gave every message the same number, so TB80BAS and TB80NET could not tell
their messages apart.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call

NAME = 0x100


def register(host, name):
    host.arena.write(host.data, NAME, name + b"\x00")
    far_call(host, "USER", 118, [NAME, host.data], pop=4)
    return host.uc.reg_read(UC_X86_REG_AX)


class RegisterWindowMessage(unittest.TestCase):
    def test_string_atom(self):
        host = fake_host()
        atom = register(host, b"TbkNet3TB80")
        self.assertGreaterEqual(atom, 0xC000)
        self.assertEqual(host.ax1, [], "RegisterWindowMessage fell through to AX = 1")

    def test_same_name_without_case_same_atom(self):
        host = fake_host()
        self.assertEqual(register(host, b"TbkNet3TB80"), register(host, b"TBKNET3tb80"))

    def test_different_names_different_atoms(self):
        host = fake_host()
        self.assertNotEqual(register(host, b"TbkNet3TB80"), register(host, b"commdlg_help"))


if __name__ == "__main__":
    unittest.main()
