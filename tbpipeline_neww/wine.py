"""Windows inside the sandbox.

A system ordinal is a gate: the guest far-calls it, the gate stops the
CPU, this module answers, and the gate's retf pops the Pascal arguments.
An ordinal with no contract stops the run. It does not invent a pop size.
"""

import struct
from pathlib import Path

from .local import LocalHeap, Stop as LocalStop

# Wine Win16 spec files, read at this commit. A row cites file and ordinal.
WINE_COMMIT = "2528aff26208257fdbf980666a4f0e66d47563ce"
KERNEL_SPEC = "dlls/krnl386.exe16/krnl386.exe16.spec"
USER_SPEC = "dlls/user.exe16/user.exe16.spec"
WIN87EM_SPEC = "dlls/win87em.dll16/win87em.dll16.spec"

# Bytes on the 16-bit Pascal stack for each Wine argument type.
SPEC_SIZES = {"word": 2, "s_word": 2, "long": 4, "ptr": 4, "str": 4, "segptr": 4, "segstr": 4}


class Contract:
    """One row: module, ordinal, name, argument sizes, return.

    args are bytes per Pascal argument, first argument first. pop is
    what the gate's retf removes, and nothing else sets it.

    A row made by from_spec() takes its args from the Wine declaration.
    binary is a pop size seen in the ToolBook binary, if anyone recorded
    one. When it differs from the spec the row is not used: the gate
    stops and names both sizes. Neither is picked.
    """

    def __init__(self, module, ordinal, name, args, ret, spec=None, binary=None, value=None):
        self.module = module
        self.ordinal = ordinal
        self.name = name
        self.args = tuple(args)
        self.ret = ret
        self.spec = spec
        self.binary = binary
        # (ax, dx) when the answer is a constant. The row is the whole contract.
        self.value = value

    @property
    def pop(self):
        return sum(self.args)

    @property
    def disagreement(self):
        if self.binary is None or self.binary == self.pop:
            return None
        where = f"{self.spec[0]}:{self.ordinal}" if self.spec else "row"
        return f"{self.module}.{self.ordinal} {self.name}: {where} pops {self.pop}, binary pops {self.binary}"

    @classmethod
    def from_spec(cls, module, path, line, binary=None, value=None):
        """line is the Wine spec entry, ordinal first, as the file has it."""
        head, _, rest = line.partition("(")
        words = head.split()
        ordinal = int(words[0])
        if words[1] != "pascal":
            raise ValueError(f"{path}:{ordinal} is {words[1]}, not a pascal entry")
        flags = words[2:-1]
        name = words[-1]
        types = rest.partition(")")[0].split()
        args = [SPEC_SIZES[t] for t in types]
        if "-register" in flags:
            ret = "register"
        elif "-ret16" in flags:
            ret = "word"
        else:
            ret = "long"
        return cls(module, ordinal, name, args, ret, spec=(path, line), binary=binary, value=value)

    def __repr__(self):
        return f"Contract({self.module}.{self.ordinal} {self.name} args={self.args} pop={self.pop} ret={self.ret})"


def _table(module, path, lines):
    """lines are spec lines, or (spec line, (ax, dx)) for a constant answer."""
    rows = []
    for line in lines:
        value = None
        if isinstance(line, tuple):
            line, value = line
        rows.append(Contract.from_spec(module, path, line, value=value))
    return {row.ordinal: row for row in rows}


# Each line is copied from the spec file named above. ret: "word" in AX,
# "long" in DX:AX, "register" when the call reads and sets registers.
KERNEL = _table("KERNEL", KERNEL_SPEC, [
    # Windows 3.10 in AX, DX 0. newl returns the same pair.
    ("3   pascal GetVersion() GetVersion16", (0x0A03, 0)),
    "4   pascal -ret16 LocalInit(word word word) LocalInit16",
    "5   pascal -ret16 LocalAlloc(word word) LocalAlloc16",
    "15  pascal -ret16 GlobalAlloc(word long) GlobalAlloc16",
    "17  pascal -ret16 GlobalFree(word) GlobalFree16",
    "18  pascal GlobalLock(word) WIN16_GlobalLock16",
    "23  pascal -ret16 LockSegment(word) LockSegment16",
    "24  pascal -ret16 UnlockSegment(word) UnlockSegment16",
    "30  pascal -ret16 WaitEvent(word) WaitEvent16",
    "50  pascal GetProcAddress(word str) GetProcAddress16",
    "74  pascal -ret16 OpenFile(str ptr word) OpenFile16",
    "81  pascal -ret16 _lclose(word) _lclose16",
    "82  pascal -ret16 _lread(word segptr word) WIN16_lread",
    "84  pascal   _llseek(word long word) _llseek16",
    "85  pascal -ret16 _lopen(str word) _lopen16",
    "91  pascal -register InitTask() InitTask16",
    "131 pascal GetDOSEnvironment() GetDOSEnvironment16",
    "95  pascal -ret16 LoadLibrary(str) LoadLibrary16",
    "102 pascal -register DOS3Call() DOS3Call",
    "128 pascal -ret16 GetPrivateProfileString(str str str ptr word str) GetPrivateProfileString16",
    # The enhanced-mode word, the same as the __WINFLAGS equate below. DX 0, as in newl.
    ("132 pascal GetWinFlags() GetWinFlags16", (0x0C25, 0)),
])

USER = _table("USER", USER_SPEC, [
    "1   pascal -ret16 MessageBox(word str str word) MessageBox16",
    "108 pascal -ret16 GetMessage(ptr word word word) GetMessage16",
    "111 pascal   SendMessage(word word word long) SendMessage16",
    "118 pascal -ret16 RegisterWindowMessage(str) RegisterWindowMessageA",
    "176 pascal -ret16 LoadString(word word ptr s_word) LoadString16",
    "266 pascal -ret16 SetMessageQueue(word) SetMessageQueue16",
])

WIN87EM = _table("WIN87EM", WIN87EM_SPEC, [
    "1 pascal -register __fpMath()",
])

# Constants, not code. A fixup stores the value.
EQUATES = {
    "KERNEL": {113: ("__AHSHIFT", 3), 114: ("__AHINCR", 8), 178: ("__WINFLAGS", 0x0C25)},
}

# Wine task.c TASK_Create: cmdShow is 1, SW_SHOWNORMAL, unless the startup info sets one.
SW_SHOWNORMAL = 1

GMEM_MOVEABLE = 0x0002
LOCAL_HEAP_MAGIC = 0x484C
HFILE_ERROR = 0xFFFF
OF_SHARE_MASK = 0x0070

SYSTEM = ("KERNEL", "USER", "GDI", "SHELL", "KEYBOARD", "WIN87EM", "COMMDLG", "TOOLHELP", "COMPOBJ", "OLE2")


class Wine:
    def __init__(self, root):
        self.root = root
        # The book a .tbk or .sbk path opens. Set from --c.
        self.book = None
        # handle -> [guest path, host path, bytes, position]
        self.files = {}
        # DOS keeps 0-4 for the standard handles.
        self.next_file = 5
        # Set by the machine: write(selector, offset, bytes) into guest memory.
        self.write = None
        # handle -> (first selector, size, flags)
        self.heap = {}
        # Set by the machine: size -> first selector of a mapped block.
        self.allocate = None
        self.trace = []
        self.exit = None
        # Wine ne_module.c NE_CreateThread posts one event before the task runs.
        # The startup WaitEvent(0) consumes it.
        self.events = 1
        # Set by the machine at entry: psp, instance, dlls (the ToolBook DLLs with init code).
        self.task = None
        # A register contract leaves its extra registers here, and "push" for a word under the return.
        self.registers = None
        # Set by the machine: selector -> size of its block in bytes, or None.
        self.size = None
        # Registered window messages: lower-case name -> atom, from MAXINTATOM (0xC000) up.
        self.messages = {}
        # selector -> lockCount, Wine's GLOBALARENA field, for LockSegment.
        self.locks = {}
        # Selector of the DOS environment block, set by the machine with the PSP.
        self.environment = None
        # Wine win87em.c statics. Installed is TRUE: an x87 is present.
        self.ctrl_word_1 = 0
        self.status_word_2 = 0

    def contract(self, module, ordinal):
        module = module.upper()
        if module == "KERNEL":
            return KERNEL.get(ordinal)
        if module == "USER":
            return USER.get(ordinal)
        if module == "WIN87EM":
            return WIN87EM.get(ordinal)
        return None

    def usable(self, module, ordinal):
        """The row the gate may pop, or None. A disagreeing row is not usable."""
        row = self.contract(module, ordinal)
        if row is None or row.disagreement:
            return None
        return row

    def equate(self, module, ordinal):
        return EQUATES.get(module.upper(), {}).get(ordinal)

    @staticmethod
    def missing(module, ordinal):
        return f"unimplemented {module}.{ordinal}: no contract, pop size not guessed"

    def answer(self, module, ordinal, arg):
        """arg(n) reads Pascal argument n. Returns (ax, dx, stop)."""
        label = self.contract(module, ordinal)
        name = label.name if label else str(ordinal)
        self.trace.append(f"{module}.{ordinal} {name}")
        if label is None:
            return 0, 0, self.missing(module, ordinal)
        if label.disagreement:
            return 0, 0, f"contract disagrees {label.disagreement}"
        if label.value is not None:
            return label.value[0], label.value[1], None
        if module == "KERNEL":
            return self._kernel(ordinal, arg)
        if module == "USER":
            return self._user(ordinal, arg)
        if module == "WIN87EM" and ordinal == 1:
            return self._fpmath(arg)
        return 0, 0, self.missing(module, ordinal)

    def _kernel(self, ordinal, arg):
        if ordinal == 91:
            return self._init_task(arg)
        if ordinal == 4:
            # LocalInit(word selector, word start, word end). Wine also returns the result in CX.
            ok = self.local_init(arg(2), arg(1), arg(0), arg.regs("ds"))
            self.registers = {"cx": ok}
            return ok, 0, None
        if ordinal == 5:
            # LocalAlloc(word flags, word size) in CURRENT_DS. Wine also returns the handle in CX.
            heap = LocalHeap(arg.regs("ds"), arg.word, self.write)
            try:
                handle = heap.alloc(arg(1), arg(0))
            except LocalStop as why:
                return 0, 0, f"KERNEL.5 LocalAlloc(flags={arg(1):#x}, size={arg(0):#x}): {why}"
            self.registers = {"cx": handle}
            return handle, 0, None
        if ordinal == 23:
            # Wine global.c LockSegment16: -1 is CURRENT_DS. An invalid handle returns 0.
            handle = arg(0)
            if handle == 0xFFFF:
                handle = arg.regs("ds")
            sel = self.selector_of(handle)
            if sel is None:
                return 0, 0, None
            self.locks[sel] = self.locks.get(sel, 0) + 1
            return handle, 0, None
        if ordinal == 24:
            # Wine global.c UnlockSegment16 is void: lockCount goes down, AX is left as it was.
            handle = arg(0)
            if handle == 0xFFFF:
                handle = arg.regs("ds")
            sel = self.selector_of(handle)
            if sel is not None:
                self.locks[sel] = self.locks.get(sel, 0) - 1
            return arg.regs("ax"), 0, None
        if ordinal == 131:
            # Wine task.c GetDOSEnvironment16: WOWGlobalLock16 of the block, a SEGPTR in DX:AX.
            if self.environment is None:
                return 0, 0, "KERNEL.131 GetDOSEnvironment with no environment block: the machine made none"
            return 0, self.environment, None
        if ordinal == 30:
            # Wine task.c WaitEvent16: hTask 0 is the current task. An event is taken and FALSE
            # returned. With no event the task blocks, and one task cannot be woken.
            task = arg(0)
            if task != 0:
                return 0, 0, f"KERNEL.30 WaitEvent hTask={task:#x}: neww has no task handle to match it"
            if self.events > 0:
                self.events -= 1
                return 0, 0, None
            return 0, 0, "KERNEL.30 WaitEvent would block: no event is posted and there is no other task"
        if ordinal == 15:
            return self._global_alloc(arg(2), arg(0) | (arg(1) << 16))
        if ordinal == 18:
            return arg(0), 0, None
        if ordinal == 17:
            self.heap.pop(arg(0), None)
            return 0, 0, None
        if ordinal == 74:
            # OpenFile(str name, ptr ofstruct, word mode): mode is arg 0, ofstruct 1-2, name 3-4.
            return self._open_file(arg.string(3), arg(2), arg(1), arg(0))
        if ordinal == 85:
            # _lopen(str name, word mode)
            return self._lopen(arg.string(1), arg(0))
        if ordinal == 81:
            if self.files.pop(arg(0), None) is None:
                return HFILE_ERROR, 0, None
            return 0, 0, None
        if ordinal == 82:
            # _lread(word file, segptr buffer, word count)
            return self._lread(arg(3), arg(2), arg(1), arg(0))
        if ordinal == 84:
            # _llseek(word file, long offset, word origin)
            return self._llseek(arg(3), arg(1) | (arg(2) << 16), arg(0))
        if ordinal in (50, 95, 128, 176):
            return 0, 0, None
        if ordinal == 102:
            ax = arg.regs("ax")
            if (ax >> 8) & 0xFF == 0x4C:
                self.exit = ax & 0xFF
                return ax, 0, f"dos exit {ax & 0xFF:#x}"
            return 0, 0, None
        return 0, 0, f"unimplemented KERNEL.{ordinal}"

    def resolve(self, path):
        """The host file a guest path opens, or None.

        A path ending in .tbk or .sbk is the book from --c, whatever its
        directory. Any other path is its base name, looked up without case
        in --b. Nothing else is searched.
        """
        name = path.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(":", 1)[-1]
        if name.lower().endswith((".tbk", ".sbk")):
            return self.book
        if not name:
            return None
        for item in Path(self.root).iterdir():
            if item.is_file() and item.name.lower() == name.lower():
                return item
        return None

    def _handle(self, path, host):
        handle = self.next_file
        self.next_file += 1
        self.files[handle] = [path, host, Path(host).read_bytes(), 0]
        return handle

    def _open_file(self, path, ofs_sel, ofs_off, mode):
        """Wine file.c OpenFile16. Read access only; any other mode stops."""
        if mode & ~(OF_SHARE_MASK | 0x0003) or mode & 0x0003:
            return 0, 0, f"KERNEL.74 OpenFile {path!r} mode {mode:#06x}: neww opens files to read and nothing else"
        host = self.resolve(path)
        ofs = bytearray(136)
        ofs[0] = 136
        if host is None:
            struct.pack_into("<H", ofs, 2, 2)  # nErrCode: file not found
            self._put(ofs_sel, ofs_off, ofs)
            self.trace.append(f"  OpenFile {path!r} not found, HFILE_ERROR")
            return HFILE_ERROR, 0, None
        name = path.encode("latin1", "replace")[:127]
        ofs[8:8 + len(name)] = name
        self._put(ofs_sel, ofs_off, ofs)
        handle = self._handle(path, host)
        self.trace.append(f"  OpenFile {path!r} -> {handle} {Path(host).name}")
        return handle, 0, None

    def _lopen(self, path, mode):
        if mode & 0x0003:
            return 0, 0, f"KERNEL.85 _lopen {path!r} mode {mode:#06x}: neww opens files to read and nothing else"
        host = self.resolve(path)
        if host is None:
            return HFILE_ERROR, 0, None
        return self._handle(path, host), 0, None

    def _lread(self, handle, sel, off, count):
        entry = self.files.get(handle)
        if entry is None:
            return HFILE_ERROR, 0, None
        chunk = entry[2][entry[3]:entry[3] + count]
        entry[3] += len(chunk)
        self._put(sel, off, chunk)
        return len(chunk), 0, None

    def _llseek(self, handle, offset, origin):
        entry = self.files.get(handle)
        if entry is None or origin not in (0, 1, 2):
            return 0xFFFF, 0xFFFF, None
        if offset & 0x80000000:
            offset -= 1 << 32
        start = (0, entry[3], len(entry[2]))[origin]
        entry[3] = max(start + offset, 0)
        return entry[3] & 0xFFFF, entry[3] >> 16, None

    def _put(self, sel, off, data):
        if self.write is not None and data:
            self.write(sel, off, bytes(data))

    def _init_task(self, arg):
        """Wine krnl386.exe16/task.c InitTask16, a register contract.

        Wine fills INSTANCEDATA, calls LocalInit16 when CX is not 0, runs the
        DLL entry points, then answers in registers. The entry points are
        guest code, so the machine runs them and calls init_task_answer().
        """
        task = self.task
        if task is None:
            return 0, 0, "KERNEL.91 InitTask with no task: the machine did not start one"
        if task.get("dll_stop"):
            return 0, 0, task["dll_stop"]
        ds = arg.regs("ds")
        # Wine's CURRENT_SP + sizeof(STACK16FRAME) is the caller's SP past the far return address.
        stackmin = (arg.regs("sp") + 4) & 0xFFFF
        stack = arg.regs("bx")
        stacktop = ((stackmin - stack) if stackmin > stack else 0) + 150
        # INSTANCEDATA at DS:0: stacktop 0x0A, stackmin 0x0C, stackbottom 0x0E.
        self.write(ds, 0x0A, struct.pack("<HHH", stacktop, stackmin, stackmin))
        heap = arg.regs("cx")
        if heap:
            # Wine: LocalInit16(GlobalHandleToSel16(hInstance), 0, CX). The instance's selector is DGROUP.
            self.local_init(task["dgroup"], 0, heap, ds)
        task["stacktop"] = stacktop
        if task["dll_init"]:
            # Wine ne_segment.c NE_InitializeDLLs. The machine calls each LibMain, then the answer.
            self.registers = {"init_dlls": task["dll_init"]}
            return 0, 0, None
        return self.init_task_answer(arg.word)

    def _fpmath(self, arg):
        """Wine win87em.c __fpMath, by the sub-function in BX.

        Wine runs fninit, fldcw and fclex on the real x87. The guest's x87 is
        Unicorn's, so those become FPCW, FPSW and FPTAG writes.
        """
        bx = arg.regs("bx")
        ax = arg.regs("ax")
        if bx in (0, 1, 2):
            # WIN87_Init: fninit twice, AX = 0x1332, then WIN87_SetCtrlWord and WIN87_ClearCtrlWord.
            self.ctrl_word_1 = 0x1332
            internal = 0x1332 & ~0x00C3
            self.status_word_2 = 0
            # fninit: tag 0xFFFF, status 0. fldcw internal. fclex leaves status 0. AX ends 0.
            self.registers = {"fpcw": internal, "fpsw": 0, "fptag": 0xFFFF}
            return 0, 0, None
        if bx == 3:
            # Wine leaves the INT 3Eh handler alone.
            self.registers = {}
            return ax, 0, None
        if bx == 4:
            self.ctrl_word_1 = ax
            internal = ax & ~0x00C3
            self.registers = {"fpcw": internal}
            return internal, 0, None
        if bx == 5:
            self.registers = {}
            return self.ctrl_word_1, 0, None
        if bx == 9:
            self.status_word_2 = 0
            self.registers = {"fpsw": 0}
            return 0, 0, None
        if bx == 10:
            self.registers = {}
            return 0, 0, None
        if bx == 11:
            self.registers = {"dx": 0}
            return 1, 0, None
        if bx == 12:
            self.registers = {}
            return ax, 0, None
        return 0, 0, (
            f"WIN87EM.1 __fpMath BX={bx}: Wine win87em.c reads or rounds on the host x87 here "
            "(6 frndint, 7 fistp, 8 fstsw), or has no case. neww does not answer it"
        )

    def _register_window_message(self, name):
        """RegisterWindowMessageA: a string atom, 0xC000 to 0xFFFF, the same for the same name.

        Wine adds the name to the session's global atom table, so the number depends
        on what the session registered first. neww's table starts empty at 0xC000.
        An empty name or one over 255 characters is not an atom, and the answer is 0.
        """
        if not name or len(name) > 255:
            return 0
        key = name.lower()
        if key not in self.messages:
            if 0xC000 + len(self.messages) > 0xFFFF:
                return 0
            self.messages[key] = 0xC000 + len(self.messages)
        return self.messages[key]

    def init_task_answer(self, word):
        """The registers InitTask16 returns, once the DLLs are initialized."""
        task = self.task
        psp = task["psp"]
        line = word(psp, 0x80) & 0xFF
        bx = 0x80
        if line:
            p = 0x81
            while word(psp, p) & 0xFF in (0x20, 0x09):
                p += 1
            bx = p
        self.registers = {
            "bx": bx, "cx": task["stacktop"], "dx": SW_SHOWNORMAL, "si": 0, "di": task["instance"],
            "es": psp, "push": 0,
        }
        return 1, SW_SHOWNORMAL, None

    def selector_of(self, handle):
        """GlobalHandleToSel16 in neww's numbering: a moveable handle is selector - 1. None if no block."""
        sel = handle + 1 if handle & 7 == 7 else handle & ~7
        return sel if self.size(sel) is not None else None

    def local_init(self, selector, start, end, ds):
        """Wine local.c LocalInit16. Writes the heap into the guest and returns TRUE or FALSE."""
        if not selector:
            selector = ds
        if start == 0:
            # Put the heap at the end of the segment, sized by GlobalSize16.
            size = self.size(selector) or 0
            start = ((0xFFFF if size > 0xFFFF else size) - 1) & 0xFFFF
            if end > 0xFFFE:
                end = 0xFFFE
            start = (start - end) & 0xFFFF
            end = (end + start) & 0xFFFF
        lalign = lambda w: (w + 3) & ~3
        # sizeof(INSTANCEDATA) 16, sizeof(LOCALARENA) 10, ARENA_HEADER_SIZE 4, sizeof(LOCALHEAPINFO) 0x2A.
        start = lalign(max(start, 16))
        info_arena = lalign(start + 10)
        free_arena = lalign(info_arena + 4 + 0x2A)
        last_arena = (end - 10) & ~3
        if free_arena + 10 >= last_arena:
            return 0
        arena = lambda at, *words: self.write(selector, at, struct.pack(f"<{len(words)}H", *words))
        # First arena (FIXED), then the heap info arena, the large free block, the last arena.
        arena(start, start | 1, info_arena, lalign(10), start, free_arena)
        arena(info_arena, start | 1, free_arena)
        info = bytearray(0x2A)
        struct.pack_into("<H", info, 0x04, 4)
        struct.pack_into("<H", info, 0x06, start)
        struct.pack_into("<H", info, 0x0A, last_arena)
        struct.pack_into("<H", info, 0x18, 0x20)
        struct.pack_into("<H", info, 0x24, 0x200)
        struct.pack_into("<H", info, 0x26, last_arena - free_arena)
        struct.pack_into("<H", info, 0x28, LOCAL_HEAP_MAGIC)
        self.write(selector, info_arena + 4, bytes(info))
        arena(free_arena, info_arena, last_arena, last_arena - free_arena, start, last_arena)
        arena(last_arena, free_arena, last_arena, lalign(10), free_arena, last_arena)
        # INSTANCEDATA.heap
        self.write(selector, 0x06, struct.pack("<H", info_arena + 4))
        return 1

    def _global_alloc(self, flags, size):
        """Wine global.c GlobalAlloc16 / GLOBAL_Alloc. size is the whole dword."""
        if size == 0:
            return 0, 0, f"KERNEL.15 GlobalAlloc flags={flags:#x} size 0: Wine makes a discarded block, neww does not have one"
        if size > 0x100000:
            return 0, 0, f"KERNEL.15 GlobalAlloc size {size:#x}: over 1M needs page-granular selectors, neww has none"
        if self.allocate is None:
            return 0, 0, "KERNEL.15 GlobalAlloc with no CPU to map the block"
        size = (size + 0x1F) & ~0x1F
        sel = self.allocate(size)
        handle = sel - 1 if flags & GMEM_MOVEABLE else sel
        self.heap[handle] = (sel, size, flags)
        return handle, 0, None

    def _user(self, ordinal, arg):
        if ordinal == 118:
            return self._register_window_message(arg.string(0)), 0, None
        if ordinal == 266:
            return 1, 0, None
        if ordinal in (1, 108, 111, 176):
            return 0, 0, None
        return 0, 0, f"unimplemented USER.{ordinal}"
