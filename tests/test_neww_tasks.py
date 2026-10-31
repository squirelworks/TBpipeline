"""Batch 3: a second task. WinExec starts an executable, and the two tasks share the CPU.

Each test checks against the Wine function its docstring names: ne_module.c WinExec16,
LoadModule16, NE_CreateThread and NE_StartTask, task.c Yield16, DirectedYield16, WaitEvent16
and PostEvent16, and USER's GetMessage, PeekMessage and SendMessage across tasks. The NE files
are built by tests/neww_ne.py. No ToolBook bytes.
"""

import struct
import tempfile
import unittest

from tests import neww_ne

KERNEL, USER = 1, 2
WINEXEC, YIELD, DOS3CALL, DIRECTED_YIELD, WAIT_EVENT, POST_EVENT = 166, 29, 102, 150, 30, 31
REGISTER_CLASS, CREATE_WINDOW, GET_MESSAGE, SEND_MESSAGE, DEF_WINDOW_PROC = 57, 41, 108, 111, 107
PEEK_MESSAGE, SET_TIMER, POST_MESSAGE = 109, 10, 110


class Asm:
    """Code and its fixups, for one segment."""

    def __init__(self):
        self.code = bytearray()
        self.fixups = []

    def emit(self, *raw):
        self.code += bytes(raw)
        return self

    def push(self, value):
        return self.emit(0x68, value & 0xFF, (value >> 8) & 0xFF)

    def push_ds(self):
        return self.emit(0x1E)

    def mov_ax(self, value):
        return self.emit(0xB8, value & 0xFF, (value >> 8) & 0xFF)

    def store(self, reg, addr):
        """mov [addr], reg for ax bx cx dx si di sp, and es ds ss."""
        lo, hi = addr & 0xFF, addr >> 8
        if reg == "ax":
            return self.emit(0xA3, lo, hi)
        if reg in ("es", "ds", "ss"):
            return self.emit(0x8C, {"es": 0x06, "ss": 0x16, "ds": 0x1E}[reg], lo, hi)
        modrm = {"cx": 0x0E, "dx": 0x16, "bx": 0x1E, "sp": 0x26, "si": 0x36, "di": 0x3E}[reg]
        return self.emit(0x89, modrm, lo, hi)

    def inc(self, addr):
        return self.emit(0xFF, 0x06, addr & 0xFF, addr >> 8)

    def call(self, module, ordinal):
        self.fixups.append((3, 1, len(self.code) + 1, module, ordinal))
        self.code += neww_ne.call_far()
        return self

    def jmp_far(self, module, ordinal):
        self.fixups.append((3, 1, len(self.code) + 1, module, ordinal))
        self.code += bytes([0xEA, 0xFF, 0xFF, 0x00, 0x00])
        return self

    def exit(self, code):
        return self.mov_ax(0x4C00 | code).call(KERNEL, DOS3CALL).emit(0xF4)


def exe(directory, filename, name, code, data, data_fixups=(), stack=0x400):
    blob = neww_ne.build(
        name, [(0x0000, bytes(code.code), code.fixups), (0x0001, bytes(data), list(data_fixups))],
        modules=("KERNEL", "USER"), entry=(1, 0), auto=2, stack=stack)
    return neww_ne.write(directory, filename, blob)


def data_with(size, strings):
    raw = bytearray(size)
    for off, text in strings.items():
        raw[off:off + len(text) + 1] = text.encode("latin1") + b"\x00"
    return raw


def win_exec(code, at=0x10, show=1):
    """WinExec(DS:at, show)."""
    return code.push_ds().push(at).push(show).call(KERNEL, WINEXEC)


def run(parent, child, child_data=None, child_fixups=(), parent_data=None):
    from tbpipeline_neww.machine import Machine
    with tempfile.TemporaryDirectory() as d:
        exe(d, "TB80RTM.EXE", "TB80RTM", parent, parent_data or data_with(0x100, {0x10: "CHILD.EXE hello"}))
        if child is not None:
            exe(d, "CHILD.EXE", "CHILD", child, child_data or bytearray(0x100), child_fixups)
        host = Machine(d)
        host.run(limit=200_000)
    return host


def word(host, sel, off):
    return host.word(sel, off)


def tasks_in(host):
    return [line for line in host.box.wine.trace if line.startswith("-- task")]


class WinExecParsing(unittest.TestCase):
    """WinExec16's split of the string into the file name and the command line."""

    def test_name_and_arguments(self):
        from tbpipeline_neww.tasks import parse_win_exec
        self.assertEqual(parse_win_exec("TB80NET.exe ToolBook"), ("TB80NET.exe", "ToolBook"))

    def test_no_arguments(self):
        from tbpipeline_neww.tasks import parse_win_exec
        self.assertEqual(parse_win_exec("APP.EXE"), ("APP.EXE", ""))

    def test_quoted_name(self):
        from tbpipeline_neww.tasks import parse_win_exec
        self.assertEqual(parse_win_exec('"MY APP.EXE" a b'), ("MY APP.EXE", "a b"))

    def test_quoted_name_without_arguments(self):
        from tbpipeline_neww.tasks import parse_win_exec
        self.assertEqual(parse_win_exec('"APP.EXE"'), ("APP.EXE", ""))


class Spawn(unittest.TestCase):
    """LoadModule16 -> NE_CreateThread: the child runs first, with NE_StartTask's registers."""

    def child_that_records(self):
        child = Asm()
        for i, name in enumerate(("ax", "bx", "cx", "si", "di", "es", "ds", "ss", "sp")):
            child.store(name, 0x20 + 2 * i)
        return child

    def missing(self, line):
        parent = win_exec(Asm()).store("ax", 0x40).exit(0)
        host = run(parent, None, parent_data=data_with(0x100, {0x10: line}))
        self.assertEqual(len(host.box.wine.tasks), 1)
        return host

    def test_missing_bare_name_stops_at_winoldap(self):
        # WinExec16: no path, the 16-bit builtin fails, and 21 sends the string to winoldap.mod.
        # neww has no winoldap task, so it stops by name instead of answering for one.
        host = self.missing("CHILD.EXE hello")
        self.assertEqual(host.stop, "KERNEL.166 WinExec('CHILD.EXE hello'): CHILD.EXE is not in --b, and "
                                    "WinExec16 would start winoldap.mod to run it as a 32-bit program, which neww does not have")

    def test_missing_name_with_a_path_is_error_2(self):
        for line in ("C:\\TBK\\CHILD.EXE hello", "sub/CHILD.EXE"):
            host = self.missing(line)
            self.assertEqual(host.stop, "dos exit 0x0")
            self.assertEqual(word(host, host.box.exe.segments[1].selector, 0x40), 2)

    def test_contains_path(self):
        from tbpipeline_neww.tasks import contains_path
        self.assertEqual([contains_path(n) for n in ("A.EXE", "C:A.EXE", "a\\b", "a/b", "")],
                         [False, True, True, True, False])

    def test_child_runs_with_ne_start_task_registers(self):
        parent = win_exec(Asm()).store("ax", 0x40).exit(0)
        child = self.child_that_records().exit(9)
        host = run(parent, child)
        self.assertEqual(host.stop, "dos exit 0x0")
        wine = host.box.wine
        kid = wine.tasks[1]
        image = host.box.images["CHILD"]
        dgroup = image.segments[1]
        regs = [word(host, dgroup.selector, 0x20 + 2 * i) for i in range(9)]
        ax, bx, cx, si, di, es, ds, ss, sp = regs
        self.assertEqual((ax, bx, cx, si), (0, image.stack, image.heap, 0))
        self.assertEqual(di, kid.instance)
        self.assertEqual(es, kid.task["psp"])
        self.assertEqual((ds, ss), (dgroup.selector, dgroup.selector))
        self.assertEqual(sp, image.segments[1].minsize + image.stack)

    def test_child_command_line_is_what_follows_the_name(self):
        parent = win_exec(Asm()).exit(0)
        child = Asm().exit(9)
        host = run(parent, child)
        psp = host.box.wine.tasks[1].task["psp"]
        raw = bytes(word(host, psp, 0x80 + i) & 0xFF for i in range(7))
        self.assertEqual(raw, b"\x05hello\x00")

    def test_child_that_ends_first_gives_its_exit_code(self):
        # LoadModule16: DirectedYield16 returns with the thread gone, and the answer is its exit code.
        parent = win_exec(Asm()).store("ax", 0x40).exit(0)
        host = run(parent, Asm().exit(9))
        dgroup = host.box.exe.segments[1].selector
        self.assertEqual(word(host, dgroup, 0x40), 9)
        self.assertFalse(host.box.wine.tasks[1].alive)
        self.assertEqual(tasks_in(host), ["-- task CHILD %#x" % host.box.wine.tasks[1].htask,
                                          "-- task CHILD %#x exits 0x9" % host.box.wine.tasks[1].htask,
                                          "-- task TB80RTM %#x" % host.box.wine.tasks[0].htask])

    def test_child_that_waits_gives_its_instance(self):
        # The child waits in GetMessage with nothing to get: the parent runs, and WinExec answers
        # the child's hInstance, which NE_StartTask set before the child's first instruction.
        parent = win_exec(Asm()).store("ax", 0x40).exit(0)
        child = Asm().push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE).exit(9)
        host = run(parent, child)
        self.assertEqual(host.stop, "dos exit 0x0")
        dgroup = host.box.exe.segments[1].selector
        kid = host.box.wine.tasks[1]
        self.assertEqual(word(host, dgroup, 0x40), kid.instance)
        self.assertEqual(kid.instance, host.box.images["CHILD"].segments[1].selector)
        self.assertTrue(kid.alive)
        self.assertEqual(kid.wait, "message")

    def test_first_task_is_hfirsttask_until_the_child_is_linked(self):
        parent = win_exec(Asm()).exit(0)
        host = run(parent, Asm().push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE).exit(9))
        wine = host.box.wine
        self.assertEqual(wine.first_task, wine.tasks[1].htask)

    def test_child_module_handle_is_listed_and_counted(self):
        parent = win_exec(Asm()).exit(0)
        host = run(parent, Asm().push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE).exit(9))
        wine = host.box.wine
        module = wine.modules["CHILD"]
        self.assertEqual(wine.first_module, module)
        self.assertEqual(wine.usage[module], 1)

    def test_second_instance_stops(self):
        parent = win_exec(Asm())
        win_exec(parent).exit(0)
        host = run(parent, Asm().push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE).exit(9))
        self.assertEqual(host.stop, "KERNEL.166 WinExec('CHILD.EXE hello'): CHILD is already running: "
                                    "LoadModule16 would make a second instance (NE_CreateInstance), which neww does not do")


class Yielding(unittest.TestCase):
    """task.c Yield16 and DirectedYield16: the other task runs, then the caller goes on."""

    def test_yield_goes_to_the_other_task_and_back(self):
        parent = win_exec(Asm()).inc(0x50).call(KERNEL, YIELD).inc(0x50).exit(0)
        child = Asm().inc(0x50).call(KERNEL, YIELD).inc(0x50).exit(3)
        host = run(parent, child)
        self.assertEqual(host.stop, "dos exit 0x0")
        wine = host.box.wine
        names = [line.split()[2] for line in tasks_in(host)]
        # Child starts; its Yield lets the parent finish WinExec; the parent's Yield lets the child
        # end; the parent resumes.
        self.assertEqual(names, ["CHILD", "TB80RTM", "CHILD", "CHILD", "TB80RTM"])
        self.assertEqual(word(host, host.box.images["CHILD"].segments[1].selector, 0x50), 2)
        self.assertEqual(word(host, host.box.exe.segments[1].selector, 0x50), 2)
        self.assertEqual(wine.tasks[1].exit, 3)

    def test_yield_alone_returns_at_once(self):
        host = run(Asm().call(KERNEL, YIELD).exit(0), None)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(tasks_in(host), [])

    def test_directed_yield_to_no_task_returns(self):
        host = run(Asm().push(0x1234).call(KERNEL, DIRECTED_YIELD).exit(0), None)
        self.assertEqual(host.stop, "dos exit 0x0")


class Events(unittest.TestCase):
    """task.c WaitEvent16 and PostEvent16."""

    def test_wait_sleeps_until_the_other_task_posts(self):
        # The child waits for an event; the parent posts one and yields; the child wakes with TRUE.
        parent = win_exec(Asm()).store("ax", 0x40)
        # GetCurrentTask's DX is hFirstTask, the child; push dx ; PostEvent.
        parent.call(KERNEL, 36).emit(0x52).call(KERNEL, POST_EVENT).call(KERNEL, YIELD).exit(0)
        child = Asm().push(0).call(KERNEL, WAIT_EVENT).store("ax", 0x60)  # takes the posted one: FALSE
        child.push(0).call(KERNEL, WAIT_EVENT).store("ax", 0x62).exit(4)  # waits: TRUE
        host = run(parent, child)
        self.assertEqual(host.stop, "dos exit 0x0")
        kid = host.box.images["CHILD"].segments[1].selector
        self.assertEqual((word(host, kid, 0x60), word(host, kid, 0x62)), (0, 1))
        self.assertEqual(host.box.wine.tasks[1].exit, 4)

    def test_wait_with_no_other_task_stops(self):
        host = run(Asm().push(0).call(KERNEL, WAIT_EVENT).push(0).call(KERNEL, WAIT_EVENT).exit(0), None)
        self.assertEqual(host.stop, "KERNEL.30 WaitEvent would block: no event is posted and no other task can run to post one")


def window_child(proc_body):
    """A child that registers a class whose procedure is proc_body (then DefWindowProc), creates a
    window, and waits in GetMessage. Returns (code, data, data fixups)."""
    code = Asm()
    code.store("di", 0x08 + 8)                     # wc.hInstance = DI, the instance
    code.push_ds().push(0x08).call(USER, REGISTER_CLASS)
    code.push_ds().push(0x40)                       # class name
    code.push(0).push(0)                            # window name: NULL
    code.push(0).push(0)                            # style 0
    for value in (0, 0, 200, 100):
        code.push(value)                            # x y cx cy
    code.push(0).push(0).emit(0x57)                 # parent, menu, push di (instance)
    code.push(0).push(0)                            # param
    code.call(USER, CREATE_WINDOW).store("ax", 0x70)
    loop = len(code.code)
    code.push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE)
    code.emit(0x09, 0xC0, 0x74, 0x02)               # or ax, ax ; jz exit
    back = loop - (len(code.code) + 2)
    code.emit(0xEB, back & 0xFF)
    code.exit(5)
    proc = len(code.code)
    code.emit(0x55, 0x89, 0xE5)                     # push bp ; mov bp, sp
    proc_body(code)
    code.emit(0x5D)                                 # pop bp
    code.jmp_far(USER, DEF_WINDOW_PROC)
    data = data_with(0x100, {0x40: "Kid"})
    # WNDCLASS16 at 0x08: style, lpfnWndProc, cbClsExtra, cbWndExtra, hInstance, hIcon, hCursor,
    # hbrBackground, lpszMenuName, lpszClassName.
    data[0x08:0x08 + 26] = struct.pack("<HIhhHHHHII", 0, 0xFFFF, 0, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into("<H", data, 0x08 + 22, 0x40)
    # Internal fixups: the procedure's far pointer, and the class name's segment (DGROUP).
    fixups = [(3, 0, 0x08 + 2, 1, proc), (2, 0, 0x08 + 24, 2, 0)]
    return code, data, fixups


def answer_0x400(code):
    # cmp word [bp+0Ch], 400h ; jne def ; mov ax, [bp+0Ah] ; shl ax, 1 ; inc ax ; mov dx, ss ;
    # pop bp ; retf 0Ah
    code.emit(0x81, 0x7E, 0x0C, 0x00, 0x04, 0x75, 0x0C)
    code.emit(0x8B, 0x46, 0x0A, 0xD1, 0xE0, 0x40, 0x8C, 0xD2, 0x5D, 0xCA, 0x0A, 0x00)


class SentMessages(unittest.TestCase):
    """SendMessage16 to another task's window runs its procedure in that task, on its stack."""

    def run_send(self, wp=5):
        parent = win_exec(Asm()).store("ax", 0x40)
        # SendMessage(0x22, 0x400, wp, 0L): the child's window is the first after the desktop.
        parent.push(0x22).push(0x400).push(wp).push(0).push(0).call(USER, SEND_MESSAGE)
        parent.store("ax", 0x42).store("dx", 0x44).exit(0)
        code, data, fixups = window_child(answer_0x400)
        return run(parent, code, data, fixups)

    def test_the_window_is_the_childs(self):
        host = self.run_send()
        kid = host.box.images["CHILD"].segments[1].selector
        self.assertEqual(word(host, kid, 0x70), 0x22)
        from tbpipeline_neww.user_wnd import wm
        self.assertEqual(wm(host.box.wine).get(0x22).task, host.box.wine.tasks[1].htask)

    def test_reply_comes_back_from_the_childs_stack(self):
        host = self.run_send(wp=5)
        self.assertEqual(host.stop, "dos exit 0x0")
        parent = host.box.exe.segments[1].selector
        kid = host.box.images["CHILD"].segments[1].selector
        # AX 2 * wParam + 1, DX the SS the procedure ran on: the child's DGROUP.
        self.assertEqual((word(host, parent, 0x42), word(host, parent, 0x44)), (11, kid))

    def test_child_goes_back_to_waiting(self):
        host = self.run_send()
        wine = host.box.wine
        self.assertEqual(wine.tasks[1].wait, "message")
        self.assertTrue(any(line.endswith("for a sent message") for line in wine.trace))


class Messages(unittest.TestCase):
    """Per-task queues: a posted message goes to the window's task, and GetMessage waits."""

    def test_posted_message_wakes_the_child(self):
        parent = win_exec(Asm()).store("ax", 0x40)
        parent.push(0x22).push(0x401).push(7).push(0).push(0).call(USER, POST_MESSAGE)
        # GetMessage in the parent: nothing for it, the child runs and gets the post.
        parent.push_ds().push(0x80).push(0).push(0).push(0).call(USER, GET_MESSAGE).exit(0)

        # The child's procedure is DefWindowProc's; it reads the message in its GetMessage loop.
        code, data, fixups = window_child(lambda code: None)
        host = run(parent, code, data, fixups)
        wine = host.box.wine
        kid = host.box.images["CHILD"].segments[1].selector
        # The child's MSG at 0x80: hwnd, message, wParam.
        self.assertEqual((word(host, kid, 0x80), word(host, kid, 0x82), word(host, kid, 0x84)), (0x22, 0x401, 7))
        self.assertTrue(host.stop.startswith("GetMessage: "), host.stop)
        self.assertEqual(wine.tasks[0].wait, "message")


class Scheduler(unittest.TestCase):
    """tasks.wait_for_message: another task that can run, else the first timer of any task."""

    def wine_with_tasks(self):
        from tbpipeline_neww.tasks import Task
        from tbpipeline_neww.wine import Wine
        w = Wine(".")
        a = Task(0x100, "A", {}, 0x10, 0x11)
        b = Task(0x200, "B", {}, 0x20, 0x21)
        w.tasks = [a, b]
        w.current = a
        w.htask = a.htask
        return w, a, b

    def test_ready_task_first(self):
        from tbpipeline_neww.tasks import wait_for_message
        w, a, b = self.wine_with_tasks()
        self.assertIs(wait_for_message(w), b)

    def test_waiting_task_with_no_message_is_not_ready(self):
        from tbpipeline_neww.tasks import wait_for_message
        w, a, b = self.wine_with_tasks()
        b.wait = "message"
        self.assertIsNone(wait_for_message(w))

    def test_other_tasks_timer_moves_the_clock(self):
        from tbpipeline_neww.tasks import wait_for_message
        from tbpipeline_neww.user_wnd import wm
        w, a, b = self.wine_with_tasks()
        b.wait = "message"
        m = wm(w)
        m.queue_of(a.htask).timers[(0, 1)] = [100, 0, 500]
        m.queue_of(b.htask).timers[(0, 1)] = [50, 0, 200]
        self.assertIs(wait_for_message(w), b)
        self.assertEqual(m.clock, 200)

    def test_own_timer_first_keeps_the_task(self):
        from tbpipeline_neww.tasks import wait_for_message
        from tbpipeline_neww.user_wnd import wm
        w, a, b = self.wine_with_tasks()
        b.wait = "message"
        m = wm(w)
        m.queue_of(a.htask).timers[(0, 1)] = [100, 0, 100]
        m.queue_of(b.htask).timers[(0, 1)] = [50, 0, 200]
        self.assertIs(wait_for_message(w), a)
        self.assertEqual(m.clock, 0)

    def test_posted_message_makes_a_waiting_task_ready(self):
        from tbpipeline_neww.tasks import wait_for_message
        from tbpipeline_neww.user_wnd import wm
        w, a, b = self.wine_with_tasks()
        b.wait = "message"
        wm(w).queue_of(b.htask).queue.append((0, 0x400, 0, 0))
        self.assertIs(wait_for_message(w), b)

    def test_event_wait(self):
        from tbpipeline_neww.tasks import can_run
        w, a, b = self.wine_with_tasks()
        b.wait = "event"
        self.assertFalse(can_run(w, b))
        b.events = 1
        self.assertTrue(can_run(w, b))

    def test_swap_moves_the_task_fields(self):
        from tbpipeline_neww.tasks import swap
        w, a, b = self.wine_with_tasks()
        w.hooks = {6: (1, 2)}
        w.events = 3
        b.hooks, b.events = {}, 0
        swap(w, b)
        self.assertEqual((w.htask, w.hooks, w.events, w.exe_name), (0x200, {}, 0, "B"))
        self.assertEqual((a.hooks, a.events), ({6: (1, 2)}, 3))


class PeekYields(unittest.TestCase):
    """PeekMessage16 with nothing: FALSE, and without PM_NOYIELD the other task runs first."""

    def test_peek_lets_the_child_run(self):
        parent = win_exec(Asm()).store("ax", 0x40)
        parent.push_ds().push(0x80).push(0).push(0).push(0).push(1).call(USER, PEEK_MESSAGE).store("ax", 0x46).exit(0)
        child = Asm().call(KERNEL, YIELD).inc(0x50).exit(2)
        host = run(parent, child)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(word(host, host.box.exe.segments[1].selector, 0x46), 0)
        self.assertEqual(word(host, host.box.images["CHILD"].segments[1].selector, 0x50), 1)

    def test_noyield_does_not_switch(self):
        parent = win_exec(Asm()).store("ax", 0x40)
        parent.push_ds().push(0x80).push(0).push(0).push(0).push(3).call(USER, PEEK_MESSAGE).exit(0)
        child = Asm().call(KERNEL, YIELD).inc(0x50).exit(2)
        host = run(parent, child)
        self.assertEqual(word(host, host.box.images["CHILD"].segments[1].selector, 0x50), 0)


if __name__ == "__main__":
    unittest.main()
