"""Windows inside the sandbox.

A system ordinal is a gate: the guest far-calls it, the gate stops the
CPU, this module answers, and the gate's retf pops the Pascal arguments.
An ordinal with no contract stops the run. It does not invent a pop size.
"""

# (name, pop bytes). Pop sizes follow the Wine Win16 argument lists.
KERNEL = {
    3: ("GetVersion", 0),
    15: ("GlobalAlloc", 6),
    17: ("GlobalFree", 2),
    18: ("GlobalLock", 2),
    50: ("GetProcAddress", 6),
    74: ("OpenFile", 10),
    81: ("_lclose", 2),
    82: ("_lread", 8),
    84: ("_llseek", 8),
    85: ("_lopen", 6),
    91: ("InitTask", 0),
    95: ("LoadLibrary", 4),
    102: ("DOS3Call", 0),
    30: ("WaitEvent", 2),
    128: ("GetPrivateProfileString", 22),
    132: ("GetWinFlags", 0),
}

USER = {
    1: ("MessageBox", 12),
    108: ("GetMessage", 10),
    111: ("SendMessage", 10),
    176: ("LoadString", 10),
    266: ("SetMessageQueue", 2),
}

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

    def equate(self, module, ordinal):
        return EQUATES.get(module.upper(), {}).get(ordinal)

    @staticmethod
    def missing(module, ordinal):
        return f"unimplemented {module}.{ordinal}: no contract, pop size not guessed"

    def answer(self, module, ordinal, arg):
        """arg(n) reads Pascal argument n. Returns (ax, dx, stop)."""
        label = self.contract(module, ordinal)
        name = label[0] if label else str(ordinal)
        self.trace.append(f"{module}.{ordinal} {name}")
        if label is None:
            return 0, 0, self.missing(module, ordinal)
        if module == "KERNEL":
            return self._kernel(ordinal, arg)
        if module == "USER":
            return self._user(ordinal, arg)
        return 0, 0, self.missing(module, ordinal)

    def _kernel(self, ordinal, arg):
        if ordinal == 3:
            return 0x0A03, 0, None
        if ordinal == 132:
            return EQUATES["KERNEL"][178][1], 0, None
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
