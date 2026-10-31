"""USER.57 RegisterClass returns the class atom, and keeps the class.

Wine's RegisterClass16 (dlls/user.exe16/class.c) copies the WNDCLASS16
into a WNDCLASSEX16 and returns RegisterClassEx16's atom. Registering a
name the same instance already has fails with 0
(ERROR_CLASS_ALREADY_EXISTS). Class names and registered window messages
are atoms in USER's one table, so a name gets the same atom from either.
The spec line is `57 pascal -ret16 RegisterClass(ptr) RegisterClass16`,
so it pops 4.

The runtime registers 9 classes before the WinExec wall. AX = 1 gave
every class atom 1.
"""

import struct
import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import far_call, fake_host

WC = 0x40
NAME = 0x80


def wndclass(host, name, inst, proc=(0x1234, 0x0010)):
    host.arena.write(host.data, NAME, name.encode() + b"\x00")
    wc = struct.pack("<HHHHHHHHHHHHH", 3, proc[1], proc[0], 0, 4, inst, 0, 0, 6, 0, 0, NAME, host.data)
    host.arena.write(host.data, WC, wc)


def register(host):
    far_call(host, "USER", 57, [WC, host.data], pop=4)
    return host.uc.reg_read(UC_X86_REG_AX)


class RegisterClass(unittest.TestCase):
    def test_returns_an_atom_and_keeps_the_procedure(self):
        host = fake_host()
        wndclass(host, "TBKMain", 0x468)
        atom = register(host)
        self.assertGreaterEqual(atom, 0xC000, "a class atom is a string atom")
        self.assertEqual(host.ax1, [], "RegisterClass fell through to AX = 1")
        cls = host.classes[("tbkmain", 0x468)]
        self.assertEqual(cls["proc"], (0x1234, 0x0010))
        self.assertEqual(cls["wnd_extra"], 4)

    def test_two_classes_get_two_atoms(self):
        host = fake_host()
        wndclass(host, "TBKMain", 0x468)
        first = register(host)
        wndclass(host, "TBKClient", 0x468)
        self.assertNotEqual(register(host), first)

    def test_the_same_name_again_for_the_same_instance_fails(self):
        host = fake_host()
        wndclass(host, "TBKMain", 0x468)
        register(host)
        wndclass(host, "tbkmain", 0x468)
        self.assertEqual(register(host), 0)

    def test_a_class_name_shares_the_registered_message_atom(self):
        host = fake_host()
        host.arena.write(host.data, 0x100, b"TBKMain\x00")
        far_call(host, "USER", 118, [0x100, host.data], pop=4)
        message = host.uc.reg_read(UC_X86_REG_AX)
        wndclass(host, "TBKMain", 0x468)
        self.assertEqual(register(host), message)


if __name__ == "__main__":
    unittest.main()
