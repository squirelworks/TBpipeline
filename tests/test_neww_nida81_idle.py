"""Roadmap #201 T2: a run with no input script ends on the named idle stop after its first
idle tick.

Without --input, nida81 draws P0 and then only waits for timers: TB80RTM's PeekMessage loop
and TB80NET's 1000 ms timer, and the call limit used to land somewhere inside that loop (20,001
calls at --cap 20000). With the idle stop that the command line asks for, the run ends by name
at the first idle point after the first timer tick. TB80RTM sends the book FirstIdle and Idle
after the message its multimedia timer callback posts, so that tick runs the book's idle
handler first: Logic Families draws "Click to continue." there. Needs TBK_BIN and TBK_BOOK
(nida81.tbk) or TBK_BOOK2 (Logic Families).
"""

import contextlib
import io
import os
import unittest
from unittest import mock


def _book(name):
    path = os.environ.get(name)
    if not path:
        raise unittest.SkipTest(f"{name} is not set")
    return path


class NoInputIdle(unittest.TestCase):
    def _command_line(self, book, cap):
        """python3 -m tbpipeline_neww --b BIN --c BOOK --cap CAP, with the host it ran kept.

        The wall-clock cap is raised so a loaded machine does not end the run on time."""
        from tests.binpath import bin_or_skip
        from tbpipeline_neww import machine
        from tbpipeline_neww.__main__ import main
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        hosts = []

        class Kept(machine.Machine):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                hosts.append(self)

        out = io.StringIO()
        with mock.patch.object(machine, "Machine", Kept), mock.patch.object(machine, "TIMEOUT_US", 10 ** 10), \
                contextlib.redirect_stdout(out):
            main(["--b", str(root), "--c", book, "--cap", str(cap)])
        text = out.getvalue()
        print("\n" + "\n".join(line for line in text.splitlines() if "stopped" in line or "calls " in line))
        host, = hosts
        stopped = next(line for line in text.splitlines() if line.startswith("  stopped "))
        self.assertIn("idle: no input script, TB80RTM waiting in PeekMessage", stopped)
        self.assertLess(host.calls, cap)
        self.assertNotIn("MessageBox", text)
        self.assertEqual(host.box.wine.messageboxes, [])
        return host.box.wine.trace

    def test_nida81_ends_idle_with_p0_drawn_and_its_first_idle_run(self):
        trace = self._command_line(_book("TBK_BOOK"), 20000)
        self.assertIn("GDI.33 TextOut 'P0'", trace)
        names = [t.split("'")[1] for t in trace if t.startswith("KERNEL.88 lstrcpy '")]
        self.assertIn("FirstIdle", names)

    def test_logic_families_0_clicks_ends_idle_with_click_to_continue_drawn(self):
        trace = self._command_line(_book("TBK_BOOK2"), 300000)
        self.assertTrue(any("'Click to continue." in t and t.startswith("GDI.") for t in trace),
                        [t for t in trace if "Click to" in t][:4])


if __name__ == "__main__":
    unittest.main()
