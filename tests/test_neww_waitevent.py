"""Item 58. WaitEvent follows Wine's WaitEvent16. No binary needed."""

import tempfile
import unittest

from tests import neww_ne


def push_word(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run_calls(tasks):
    """One WaitEvent(task) per entry, then the DOS exit."""
    from tbpipeline_neww.machine import Machine
    code = bytearray()
    fixups = []
    for task in tasks:
        code += push_word(task)
        fixups.append((3, 1, len(code) + 1, 1, 30))
        code += neww_ne.call_far()
    d = tempfile.mkdtemp()
    neww_ne.exit_program_with(d, bytes(code), fixups)
    return Machine(d).run()


class WaitEventContract(unittest.TestCase):
    def test_row(self):
        from tbpipeline_neww.wine import KERNEL
        row = KERNEL[30]
        self.assertEqual((row.name, row.args, row.ret), ("WaitEvent", (2,), "word"))

    def test_first_wait_takes_the_posted_event(self):
        host = run_calls([0])
        self.assertEqual(host.stop, "dos exit 0x0")

    def test_second_wait_would_block(self):
        host = run_calls([0, 0])
        self.assertEqual(host.stop, "KERNEL.30 WaitEvent would block: no event is posted and there is no other task")

    def test_named_task_stops(self):
        host = run_calls([0x1234])
        self.assertEqual(host.stop, "KERNEL.30 WaitEvent hTask=0x1234: neww has no task handle to match it")
        self.assertEqual(host.box.wine.events, 1)


if __name__ == "__main__":
    unittest.main()
