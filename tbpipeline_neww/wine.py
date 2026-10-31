"""Windows inside the sandbox.

A system ordinal is a gate: the guest far-calls it, the gate stops the
CPU, this module answers, and the gate's retf pops the Pascal arguments.
An ordinal with no contract stops the run. It does not invent a pop size.
"""

import struct
from pathlib import Path

from .local import LocalHeap, Stop as LocalStop
from .resource import NE_SEGFLAGS_MOVEABLE, Resources, Stop as ResourceStop, res_name
from .spec_rows import SPEC_ROWS
from .handlers import HANDLERS
from .kstate import KernelState
from .guest import Call, GuestCalls

# Wine Win16 spec files, read at this commit. A row cites file and ordinal.
WINE_COMMIT = "2528aff26208257fdbf980666a4f0e66d47563ce"
KERNEL_SPEC = "dlls/krnl386.exe16/krnl386.exe16.spec"
USER_SPEC = "dlls/user.exe16/user.exe16.spec"
GDI_SPEC = "dlls/gdi.exe16/gdi.exe16.spec"
MMSYSTEM_SPEC = "dlls/mmsystem.dll16/mmsystem.dll16.spec"
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

    def __init__(self, module, ordinal, name, args, ret, spec=None, binary=None, value=None, default=False, void=False):
        self.module = module
        self.ordinal = ordinal
        self.name = name
        self.args = tuple(args)
        self.ret = ret
        self.spec = spec
        self.binary = binary
        # (ax, dx) when the answer is a constant. The row is the whole contract.
        self.value = value
        # A row loaded from spec_rows.py with no handler written for it. Its answer is
        # the default: 0 for a word or a long, AX left for a void, a stop for -register.
        self.default = default
        # Wine's C function returns void, so there is no answer to give.
        self.void = void

    caller_pops = False

    @property
    def pop(self):
        return 0 if self.caller_pops else sum(self.args)

    @property
    def disagreement(self):
        if self.binary is None or self.binary == self.pop:
            return None
        where = f"{self.spec[0]}:{self.ordinal}" if self.spec else "row"
        return f"{self.module}.{self.ordinal} {self.name}: {where} pops {self.pop}, binary pops {self.binary}"

    @classmethod
    def from_spec(cls, module, path, line, binary=None, value=None, default=False, void=False):
        """line is the Wine spec entry, ordinal first, as the file has it."""
        head, _, rest = line.partition("(")
        words = head.split()
        ordinal = int(words[0])
        if words[1] not in ("pascal", "varargs"):
            raise ValueError(f"{path}:{ordinal} is {words[1]}, not a pascal or varargs entry")
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
        row = cls(module, ordinal, name, args, ret, spec=(path, line), binary=binary, value=value,
                  default=default, void=void)
        # A varargs entry is cdecl: the caller pops, so the gate's retf pops nothing.
        row.caller_pops = words[1] == "varargs"
        return row

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
    "7   pascal -ret16 LocalFree(word) LocalFree16",
    "15  pascal -ret16 GlobalAlloc(word long) GlobalAlloc16",
    "17  pascal -ret16 GlobalFree(word) GlobalFree16",
    "18  pascal GlobalLock(word) WIN16_GlobalLock16",
    "20  pascal GlobalSize(word) GlobalSize16",
    "23  pascal -ret16 LockSegment(word) LockSegment16",
    "24  pascal -ret16 UnlockSegment(word) UnlockSegment16",
    "30  pascal -ret16 WaitEvent(word) WaitEvent16",
    "36  pascal   GetCurrentTask() WIN16_GetCurrentTask",
    "55  pascal -register Catch(ptr) Catch16",
    "56  pascal -register Throw(ptr word) Throw16",
    "47  pascal   GetModuleHandle(segstr) WIN16_GetModuleHandle",
    "49  pascal -ret16 GetModuleFileName(word ptr s_word) GetModuleFileName16",
    "50  pascal GetProcAddress(word str) GetProcAddress16",
    "60  pascal -ret16 FindResource(word str str) FindResource16",
    "61  pascal -ret16 LoadResource(word word) LoadResource16",
    "62  pascal LockResource(word) WIN16_LockResource16",
    "63  pascal -ret16 FreeResource(word) FreeResource16",
    "64  pascal -ret16 AccessResource(word word) AccessResource16",
    "65  pascal SizeofResource(word word) SizeofResource16",
    "74  pascal -ret16 OpenFile(str ptr word) OpenFile16",
    "81  pascal -ret16 _lclose(word) _lclose16",
    "82  pascal -ret16 _lread(word segptr word) WIN16_lread",
    "84  pascal   _llseek(word long word) _llseek16",
    "85  pascal -ret16 _lopen(str word) _lopen16",
    "91  pascal -register InitTask() InitTask16",
    "198 pascal -ret16 GlobalUnfix(word) GlobalUnfix16",
    "131 pascal GetDOSEnvironment() GetDOSEnvironment16",
    "95  pascal -ret16 LoadLibrary(str) LoadLibrary16",
    "102 pascal -register DOS3Call() DOS3Call",
    # The enhanced-mode word, the same as the __WINFLAGS equate below. DX 0, as in newl.
    ("132 pascal GetWinFlags() GetWinFlags16", (0x0C25, 0)),
])

USER = _table("USER", USER_SPEC, [
    "1   pascal -ret16 MessageBox(word str str word) MessageBox16",
    "5   pascal -ret16 InitApp(word) InitApp16",
    "420 varargs -ret16 _wsprintf(ptr str) wsprintf16",
    "66  pascal -ret16 GetDC(word) GetDC16",
    "68  pascal -ret16 ReleaseDC(word word) ReleaseDC16",
    "108 pascal -ret16 GetMessage(ptr word word word) GetMessage16",
    "111 pascal   SendMessage(word word word long) SendMessage16",
    "118 pascal -ret16 RegisterWindowMessage(str) RegisterWindowMessageA",
    "179 pascal -ret16 GetSystemMetrics(s_word) GetSystemMetrics16",
    "176 pascal -ret16 LoadString(word word ptr s_word) LoadString16",
    "266 pascal -ret16 SetMessageQueue(word) SetMessageQueue16",
    "291 pascal   SetWindowsHookEx(s_word segptr word word) SetWindowsHookEx16",
])

# win32u sysparams.c get_system_metrics: the indices that return a constant. SM_CXBORDER and
# SM_CYBORDER are 1 "regardless of 'BorderWidth' value in registry". SM_CMETRICS is 90.
METRICS = {
    5: 1, 6: 1, 7: 3, 8: 3, 18: 0, 19: 1, 22: 0, 24: 0, 25: 0, 26: 0, 27: 0, 41: 0, 43: 3, 44: 0,
    63: 3, 67: 0, 73: 0, 74: 0, 75: 1, 81: 1, 82: 0, 83: 1, 84: 1, 86: 0, 87: 0, 90: 90,
}

# SM_CXSCREEN and SM_CYSCREEN are the primary monitor. neww has no display driver, and with a
# driver that does not implement UpdateDisplayDevices Wine's default_update_display_devices
# exposes one monitor in modes[2], 1024x768, when no current mode is saved in the registry.
METRICS[0], METRICS[1] = 1024, 768

# SM_CXFRAME and SM_CYFRAME are SM_CXDLGFRAME 3 plus max(BorderWidth, 1). BorderWidth is
# TWIPS_ENTRY( BORDER, -15, ...), and get_twips_entry turns -15 twips into muldiv(15, dpi, 1440)
# pixels. A Win16 task is DPI unaware, so get_system_dpi is USER_DEFAULT_SCREEN_DPI 96: 1 pixel.
METRICS[32], METRICS[33] = 3 + 1, 3 + 1

# SM_CYCAPTION is SPI_GETNONCLIENTMETRICS iCaptionHeight + 1. iCaptionHeight is
# TWIPS_ENTRY( CAPTIONHEIGHT, -270, ... ), muldiv(270, 96, 1440) = 18 pixels, and
# normalize_nonclientmetrics raises it to 2 + tmHeight of the caption font if that is more.
# The caption font defaults to DEFAULT_GUI_FONT at -11 pixels, bold. Wine's Tahoma Bold
# (fonts/tahomabd.sfd, OS2WinAscent 2049 + OS2WinDescent 423 over 2048 units) is
# 11 * 2472 / 2048 = 13 pixels tall, so 18 stands.
METRICS[4] = 18 + 1

# The other cases of that switch. Any index that is not a case returns 0.
METRICS_FROM_HOST = frozenset([
    2, 3, 9, 10, 11, 12, 13, 14, 15, 16, 17, 20, 21, 23, 28, 29, 30, 31, 34, 35,
    36, 37, 38, 39, 40, 42, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62,
    68, 69, 70, 71, 72, 76, 77, 78, 79, 80,
])

GDI = _table("GDI", GDI_SPEC, [
    "80  pascal -ret16 GetDeviceCaps(word s_word) GetDeviceCaps16",
])

# win32u driver.c nulldrv_GetDeviceCaps, for the screen DC with no display driver: the
# null user driver's DC functions are nulldrv's. The display is default_update_display_devices'
# modes[2], 1024x768 at 32 bits and 60 Hz, and a Win16 task is DPI unaware, 96 dpi. Sizes in
# millimetres are win32u mapping.c muldiv(res, 254, dpi * 10), which rounds to nearest.
# SIZEPALETTE is 0, so RASTERCAPS has no RC_PALETTE. A cap with no case is 0.
SCREEN_CAPS = {
    0: 0x4000,      # DRIVERVERSION
    2: 1,           # TECHNOLOGY, DT_RASDISPLAY
    4: 271,         # HORZSIZE, muldiv(1024, 254, 960)
    6: 203,         # VERTSIZE, muldiv(768, 254, 960)
    8: 1024,        # HORZRES
    10: 768,        # VERTRES
    12: 32,         # BITSPIXEL, get_display_depth of the current mode
    14: 1,          # PLANES
    16: -1,         # NUMBRUSHES
    18: -1,         # NUMPENS
    24: -1,         # NUMCOLORS, -1 above 4 bits
    28: 0x01FF,     # CURVECAPS
    30: 0x00FE,     # LINECAPS
    32: 0x00FF,     # POLYGONALCAPS
    34: 0x79F7,     # TEXTCAPS
    36: 1,          # CLIPCAPS, CP_RECTANGLE
    38: 0xBE99,     # RASTERCAPS
    40: 36,         # ASPECTX
    42: 36,         # ASPECTY
    44: 51,         # ASPECTXY, (int)(hypot(36, 36) + 0.5)
    88: 96,         # LOGPIXELSX
    90: 96,         # LOGPIXELSY
    106: 20,        # NUMRESERVED
    108: 24,        # COLORRES, min(24, 32)
    116: 60,        # VREFRESH
    117: 768,       # DESKTOPVERTRES
    118: 1024,      # DESKTOPHORZRES
}

MMSYSTEM = _table("MMSYSTEM", MMSYSTEM_SPEC, [
    # winmm waveform.c waveOutGetNumDevs is g_outmmdevices_count, mmdevapi's render endpoints.
    # neww has no audio driver. With none of pulse, alsa, oss or coreaudio loaded, mmdevapi
    # init_driver loads no devices, so the count is 0.
    ("401 pascal waveOutGetNumDevs() waveOutGetNumDevs16", (0, 0)),
])

WIN87EM = _table("WIN87EM", WIN87EM_SPEC, [
    "1 pascal -register __fpMath()",
])

# Constants, not code. A fixup stores the value.
EQUATES = {
    "KERNEL": {113: ("__AHSHIFT", 3), 114: ("__AHINCR", 8), 178: ("__WINFLAGS", 0x0C25)},
}

# Every pascal entry of every Win16 spec file, from spec_rows.py (specgen.py wrote it from the
# Wine checkout at WINE_COMMIT). A hand row above, with its handler, wins over the loaded row.
SPEC_PATHS = {
    "KERNEL": KERNEL_SPEC, "USER": USER_SPEC, "GDI": GDI_SPEC, "MMSYSTEM": MMSYSTEM_SPEC,
    "WIN87EM": WIN87EM_SPEC,
    "KEYBOARD": "dlls/keyboard.drv16/keyboard.drv16.spec",
    "SHELL": "dlls/shell.dll16/shell.dll16.spec",
    "COMMDLG": "dlls/commdlg.dll16/commdlg.dll16.spec",
    "TOOLHELP": "dlls/toolhelp.dll16/toolhelp.dll16.spec",
    "COMPOBJ": "dlls/compobj.dll16/compobj.dll16.spec",
    "OLE2": "dlls/ole2.dll16/ole2.dll16.spec",
    "OLE2DISP": "dlls/ole2disp.dll16/ole2disp.dll16.spec",
    "DDEML": "dlls/ddeml.dll16/ddeml.dll16.spec",
    "VER": "dlls/ver.dll16/ver.dll16.spec",
}
def _loaded(module, line, void, value=None):
    """A loaded row. A Wine stub's constant return is the row's value: its answer, not a default."""
    row = Contract.from_spec(module, SPEC_PATHS[module], line, default=True, void=void)
    if value is not None and row.ret != "register":
        value &= 0xFFFFFFFF
        row.value = (value & 0xFFFF, (value >> 16) if row.ret == "long" else 0)
        row.default = False
    return row


LOADED = {
    module: {row.ordinal: row for row in (_loaded(module, *item) for item in rows)}
    for module, rows in SPEC_ROWS.items()
}
HAND = {"KERNEL": KERNEL, "USER": USER, "GDI": GDI, "MMSYSTEM": MMSYSTEM, "WIN87EM": WIN87EM}


def row_for(module, ordinal):
    """The hand row if there is one, else the loaded spec row, else None."""
    module = module.upper()
    return HAND.get(module, {}).get(ordinal) or LOADED.get(module, {}).get(ordinal)


# Wine task.c TASK_Create: cmdShow is 1, SW_SHOWNORMAL, unless the startup info sets one.
SW_SHOWNORMAL = 1

# The --b directory as the guest sees it, in module paths. Wine would show the host
# directory through a DOS drive. Any directory finds the file: resolve() goes by base name.
BIN_DIR = "C:\\TBK"

# Wine hook.c: WH_MINHOOK is WH_MSGFILTER (-1), Win16 goes up to WH_SHELL (10), and only
# these indexes (id - WH_MINHOOK) have a hook_procs entry.
WH_MINHOOK = -1
WH_MAXHOOK16 = 10
HOOKS16 = {0: "WH_MSGFILTER", 3: "WH_KEYBOARD", 4: "WH_GETMESSAGE", 5: "WH_CALLWNDPROC", 6: "WH_CBT", 8: "WH_MOUSE", 11: "WH_SHELL"}

GMEM_MOVEABLE = 0x0002
LOCAL_HEAP_MAGIC = 0x484C
HFILE_ERROR = 0xFFFF
OF_SHARE_MASK = 0x0070

# The Windows modules ToolBook imports. Wine builds each as a 16-bit DLL with a spec file in
# dlls/<name>.dll16 or .exe16, so each is a gate, and an ordinal with no contract stops by name.
SYSTEM = (
    "KERNEL", "USER", "GDI", "SHELL", "KEYBOARD", "WIN87EM", "COMMDLG", "TOOLHELP", "COMPOBJ", "OLE2",
    "MMSYSTEM", "DDEML", "OLE2DISP", "VER",
)


def moveable_handle(sel):
    """A moveable block's handle: its selector with the table bit set.

    Wine's handle is the selector - 1, the same LDT entry at RPL 2, so a guest can load the
    handle as a selector. neww's selectors are GDT entries at RPL 0, and Machine copies each
    one into the LDT at the same index, so the selector with TI set loads the same block.
    """
    return sel | 4


class Wine(KernelState):
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
        # (module, ordinal, name, "0" or "void") for each call a loaded row answered by default.
        self.defaults = []
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
        # Module name -> module handle, and the head of the module list. Set by the machine.
        self.modules = {}
        self.first_module = 0
        # Set by the machine: selector -> path of the NE file whose segment it is, or None.
        self.owner = None
        # Win16 hooks: index (id - WH_MINHOOK) -> (HHOOK, 16-bit proc), Wine hook.c hook16_queue_info.
        self.hooks = {}
        self.dcs = {}
        # NE file path -> its Resources, read the first time a resource call names the module.
        self.tables = {}
        # Set by the machine: read(sel, off, n), linear(sel), write_linear(addr, bytes),
        # resize(sel, new, old) -> stop or None, is_code(sel), is_dll(path).
        self.read = None
        self.linear = None
        self.write_linear = None
        self.resize = None
        self.is_code = None
        self.is_dll = None
        # Set by the machine: instance_of(path) -> the module's instance handle,
        # entry_point(path, ordinal or name) -> (selector, offset) or None.
        self.instance_of = None
        self.entry_point = None
        self.exe_name = "TB80RTM"
        # Gate module name -> its module handle, and gate_address(module, ordinal) -> (sel, off).
        self.system_modules = {}
        # (text, caption, type) of each MessageBox the guest showed.
        self.messageboxes = []
        self.gate_address = None
        # Set by the machine: load_module(base name) -> (module handle or None, [Call]).
        self.load_module = None
        # Set by the machine: a code selector for MakeProcInstance thunks, and the next free offset.
        self.thunk_block = None
        self.thunk_next = 0
        self.alloc_code = None
        self._kstate()
        self.htask = 0
        # Registered window messages: lower-case name -> atom, from MAXINTATOM (0xC000) up.
        self.messages = {}
        # Original name -> atom, references per atom, and the next number to give.
        self.atom_names = {}
        self.atom_refs = {}
        self.next_atom = 0xC000
        # selector -> lockCount, Wine's GLOBALARENA field, for LockSegment.
        self.locks = {}
        # Selector of the DOS environment block, set by the machine with the PSP.
        self.environment = None
        # Wine win87em.c statics. Installed is TRUE: an x87 is present.
        self.ctrl_word_1 = 0
        self.status_word_2 = 0

    def contract(self, module, ordinal):
        return row_for(module, ordinal)

    def usable(self, module, ordinal):
        """The row the gate may pop, or None. A disagreeing row is not usable.

        A loaded -register row is not usable: it sets registers no default can name,
        so its stub has no retf and the call stops, as an ordinal with no row does.
        """
        row = self.contract(module, ordinal)
        if row is None or row.disagreement:
            return None
        if self.defaulted(row) and row.ret == "register":
            return None
        return row

    @staticmethod
    def defaulted(row):
        """A loaded row that no hand row and no handler answers."""
        return row.default and (row.module, row.ordinal) not in HANDLERS

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
        handler = HANDLERS.get((label.module, label.ordinal))
        if handler is not None:
            return handler(self, arg)
        if label.default:
            return self._default(label, arg)
        if module == "KERNEL":
            return self._kernel(ordinal, arg)
        if module == "USER":
            return self._user(ordinal, arg)
        if module == "GDI":
            return self._gdi(ordinal, arg)
        if module == "WIN87EM" and ordinal == 1:
            return self._fpmath(arg)
        return 0, 0, self.missing(module, ordinal)

    def _default(self, row, arg):
        """A loaded spec row with no handler. Never AX = 1.

        -register stops: the call sets registers, and 0 in each is not Wine's answer.
        A void function has no answer, so AX is left as the call found it, and DX is 0
        as the void handlers above leave it. A word or a long is 0.
        """
        where = f"{row.spec[0]}:{row.ordinal}"
        if row.ret == "register":
            return 0, 0, (
                f"register {row.module}.{row.ordinal} {row.name}: {where} is -register, "
                "so it sets registers and a default answer would be made up"
            )
        if row.void:
            self.defaults.append((row.module, row.ordinal, row.name, "void"))
            self.trace[-1] += " (default: void, AX left)"
            return arg.regs("ax"), 0, None
        self.defaults.append((row.module, row.ordinal, row.name, "0"))
        self.trace[-1] += f" (default: {row.ret} 0)"
        return 0, 0, None

    def _kernel(self, ordinal, arg):
        if ordinal == 91:
            return self._init_task(arg)
        if ordinal == 4:
            # LocalInit(word selector, word start, word end). Wine also returns the result in CX.
            ok = self.local_init(arg(2), arg(1), arg(0), arg.regs("ds"))
            self.registers = {"cx": ok}
            return ok, 0, None
        if ordinal == 7:
            # LocalFree(word handle) in CURRENT_DS.
            heap = LocalHeap(arg.regs("ds"), arg.word, self.write)
            try:
                return heap.free(arg(0)), 0, None
            except LocalStop as why:
                return 0, 0, f"KERNEL.7 LocalFree({arg(0):#x}): {why}"
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
        if ordinal == 198:
            # Wine global.c GlobalUnfix16 is void: lockCount goes down, AX is left as it was.
            # Unlike UnlockSegment16, -1 is not CURRENT_DS.
            sel = self.selector_of(arg(0))
            if sel is not None:
                self.locks[sel] = self.locks.get(sel, 0) - 1
            return arg.regs("ax"), 0, None
        if ordinal in (60, 61, 62, 63, 64, 65):
            return self._resource(ordinal, arg)
        if ordinal == 55:
            return self._catch(arg)
        if ordinal == 56:
            return self._throw(arg)
        if ordinal == 36:
            # WIN16_GetCurrentTask: the current task in AX, hFirstTask in DX.
            return self.htask, self.htask, None
        if ordinal == 47:
            # WIN16_GetModuleHandle(segstr name): the module in AX, hFirstModule in DX.
            if arg(1) == 0:
                return self._exe_ptr(arg(0)), self.first_module, None
            return self._module_handle(arg.string(0))
        if ordinal == 49:
            # GetModuleFileName(word hModule, ptr buffer, s_word size)
            size = arg(0) - 0x10000 if arg(0) & 0x8000 else arg(0)
            return self._module_file_name(arg(3), arg(2), arg(1), size)
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
            return self._global_lock(arg(0), arg.regs("ds"))
        if ordinal == 20:
            size = self._global_size(arg(0))
            return size & 0xFFFF, size >> 16, None
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
        if ordinal == 95:
            return self._load_library(arg.string(0))
        if ordinal == 50:
            # GetProcAddress(word hModule, str name): an ordinal when the selector is 0.
            name = arg(0) if arg(1) == 0 else arg.string(0)
            return self._get_proc_address(arg(2), name)
        if ordinal == 176:
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
        name = path.replace("/", "\\").rsplit("\\", 1)[-1].upper()
        if host is None and name in self.written:
            # A file the guest created this run: read and written in memory.
            self.files[handle] = [path, None, self.written[name], 0]
        else:
            self.files[handle] = [path, host, Path(host).read_bytes(), 0]
        return handle

    def _open_file(self, path, ofs_sel, ofs_off, mode):
        """Wine file.c OpenFile16. Read, OF_EXIST, OF_CREATE; any other mode stops."""
        OF_EXIST, OF_CREATE = 0x4000, 0x1000
        if mode & OF_CREATE:
            if mode & ~(OF_SHARE_MASK | 0x0003 | OF_CREATE):
                return 0, 0, f"KERNEL.74 OpenFile {path!r} mode {mode:#06x}: neww has OF_CREATE only on its own"
            handle = self.create_file(path)
            ofs = bytearray(136)
            ofs[0] = 136
            name = path.encode("latin1", "replace")[:127]
            ofs[8:8 + len(name)] = name
            self._put(ofs_sel, ofs_off, ofs)
            return handle, 0, None
        if mode & ~(OF_SHARE_MASK | 0x0003 | OF_EXIST) or mode & 0x0003:
            return 0, 0, f"KERNEL.74 OpenFile {path!r} mode {mode:#06x}: neww opens files to read and nothing else"
        name_only = path.replace("/", "\\").rsplit("\\", 1)[-1]
        if not name_only:
            # A directory: GetFullPathName gives it, and _lopen of a directory fails, ERROR_ACCESS_DENIED.
            ofs = bytearray(136)
            ofs[0] = 136
            struct.pack_into("<H", ofs, 2, 5)
            self._put(ofs_sel, ofs_off, ofs)
            return HFILE_ERROR, 0, None
        if name_only.upper() in self.written:
            handle = self._handle(path, None)
            if mode & OF_EXIST:
                self.files.pop(handle, None)
            return handle, 0, None
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
        if mode & OF_EXIST:
            # Wine returns the handle, but closes it first.
            self.files.pop(handle, None)
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
        if bx == 7:
            # Wine's fistp is commented out ("could someone who really understands asm() fix
            # this"): dw stays 0, DX:AX is 0, and the x87 stack is not popped.
            self.registers = {"dx": 0}
            return 0, 0, None
        if bx == 8:
            # fstsw into StatusWord_1, its low 6 bits OR StatusWord_2, bits 13-15 cleared.
            ax = ((arg.regs("fpsw") & 0x3F) | self.status_word_2) & ~0xE000
            self.status_word_2 = ax
            self.registers = {}
            return ax, 0, None
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
            f"WIN87EM.1 __fpMath BX={bx}: Wine win87em.c rounds on the host x87 here "
            "(6 frndint), or has no case. neww does not answer it"
        )

    def alloc_thunk(self):
        """TASK_AllocThunk: 8 bytes in a thunk segment, a new segment when one is full."""
        if self.thunk_block is None or self.thunk_next + 8 > 0x1000:
            self.thunk_block = self.alloc_code(0x1000)
            self.thunk_next = 0
        off = self.thunk_next
        self.thunk_next += 8
        return self.thunk_block, off

    def _load_library(self, name):
        """Wine ne_module.c LoadLibrary16 -> LoadModule16(name, -1).

        A module neww already loaded is found by module name, then by file base name, as
        GetModuleHandle16 finds it, and the answer is its instance (NE_GetInstance: the DGROUP
        handle, or the module handle when there is none). neww loads every NE file in --b at the
        start, so a name that is none of them is not found, error 2. A system module stops.
        """
        base = name.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(":", 1)[-1]
        stem = base.rsplit(".", 1)[0].upper()
        if stem in SYSTEM:
            # Wine's builtin. neww's is the gate module, with a module handle of its own.
            handle = self.system_modules.get(stem)
            if handle is None:
                return 0, 0, f"KERNEL.95 LoadLibrary({name!r}): nothing imports {stem}, so neww made no gate for it"
            self.trace[-1] += f" {name!r} -> gate module {handle:#x}"
            return handle, 0, None
        module = self.modules.get(stem)
        if module is None:
            for mname, handle in self.modules.items():
                if Path(self.owner(handle)).name.upper() == base.upper():
                    module = handle
                    break
        calls = []
        if module is None and self.load_module is not None:
            # A file in --b that nothing imported: Wine's NE_LoadModule loads it now, and
            # NE_InitializeDLLs runs its LibMain and those of DLLs it loads first.
            module, calls = self.load_module(base)
        if module is None:
            self.trace[-1] += f" {name!r} not found"
            return 2, 0, None
        instance = self.instance_of(self.owner(module)) or module
        self.trace[-1] += f" {name!r} -> {instance:#x}"
        if calls:
            self.trace[-1] += f", LibMain of {', '.join(c.name for c in calls)}"
            self.registers = {"guest": GuestCalls(calls, lambda results: (instance, 0))}
        return instance, 0, None

    def _get_proc_address(self, handle, name):
        """Wine ne_module.c GetProcAddress16: GetExePtr, then NE_GetOrdinal for a name (resident,
        then nonresident names, the name upper-cased), then NE_GetEntryPoint. 0 when not found."""
        for stem, sys_handle in self.system_modules.items():
            if handle == sys_handle:
                # A gate module: the stub of the spec row with that ordinal or name.
                if isinstance(name, str):
                    want = name.upper()
                    rows = {**LOADED.get(stem, {}), **HAND.get(stem, {})}
                    name = next((o for o, r in rows.items() if r.name.upper() == want), None)
                found = self.gate_address(stem, name) if name is not None else None
                self.trace[-1] += f" {stem}.{name} -> {'%#x:%#x' % found if found else 'none'}"
                return (found[1], found[0], None) if found else (0, 0, None)
        module = self._exe_ptr(handle) if handle else self.modules.get(self.exe_name, 0)
        path = self.owner(module) if module else None
        if path is None:
            return 0, 0, None
        found = self.entry_point(path, name)
        self.trace[-1] += f" {name!r} -> {'%#x:%#x' % found if found else 'none'}"
        if not found:
            return 0, 0, None
        return found[1], found[0], None

    def _exe_ptr(self, handle):
        """GetExePtr: the module handle of whatever module owns the handle's block, or 0."""
        sel = self.selector_of(handle)
        owner = self.owner(sel) if sel is not None else None
        if owner is None:
            return 0
        for name, module in self.modules.items():
            if self.owner(module) == owner:
                return module
        return 0

    def _module_handle(self, name):
        """Wine ne_module.c GetModuleHandle16, over neww's modules. Returns (ax, dx, stop)."""
        if not name:
            return 0, self.first_module, None
        base = name.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(":", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        if name.upper() in SYSTEM or stem.upper() in SYSTEM:
            # Wine's builtin modules are on the same list, by module name and by file name.
            handle = self.system_modules.get(stem.upper())
            if handle is None:
                return 0, 0, f"KERNEL.47 GetModuleHandle({name!r}): nothing imports {stem.upper()}, so neww made no gate for it"
            return handle, self.first_module, None
        # The module name without case (Wine's exact and upper-cased passes), then the base
        # name against the base name of the loaded file.
        for module, handle in self.modules.items():
            if name.upper() == module:
                return handle, self.first_module, None
        for module, handle in self.modules.items():
            if Path(self.owner(handle)).name.upper() == base.upper():
                return handle, self.first_module, None
        return 0, self.first_module, None

    def _module_file_name(self, handle, sel, off, size):
        """Wine ne_module.c GetModuleFileName16: the module's path, lstrcpynA into the buffer."""
        if handle == 0:
            # Wine: GetCurrentTask(), whose module is the executable.
            handle = self.task["instance"] if self.task else 0
        owner = self.owner(self.selector_of(handle)) if self.selector_of(handle) is not None else None
        if owner is None:
            # NE_GetPtr finds no module.
            return 0, 0, None
        name = Path(owner).name.upper()
        stem, _, ext = name.partition(".")
        if len(stem) > 8 or len(ext) > 3 or "." in ext:
            return 0, 0, f"KERNEL.49 GetModuleFileName: {name} has no 8.3 name, and Wine's GetShortPathNameA would make one"
        path = f"{BIN_DIR}\\{name}".encode("latin1")
        if size <= 0:
            return 0, 0, None
        path = path[:size - 1]
        self._put(sel, off, path + b"\x00")
        return len(path), 0, None

    def _set_windows_hook(self, id_, proc, task):
        """Wine user.exe16/hook.c SetWindowsHookEx16. Returns (ax, dx, stop): the HHOOK in DX:AX."""
        index = id_ - WH_MINHOOK
        if id_ < WH_MINHOOK or id_ > WH_MAXHOOK16:
            return 0, 0, None
        if index not in HOOKS16:
            # Wine: "hook type %d broken in Win16".
            return 0, 0, None
        if task:
            return 0, 0, f"USER.291 SetWindowsHookEx hTask={task:#x}: Wine compares it with GetCurrentTask, and neww has no task handle"
        if index in self.hooks:
            # Wine: "Multiple hooks (%d) for the same task not supported yet".
            return 0, 0, None
        # Wine returns user32's HHOOK. neww numbers its own from 0x00010001.
        hook = 0x00010001 + len(self.hooks)
        self.hooks[index] = (hook, proc)
        return hook & 0xFFFF, hook >> 16, None

    def _get_dc(self, hwnd):
        """Wine user.exe16/window.c GetDC16: HDC_16 of user32 GetDC. Returns (ax, dx, stop).

        hwnd 0 is the screen, a DCX_CACHE DCE of the desktop window. win32u dce.c
        NtUserGetDCEx takes the first released DCE of that window in dce_list, which
        list_add_head keeps newest first, or allocates a new one. Wine's HDC is a win32u
        GDI handle. neww numbers its own from 0x1004 by 4, which is never a selector.
        """
        if hwnd:
            return 0, 0, f"USER.66 GetDC({hwnd:#x}): Wine gets a DC for that window, and neww has no windows"
        free = [hdc for hdc, used in self.dcs.items() if not used]
        hdc = max(free) if free else 0x1004 + 4 * len(self.dcs)
        self.dcs[hdc] = True
        return hdc, 0, None

    def _release_dc(self, hwnd, hdc):
        """Wine ReleaseDC16, win32u dce.c release_dc: 1 for a DC in use, which goes back to the cache.

        release_dc does not look at hwnd.
        """
        if not self.dcs.get(hdc):
            return 0, 0, None
        self.dcs[hdc] = False
        return 1, 0, None

    def _register_window_message(self, name):
        """RegisterWindowMessageA: a string atom, 0xC000 to 0xFFFF, the same for the same name.

        Wine adds the name to the session's global atom table, so the number depends
        on what the session registered first. neww's table starts empty at 0xC000.
        An empty name or one over 255 characters is not an atom, and the answer is 0.
        """
        if not name or len(name) > 255:
            return 0
        return self.add_atom(name)

    def add_atom(self, name):
        """A string atom in the global table, one reference more. The same name, without case,
        is the same atom. Atoms are numbered from 0xC000 in the order names first arrive."""
        key = name.lower()
        if key not in self.messages:
            if self.next_atom > 0xFFFF:
                return 0
            self.messages[key] = self.next_atom
            self.atom_names[name] = self.next_atom
            self.next_atom += 1
        atom = self.messages[key]
        self.atom_refs[atom] = self.atom_refs.get(atom, 0) + 1
        return atom

    def delete_atom(self, atom):
        """GlobalDeleteAtom: 0 when the reference was dropped, the atom when it is not one."""
        if atom < 0xC000:
            return 0
        if atom not in self.atom_refs:
            return atom
        self.atom_refs[atom] -= 1
        if self.atom_refs[atom] <= 0:
            del self.atom_refs[atom]
            self.messages = {k: v for k, v in self.messages.items() if v != atom}
            self.atom_names = {k: v for k, v in self.atom_names.items() if v != atom}
        return 0

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

    def _global_lock(self, handle, ds):
        """Wine global.c WIN16_GlobalLock16: the SEGPTR (selector, 0) in DX:AX, and the selector in CX.

        K32WOWGlobalLock16: -1 is CURRENT_DS, and an invalid handle is selector 0. A valid one
        counts a lock. Handle 0 gives GlobalHandleToSel16(0), 0, with no lock.
        """
        sel = 0
        if handle:
            if handle == 0xFFFF:
                handle = ds
            found = self.selector_of(handle)
            if found is not None:
                sel = found
                self.locks[sel] = self.locks.get(sel, 0) + 1
        self.registers = {"cx": sel}
        return 0, sel, None

    def _catch(self, arg):
        """Wine thunk.c Catch16: the caller's registers into the 9-word CATCHBUF, and AX 0.

        winebuild's __wine_call_from_16_regs gives a register function the caller's CS:IP and,
        in Esp, the SP at the far return address: the stub's retf pops the arguments after.
        Windows saves SP 4 words lower. Word 7 is 0.
        """
        off, sel = arg(0), arg(1)
        size = self.size(sel)
        if size is None or off + 18 > size:
            return 0, 0, f"KERNEL.55 Catch({sel:#x}:{off:#x}): the CATCHBUF is not in a block neww has"
        esp = arg.regs("sp")
        ip, cs = arg.word(arg.regs("ss"), esp), arg.word(arg.regs("ss"), esp + 2)
        words = (
            ip, cs, (esp - 8) & 0xFFFF, arg.regs("bp"), arg.regs("si"), arg.regs("di"),
            arg.regs("ds"), 0, arg.regs("ss"),
        )
        self.write(sel, off, struct.pack("<9H", *words))
        return 0, 0, None

    def resources(self, handle):
        """The resource table of the module a handle names (Wine get_module: NE_GetPtr), or None."""
        module = self._exe_ptr(handle) if handle else 0
        path = self.owner(module) if module else None
        if path is None:
            return None
        table = self.tables.get(path)
        if table is None:
            table = self.tables[path] = Resources(path)
        return table

    def _resource(self, ordinal, arg):
        """Wine resource.c FindResource16, LoadResource16, WIN16_LockResource16, FreeResource16,
        SizeofResource16, for NE modules. Returns (ax, dx, stop)."""
        if ordinal == 60:
            # FindResource(word hModule, str name, str type)
            table = self.resources(arg(4))
            if table is None:
                return 0, 0, None
            name = res_name(arg(2), arg(3), arg.machine.string)
            type_ = res_name(arg(0), arg(1), arg.machine.string)
            try:
                hrsrc = table.find(name, type_)
            except ResourceStop as why:
                return 0, 0, f"KERNEL.60 FindResource({name!r}, {type_!r}): {why}"
            self.trace[-1] += f" {name!r} type {type_!r} -> {hrsrc:#x}"
            return hrsrc, 0, None
        if ordinal == 61:
            # LoadResource(word hModule, word hRsrc): NE_DefResourceHandler reads it into a new block.
            hrsrc = arg(0)
            table = self.resources(arg(1))
            if not hrsrc or table is None or table.entry(hrsrc) is None:
                return 0, 0, None
            got = table.loaded.get(hrsrc)
            if got and got[0] in self.heap:
                got[1] += 1
                return got[0], 0, None
            data = table.bytes_of(hrsrc)
            flags = 0x0002 if table.entry(hrsrc)[2] & NE_SEGFLAGS_MOVEABLE else 0
            handle, _dx, why = self._global_alloc(flags, max(len(data), 1))
            if why:
                return 0, 0, f"KERNEL.61 LoadResource({hrsrc:#x}): {why}"
            self._put(self.heap[handle][0], 0, data)
            table.loaded[hrsrc] = [handle, 1]
            return handle, 0, None
        if ordinal == 62:
            # WIN16_LockResource16 is WOWGlobalLock16: the SEGPTR (selector, 0).
            sel = self.selector_of(arg(0)) if arg(0) else None
            return 0, sel or 0, None
        if ordinal == 63:
            # FreeResource16: the usage count goes down and the block is freed at 0. FALSE either way.
            handle = arg(0)
            for table in self.tables.values():
                for hrsrc, got in list(table.loaded.items()):
                    if got[0] == handle:
                        got[1] -= 1
                        if got[1] <= 0:
                            self.heap.pop(handle, None)
                            del table.loaded[hrsrc]
                        return 0, 0, None
            return 0, 0, f"KERNEL.63 FreeResource({handle:#x}): not a resource, and Wine would call USER.DestroyIcon32"
        if ordinal == 64:
            # AccessResource(word hModule, word hRsrc): the module's file, opened and at the resource.
            table = self.resources(arg(1))
            hrsrc = arg(0)
            if table is None or not table.rsrctab or not hrsrc or table.entry(hrsrc) is None:
                return 0xFFFF, 0, None
            path = self.owner(self._exe_ptr(arg(1)))
            handle = self._handle(Path(path).name, path)
            self.files[handle][3] = table.entry(hrsrc)[0] << table.shift
            return handle, 0, None
        if ordinal == 65:
            # SizeofResource(word hModule, word hRsrc)
            table = self.resources(arg(1))
            size = table.size(arg(0)) if table is not None and arg(0) else 0
            return size & 0xFFFF, size >> 16, None
        return 0, 0, f"unimplemented KERNEL.{ordinal}"

    def _throw(self, arg):
        """Wine thunk.c Throw16(lpbuf, retval): AX = retval, then the CATCHBUF's registers.

        Wine sets IP, CS, BP, SI, DI and DS from the buffer and Esp to lpbuf[2] + 4 words - 1
        word. The relay then returns through the new stack as it returns from any register
        function: CS:IP at SS:Esp and the stub's retf pops Throw's 6 argument bytes, which leaves
        SP where Catch's own return left it. Wine logs an ERR and goes on when lpbuf[8] is not
        SS. neww stops there.
        """
        off, sel, retval = arg(1), arg(2), arg(0)
        size = self.size(sel)
        if size is None or off + 18 > size:
            return 0, 0, f"KERNEL.56 Throw({sel:#x}:{off:#x}): the CATCHBUF is not in a block neww has"
        buf = [arg.word(sel, off + 2 * i) for i in range(9)]
        if buf[8] != arg.regs("ss"):
            return 0, 0, f"KERNEL.56 Throw: CATCHBUF SS {buf[8]:#x} is not SS {arg.regs('ss'):#x}, and Wine does not switch stacks"
        sp = (buf[2] + 4 * 2 - 2) & 0xFFFF
        self.registers = {"sp": sp, "bp": buf[3], "si": buf[4], "di": buf[5], "ds": buf[6], "frame": (buf[0], buf[1])}
        return retval, 0, None

    def _global_size(self, handle):
        """Wine global.c GlobalSize16: the arena's size, 0 for handle 0 or an invalid handle.

        GET_ARENA_PTR takes the arena from the selector, so the handle or the selector of a
        moveable block finds it. A GlobalAlloc block is its rounded size, which over 64K is
        more than its first selector's segment.
        """
        if not handle:
            return 0
        sel = self.selector_of(handle)
        if sel is None:
            return 0
        for block_sel, size, _flags in self.heap.values():
            if block_sel == sel:
                return size
        return self.size(sel)

    def selector_of(self, handle):
        """GlobalHandleToSel16 in neww's numbering, moveable_handle's inverse. None if no block."""
        sel = handle & ~7
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
        handle = moveable_handle(sel) if flags & GMEM_MOVEABLE else sel
        self.heap[handle] = (sel, size, flags)
        return handle, 0, None

    def _system_metrics(self, index):
        """Wine user.c GetSystemMetrics16 is win32u sysparams.c get_system_metrics. Returns (ax, dx, stop)."""
        if index in METRICS:
            return METRICS[index], 0, None
        if index in METRICS_FROM_HOST:
            return 0, 0, (
                f"USER.179 GetSystemMetrics({index}): Wine reads it from the registry, "
                "fonts, or display, and neww has none of them"
            )
        # The switch's default.
        return 0, 0, None

    def _device_caps(self, hdc, cap):
        """Wine gdi.exe16/gdi.c GetDeviceCaps16 of a screen DC. Returns (ax, dx, stop)."""
        if hdc not in self.dcs:
            return 0, 0, f"GDI.80 GetDeviceCaps({hdc:#x}, {cap}): not a DC neww made"
        value = SCREEN_CAPS.get(cap, 0)
        if cap == 24 and value == -1:
            # NUMCOLORS: "some apps don't expect -1 and think it's a B&W screen".
            value = 2048
        return value & 0xFFFF, 0, None

    def _gdi(self, ordinal, arg):
        if ordinal == 80:
            cap = arg(0) - 0x10000 if arg(0) & 0x8000 else arg(0)
            return self._device_caps(arg(1), cap)
        return 0, 0, self.missing("GDI", ordinal)

    def _user(self, ordinal, arg):
        if ordinal == 118:
            return self._register_window_message(arg.string(0)), 0, None
        if ordinal == 66:
            return self._get_dc(arg(0))
        if ordinal == 68:
            return self._release_dc(arg(1), arg(0))
        if ordinal == 179:
            index = arg(0) - 0x10000 if arg(0) & 0x8000 else arg(0)
            return self._system_metrics(index)
        if ordinal == 266:
            return 1, 0, None
        if ordinal == 5:
            # Wine user.c InitApp16: InitThreadInput16(0, 0) != 0. The queue is made, so TRUE.
            return 1, 0, None
        if ordinal == 291:
            # SetWindowsHookEx(s_word id, segptr proc, word hInst, word hTask)
            id_ = arg(4) - 0x10000 if arg(4) & 0x8000 else arg(4)
            return self._set_windows_hook(id_, arg(2) | (arg(3) << 16), arg(0))
        if ordinal == 1:
            # MessageBox(word hwnd, str text, str caption, word type): the text goes to the trace.
            self.trace[-1] += f" {arg.string(3)!r} caption {arg.string(1)!r} type {arg(0):#x}"
            self.messageboxes.append((arg.string(3), arg.string(1), arg(0)))
            return 0, 0, None
        if ordinal in (108, 111, 176):
            return 0, 0, None
        return 0, 0, f"unimplemented USER.{ordinal}"


# Handler modules register themselves in HANDLERS when imported.
from . import kernel16, user16, shell16  # noqa: E402,F401
