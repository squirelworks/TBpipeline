"""Bare Windows. A call either has a contract here or it does not.

ToolBook DLLs are not this layer. A missing name is the result, not a
guessed return value.
"""

# ordinal, name, argument bytes the callee pops. From Wine's Win16 specs.
# __WINFLAGS is the enhanced-mode value this program tests, not Wine's 0x413.
KERNEL = {
    3: ("GetVersion", 0),
    5: ("LocalAlloc", 4),
    7: ("LocalFree", 2),
    8: ("LocalLock", 2),
    9: ("LocalUnlock", 2),
    15: ("GlobalAlloc", 6),
    17: ("GlobalFree", 2),
    18: ("GlobalLock", 2),
    20: ("GlobalSize", 2),
    36: ("GetCurrentTask", 0),
    49: ("GetModuleFileName", 8),
    50: ("GetProcAddress", 6),
    74: ("OpenFile", 10),
    81: ("_lclose", 2),
    82: ("_lread", 8),
    84: ("_llseek", 8),
    85: ("_lopen", 6),
    91: ("InitTask", 0),
    95: ("LoadLibrary", 4),
    102: ("DOS3Call", 0),
    23: ("LockSegment", 2),
    24: ("UnlockSegment", 2),
    30: ("WaitEvent", 2),
    128: ("GetPrivateProfileString", 22),
    131: ("GetDOSEnvironment", 0),
    132: ("GetWinFlags", 0),
}

EQUATES = {
    "KERNEL": {113: ("__AHSHIFT", 3), 114: ("__AHINCR", 8), 178: ("__WINFLAGS", 0x0C25)},
}

USER = {
    1: ("MessageBox", 12),
    5: ("InitApp", 2),
    108: ("GetMessage", 10),
    111: ("SendMessage", 10),
    176: ("LoadString", 10),
    266: ("SetMessageQueue", 2),
    # pascal SetWindowsHookEx(s_word segptr word word): returns HHOOK in DX:AX.
    # Added for "gap USER.291 far call at 0x1428:0xc9a0" (TB80RCR segment 3).
    291: ("SetWindowsHookEx", 10),
}

WIN87EM = {
    1: ("__fpmath", 0),
}

TABLES = {"KERNEL": KERNEL, "USER": USER, "WIN87EM": WIN87EM}


class Gap(Exception):
    """module.ordinal, the name if there is one, and where the far call was.

    at is (cs, ip, how): "call" when the far call itself was found, "return"
    when only the return address on the stack is known.
    """

    def __init__(self, module, ordinal, name="", at=None):
        self.module = module
        self.ordinal = ordinal
        self.name = name
        self.at = at
        super().__init__(self.text())

    def text(self):
        out = f"gap {self.module}.{self.ordinal}"
        if self.name:
            out += f" {self.name}"
        if self.at:
            cs, ip, how = self.at
            out += f" far call at {cs:#x}:{ip:#x}" if how == "call" else f" returning to {cs:#x}:{ip:#x}"
        return out


class Refused(Exception):
    """The layer has the contract but not what the call asks for."""


BOOK_SUFFIXES = (".tbk", ".sbk")


class Layer:
    def __init__(self, book=None):
        self.book = book  # the .tbk on the command line
        self.last_read = b""
        self.files = {}
        self.next_file = 1
        self.heap = {}
        self.next_heap = 1
        self.exit = None
        self.trace = []
        self.events = 1
        self.dgroup = 0
        self.heap_brk = 0
        self.heap_end = 0
        self.module_name = b"TB80RTM.EXE"
        self.module_name_len = len(self.module_name)
        self.task = 0
        self.gsizes = {}
        self.hooks = []  # (idHook, proc seg, proc off, hinst, htask); never called
        self.capped = []  # (handle, size asked) for GlobalAlloc over 64K

    def name_of(self, module, ordinal, name=""):
        module = module.upper()
        if name:
            return name
        equated = EQUATES.get(module, {}).get(ordinal)
        if equated:
            return equated[0]
        pair = TABLES.get(module, {}).get(ordinal)
        return pair[0] if pair else ""

    def knows(self, module, ordinal=0, name=""):
        module = module.upper()
        if module not in TABLES and module not in EQUATES:
            return False
        if name and not ordinal:
            want = name.upper()
            for table in (TABLES.get(module, {}),):
                if any(pair[0].upper() == want for pair in table.values()):
                    return True
            return any(pair[0].upper() == want for pair in EQUATES.get(module, {}).values())
        if ordinal in EQUATES.get(module, {}) or ordinal in TABLES.get(module, {}):
            return True
        return False

    def call(self, module, ordinal, args=(), at=None, path=None):
        module = module.upper()
        label = self.name_of(module, ordinal)
        try:
            if not self.knows(module, ordinal):
                raise Gap(module, ordinal, label)
            self.trace.append((module, ordinal, label, tuple(args)))
            if module == "KERNEL":
                return self._kernel(ordinal, args, path)
            if module == "USER":
                return self._user(ordinal, args)
            if module == "WIN87EM":
                return 0
            raise Gap(module, ordinal, label)
        except Gap as gap:
            if at and not gap.at:
                gap.at = at
                gap.args = (gap.text(),)
            raise

    def _kernel(self, ordinal, args, path=None):
        if ordinal == 3:
            return 0x0A03  # Windows 3.10
        if ordinal == 132:
            return EQUATES["KERNEL"][178][1]
        if ordinal == 131:
            return 0
        if ordinal == 91:
            return 1
        if ordinal == 30:
            if self.events <= 0:
                raise Gap("KERNEL", 30, "WaitEvent")
            self.events -= 1
            return 0
        if ordinal == 23:
            seg = args[0] if args else 0
            if seg in (0, 0xFFFF):
                return self.dgroup
            return seg
        if ordinal == 24:
            return 0
        if ordinal == 20:
            return self.gsizes.get(args[0] if args else 0, 0)
        if ordinal == 36:
            return self.task or 1
        if ordinal == 5:
            size = args[1] if len(args) > 1 else 0
            if size == 0 or self.heap_brk == 0:
                return 0
            size = (size + 1) & ~1
            if self.heap_brk + size > self.heap_end:
                return 0
            handle = self.heap_brk
            self.heap_brk += size
            return handle
        if ordinal == 8:
            return args[0] if args else 0
        if ordinal in (7, 9):
            return 0
        if ordinal == 49:
            return self.module_name_len
        if ordinal == 15:
            handle = self.next_heap
            self.next_heap += 1
            size = (args[0] if args else 0) | ((args[1] if len(args) > 1 else 0) << 16)
            self.heap[handle] = bytearray(min(size, 0x10000) or 1)
            return handle
        if ordinal == 18:
            return args[0] if args else 0
        if ordinal == 17:
            self.heap.pop(args[0] if args else 0, None)
            return 0
        if ordinal == 74 or ordinal == 85:
            return self._open(path or "")
        if ordinal == 81:
            self.files.pop(args[0] if args else 0, None)
            return 0
        if ordinal == 82:
            # pascal16 _lread(word segptr word): count on top, handle deepest
            entry = self.files.get(args[3] if len(args) > 3 else 0)
            self.last_read = b""
            if not entry or entry["data"] is None:
                return 0
            count = args[0]
            self.last_read = entry["data"][entry["pos"]:entry["pos"] + count]
            entry["pos"] += len(self.last_read)
            return len(self.last_read)
        if ordinal == 84:
            # pascal16 _llseek(word long word): origin, offset lo, hi, handle
            entry = self.files.get(args[3] if len(args) > 3 else 0)
            if not entry or entry["data"] is None:
                return 0
            origin, offset = args[0], args[1] | (args[2] << 16)
            if offset & 0x80000000:
                offset -= 1 << 32
            base = {0: 0, 1: entry["pos"], 2: len(entry["data"])}.get(origin, 0)
            entry["pos"] = max(base + offset, 0)
            return entry["pos"]
        if ordinal in (50, 95, 128):
            return 0
        if ordinal == 102:
            ax = args[0] if args else 0
            ah = (ax >> 8) & 0xFF
            if ah == 0x4C:
                self.exit = ax & 0xFF
                return 0
            if ah == 0x30:
                return 5
            return 0
        raise Gap("KERNEL", ordinal, self.name_of("KERNEL", ordinal))

    def _user(self, ordinal, args):
        if ordinal == 291:
            # Pushed first is deepest: idHook, lpfn seg:off, hInstance, hTask.
            hook_id = args[4] - 0x10000 if args[4] & 0x8000 else args[4]
            self.hooks.append((hook_id, args[3], args[2], args[1], args[0]))
            return 0x00010000 | len(self.hooks)  # HHOOK: opaque, nonzero, one per call
        if ordinal in (5, 266):
            return 1
        if ordinal == 108:
            return 0
        if ordinal in (1, 111, 176):
            return 0
        raise Gap("USER", ordinal, self.name_of("USER", ordinal))

    def _open(self, path):
        """A path ending in .tbk or .sbk is the book on the command line.
        Any other path keeps the old answer: a handle with nothing behind it."""
        data = None
        if path.lower().endswith(BOOK_SUFFIXES):
            if self.book is None:
                raise Refused(f"OpenFile {path}: no book on the command line (--c)")
            with open(self.book, "rb") as fh:
                data = fh.read()
        handle = self.next_file
        self.next_file += 1
        self.files[handle] = {"path": path, "data": data, "pos": 0}
        return handle
