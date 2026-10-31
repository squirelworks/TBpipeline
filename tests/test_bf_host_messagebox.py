"""Item 27: USER.1 MessageBox stops the run and quotes the box.

The real pass 06 run reached TB80UTL's internal-error box ("A internal
error has occurred in File '%s' line %d ... Press OK to continue") five
times. AX = 1 is IDOK, so the runtime carried on past its own assertion,
failed to open the book, and exited 0. The box is the wall. It is not
answered.
"""

import unittest

from tests.bf_host_fake import fake_host, far_call

TEXT = 0x100
CAPTION = 0x200
MB_OKCANCEL_ICONHAND_SYSTEMMODAL = 0x1011


class MessageBoxStops(unittest.TestCase):
    def call(self):
        host = fake_host()
        host.arena.write(host.data, TEXT, b"A internal error has occurred in File 'Unknown' line 629.\x00")
        host.arena.write(host.data, CAPTION, b"Toolbook\x00")
        stopped = []
        host.uc.emu_stop = lambda: stopped.append(True)
        # MessageBox(hwnd, lpText, lpCaption, uType): uType is the last push.
        far_call(host, "USER", 1, [MB_OKCANCEL_ICONHAND_SYSTEMMODAL, CAPTION, host.data, TEXT, host.data, 0], pop=12)
        return host, stopped

    def test_messagebox_is_not_ax1(self):
        host, _ = self.call()
        self.assertEqual(host.ax1, [], "MessageBox fell through to AX = 1 (IDOK)")

    def test_messagebox_stops_and_quotes(self):
        host, stopped = self.call()
        self.assertTrue(stopped, "the run went on past the box")
        self.assertEqual(
            host.fault,
            "message box 'Toolbook' type 0x1011: "
            "\"A internal error has occurred in File 'Unknown' line 629.\"",
        )


if __name__ == "__main__":
    unittest.main()
