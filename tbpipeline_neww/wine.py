"""Windows inside the sandbox.

A system ordinal is a gate: the guest far-calls it, the gate stops the
CPU, this module answers, and the gate's retf pops the Pascal arguments.
An ordinal with no contract stops the run. It does not invent a pop size.
"""

# Wine Win16 spec files, read at this commit. A row cites file and ordinal.
WINE_COMMIT = "2528aff26208257fdbf980666a4f0e66d47563ce"
KERNEL_SPEC = "dlls/krnl386.exe16/krnl386.exe16.spec"
USER_SPEC = "dlls/user.exe16/user.exe16.spec"

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
    "15  pascal -ret16 GlobalAlloc(word long) GlobalAlloc16",
    "17  pascal -ret16 GlobalFree(word) GlobalFree16",
    "18  pascal GlobalLock(word) WIN16_GlobalLock16",
    "30  pascal -ret16 WaitEvent(word) WaitEvent16",
    "50  pascal GetProcAddress(word str) GetProcAddress16",
    "74  pascal -ret16 OpenFile(str ptr word) OpenFile16",
    "81  pascal -ret16 _lclose(word) _lclose16",
    "82  pascal -ret16 _lread(word segptr word) WIN16_lread",
    "84  pascal   _llseek(word long word) _llseek16",
    "85  pascal -ret16 _lopen(str word) _lopen16",
    "91  pascal -register InitTask() InitTask16",
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
    "176 pascal -ret16 LoadString(word word ptr s_word) LoadString16",
    "266 pascal -ret16 SetMessageQueue(word) SetMessageQueue16",
])

# Constants, not code. A fixup stores the value.
EQUATES = {
    "KERNEL": {113: ("__AHSHIFT", 3), 114: ("__AHINCR", 8), 178: ("__WINFLAGS", 0x0C25)},
}

SYSTEM = ("KERNEL", "USER", "GDI", "SHELL", "KEYBOARD", "WIN87EM", "COMMDLG", "TOOLHELP", "COMPOBJ", "OLE2")


class Wine:
    def __init__(self, root):
        self.root = root
        self.files = {}
        self.next_file = 1
        self.heap = {}
        self.next_heap = 1
        self.trace = []
        self.exit = None
        # The loader posts one event before the entry. WaitEvent consumes it.
        self.events = 1

    def contract(self, module, ordinal):
        module = module.upper()
        if module == "KERNEL":
            return KERNEL.get(ordinal)
        if module == "USER":
            return USER.get(ordinal)
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
        return 0, 0, self.missing(module, ordinal)

    def _kernel(self, ordinal, arg):
        if ordinal == 91:
            return 1, 0, None
        if ordinal == 30:
            if self.events > 0:
                self.events -= 1
                return 0, 0, None
            return 0, 0, "WaitEvent with no event"
        if ordinal == 15:
            handle = self.next_heap
            self.next_heap += 1
            size = arg(2) or 1
            self.heap[handle] = bytearray(size)
            return handle, 0, None
        if ordinal == 18:
            return arg(0), 0, None
        if ordinal == 17:
            self.heap.pop(arg(0), None)
            return 0, 0, None
        if ordinal in (74, 85):
            handle = self.next_file
            self.next_file += 1
            self.files[handle] = arg.string(0)
            return handle, 0, None
        if ordinal == 81:
            self.files.pop(arg(0), None)
            return 0, 0, None
        if ordinal in (82, 84, 50, 95, 128, 176):
            return 0, 0, None
        if ordinal == 102:
            ax = arg.regs("ax")
            if (ax >> 8) & 0xFF == 0x4C:
                self.exit = ax & 0xFF
                return ax, 0, f"dos exit {ax & 0xFF:#x}"
            return 0, 0, None
        return 0, 0, f"unimplemented KERNEL.{ordinal}"

    def _user(self, ordinal, arg):
        if ordinal == 266:
            return 1, 0, None
        if ordinal in (1, 108, 111, 176):
            return 0, 0, None
        return 0, 0, f"unimplemented USER.{ordinal}"
