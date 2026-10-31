"""KERNEL.36 GetCurrentTask is Wine task.c WIN16_GetCurrentTask.

Spec: `36 pascal GetCurrentTask() WIN16_GetCurrentTask`, pop 0, a long:
the current task in AX and hFirstTask in DX. The task handle is
TASK_Create's GlobalAlloc16(GMEM_FIXED, sizeof(TDB)), 0x200 bytes.
The exe's task is linked after the main task at the same priority, so
TASK_LinkTask puts it first. neww makes the block but not the TDB in it,
so reading it stops. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS

# call ; mov [0x40], ax ; mov [0x42], dx
AFTER = neww_ne.call_far() + bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00])


def run(after=b""):
    from tbpipeline_neww.machine import Machine
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, AFTER + after, [(3, 1, 1, 1, 36)])
        host = Machine(d).run(limit=5000)
    ds = host.uc.reg_read(UC_X86_REG_DS)
    return host, host.word(ds, 0x40), host.word(ds, 0x42)


class GetCurrentTask(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[36]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("GetCurrentTask", (), 0, "long"))

    def test_task_and_first_task(self):
        host, ax, dx = run()
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertNotEqual(ax, 0)
        self.assertEqual((ax, dx), (host.box.wine.htask, host.box.wine.htask))
        self.assertEqual(host.box.selectors[ax].base & 0xFFF, 0)
        self.assertEqual(len(host.box.selectors[ax].data), 0x200)

    def test_reading_the_task_database_stops(self):
        # mov es, ax ; mov ax, es:[0x1E]
        host, _ax, _dx = run(bytes([0x8E, 0xC0, 0x26, 0xA1, 0x1E, 0x00]))
        self.assertTrue(host.stop.startswith("task database read at +0x1e "), host.stop)
        self.assertTrue(host.stop.endswith("neww has only the handle"), host.stop)


if __name__ == "__main__":
    unittest.main()
