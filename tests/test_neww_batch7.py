"""Batch 7: what the real run needed to get from the drawn title page to the idle loop with the
system book open.

Each test checks against the Wine function its docstring or comment names. No ToolBook bytes:
the NE files are built by tests/neww_ne.py, and handlers run on fake memory
(tests/test_neww_batch2.py's harness).
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne
from tests.test_neww_batch1_handlers import DATA, NUL
from tests.test_neww_batch2 import by_name, window_wine
from tests.test_neww_tasks import Asm

KERNEL, USER, MMSYSTEM, TOOLHELP = 1, 2, 3, 4
GET_CURRENT_TASK, SET_TIMER, GET_MESSAGE = 36, 10, 108
TIME_SET_EVENT, TASK_FIND_HANDLE = 602, 65


def build(directory, code, modules=("KERNEL", "USER", "MMSYSTEM", "TOOLHELP"), data=None):
    blob = neww_ne.build("TB80RTM", [(0x0000, bytes(code.code), code.fixups),
                                     (0x0001, bytes(data or bytearray(0x200)), [])],
                         modules=modules, entry=(1, 0), auto=2, stack=0x400)
    neww_ne.write(directory, "TB80RTM.EXE", blob)


def run(code, limit=200_000):
    from tbpipeline_neww.machine import Machine
    with tempfile.TemporaryDirectory() as d:
        build(d, code)
        host = Machine(d)
        host.run(limit=limit)
    return host


def dgroup(host):
    return host.box.exe.segments[1].selector


# ---------------------------------------------------------------- the system book

class SystemBook(unittest.TestCase):
    """The book from --c answers only for a .tbk path; tb80r.sbk is its own file in --b."""

    def setUp(self):
        from tbpipeline_neww.wine import Wine
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "TB80R.SBK").write_bytes(b"sys")
        self.book = self.dir / "nida81.tbk"
        self.book.write_bytes(b"book")
        self.w = Wine(str(self.dir))
        self.w.book = self.book

    def test_tbk_is_the_book_whatever_its_directory(self):
        self.assertEqual(self.w.resolve("D:\\ELSEWHERE\\NIDA81.TBK"), self.book)

    def test_sbk_is_looked_up_by_name_without_case(self):
        self.assertEqual(self.w.resolve("C:\\TBK\\tb80r.sbk"), self.dir / "TB80R.SBK")

    def test_missing_sbk_is_not_the_book(self):
        self.assertIsNone(self.w.resolve("C:\\TBK\\other.sbk"))


# ---------------------------------------------------------------- the FPU emulator

class FpuEmulatorInterrupts(unittest.TestCase):
    """krnl386 fpu.c FPU_ModifyCode: INT 34h-3Bh becomes FWAIT + D8h..DFh, INT 3Dh FWAIT + NOP."""

    def run_code(self, raw):
        from tbpipeline_neww.machine import Machine
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, raw, [])
            host = Machine(d)
            host.run(limit=5000)
        return host

    def code_bytes(self, host, count):
        cs = host.box.exe.segments[0].selector
        return bytes(host.word(cs, i) & 0xFF for i in range(count))

    def test_int_3d_becomes_fwait_nop_and_runs(self):
        host = self.run_code(bytes([0xCD, 0x3D]))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(self.code_bytes(host, 2), bytes([0x9B, 0x90]))

    def test_int_35_becomes_the_d9_opcode(self):
        # INT 35h, then C0h: FWAIT; FLD ST(0). The modrm byte after the INT stays.
        host = self.run_code(bytes([0xCD, 0x35, 0xC0]))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(self.code_bytes(host, 3), bytes([0x9B, 0xD9, 0xC0]))

    def test_patched_code_runs_twice_without_another_interrupt(self):
        # A loop over the same INT: the second pass runs the patched bytes.
        # mov cx, 2 ; top: int 3dh ; loop top
        host = self.run_code(bytes([0xB9, 0x02, 0x00, 0xCD, 0x3D, 0xE2, 0xFC]))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(self.code_bytes(host, 7)[3:5], bytes([0x9B, 0x90]))


# ---------------------------------------------------------------- TOOLHELP and module names

class TaskFindHandle(unittest.TestCase):
    """toolhelp.c TaskFindHandle16 -> TaskNext16: TASKENTRY from the TDB and instance data."""

    def test_current_task_entry(self):
        code = Asm().call(KERNEL, GET_CURRENT_TASK).store("ax", 0x40)
        code.push_ds().push(0x100).emit(0xFF, 0x36, 0x40, 0x00).call(TOOLHELP, TASK_FIND_HANDLE)
        code.store("ax", 0x42).exit(0)
        host = run(code)
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = dgroup(host)
        w = lambda off: host.word(ds, off)
        self.assertEqual(w(0x42), 1)
        entry = 0x100
        self.assertEqual(w(entry + 4), w(0x40))          # hTask
        self.assertEqual(w(entry + 6), 0)                # hParent: the first task has none
        self.assertEqual(w(entry + 8), ds)               # hInst
        self.assertEqual(w(entry + 10), host.box.wine.modules["TB80RTM"])
        name = bytes(w(entry + 0x1A + i) & 0xFF for i in range(10))
        self.assertEqual(name, b"TB80RTM\0\0\0")
        self.assertEqual(w(entry + 0x24), 0x100)         # wPSPOffset
        self.assertEqual(w(entry + 0x26), 0)             # hNext: no other task

    def test_unknown_task_is_false(self):
        code = Asm().push_ds().push(0x100).push(0x7770).call(TOOLHELP, TASK_FIND_HANDLE)
        code.store("ax", 0x42).exit(0)
        host = run(code)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(host.word(dgroup(host), 0x42), 0)


class GateModuleFileName(unittest.TestCase):
    """ne_module.c GetModuleFileName16 of a builtin loaded by import: its base name, "NAME.DLL"."""

    def test_mmsystem_is_its_dll_name(self):
        w = window_wine()
        # The machine gives each imported builtin a gate module handle of its own.
        handle = w.system_modules["MMSYSTEM"] = 0x1EF8
        ax, _dx, stop, _ = by_name(w, "KERNEL", "GetModuleFileName", handle, (DATA, 0x80), 0x40)
        self.assertIsNone(stop)
        self.assertEqual(w.memory.read(DATA, 0x80, ax + 1), b"MMSYSTEM.DLL\0")

    def test_kernel_stops(self):
        w = window_wine()
        handle = w.system_modules["KERNEL"] = 0x1EA8
        stop = by_name(w, "KERNEL", "GetModuleFileName", handle, (DATA, 0x80), 0x40)[2]
        self.assertIn("GetModuleFileName(KERNEL)", stop)


# ---------------------------------------------------------------- MMSYSTEM timers

class TimerCalls(unittest.TestCase):
    """mmsystem.c time*16 -> winmm time.c."""

    def setUp(self):
        self.w = window_wine()
        self.w.ss = DATA

    def call(self, name, *a):
        return by_name(self.w, "MMSYSTEM", name, *a)

    def test_dev_caps(self):
        self.assertEqual(self.call("timeGetDevCaps", (DATA, 0x80), 4)[0], 0)
        self.assertEqual(struct.unpack("<HH", self.w.memory.read(DATA, 0x80, 4)), (1, 65535))
        self.assertEqual(self.call("timeGetDevCaps", NUL, 4)[0], 11)

    def test_period_limits(self):
        self.assertEqual(self.call("timeBeginPeriod", 0)[0], 97)
        self.assertEqual(self.call("timeBeginPeriod", 1)[0], 0)
        self.assertEqual(self.call("timeEndPeriod", 1)[0], 0)

    def test_set_event_ids_are_16_times_created_plus_slot(self):
        func = (0x0120, 0x10)
        first = self.call("timeSetEvent", 10, 1, func, (0, 0), 0)[0]
        second = self.call("timeSetEvent", 10, 1, func, (0, 0), 0)[0]
        self.assertEqual((first, second), (16 * 1 + 0, 16 * 2 + 1))
        # timeKillEvent frees slot 0; the next timer takes it with the next count.
        self.assertEqual(self.call("timeKillEvent", first)[0], 0)
        self.assertEqual(self.call("timeKillEvent", first)[0], 97)
        self.assertEqual(self.call("timeSetEvent", 10, 1, func, (0, 0), 0)[0], 16 * 3 + 0)

    def test_set_event_delay_out_of_range_is_zero(self):
        self.assertEqual(self.call("timeSetEvent", 0, 1, (0x0120, 0x10), (0, 0), 0)[0], 0)

    def test_win32_event_callback_stops(self):
        stop = self.call("timeSetEvent", 10, 1, (0x0120, 0x10), (0, 0), 0x10)[2]
        self.assertIn("Win32 event", stop)

    def test_callback_due_one_shot_frees_its_slot(self):
        from tbpipeline_neww.mmsystem16 import callback_due
        from tbpipeline_neww.user_wnd import wm
        ident = self.call("timeSetEvent", 10, 1, (0x0120, 0x10), (0x1234, 0x5678), 0)[0]
        self.assertIsNone(callback_due(self.w, waiting=False))
        calls = callback_due(self.w, waiting=True)
        self.assertEqual(wm(self.w).clock, 10)
        self.assertTrue(calls.retry)
        call = calls.calls[0]
        self.assertEqual((call.cs, call.ip), (0x0120, 0x10))
        # timeCB3216: id, uMsg 0, dwUser, dw1 0, dw2 0, first argument first.
        self.assertEqual(call.words, [ident, 0, 0x1234, 0x5678, 0, 0, 0, 0])
        calls.finish([(0, 0)])
        self.assertIsNone(callback_due(self.w, waiting=True))

    def test_periodic_timer_moves_on_by_its_delay(self):
        from tbpipeline_neww.mmsystem16 import callback_due, earliest
        self.call("timeSetEvent", 25, 1, (0x0120, 0x10), (0, 0), 1)
        callback_due(self.w, waiting=True).finish([(0, 0)])
        self.assertEqual(earliest(self.w).due, 50)

    def test_window_timer_first_waits_for_it(self):
        from tbpipeline_neww.mmsystem16 import callback_due
        by_name(self.w, "USER", "SetTimer", 0, 1, 20, (0, 0))
        self.call("timeSetEvent", 30, 1, (0x0120, 0x10), (0, 0), 0)
        self.assertIsNone(callback_due(self.w, waiting=True))


class TimerCallbackRuns(unittest.TestCase):
    """The callback runs while GetMessage waits, then GetMessage looks again with its own
    arguments and gets the window timer that comes later."""

    def program(self, flags=0):
        def make(cb):
            code = Asm()
            code.push(10).push(1).emit(0x0E).push(cb).push(0x1234).push(0x5678).push(flags)
            code.call(MMSYSTEM, TIME_SET_EVENT).store("ax", 0x40)
            code.push(0).push(1).push(50).push(0).push(0).call(USER, SET_TIMER)
            code.push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE)
            code.store("ax", 0x42).exit(0)
            return code
        cb = len(make(0).code)
        code = make(cb)
        # The callback: inc word [0x50] ; retf 16
        code.emit(0xFF, 0x06, 0x50, 0x00, 0xCA, 0x10, 0x00)
        return code

    def test_one_shot(self):
        host = run(self.program())
        self.assertEqual(host.stop, "dos exit 0x0")
        ds = dgroup(host)
        self.assertEqual(host.word(ds, 0x40), 16)
        self.assertEqual(host.word(ds, 0x50), 1)
        # GetMessage ran again and got WM_TIMER into the buffer its arguments name.
        self.assertEqual(host.word(ds, 0x42), 1)
        self.assertEqual(host.word(ds, 0x82), 0x113)
        trace = host.box.wine.trace
        self.assertEqual(sum(1 for t in trace if t.startswith("USER.108 GetMessage")), 2)
        self.assertTrue(any(t.startswith("  mm timer 0x10 ->") for t in trace))

    def test_periodic_fires_until_the_window_timer(self):
        # Due at 10, 20, 30, 40 and 50; the window timer is due at 50 and comes first then.
        host = run(self.program(flags=1))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(host.word(dgroup(host), 0x50), 4)
        self.assertEqual(host.word(dgroup(host), 0x82), 0x113)


# ---------------------------------------------------------------- the real book

class RealBook(unittest.TestCase):
    def test_system_book_opens_and_the_page_idles(self):
        # TBK_BIN and TBK_BOOK: tb80r.sbk is its own file, the timer services start, and the
        # startup messages reach Idle.
        import os
        from tests.binpath import bin_or_skip
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "tb80r.sbk")
        book = os.environ.get("TBK_BOOK")
        if not book:
            raise unittest.SkipTest("TBK_BOOK is not set")
        from tbpipeline_neww.machine import Machine
        host = Machine(str(root), book)
        host.call_limit = 25000
        host.run(limit=25000 * 1000)
        trace = host.box.wine.trace
        print(f"\nneww stop: {host.stop} after {len(trace)} trace lines")
        self.assertTrue(any(t.startswith("  OpenFile ") and "tb80r.sbk' -> " in t and t.endswith(" tb80r.sbk")
                            for t in trace))
        self.assertFalse(any("timer services" in t for t in trace))
        self.assertTrue(any(t.startswith("  mm timer ") for t in trace))
        names = [t.split("'")[1] for t in trace if t.startswith("KERNEL.88 lstrcpy '")]
        order = ["EnterBook", "EnterWindow", "EnterBackground", "EnterPage", "FirstIdle", "Idle"]
        at = [names.index(n) for n in order]
        self.assertEqual(at, sorted(at), list(zip(order, at)))
        self.assertFalse(any("Cannot load DLL \"MMSystem" in t or "Cannot load DLL MMSystem" in t for t in trace))


if __name__ == "__main__":
    unittest.main()
