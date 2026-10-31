"""USER.118 RegisterWindowMessage returns a string atom, the same for the same name.

Spec: user.exe16.spec `118 pascal -ret16 RegisterWindowMessage(str)
RegisterWindowMessageA`, pop 4. The atom is 0xC000 or above; names are
compared without case. Wine's number depends on its session's atom
table. neww's starts empty at 0xC000. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def call(name_at):
    # push ds ; push name_at ; call RegisterWindowMessage
    return bytes([0x1E, 0x68, name_at & 0xFF, name_at >> 8]) + neww_ne.call_far()


class RegisterWindowMessage(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import USER
        row = USER[118]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("RegisterWindowMessage", (4,), 4, "word"))

    def test_same_name_same_atom(self):
        from tbpipeline_neww.machine import Machine
        data = bytearray(256)
        data[0x80:0x80 + 8] = b"asymhelp"
        data[0x90:0x90 + 8] = b"ASYMHELP"
        data[0xA0:0xA0 + 5] = b"other"
        code = bytearray()
        fixups = []
        for i, at in enumerate((0x80, 0x90, 0xA0)):
            fixups.append((3, 1, len(code) + 5, 2, 118))
            code += call(at) + bytes([0xA3, 0x40 + 2 * i, 0x00])
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, bytes(code), fixups, modules=("KERNEL", "USER"), data=bytes(data))
            host = Machine(d).run(limit=5000)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual([host.word(ds, 0x40 + 2 * i) for i in range(3)], [0xC000, 0xC000, 0xC001])

    def test_empty_name_is_zero(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine(".")._register_window_message(""), 0)


if __name__ == "__main__":
    unittest.main()
