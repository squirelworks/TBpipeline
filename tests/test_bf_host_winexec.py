"""Item 27: KERNEL.166 WinExec is the wall, and the run stops on it.

TB80BAS seg 45 0x50 starts the book file manager with
WinExec("TB80NET.exe ToolBook", SW_SHOWMINIMIZED) and then waits for that
task to call back into TB80BAS (seg 45 0x68) with its window. AX = 1 is an
error code, so the runtime said "Failed initializing the book file
manager". A second Win16 task is not something this host runs, so the call
is a stop that quotes the command line, not an answer.
"""

import unittest

from tests.bf_host_fake import fake_host, far_call

CMD = 0x100


class WinExecWall(unittest.TestCase):
    def test_winexec_stops_and_quotes(self):
        host = fake_host()
        host.arena.write(host.data, CMD, b"TB80NET.exe ToolBook\x00")
        stopped = []
        host.uc.emu_stop = lambda: stopped.append(True)
        far_call(host, "KERNEL", 166, [2, CMD, host.data], pop=6)
        self.assertTrue(stopped, "the run went on past WinExec")
        self.assertEqual(host.ax1, [], "WinExec fell through to AX = 1")
        self.assertEqual(host.fault, "winexec 'TB80NET.exe ToolBook' show 2")


if __name__ == "__main__":
    unittest.main()
