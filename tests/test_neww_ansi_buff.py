"""AnsiUpperBuff16 / AnsiLowerBuff16 (user.exe16/user.c:2643): CharUpperBuffA or CharLowerBuffA
over len bytes in place (0 is 65536), answering len."""

import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine


class AnsiBuff(unittest.TestCase):
    def test_upper_and_lower_in_place(self):
        w = window_wine()
        w.memory.write(DATA, 0x300, b"caf\xe9 Xy\x00z")
        ax, _dx, stop, _calls = by_name(w, "USER", "AnsiUpperBuff", (DATA, 0x300), 7)
        self.assertIsNone(stop)
        self.assertEqual(ax, 7)
        # e acute upper-cases to E acute in code page 1252; past len nothing changes.
        self.assertEqual(w.memory.read(DATA, 0x300, 9), b"CAF\xc9 XY\x00z")
        by_name(w, "USER", "AnsiLowerBuff", (DATA, 0x300), 7)
        self.assertEqual(w.memory.read(DATA, 0x300, 9), b"caf\xe9 xy\x00z")



class InvertRect(unittest.TestCase):
    def test_dstinvert_over_the_rectangle(self):
        # InvertRect16 (user.exe16/user.c:775): PatBlt DSTINVERT; void, so AX and DX stay.
        import struct
        from tbpipeline_neww import gdi16
        w = window_wine()
        hdc = gdi16.new_dc(w)
        g = gdi16.gdi(w)
        before = g.screen.getpixel((5, 5))
        w.memory.write(DATA, 0x300, struct.pack("<hhhh", 2, 2, 10, 10))
        ax, dx, stop, _calls = by_name(w, "USER", "InvertRect", hdc, (DATA, 0x300), regs={"ax": 0x1234, "dx": 0x5678})
        self.assertIsNone(stop)
        self.assertEqual((ax, dx), (0x1234, 0x5678))
        self.assertEqual(g.screen.getpixel((5, 5)), tuple(255 - c for c in before))
        self.assertEqual(g.screen.getpixel((10, 10)), before)


if __name__ == "__main__":
    unittest.main()


class TickPolling(unittest.TestCase):
    def test_a_poll_loop_sees_time_pass(self):
        # A program that waits by polling GetTickCount sees neww's clock move 1 ms per call
        # that follows another; anything between leaves it.
        w = window_wine()
        t0 = by_name(w, "USER", "GetTickCount")[0]
        t1 = by_name(w, "USER", "GetTickCount")[0]
        t2 = by_name(w, "USER", "GetTickCount")[0]
        self.assertEqual((t1 - t0, t2 - t1), (1, 1))
        by_name(w, "USER", "GetCursorPos", (DATA, 0x300))
        self.assertEqual(by_name(w, "USER", "GetTickCount")[0], t2)


class IdleDriverInGetMessage(unittest.TestCase):
    def test_input_the_driver_gives_is_taken_at_once(self):
        # The run's idle driver (Machine.on_idle) gives more input while the task waits in
        # GetMessage (a modal loop): GetMessage takes it instead of stopping with no input.
        from tests.test_neww_batch6 import control_wine, top_window
        from tbpipeline_neww import input16
        w = control_wine()
        top_window(w)
        input16.state(w).scripted = True
        fed = []

        def driver(wine):
            if fed:
                return None
            fed.append(1)
            return "move 100,100"
        w.on_idle = driver
        ax, _dx, stop, _calls = by_name(w, "USER", "GetMessage", (DATA, 0x300), 0, 0, 0, reply=lambda c: (1, 0))
        self.assertIsNone(stop)
        self.assertEqual(ax, 1)


class AnsiToOemBuffer(unittest.TestCase):
    def test_len_bytes_converted_and_len_0_does_nothing(self):
        # keyboard.c:177: CharToOemBuffA over len bytes, NULs included; e acute is 0x82 in 437.
        w = window_wine()
        w.memory.write(DATA, 0x300, b"caf\xe9\x00x")
        w.memory.write(DATA, 0x310, b"\xff" * 8)
        _ax, _dx, stop, _c = by_name(w, "KEYBOARD", "AnsiToOemBuff", (DATA, 0x300), (DATA, 0x310), 6,
                                     regs={"ax": 1, "dx": 2})
        self.assertIsNone(stop)
        self.assertEqual(w.memory.read(DATA, 0x310, 7), b"caf\x82\x00x\xff")
        by_name(w, "KEYBOARD", "OemToAnsiBuff", (DATA, 0x310), (DATA, 0x320), 4, regs={"ax": 1, "dx": 2})
        self.assertEqual(w.memory.read(DATA, 0x320, 4), b"caf\xe9")
        w.memory.write(DATA, 0x330, b"\xff")
        by_name(w, "KEYBOARD", "AnsiToOemBuff", (DATA, 0x300), (DATA, 0x330), 0, regs={"ax": 1, "dx": 2})
        self.assertEqual(w.memory.read(DATA, 0x330, 1), b"\xff")

    def test_find_executable_stops_by_name(self):
        w = window_wine()
        w.memory.write(DATA, 0x300, b"C:\\WINDOWS\\TEMP\\A.HTM\x00")
        stop = by_name(w, "SHELL", "FindExecutable", (DATA, 0x300), (0, 0), (DATA, 0x340))[2]
        self.assertIn("FindExecutable('C:\\\\WINDOWS\\\\TEMP\\\\A.HTM', None)", stop)
