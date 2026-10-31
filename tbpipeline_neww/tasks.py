"""Win16 tasks, from Wine dlls/krnl386.exe16 task.c and ne_module.c at WINE_COMMIT.

A Win16 task is a Wine thread holding the Win16 lock. Only one runs 16-bit code at a
time, and it gives the lock up only where it waits: GetMessage, WaitMessage and
PeekMessage with nothing to return, Yield, DirectedYield, WaitEvent. neww has one
CPU, so a task switch happens at one of those gate calls. The machine saves the
caller's registers and loads the next task's (Machine._switch).

A task that waits is saved one of two ways:

- "retry": it resumes at the start of the gate stub, so the call runs again. GetMessage
  and WaitMessage resume this way, and then find the message that woke them.
- "answer": it resumes at the stub's retf with the answer in DX:AX. Yield and an empty
  PeekMessage resume this way. The answer may be a function, run when the task resumes,
  as WinExec's is: LoadModule16 reads the child's instance after its DirectedYield returns.

Which task runs next: Wine leaves that to the host's thread scheduler. neww takes the
first task, in creation order after the current one, that can run: one that yielded,
one that has a message waiting, one whose event was posted. When none can, the clock
moves to the earliest timer of a task waiting for messages, and that task runs. When
there is no timer either, every task waits for input, and the run stops there.
"""

from .handlers import handles
from .kernel16 import cstr

# The wine fields that belong to the current task. A switch saves them in the old task and
# loads them from the new one.
SWAPPED = ("htask", "task", "exe_name", "hooks", "events", "exit")


class Task:
    def __init__(self, htask, name, task, module, instance, events=0):
        self.htask = htask
        self.exe_name = name
        # The machine's task dict: psp, instance, dgroup, the DLLs InitTask initializes.
        self.task = task
        self.hooks = {}
        # TDB nEvents. NE_CreateThread posts one before the task first runs.
        self.events = events
        self.exit = None
        self.module = module
        self.instance = instance
        self.alive = True
        # What the task waits for: None (it can run), "message" or "event".
        self.wait = None
        # Saved registers while another task runs, or the start registers before it first runs.
        self.context = None

    def __repr__(self):
        return f"Task({self.exe_name} {self.htask:#x})"


class Switch:
    """A gate call's request to give the CPU to another task. kind is "retry" or "answer"."""

    def __init__(self, kind, task, wait=None, answer=None):
        self.kind = kind
        self.task = task
        self.wait = wait
        self.answer = answer
        # A guest call to make in task first (a message sent from another task), and
        # done(ax, dx) -> the task to run when it returns.
        self.call = None
        self.done = None


def current(wine):
    return wine.current


def swap(wine, target):
    """Save the current task's fields and load target's."""
    cur = wine.current
    if cur is not None:
        for name in SWAPPED:
            setattr(cur, name, getattr(wine, name))
    for name in SWAPPED:
        setattr(wine, name, getattr(target, name))
    wine.current = target


def by_handle(wine, htask):
    for t in wine.tasks:
        if t.htask == htask and t.alive:
            return t
    return None


def can_run(wine, t):
    """The task is ready, or what it waits for has come."""
    if not t.alive:
        return False
    if t.wait is None:
        return True
    if t.wait == "event":
        return (wine.events if t is wine.current else t.events) > 0
    if t.wait == "message":
        from .user_wnd import message_waiting
        return message_waiting(wine, t.htask)
    return False


def others(wine):
    """The other live tasks, in creation order after the current one."""
    tasks = wine.tasks
    if wine.current not in tasks:
        return [t for t in tasks if t.alive]
    i = tasks.index(wine.current)
    return [t for t in tasks[i + 1:] + tasks[:i] if t.alive]


def next_ready(wine, prefer=None):
    """Another task that can run now, prefer first, or None."""
    if prefer is not None and prefer is not wine.current and can_run(wine, prefer):
        return prefer
    for t in others(wine):
        if can_run(wine, t):
            return t
    return None


def earliest_timer(wine, include_current=True):
    """(due, task) of the first timer of a task waiting for messages, or None."""
    from .user_wnd import wm
    m = wm(wine)
    best = None
    for t in wine.tasks:
        if not t.alive:
            continue
        if t is wine.current:
            if not include_current:
                continue
        elif t.wait != "message":
            continue
        for timer in m.queue_of(t.htask).timers.values():
            if best is None or timer[2] < best[0]:
                best = (timer[2], t)
    return best


def wait_for_message(wine):
    """The current task has no message. Returns the task to run: another task that can run,
    or the one whose timer comes first, with the clock moved to it. The current task when
    its own timer is first. None when every task waits for input."""
    nxt = next_ready(wine)
    if nxt is not None:
        return nxt
    found = earliest_timer(wine)
    if found is None:
        return None
    due, t = found
    if t is not wine.current:
        from .user_wnd import wm
        m = wm(wine)
        m.clock = max(m.clock, due)
    return t


def yield_to(wine, prefer=None, answer=None):
    """OldYield16 and DirectedYield16: the current task stays ready, another runs first if one
    can. Sets the switch request and returns True when one does."""
    nxt = next_ready(wine, prefer)
    if nxt is None:
        return False
    wine.registers = {"switch": Switch("answer", nxt, answer=answer)}
    return True


# ---------------------------------------------------------------- KERNEL

@handles("KERNEL", 29)
def yield16(wine, arg):
    """task.c Yield16: a task with a queue does PeekMessage(PM_REMOVE | PM_QS_SENDMESSAGE),
    which only takes sent messages; then, or without a queue, OldYield16 lets the other tasks
    run. Void."""
    ax = arg.regs("ax")
    if yield_to(wine, answer=(ax, 0)):
        wine.trace[-1] += f" -> {wine.registers['switch'].task.exe_name}"
    return ax, 0, None


@handles("KERNEL", 150)
def directed_yield(wine, arg):
    """task.c DirectedYield16(hTask): Yield16, with hTask the next to run. Void."""
    ax = arg.regs("ax")
    if yield_to(wine, by_handle(wine, arg(0)), answer=(ax, 0)):
        wine.trace[-1] += f" -> {wine.registers['switch'].task.exe_name}"
    return ax, 0, None


@handles("KERNEL", 30)
def wait_event(wine, arg):
    """task.c WaitEvent16(hTask), 0 the current task. With an event posted, one is taken and the
    answer is FALSE. Without, the current task sleeps until PostEvent16 posts one, takes it and
    answers TRUE. For another task with no event Wine only prints a FIXME and answers TRUE."""
    htask = arg(0) or wine.htask
    t = by_handle(wine, htask)
    if t is None:
        # TASK_GetPtr finds no TDB and Wine reads through the NULL.
        return 0, 0, f"KERNEL.30 WaitEvent hTask={htask:#x}: no task has that handle, and Wine reads its TDB"
    if t is not wine.current:
        if t.events > 0:
            t.events -= 1
            return 0, 0, None
        return 1, 0, None
    if wine.events > 0:
        wine.events -= 1
        return 0, 0, None
    nxt = next_ready(wine)
    if nxt is None:
        return 0, 0, "KERNEL.30 WaitEvent would block: no event is posted and no other task can run to post one"

    def woken():
        if wine.events > 0:
            wine.events -= 1
        return 1, 0

    wine.registers = {"switch": Switch("answer", nxt, wait="event", answer=woken)}
    return 0, 0, None


@handles("KERNEL", 31)
def post_event(wine, arg):
    """task.c PostEvent16(hTask): nEvents of the task (0 is the current one) goes up. Void."""
    htask = arg(0) or wine.htask
    t = by_handle(wine, htask)
    if t is not None:
        if t is wine.current:
            wine.events += 1
        else:
            t.events += 1
    return arg.regs("ax"), 0, None


@handles("KERNEL", 320)
def is_task(wine, arg):
    """task.c IsTask16: TRUE for the handle of a live task's TDB."""
    return (1 if arg(0) and by_handle(wine, arg(0)) is not None else 0), 0, None


@handles("KERNEL", 36)
def get_current_task(wine, arg):
    """task.c WIN16_GetCurrentTask: the current task in AX, hFirstTask in DX."""
    return wine.htask, wine.first_task or wine.htask, None


@handles("KERNEL", 48)
def get_module_usage(wine, arg):
    """ne_module.c GetModuleUsage16: the module's count. Each module neww loaded is used once,
    an executable once per running task, and a freed one is no module."""
    module = wine._exe_ptr(arg(0))
    if not module:
        return 0, 0, None
    return wine.usage.get(module, 1), 0, None


def contains_path(name):
    """ne_module.c contains_path: a drive letter, or a / or \\ anywhere."""
    return (len(name) > 1 and name[1] == ":") or "/" in name or "\\" in name


def parse_win_exec(line):
    """ne_module.c WinExec16: (file name, command line) from the WinExec string. The command
    line is what follows the first space. A quoted name ends at the next quote."""
    if line.startswith('"'):
        end = line.find('"', 1)
        if end < 0:
            return line[1:], ""
        name, rest = line[1:end], line[end:]
        space = rest.find(" ")
        return name, rest[space + 1:] if space >= 0 else ""
    space = line.find(" ")
    if space < 0:
        return line, ""
    return line[:space], line[space + 1:]


@handles("KERNEL", 166)
def win_exec(wine, arg):
    """ne_module.c WinExec16(lpCmdLine, nCmdShow) -> LoadModule16 -> NE_CreateThread.

    SearchPathA finds the file, ".exe" added when it has no extension, in the application's
    directory first, which is --b. A missing file is 1 for a bare name (winoldap's exit code) and
    ERROR_FILE_NOT_FOUND, 2, for a name with a path.
    For an executable, TASK_SpawnTask makes the task and PostEvent16 posts its event. The
    caller then loops on DirectedYield16(hTask): the child runs until it first waits, and
    WinExec answers its hInstance, or its exit code when it has already ended.
    """
    line = cstr(wine, arg(2), arg(1)).decode("latin1")
    show = arg(0)
    name, cmdline = parse_win_exec(line)
    wine.trace[-1] += f" {line!r}"
    image, why = wine.find_exe(name)
    if why:
        return 0, 0, f"KERNEL.166 WinExec({line!r}): {why}"
    if image is None:
        # SearchPathA failed. A name with a drive or a slash is ERROR_FILE_NOT_FOUND, 2. A bare
        # name is tried as a 16-bit builtin, which fails, and ERROR_FILE_NOT_FOUND becomes 21
        # (ne_module.c:1462-1467). With 21, WinExec16 loads winoldap.mod with the whole string
        # and returns what that gives (:1477-1497). Wine's winoldap.mod16 WinMain16 starts with
        # exit_code = 1, CreateProcessA fails for a missing file, and it calls ExitThread(1)
        # before it ever waits (programs/winoldap.mod16/winoldap.c:65,72,88). NE_CreateThread's
        # DirectedYield16 loop then finds the task dead and returns its exit code (:928-935): 1.
        if contains_path(name):
            wine.trace[-1] += " not found"
            return 2, 0, None
        wine.trace[-1] += " not found: winoldap.mod's task ends with exit code 1"
        return 1, 0, None
    child = wine.spawn(image, cmdline, show)
    if isinstance(child, str):
        return 0, 0, f"KERNEL.166 WinExec({line!r}): {child}"

    def answer():
        if not child.alive:
            return child.exit or 0, 0
        return child.instance, 0

    wine.trace[-1] += f" -> task {child.htask:#x}"
    wine.registers = {"switch": Switch("answer", child, answer=answer)}
    return 0, 0, None

