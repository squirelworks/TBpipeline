"""USER.291 SetWindowsHookEx is Wine user.exe16/hook.c SetWindowsHookEx16.

Spec: `291 pascal SetWindowsHookEx(s_word segptr word word)`, pop 10,
long. Ids outside WH_MSGFILTER..WH_SHELL, and the ones Wine has no
hook_procs entry for, return 0. A second hook of one id returns 0. A
nonzero hTask is compared with the current task, which neww does not
have, so it stops. The HHOOK is neww's own number. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


def push(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def hook_call(id_, task=0):
    # push id ; push seg ; push ofs ; push hInst ; push hTask ; call
    return push(id_) + push(0x1234) + push(0x5678) + push(0x10) + push(task) + neww_ne.call_far()


def run(calls):
    from tbpipeline_neww.machine import Machine
    code = bytearray()
    fixups = []
    for i, (id_, task) in enumerate(calls):
        fixups.append((3, 1, len(code) + 16, 2, 291))
        code += hook_call(id_, task)
        at = 0x40 + 4 * i
        code += bytes([0xA3, at, 0x00, 0x89, 0x16, at + 2, 0x00])
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, bytes(code), fixups, modules=("KERNEL", "USER"))
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, [(host.word(ds, 0x40 + 4 * i), host.word(ds, 0x42 + 4 * i)) for i in range(len(calls))]


class SetWindowsHookEx(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import USER
        row = USER[291]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("SetWindowsHookEx", (2, 4, 2, 2), 10, "long"))

    def test_mouse_hook_then_a_second_one(self):
        host, answers = run([(7, 0), (7, 0), (0, 0), (11, 0)])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(answers, [(0x0001, 0x0001), (0, 0), (0, 0), (0, 0)])
        self.assertEqual(host.box.wine.hooks, {8: (0x00010001, 0x12345678)})

    def test_other_task_is_zero(self):
        # Wine: "setting hook (%d) on other task not supported", 0.
        host, answers = run([(7, 0x99)])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(answers, [(0, 0)])


if __name__ == "__main__":
    unittest.main()
