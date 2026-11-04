"""INT 21h GET SYSTEM DATE (2Ah) and TIME (2Ch) read a fixed host_time when a run sets one.

Roadmap #201 T4. Wine 2528aff2 dlls/krnl386.exe16/int21.c answers 2Ah and 2Ch from
GetLocalTime, the host's clock, and neww does the same by default. ToolBook's C runtime
seeds random from that time, so the Logic Families quiz (whose question order comes from
random) differs from run to run. Machine(..., host_time=seconds) fixes the clock the two calls
read, so a click test repeats. The answers stay int21.c's layout: CX year, DH month, DL day,
AL weekday (Sunday 0); CH hour, CL minute, DH second, DL hundredths. No binary needed.
"""

import tempfile
import time
import unittest

from tests.test_neww_batch1_handlers import wine

FIXED = time.mktime((2001, 2, 3, 12, 34, 56, 0, 0, -1))   # a Saturday, local time


def call(w, ax):
    return w.int21(lambda name: {"ax": ax}.get(name, 0))


class HostTime(unittest.TestCase):
    def test_time_reads_the_fixed_clock(self):
        w = wine()
        w.host_time = FIXED + 0.25
        regs, stop = call(w, 0x2C00)
        self.assertIsNone(stop)
        self.assertEqual((regs["cx"], regs["dx"]), (12 << 8 | 34, 56 << 8 | 25))

    def test_date_reads_the_fixed_clock(self):
        w = wine()
        w.host_time = FIXED
        regs, stop = call(w, 0x2A00)
        self.assertIsNone(stop)
        self.assertEqual((regs["cx"], regs["dx"], regs["ax"] & 0xFF), (2001, 2 << 8 | 3, 6))

    def test_two_runs_with_one_host_time_agree(self):
        a, b = wine(), wine()
        a.host_time = b.host_time = FIXED
        self.assertEqual(call(a, 0x2C00), call(b, 0x2C00))

    def test_machine_passes_it_on(self):
        from tests import neww_ne
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, b"", [], modules=("KERNEL",))
            self.assertEqual(Machine(d, host_time=FIXED).box.wine.host_time, FIXED)
            self.assertIsNone(Machine(d).box.wine.host_time)


if __name__ == "__main__":
    unittest.main()
