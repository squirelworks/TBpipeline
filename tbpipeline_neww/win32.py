"""Win32 from Win16: Wine krnl386.exe16 thunk.c's generic thunks, KERNEL.513 to 518, and
the 32-bit side they reach.

A 16-bit DLL loads a Win32 module with LoadLibraryEx32W, finds a function with
GetProcAddress32W and calls it with CallProc32W. A PE file in --b loads as Wine's
loader (dlls/ntdll/loader.c) loads it: mapped at its base, relocated if that is
taken, its imports bound, then DllMain(DLL_PROCESS_ATTACH). Its code runs on the
CPU, in a flat 32-bit code segment, on a 32-bit stack, with FS a TEB.

Wine's own Win32 modules (kernel32 and the rest) are not PE files here. Each
function a PE file imports, or GetProcAddress finds, is a stub in the stub page:

    mov edx, n ; out 0EDh ; ret pop

The hook for OUT 0EDh runs the Python function written from the Wine function
(the @win32 registry), and the stub's ret pops what the function's row in
spec32_rows.py says. A function Wine exports that neww has no Python for stops
there, by name, when it is called. One Wine does not export stops by name too:
Wine's loader binds it to a stub that raises an exception when called.

A call from 16-bit code into 32-bit code is a Call32: the gate's retf goes to the
entry tail (Machine._start32), the 32-bit function returns to the return stub,
OUT 0ECh, and the answer goes back to the 16-bit caller in DX:AX.
"""

import re
import struct
from pathlib import Path

from .handlers import handles
from .kernel16 import cstr
from .pe import PE, exports as pe_exports, imports as pe_imports, relocate
from .spec32_rows import SPEC32_ROWS

# The Win32 modules Wine always has, by base name. Their HMODULE is neww's own number, with
# nothing mapped there.
WIN32_MODULES = ("KERNEL32", "USER32", "GDI32", "ADVAPI32", "WOW32", "SHELL32", "OLE32", "VERSION", "WINMM", "NTDLL", "COMDLG32")
HMODULE_BASE = 0x7B000000
# include/winnt.h CPEX_DEST_CDECL, a flag in nrofargs of _CallProcEx32W.
CPEX_DEST_CDECL = 0x80000000
DLL_PROCESS_ATTACH = 1

# The 32-bit layout. The 16-bit segments sit from 0x200000 up.
PE_LOW = 0x10000000
STACK32_TOP = 0x30000000
STACK32_SIZE = 0x100000
HEAP_BASE = 0x40000000
TEB_BASE = 0x7FFDE000
PEB_BASE = TEB_BASE + 0x1000
STUB_BASE = 0x7F000000
STUB_SIZE = 0x10000
STUB_FIRST = 0x20
STUB_LEN = 0x10

WIN32 = {}


def win32(module, name):
    """Register fn(wine, *args) for module!name. args are the 32-bit argument words, first
    argument first, as many as the spec row has (two for an int64 or a double). A pointer is
    a linear address. It returns the answer, EDX:EAX for one over 32 bits, or a stop string."""
    def wrap(fn):
        WIN32[(module, name)] = fn
        return fn
    return wrap


# ---------------------------------------------------------------- spec rows

ROW = re.compile(r"^(@|\d+)\s+(stdcall|cdecl|varargs)\s+((?:-\S+\s+)*)([\w@?$]+)\s*\((.*?)\)")


class Row:
    def __init__(self, line):
        m = ROW.match(line)
        self.line = line
        self.ordinal = None if m.group(1) == "@" else int(m.group(1))
        self.convention = m.group(2)
        self.flags = m.group(3).split()
        self.name = m.group(4)
        self.args = m.group(5).split()
        self.words = sum(2 if a in ("int64", "double") else 1 for a in self.args)
        self.pop = 4 * self.words if self.convention == "stdcall" else 0
        self.noname = "-noname" in self.flags


def _index():
    by_name, by_ord = {}, {}
    for module, lines in SPEC32_ROWS.items():
        for line in lines:
            row = Row(line)
            if not row.noname:
                by_name.setdefault((module, row.name), row)
            if row.ordinal is not None:
                by_ord.setdefault((module, row.ordinal), row)
    return by_name, by_ord


ROWS_BY_NAME, ROWS_BY_ORDINAL = _index()


def spec_row(module, what):
    if isinstance(what, int):
        return ROWS_BY_ORDINAL.get((module, what))
    return ROWS_BY_NAME.get((module, what))


# ---------------------------------------------------------------- state

class Module:
    def __init__(self, name, base, path=None, pe=None):
        self.name = name
        self.base = base
        self.path = path
        self.pe = pe
        self.refs = 1
        self.by_name = {}
        self.by_ordinal = {}
        self.export_range = (0, 0)

    @property
    def builtin(self):
        return self.pe is None


class State:
    def __init__(self):
        self.modules = {}
        # [(module, name or ordinal, row)], stub n at STUB_BASE + STUB_FIRST + n * STUB_LEN.
        self.stubs = []
        self.stub_at = {}
        self.ranges = []
        self.last_error = 0


def state(wine):
    if getattr(wine, "w32", None) is None:
        wine.w32 = State()
    return wine.w32


def builtin_module(wine, base):
    """The Module for a Wine builtin, by base name, or None."""
    stem = base.upper()
    if stem.endswith(".DLL"):
        stem = stem[:-4]
    if stem not in WIN32_MODULES:
        return None
    st = state(wine)
    if stem not in st.modules:
        st.modules[stem] = Module(stem, HMODULE_BASE + (WIN32_MODULES.index(stem) << 16))
    return st.modules[stem]


def module_at(wine, handle):
    for m in state(wine).modules.values():
        if m.base == handle and handle:
            return m
    return None


def stub_for(wine, module, what):
    """The stub address for module!what (a name or an ordinal)."""
    st = state(wine)
    key = (module, what)
    if key not in st.stub_at:
        wine.setup32()
        n = len(st.stubs)
        addr = STUB_BASE + STUB_FIRST + n * STUB_LEN
        if addr + STUB_LEN > STUB_BASE + STUB_SIZE:
            raise RuntimeError("out of Win32 stubs")
        row = spec_row(module, what)
        pop = row.pop if row else 0
        code = bytes([0xBA]) + struct.pack("<I", n) + bytes([0xE6, 0xED])
        code += bytes([0xC2]) + struct.pack("<H", pop) if pop else bytes([0xC3])
        wine.write_linear(addr, code)
        st.stubs.append((module, what, row))
        st.stub_at[key] = addr
    return st.stub_at[key]


def call_stub(wine, n, esp, read):
    """OUT 0EDh from stub n with ESP at its return address. The answer, or a stop."""
    st = state(wine)
    if n >= len(st.stubs):
        return f"out 0xed from no stub ({n:#x})"
    module, what, row = st.stubs[n]
    label = f"{module}!{what}"
    if row is None:
        return (f"{label}: Wine's {module.lower()}.spec exports no {what}, and Wine's loader "
                "binds it to a stub that raises an exception when it is called")
    args = list(struct.unpack(f"<{row.words}I", read(esp + 4, 4 * row.words))) if row.words else []
    wine.trace.append(f"{label}({', '.join(hex(a) for a in args)})")
    fn = WIN32.get((module, row.name))
    if fn is None:
        return f"{label}: {row.line} has no neww handler yet"
    wine.w32_esp = esp
    wine.w32_read = read
    out = fn(wine, *args)
    if isinstance(out, str):
        return f"{label}: {out}"
    out = int(out) & 0xFFFFFFFFFFFFFFFF
    wine.trace[-1] += f" -> {out:#x}"
    return out


# ---------------------------------------------------------------- calls from 16-bit code

class Call32:
    """Calls into 32-bit code for a 16-bit gate. gen yields (proc, args) and gets EAX back,
    or yields a stop string. What it returns is the answer: an int (DX:AX), (ax, dx) or
    (ax, dx, stop). pop is what the gate pops besides its own spec's pop (CallProc32W pops
    its arguments itself)."""

    def __init__(self, gen, pop=0):
        self.gen = gen
        self.pop = pop

    def step(self, eax):
        try:
            nxt = self.gen.send(eax)
        except StopIteration as done:
            return "done", _answer(done.value)
        if isinstance(nxt, str):
            return "done", (0, 0, nxt)
        return "call", nxt[0], list(nxt[1])


def _answer(value):
    if value is None:
        return 0, 0, None
    if isinstance(value, int):
        value &= 0xFFFFFFFF
        return value & 0xFFFF, value >> 16, None
    if len(value) == 2:
        return value[0], value[1], None
    return value


def call32(wine, gen, pop=0):
    """Set the gate's request. The gate answers nothing itself."""
    wine.registers = {"call32": Call32(gen, pop)}
    return 0, 0, None


# ---------------------------------------------------------------- loading

def _free_base(wine, want, size):
    st = state(wine)

    def free(b):
        return all(b + size <= lo or b >= hi for lo, hi in st.ranges)
    if want and free(want):
        return want
    b = PE_LOW
    while not free(b):
        b += 0x10000
    return b


def find_file(wine, name):
    """OpenFile16(OF_EXIST) over --b, the application's directory: the path, or None."""
    base = name.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(":", 1)[-1]
    for item in Path(wine.root).iterdir():
        if item.is_file() and item.name.upper() == base.upper():
            return item
    return None


def load_pe(wine, path, new=None):
    """Map, relocate and bind a PE file, as ntdll loader.c load_native_dll and fixup_imports
    do. Returns (module, stop). DllMain has not run. A PE import not loaded yet is found in
    --b and loaded first (fixup_imports -> load_dll), and each module loaded is appended to
    new after the ones it imports, the order process_attach runs their DllMain in."""
    if new is None:
        new = []
    try:
        pe = PE(Path(path).read_bytes(), Path(path).name)
    except ValueError as exc:
        return None, f"{Path(path).name} is not an i386 PE file: {exc}"
    st = state(wine)
    wine.setup32()
    base = _free_base(wine, pe.image_base, pe.size_of_image)
    img = pe.image()
    why = relocate(img, pe, base)
    if why:
        return None, f"{Path(path).name}: {why}"
    name = Path(path).name.upper().rsplit(".", 1)[0]
    module = Module(name, base, path, pe)
    module.by_name, module.by_ordinal, module.export_range = pe_exports(img, pe)
    for dll, items in pe_imports(img, pe):
        target = builtin_module(wine, dll)
        if target is None:
            other = st.modules.get(dll.upper().rsplit(".", 1)[0])
            if other is None:
                found = find_file(wine, dll)
                if found is None:
                    return None, (f"{Path(path).name} imports {dll}, which is neither a Wine builtin "
                                  "nor a file in --b: Wine's loader fails the load (STATUS_DLL_NOT_FOUND)")
                other, why = load_pe(wine, found, new)
                if why:
                    return None, why
            else:
                other.refs += 1
            target = other
        for iat, what in items:
            addr = proc_address(wine, target, what, bind=True)
            if isinstance(addr, str):
                return None, f"{Path(path).name}: {addr}"
            struct.pack_into("<I", img, iat, addr)
    wine.map_linear(base, pe.size_of_image)
    wine.write_linear(base, bytes(img))
    st.ranges.append((base, base + pe.size_of_image))
    st.modules[name] = module
    new.append(module)
    wine.trace.append(f"  loaded {Path(path).name} at {base:#x}")
    return module, None


def proc_address(wine, module, what, bind=False):
    """GetProcAddress: the address of module!what, a name or an ordinal. 0 when a PE module
    does not export it, or a Wine builtin's spec has no such entry. For binding an import,
    a missing builtin function still gets a stub, as Wine's loader gives it one."""
    if module.builtin:
        if spec_row(module.name, what) is None and not bind:
            return 0
        return stub_for(wine, module.name, what)
    rva = module.by_ordinal.get(what) if isinstance(what, int) else module.by_name.get(what)
    if rva is None:
        if bind:
            return f"{module.name} exports no {what}"
        return 0
    lo, hi = module.export_range
    if lo <= rva < hi:
        return f"{module.name}!{what} is a forwarder, which neww does not follow yet"
    return module.base + rva


def load_library(wine, name):
    """LoadLibraryExA: generator for a Call32. Yields DllMain's call, returns the HMODULE."""
    base = name.replace("/", "\\").rsplit("\\", 1)[-1]
    st = state(wine)
    stem = base.upper().rsplit(".", 1)[0] if "." in base else base.upper()
    builtin = builtin_module(wine, base if "." in base else base + ".DLL")
    if builtin is not None:
        return builtin.base
    if stem in st.modules:
        st.modules[stem].refs += 1
        return st.modules[stem].base
    path = find_file(wine, base if "." in base else base + ".dll")
    if path is None:
        # ERROR_MOD_NOT_FOUND.
        st.last_error = 126
        return 0
    new = []
    module, why = load_pe(wine, path, new)
    if why:
        yield why
    for each in new:
        # process_attach: the imports' DllMain first, then the importer's.
        if not each.pe.entry:
            continue
        wine.trace.append(f"  {each.name} DllMain(PROCESS_ATTACH)")
        ok = yield each.base + each.pe.entry, [each.base, DLL_PROCESS_ATTACH, 0]
        wine.trace.append(f"  {each.name} DllMain -> {ok:#x}")
        if not ok:
            yield (f"{each.name}'s DllMain(DLL_PROCESS_ATTACH) answered FALSE: Wine's loader would "
                   "call it with DLL_PROCESS_DETACH and unload it, which neww does not do yet")
    return module.base


# ---------------------------------------------------------------- KERNEL

@handles("KERNEL", 513)
def load_library_ex32w(wine, arg):
    """thunk.c LoadLibraryEx32W16(name, hFile, flags) -> LoadLibraryExA."""
    if not arg(5) and not arg(4):
        # ERROR_INVALID_PARAMETER and 0.
        state(wine).last_error = 87
        return 0, 0, None
    name = cstr(wine, arg(5), arg(4)).decode("latin1")
    wine.trace[-1] += f" {name!r}"
    return call32(wine, load_library(wine, name))


@handles("KERNEL", 514)
def free_library32w(wine, arg):
    """thunk.c FreeLibrary32W16 -> FreeLibrary. A builtin stays loaded: TRUE. A PE module's
    count drops; at 0 Wine runs DllMain(DLL_PROCESS_DETACH) and unmaps it, which stops here."""
    handle = arg(0) | arg(1) << 16
    module = module_at(wine, handle)
    if module is None:
        return 0, 0, None
    if module.builtin:
        return 1, 0, None
    if module.refs > 1:
        module.refs -= 1
        return 1, 0, None
    return 0, 0, f"KERNEL.514 FreeLibrary32W({module.name}): the last reference, and neww does not unload a PE module yet"


@handles("KERNEL", 515)
def get_proc_address32w(wine, arg):
    """thunk.c GetProcAddress32W16(hModule, name) -> GetProcAddress. An ordinal when the
    name's selector is 0."""
    handle = arg(2) | arg(3) << 16
    what = arg(0) if arg(1) == 0 else cstr(wine, arg(1), arg(0)).decode("latin1")
    module = module_at(wine, handle)
    wine.trace[-1] += f" {module.name if module else hex(handle)}!{what}"
    if module is None:
        return 0, 0, None
    addr = proc_address(wine, module, what)
    if isinstance(addr, str):
        return 0, 0, f"KERNEL.515 GetProcAddress32W: {addr}"
    wine.trace[-1] += f" -> {addr:#x}"
    return addr & 0xFFFF, addr >> 16, None


def _nothing():
    return 0
    yield


def _one_call(proc, args):
    eax = yield proc, args
    return eax


@handles("KERNEL", 517)
def call_proc32w(wine, arg):
    """thunk.c CallProc32W16(nrofargs, argconvmask, proc32, ...): the arguments follow, last
    first. A bit set in argconvmask makes that one a SEGPTR, passed through MapSL. It pops
    3 + nrofargs DWORDs itself (stack16_pop). WOW_CallProc32W16 answers 0 for a null proc32."""
    count = arg(0) | arg(1) << 16
    mask = arg(2) | arg(3) << 16
    proc = arg(4) | arg(5) << 16
    if count > 32:
        return 0, 0, f"KERNEL.517 CallProc32W with {count} arguments: Wine's args[32] holds 32"
    args = [0] * count
    for i in range(count):
        value = arg(6 + 2 * i) | arg(7 + 2 * i) << 16
        if mask & (1 << i):
            value = map_sl(wine, value)
        args[count - i - 1] = value
    wine.trace[-1] += f" {proc:#x}({', '.join(hex(a) for a in args)})"
    pop = (3 + count) * 4
    if not proc:
        return call32(wine, _nothing(), pop)
    return call32(wine, _one_call(proc, args), pop)


@handles("KERNEL", 518)
def call_proc_ex32w(wine, arg):
    """thunk.c CallProcEx32W16(nrofargs, argconvmask, proc32, ...): as CallProc32W, but the
    arguments come first first, at most 32, and the caller pops them (cdecl). CPEX_DEST_CDECL in
    nrofargs only says how the Win32 function is called."""
    count = min(32, (arg(0) | arg(1) << 16) & ~CPEX_DEST_CDECL)
    mask = arg(2) | arg(3) << 16
    proc = arg(4) | arg(5) << 16
    args = []
    for i in range(count):
        value = arg(6 + 2 * i) | arg(7 + 2 * i) << 16
        args.append(map_sl(wine, value) if mask & (1 << i) else value)
    wine.trace[-1] += f" {proc:#x}({', '.join(hex(a) for a in args)})"
    if not proc:
        return call32(wine, _nothing())
    return call32(wine, _one_call(proc, args))


def map_sl(wine, segptr):
    """MapSL: the linear address of a SEGPTR. 0 stays 0."""
    if not segptr:
        return 0
    base = wine.linear(segptr >> 16)
    if base is None:
        return 0
    return base + (segptr & 0xFFFF)


def read_str(wine, addr, limit=0x1000):
    out = bytearray()
    while len(out) < limit:
        chunk = wine.read_linear(addr + len(out), 64)
        cut = chunk.find(b"\x00")
        if cut >= 0:
            return bytes(out + chunk[:cut])
        out += chunk
    return bytes(out)


def environment_value(_wine, name):
    """A variable of the DOS environment block, which is the process environment Wine's
    GetEnvironmentVariable reads. None when it is not set."""
    from .machine import ENV_STRINGS
    for text in ENV_STRINGS:
        key, _, value = text.partition(b"=")
        if key.decode("latin1").upper() == name.upper():
            return value.decode("latin1")
    return None
