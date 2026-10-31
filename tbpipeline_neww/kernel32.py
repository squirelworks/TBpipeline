"""KERNEL32 for the Win32 side (win32.py), from Wine's kernel32 and kernelbase at WINE_COMMIT.

The process is the one Wine runs a Win16 program in: winevdm.exe, started by
kernelbase process.c create_vdm_process as `winevdm.exe --app-name "app" cmdline`,
under the Windows version neww answers everywhere, win31 (ntdll version.c:
3.10, VER_PLATFORM_WIN32s). Its environment is the DOS environment block's
strings. It has no console, so its standard handles are NULL.
"""

import struct

from .kernel16 import WINDOWS_DIR
from .win32 import (HEAP_BASE, builtin_module, environment_value,
                    load_library, module_at, proc_address, read_str, state, win32)

BIN_DIR = "C:\\TBK"
WINEVDM = WINDOWS_DIR + "\\system32\\winevdm.exe"
APP = BIN_DIR + "\\TB80RTM.EXE"

# include/winerror.h
ERROR_FILE_NOT_FOUND = 2
ERROR_INVALID_HANDLE = 6
ERROR_NOT_ENOUGH_MEMORY = 8
ERROR_INVALID_PARAMETER = 87
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_MOD_NOT_FOUND = 126
ERROR_ALREADY_EXISTS = 183

HEAP_ZERO_MEMORY = 0x08
HEAP_REALLOC_IN_PLACE_ONLY = 0x10
MEM_COMMIT, MEM_RESERVE, MEM_RELEASE, MEM_DECOMMIT = 0x1000, 0x2000, 0x8000, 0x4000
STD_INPUT_HANDLE, STD_ERROR_HANDLE = 0xFFFFFFF6, 0xFFFFFFF4
FILE_TYPE_UNKNOWN = 0
CURRENT_PROCESS = 0xFFFFFFFF
CURRENT_THREAD = 0xFFFFFFFE
WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 0x102
INFINITE = 0xFFFFFFFF
# The ANSI and OEM code pages of Wine's default en-US locale.
ACP, OEMCP = 1252, 437
LCID_EN_US = 0x0409


def _w(wine, addr, data):
    wine.write_linear(addr, bytes(data))


def _r(wine, addr, n):
    return wine.read_linear(addr, n)


def _dword(wine, addr, value):
    _w(wine, addr, struct.pack("<I", value & 0xFFFFFFFF))


def _error(wine, code):
    state(wine).last_error = code


def _process(wine):
    """The process's own blocks: the heap Wine makes at start (GetProcessHeap) and the
    strings kernel32 keeps."""
    st = state(wine)
    if getattr(st, "process_heap", None) is None:
        st.heaps = {}
        st.next_heap = HEAP_BASE
        st.handles = {}
        st.next_handle = 0x100
        st.process_heap = _new_heap(wine, 0, 0)
        st.strings = {}
    return st


def _string(wine, key, raw):
    """A NUL-ended string kept in the process heap, made once."""
    st = _process(wine)
    if key not in st.strings:
        addr = st.heaps[st.process_heap].alloc(len(raw) + 2)
        _w(wine, addr, raw + b"\x00\x00")
        st.strings[key] = addr
    return st.strings[key]


# ---------------------------------------------------------------- heaps

class Win32Heap:
    """A Win32 heap in its own reserved range. Blocks are 8-aligned, as RtlAllocateHeap's
    are on i386; a freed block is used again for a request it fits."""

    RESERVE = 0x1000000

    def __init__(self, wine, base, maximum):
        self.wine = wine
        self.base = base
        self.top = base + 0x20
        self.limit = base + (maximum or self.RESERVE)
        self.blocks = {}
        self.free = []
        self.mapped = base
        self._grow(self.top)

    def _grow(self, end):
        if end > self.mapped:
            want = (end + 0xFFFF) & ~0xFFFF
            self.wine.map_linear(self.mapped, want - self.mapped)
            self.mapped = want

    def alloc(self, size, zero=True):
        need = (max(size, 1) + 7) & ~7
        for i, (addr, room) in enumerate(self.free):
            if room >= need:
                del self.free[i]
                self.blocks[addr] = (size, room)
                if zero:
                    _w(self.wine, addr, bytes(room))
                return addr
        addr = self.top
        if addr + need > self.limit:
            return 0
        self._grow(addr + need)
        self.top = addr + need
        self.blocks[addr] = (size, need)
        if zero:
            _w(self.wine, addr, bytes(need))
        return addr

    def release(self, addr):
        if addr not in self.blocks:
            return False
        _size, room = self.blocks.pop(addr)
        self.free.append((addr, room))
        return True

    def size(self, addr):
        return self.blocks[addr][0] if addr in self.blocks else None


def _new_heap(wine, flags, maximum):
    st = state(wine)
    base = st.next_heap
    span = (maximum + 0xFFFF) & ~0xFFFF if maximum else Win32Heap.RESERVE
    st.next_heap += span
    st.heaps[base] = Win32Heap(wine, base, span)
    return base


@win32("KERNEL32", "GetProcessHeap")
def get_process_heap(wine):
    return _process(wine).process_heap


@win32("KERNEL32", "HeapCreate")
def k32_heap_create(wine, flags, initial, maximum):
    """memory.c HeapCreate -> RtlCreateHeap. maximum 0 is a growable heap."""
    _process(wine)
    return _new_heap(wine, flags, maximum)


@win32("KERNEL32", "HeapDestroy")
def k32_heap_destroy(wine, heap):
    st = _process(wine)
    if heap not in st.heaps or heap == st.process_heap:
        _error(wine, ERROR_INVALID_HANDLE)
        return 0
    del st.heaps[heap]
    return 1


def _find_heap(wine, heap):
    st = _process(wine)
    return st.heaps.get(heap)


@win32("KERNEL32", "HeapAlloc")
def k32_heap_alloc(wine, heap, flags, size):
    """RtlAllocateHeap. Wine's blocks come zeroed only with HEAP_ZERO_MEMORY; neww's are always
    zero, so a program reading one it did not fill reads 0 as it would from fresh pages."""
    h = _find_heap(wine, heap)
    if h is None:
        return f"heap {heap:#x} is not a heap HeapCreate or GetProcessHeap gave"
    addr = h.alloc(size)
    if not addr:
        _error(wine, ERROR_NOT_ENOUGH_MEMORY)
    return addr


@win32("KERNEL32", "HeapFree")
def k32_heap_free(wine, heap, flags, ptr):
    """RtlFreeHeap: TRUE for a null pointer too."""
    if not ptr:
        return 1
    h = _find_heap(wine, heap)
    if h is None or not h.release(ptr):
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    return 1


@win32("KERNEL32", "HeapSize")
def k32_heap_size(wine, heap, flags, ptr):
    h = _find_heap(wine, heap)
    size = h.size(ptr) if h else None
    if size is None:
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0xFFFFFFFF
    return size


@win32("KERNEL32", "HeapReAlloc")
def k32_heap_realloc(wine, heap, flags, ptr, size):
    """RtlReAllocateHeap: the block grows in place when its room holds the new size, else it
    moves (not with HEAP_REALLOC_IN_PLACE_ONLY). Bytes past the old size are zero."""
    h = _find_heap(wine, heap)
    if h is None or ptr not in h.blocks:
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    old, room = h.blocks[ptr]
    need = (max(size, 1) + 7) & ~7
    if need <= room:
        if size > old:
            _w(wine, ptr + old, bytes(size - old))
        h.blocks[ptr] = (size, room)
        return ptr
    if flags & HEAP_REALLOC_IN_PLACE_ONLY:
        _error(wine, ERROR_NOT_ENOUGH_MEMORY)
        return 0
    new = h.alloc(size)
    if not new:
        _error(wine, ERROR_NOT_ENOUGH_MEMORY)
        return 0
    _w(wine, new, _r(wine, ptr, old))
    h.release(ptr)
    return new


# ---------------------------------------------------------------- virtual memory

def _regions(wine):
    st = _process(wine)
    if not hasattr(st, "regions"):
        st.regions = {}
        st.next_region = 0x50000000
    return st


@win32("KERNEL32", "VirtualAlloc")
def virtual_alloc(wine, addr, size, kind, protect):
    """NtAllocateVirtualMemory: a reservation is 64K-aligned; a commit inside one is
    page-aligned and zero. Pages are mapped when reserved."""
    st = _regions(wine)
    if not size:
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    if addr:
        for base, span in st.regions.items():
            if base <= addr < base + span:
                if kind & MEM_COMMIT:
                    return addr & ~0xFFF
                return 0
        if not kind & MEM_RESERVE:
            _error(wine, ERROR_INVALID_PARAMETER)
            return 0
        return f"VirtualAlloc at {addr:#x}, outside any reservation, which neww does not place yet"
    span = (size + 0xFFFF) & ~0xFFFF
    base = st.next_region
    st.next_region += span
    wine.map_linear(base, span)
    st.regions[base] = span
    return base


@win32("KERNEL32", "VirtualFree")
def virtual_free(wine, addr, size, kind):
    st = _regions(wine)
    if kind & MEM_RELEASE:
        if size or addr not in st.regions:
            _error(wine, ERROR_INVALID_PARAMETER)
            return 0
        del st.regions[addr]
        return 1
    if kind & MEM_DECOMMIT:
        return 1
    _error(wine, ERROR_INVALID_PARAMETER)
    return 0


# ---------------------------------------------------------------- process

@win32("KERNEL32", "GetVersion")
def get_version(wine):
    """version.c GetVersion: MAKELONG(MAKEWORD(major, minor), (platform ^ 2) << 14), and the
    build for NT. win31 is 3.10 on VER_PLATFORM_WIN32s (0)."""
    return 3 | 10 << 8 | (0 ^ 2) << 14 << 16


def command_line():
    """create_vdm_process: winevdm.exe --app-name "image" and the original command line."""
    return f'{WINEVDM} --app-name "{APP}" {APP}'


@win32("KERNEL32", "GetCommandLineA")
def get_command_line_a(wine):
    line = command_line()
    if wine.book:
        line += " " + wine.dos_name(wine.book)
    return _string(wine, "cmdline", line.encode("latin1"))


def _environment_block():
    from .machine import ENV_STRINGS
    return b"".join(s + b"\x00" for s in ENV_STRINGS) + b"\x00"


@win32("KERNEL32", "GetEnvironmentStrings")
def get_environment_strings(wine):
    """process.c GetEnvironmentStringsA: an ANSI copy of the block, from the process heap."""
    block = _environment_block()
    st = _process(wine)
    addr = st.heaps[st.process_heap].alloc(len(block))
    _w(wine, addr, block)
    return addr


@win32("KERNEL32", "GetEnvironmentStringsA")
def get_environment_strings_a(wine):
    return get_environment_strings(wine)


@win32("KERNEL32", "GetEnvironmentStringsW")
def get_environment_strings_w(wine):
    """The block itself, UTF-16."""
    block = _environment_block().decode("latin1").encode("utf-16-le")
    return _string(wine, "envW", block[:-2])


@win32("KERNEL32", "FreeEnvironmentStringsA")
def free_environment_strings_a(wine, ptr):
    st = _process(wine)
    st.heaps[st.process_heap].release(ptr)
    return 1


@win32("KERNEL32", "FreeEnvironmentStringsW")
def free_environment_strings_w(wine, ptr):
    return 1


@win32("KERNEL32", "GetStartupInfoA")
def get_startup_info_a(wine, ptr):
    """kernel_main.c copy_startup_info: the process parameters. winevdm was started with
    none set: no flags, no standard handles, desktop and title from the parameters, which
    are empty strings."""
    empty = _string(wine, "empty", b"")
    info = struct.pack("<IIII", 68, 0, empty, empty) + bytes(68 - 16)
    _w(wine, ptr, info)
    return 0


@win32("KERNEL32", "GetStdHandle")
def get_std_handle(wine, which):
    """process.c GetStdHandle: the parameters' handle, NULL with no console."""
    if STD_ERROR_HANDLE <= which <= STD_INPUT_HANDLE:
        return 0
    _error(wine, ERROR_INVALID_HANDLE)
    return 0xFFFFFFFF


@win32("KERNEL32", "GetFileType")
def get_file_type(wine, handle):
    """file.c GetFileType: NtQueryVolumeInformationFile fails on a handle that is no file,
    and the answer is FILE_TYPE_UNKNOWN with ERROR_INVALID_HANDLE."""
    _error(wine, ERROR_INVALID_HANDLE)
    return FILE_TYPE_UNKNOWN


@win32("KERNEL32", "SetHandleCount")
def set_handle_count(wine, count):
    return count


@win32("KERNEL32", "GetCurrentProcess")
def get_current_process(wine):
    return CURRENT_PROCESS


@win32("KERNEL32", "GetLastError")
def get_last_error(wine):
    return state(wine).last_error


@win32("KERNEL32", "SetLastError")
def set_last_error(wine, code):
    state(wine).last_error = code
    return 0


@win32("KERNEL32", "GetWindowsDirectoryA")
def get_windows_directory_a(wine, buf, size):
    raw = WINDOWS_DIR.encode("latin1")
    if size <= len(raw):
        return len(raw) + 1
    _w(wine, buf, raw + b"\x00")
    return len(raw)


# ---------------------------------------------------------------- modules

def _module_path(wine, handle):
    if handle == 0:
        return WINEVDM
    module = module_at(wine, handle)
    if module is None:
        return None
    if module.builtin:
        return f"{WINDOWS_DIR}\\system32\\{module.name.lower()}.dll"
    return BIN_DIR + "\\" + module.path.name


@win32("KERNEL32", "GetModuleFileNameA")
def get_module_file_name_a(wine, handle, buf, size):
    """loader.c GetModuleFileNameA: the path, cut to size - 1 with a NUL; the length copied.
    A module that is not loaded: 0 and ERROR_MOD_NOT_FOUND."""
    path = _module_path(wine, handle)
    if path is None:
        _error(wine, ERROR_MOD_NOT_FOUND)
        return 0
    raw = path.encode("latin1")
    if not size:
        return 0
    if len(raw) >= size:
        _w(wine, buf, raw[:size - 1] + b"\x00")
        _error(wine, ERROR_INSUFFICIENT_BUFFER)
        return size
    _w(wine, buf, raw + b"\x00")
    return len(raw)


@win32("KERNEL32", "GetModuleHandleA")
def get_module_handle_a(wine, name_ptr):
    """GetModuleHandleExA: NULL is the main module, winevdm.exe, at its image base."""
    if not name_ptr:
        return 0x00400000
    name = read_str(wine, name_ptr).decode("latin1")
    base = name.replace("/", "\\").rsplit("\\", 1)[-1]
    if "." not in base:
        base += ".DLL"
    builtin = builtin_module(wine, base)
    if builtin is not None:
        return builtin.base
    module = state(wine).modules.get(base.upper().rsplit(".", 1)[0])
    if module is None:
        _error(wine, ERROR_MOD_NOT_FOUND)
        return 0
    return module.base


@win32("KERNEL32", "GetProcAddress")
def get_proc_address(wine, handle, name_ptr):
    module = module_at(wine, handle)
    if module is None:
        _error(wine, ERROR_MOD_NOT_FOUND)
        return 0
    what = name_ptr if name_ptr < 0x10000 else read_str(wine, name_ptr).decode("latin1")
    wine.trace[-1] += f" {module.name}!{what}"
    addr = proc_address(wine, module, what)
    if isinstance(addr, str):
        return addr
    if not addr:
        _error(wine, 127)
    return addr


@win32("KERNEL32", "LoadLibraryA")
def load_library_a(wine, name_ptr):
    name = read_str(wine, name_ptr).decode("latin1")
    wine.trace[-1] += f" {name!r}"
    gen = load_library(wine, name)
    try:
        nxt = gen.send(None)
    except StopIteration as done:
        return done.value
    if isinstance(nxt, str):
        return nxt
    return f"LoadLibraryA({name!r}) would run its DllMain from 32-bit code, which neww does not nest yet"


@win32("KERNEL32", "FreeLibrary")
def free_library(wine, handle):
    module = module_at(wine, handle)
    if module is None:
        _error(wine, ERROR_MOD_NOT_FOUND)
        return 0
    if module.builtin or module.refs > 1:
        module.refs = max(1, module.refs - 1)
        return 1
    return f"FreeLibrary({module.name}): the last reference, and neww does not unload a PE module yet"


# ---------------------------------------------------------------- strings

@win32("KERNEL32", "lstrlenA")
def lstrlen_a(wine, ptr):
    return len(read_str(wine, ptr, 0x100000)) if ptr else 0


@win32("KERNEL32", "lstrcpyA")
def lstrcpy_a(wine, dst, src):
    raw = read_str(wine, src, 0x100000)
    _w(wine, dst, raw + b"\x00")
    wine.trace[-1] += f" {raw.decode('latin1')!r}"
    return dst


@win32("KERNEL32", "lstrcpynA")
def lstrcpyn_a(wine, dst, src, n):
    """kernelbase lstrcpynA: at most n - 1 characters and a NUL."""
    if not n:
        return dst
    raw = read_str(wine, src, n - 1)[:n - 1]
    _w(wine, dst, raw + b"\x00")
    return dst


@win32("KERNEL32", "lstrcatA")
def lstrcat_a(wine, dst, src):
    head = read_str(wine, dst, 0x100000)
    raw = read_str(wine, src, 0x100000)
    _w(wine, dst + len(head), raw + b"\x00")
    wine.trace[-1] += f" {(head + raw).decode('latin1')!r}"
    return dst


def _fold(raw):
    return raw.decode("cp1252", "replace").lower()


@win32("KERNEL32", "lstrcmpiA")
def lstrcmpi_a(wine, a, b):
    """lstrcmpiA -> CompareStringA(LOCALE_USER_DEFAULT, NORM_IGNORECASE): -1, 0 or 1."""
    x, y = _fold(read_str(wine, a)), _fold(read_str(wine, b))
    return 0 if x == y else (0xFFFFFFFF if x < y else 1)


# ---------------------------------------------------------------- code pages and locale

@win32("KERNEL32", "GetACP")
def get_acp(wine):
    return ACP


@win32("KERNEL32", "GetOEMCP")
def get_oemcp(wine):
    return OEMCP


@win32("KERNEL32", "GetCPInfo")
def get_cp_info(wine, cp, ptr):
    """locale.c GetCPInfo: the table's MaxCharSize, DefaultChar and LeadByte. 1252 and 437 are
    single-byte with '?' as default character. 0 is CP_ACP, 1 CP_OEMCP."""
    cp = {0: ACP, 1: OEMCP}.get(cp, cp)
    if not ptr or cp not in (ACP, OEMCP):
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    _w(wine, ptr, struct.pack("<I", 1) + b"?\x00" + bytes(12))
    return 1


def _codec(cp):
    cp = {0: ACP, 1: OEMCP, 3: ACP}.get(cp, cp)
    return {ACP: "cp1252", OEMCP: "cp437", 65001: "utf-8"}.get(cp)


def _decode(raw, codec):
    if codec == "cp1252":
        # Wine's 1252 table maps the five undefined bytes to the same code points.
        return "".join(chr(b) if b in (0x81, 0x8D, 0x8F, 0x90, 0x9D) else bytes([b]).decode("cp1252") for b in raw)
    return raw.decode(codec, "replace")


def _encode(text, codec):
    out = bytearray()
    for ch in text:
        if codec == "cp1252" and ord(ch) in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
            out.append(ord(ch))
            continue
        try:
            out += ch.encode(codec)
        except UnicodeEncodeError:
            out += b"?"
    return bytes(out)


@win32("KERNEL32", "MultiByteToWideChar")
def multi_byte_to_wide_char(wine, cp, flags, src, srclen, dst, dstlen):
    """locale.c MultiByteToWideChar: srclen -1 includes the NUL. dstlen 0 asks for the size."""
    codec = _codec(cp)
    if codec is None:
        return f"code page {cp}, which neww has no table for"
    if not src or (dstlen and not dst):
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    raw = read_str(wine, src, 0x100000) + b"\x00" if srclen == 0xFFFFFFFF else _r(wine, src, srclen)
    text = _decode(raw, codec).encode("utf-16-le")
    count = len(text) // 2
    if not dstlen:
        return count
    if count > dstlen:
        _w(wine, dst, text[:2 * dstlen])
        _error(wine, ERROR_INSUFFICIENT_BUFFER)
        return 0
    _w(wine, dst, text)
    return count


def _wstr(wine, ptr, limit=0x80000):
    out = bytearray()
    while len(out) < 2 * limit:
        chunk = _r(wine, ptr + len(out), 64)
        for i in range(0, 64, 2):
            if chunk[i:i + 2] == b"\x00\x00":
                return bytes(out + chunk[:i])
        out += chunk
    return bytes(out)


@win32("KERNEL32", "WideCharToMultiByte")
def wide_char_to_multi_byte(wine, cp, flags, src, srclen, dst, dstlen, defchar, used):
    codec = _codec(cp)
    if codec is None:
        return f"code page {cp}, which neww has no table for"
    if not src or (dstlen and not dst):
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    raw = _wstr(wine, src) + b"\x00\x00" if srclen == 0xFFFFFFFF else _r(wine, src, 2 * srclen)
    out = _encode(raw.decode("utf-16-le", "replace"), codec)
    if used:
        _dword(wine, used, 0)
    if not dstlen:
        return len(out)
    if len(out) > dstlen:
        _w(wine, dst, out[:dstlen])
        _error(wine, ERROR_INSUFFICIENT_BUFFER)
        return 0
    _w(wine, dst, out)
    return len(out)


@win32("KERNEL32", "GetUserDefaultLCID")
def get_user_default_lcid(wine):
    return LCID_EN_US


@win32("KERNEL32", "GetSystemDefaultLCID")
def get_system_default_lcid(wine):
    return LCID_EN_US


# ---------------------------------------------------------------- synchronization

def _new_handle(wine, kind, **fields):
    st = _process(wine)
    h = st.next_handle
    st.next_handle += 4
    st.handles[h] = dict(kind=kind, **fields)
    return h


@win32("KERNEL32", "CreateMutexA")
def create_mutex_a(wine, attrs, initial, name_ptr):
    """sync.c CreateMutexA: a named mutex that exists is opened, with ERROR_ALREADY_EXISTS."""
    st = _process(wine)
    name = read_str(wine, name_ptr).decode("latin1") if name_ptr else None
    if name is not None:
        for h, obj in st.handles.items():
            if obj["kind"] == "mutex" and obj.get("name") == name:
                _error(wine, ERROR_ALREADY_EXISTS)
                return _new_handle(wine, "mutex", name=name, shared=obj["shared"])
    shared = {"owner": "thread" if initial else None, "count": 1 if initial else 0}
    _error(wine, 0)
    wine.trace[-1] += f" {name!r}"
    return _new_handle(wine, "mutex", name=name, shared=shared)


@win32("KERNEL32", "OpenMutexA")
def open_mutex_a(wine, access, inherit, name_ptr):
    st = _process(wine)
    name = read_str(wine, name_ptr).decode("latin1") if name_ptr else None
    wine.trace[-1] += f" {name!r}"
    for obj in list(st.handles.values()):
        if obj["kind"] == "mutex" and name is not None and obj.get("name") == name:
            return _new_handle(wine, "mutex", name=name, shared=obj["shared"])
    _error(wine, ERROR_FILE_NOT_FOUND)
    return 0


@win32("KERNEL32", "ReleaseMutex")
def release_mutex(wine, handle):
    obj = _process(wine).handles.get(handle)
    if obj is None or obj["kind"] != "mutex":
        _error(wine, ERROR_INVALID_HANDLE)
        return 0
    shared = obj["shared"]
    if not shared["count"]:
        # STATUS_MUTANT_NOT_OWNED -> ERROR_NOT_OWNER.
        _error(wine, 288)
        return 0
    shared["count"] -= 1
    if not shared["count"]:
        shared["owner"] = None
    return 1


@win32("KERNEL32", "WaitForSingleObject")
def wait_for_single_object(wine, handle, timeout):
    """A mutex that is free or this thread's is taken at once. Waiting on one another thread
    holds would block, and neww has one thread."""
    obj = _process(wine).handles.get(handle)
    if obj is None:
        return f"WaitForSingleObject({handle:#x}): not a handle neww made"
    if obj["kind"] == "mutex":
        shared = obj["shared"]
        shared["owner"] = "thread"
        shared["count"] += 1
        return WAIT_OBJECT_0
    return f"WaitForSingleObject on a {obj['kind']}, which neww does not wait on yet"


@win32("KERNEL32", "CloseHandle")
def close_handle(wine, handle):
    st = _process(wine)
    if handle not in st.handles:
        _error(wine, ERROR_INVALID_HANDLE)
        return 0
    del st.handles[handle]
    return 1


# ---------------------------------------------------------------- WOW32, wowthunk.c K32WOW*

class Words:
    """Pascal arguments for a 16-bit handler called from 32-bit code: words in the order the
    caller pushes them, so arg(0) is the last."""

    def __init__(self, wine, words, regs=None):
        self.wine = wine
        self.words = [w & 0xFFFF for w in words]
        self.registers = regs or {}

    def __call__(self, n):
        return self.words[len(self.words) - 1 - n]

    def regs(self, name):
        return self.registers.get(name, 0)

    def word(self, sel, offset):
        return struct.unpack("<H", self.wine.read(sel, offset, 2))[0]


def call16(wine, module, ordinal, *words):
    """A KERNEL handler as the 16-bit function Wine's K32WOW* calls. (ax, dx) or a stop."""
    saved = wine.registers
    wine.registers = None
    ax, dx, why = wine.answer(module, ordinal, Words(wine, words))
    wine.registers = saved
    if why:
        return why
    return ax, dx


@win32("WOW32", "WOWGetVDMPointer")
def wow_get_vdm_pointer(wine, vp, size, protected):
    """MapSL in protected mode. A real-mode address would be DOS memory, which neww has not."""
    if not protected:
        return f"WOWGetVDMPointer({vp:#x}) in real mode: DOSMEM_MapRealToLinear, and neww has no DOS memory"
    from .win32 import map_sl
    return map_sl(wine, vp)


@win32("WOW32", "WOWGetVDMPointerFix")
def wow_get_vdm_pointer_fix(wine, vp, size, protected):
    """K32WOWGetVDMPointer: Wine never moves a block, so nothing is fixed."""
    return wow_get_vdm_pointer(wine, vp, size, protected)


@win32("WOW32", "WOWGetVDMPointerUnfix")
def wow_get_vdm_pointer_unfix(wine, vp):
    return 0


@win32("WOW32", "WOWGlobalAlloc16")
def wow_global_alloc16(wine, flags, size):
    out = call16(wine, "KERNEL", 15, flags, size >> 16, size)
    return out if isinstance(out, str) else out[0]


@win32("WOW32", "WOWGlobalLock16")
def wow_global_lock16(wine, handle):
    """WIN16_GlobalLock16: the SEGPTR."""
    out = call16(wine, "KERNEL", 18, handle)
    return out if isinstance(out, str) else out[1] << 16 | out[0]


@win32("WOW32", "WOWGlobalUnlock16")
def wow_global_unlock16(wine, handle):
    out = call16(wine, "KERNEL", 19, handle)
    return out if isinstance(out, str) else out[0]


@win32("WOW32", "WOWGlobalFree16")
def wow_global_free16(wine, handle):
    out = call16(wine, "KERNEL", 17, handle)
    return out if isinstance(out, str) else out[0]


@win32("WOW32", "WOWGlobalAllocLock16")
def wow_global_alloc_lock16(wine, flags, size, ph):
    handle = wow_global_alloc16(wine, flags, size)
    if isinstance(handle, str):
        return handle
    if ph:
        _w(wine, ph, struct.pack("<H", handle))
    return wow_global_lock16(wine, handle)


@win32("WOW32", "WOWGlobalLockSize16")
def wow_global_lock_size16(wine, handle, pcb):
    if pcb:
        out = call16(wine, "KERNEL", 20, handle)
        if isinstance(out, str):
            return out
        _dword(wine, pcb, out[1] << 16 | out[0])
    return wow_global_lock16(wine, handle)


@win32("WOW32", "WOWGlobalUnlockFree16")
def wow_global_unlock_free16(wine, vp):
    """FALSE when GlobalUnlock16 answers 0, as K32WOWGlobalUnlockFree16 does."""
    ok = wow_global_unlock16(wine, vp >> 16)
    if isinstance(ok, str) or not ok:
        return ok if isinstance(ok, str) else 0
    return wow_global_free16(wine, vp >> 16)


@win32("WOW32", "WOWHandle16")
def wow_handle16(wine, handle, kind):
    """The low word for every type but WOW_TYPE_HTASK (11)."""
    if kind == 11:
        return f"WOWHandle16({handle:#x}, WOW_TYPE_HTASK): TASK_GetTaskFromThread, which neww has no threads for"
    return handle & 0xFFFF


@win32("WOW32", "WOWHandle32")
def wow_handle32(wine, handle, kind):
    """The word itself for windows, menus and the like; gdi_handle32 for GDI objects."""
    if kind in (0, 1, 2, 3, 12, 13):
        return handle
    return f"WOWHandle32({handle:#x}, type {kind}): gdi_handle32 or a TDB's thread, which neww does not map yet"


# ---------------------------------------------------------------- locale

# en-US, Wine's default locale, for the LCTYPEs the run has asked for.
LOCALE_EN_US = {
    0x0001: "0409",                     # LOCALE_ILANGUAGE
    0x0003: "ENU",                      # LOCALE_SABBREVLANGNAME
    0x0007: "USA",                      # LOCALE_SABBREVCTRYNAME
    0x000B: "437",                      # LOCALE_IDEFAULTCODEPAGE
    0x1004: "1252",                     # LOCALE_IDEFAULTANSICODEPAGE
}
LOCALE_NOUSEROVERRIDE = 0x80000000
LOCALE_USE_CP_ACP = 0x40000000
LOCALE_RETURN_NUMBER = 0x20000000


@win32("KERNEL32", "GetLocaleInfoA")
def get_locale_info_a(wine, lcid, lctype, buf, size):
    """locale.c GetLocaleInfoA: the value with its NUL, the count with the NUL; size 0 asks for
    the count; a buffer too small is 0 and ERROR_INSUFFICIENT_BUFFER."""
    kind = lctype & ~(LOCALE_NOUSEROVERRIDE | LOCALE_USE_CP_ACP)
    # LANG_ENGLISH alone is the neutral "en", whose values are en-US's but for its own number.
    if lcid not in (0x0400, 0x0800, 0x0409, 0) and not (lcid == 0x0009 and kind != 0x0001):
        return f"GetLocaleInfoA for LCID {lcid:#x}: neww has only en-US, the default"
    if kind & LOCALE_RETURN_NUMBER:
        return f"GetLocaleInfoA LOCALE_RETURN_NUMBER {kind:#x}, which neww does not have yet"
    if kind not in LOCALE_EN_US:
        return f"GetLocaleInfoA LCTYPE {kind:#x}, whose en-US value neww does not have yet"
    raw = LOCALE_EN_US[kind].encode("latin1") + b"\x00"
    wine.trace[-1] += f" {LOCALE_EN_US[kind]!r}"
    if not size:
        return len(raw)
    if size < len(raw):
        _error(wine, ERROR_INSUFFICIENT_BUFFER)
        return 0
    _w(wine, buf, raw)
    return len(raw)


# ---------------------------------------------------------------- files

@win32("KERNEL32", "GetTempPathA")
def get_temp_path_a(wine, length, buffer):
    """kernelbase file.c GetTempPathA -> GetTempPathW: TMP, then TEMP, then USERPROFILE, then the
    Windows directory; made a full path with a backslash at the end. The length without the NUL
    when it fits, else the size needed with the NUL, and the buffer untouched."""
    path = None
    for name in ("TMP", "TEMP", "USERPROFILE"):
        path = environment_value(wine, name)
        if path:
            break
    if not path:
        path = WINDOWS_DIR
    path = wine.full_path(path)
    if not path.endswith("\\"):
        path += "\\"
    raw = path.encode("latin1")
    if len(raw) + 1 > length:
        return len(raw) + 1
    if buffer:
        wine.write_linear(buffer, raw + b"\x00")
    return len(raw)


ERROR_DIRECTORY = 267


def temp_dir():
    """The directory GetTempPathA answers, without its backslash."""
    from .win32 import environment_value
    for name in ("TMP", "TEMP", "USERPROFILE"):
        path = environment_value(None, name)
        if path:
            return path
    return WINDOWS_DIR


def directory_exists(wine, path):
    """neww's directories: the application's, the Windows directory and its SYSTEM, and the
    temp directory. GetFileAttributes of any other is INVALID_FILE_ATTRIBUTES."""
    full = wine.full_path(path).rstrip("\\").upper()
    known = {BIN_DIR, WINDOWS_DIR, WINDOWS_DIR + "\\SYSTEM", WINDOWS_DIR + "\\SYSTEM32",
             wine.full_path(temp_dir()).rstrip("\\")}
    return full in {k.upper() for k in known} or full == "C:"


@win32("KERNEL32", "GetTempFileNameA")
def get_temp_file_name_a(wine, path_ptr, prefix_ptr, unique, buf):
    """file.c GetTempFileNameW: path, a backslash, up to 3 prefix characters, the number in hex
    and ".tmp". With unique 0 the number starts at NtGetTickCount's low word and the file is
    created (CREATE_NEW), the next number tried while one exists."""
    if not path_ptr or not buf:
        _error(wine, ERROR_INVALID_PARAMETER)
        return 0
    path = read_str(wine, path_ptr).decode("latin1")
    prefix = read_str(wine, prefix_ptr).decode("latin1")[:3] if prefix_ptr else ""
    if not directory_exists(wine, path):
        _error(wine, ERROR_DIRECTORY)
        return 0
    head = path if path.endswith("\\") else path + "\\"
    head += prefix
    unique &= 0xFFFF
    if unique:
        name = f"{head}{unique:X}.tmp"
    else:
        from .user_wnd import m_time
        st = _process(wine)
        last = getattr(st, "last_temp", 0)
        num = m_time(wine) & 0xFFFF
        if (last - num) & 0xFFFFFFFF < 10:
            num = last + 1
        num = num or 1
        unique = num
        while True:
            name = f"{head}{unique:X}.tmp"
            if not wine.file_exists(name):
                wine.create_file(name, keep_open=False)
                st.last_temp = unique
                break
            unique = (unique + 1) & 0xFFFF or 1
            if unique == num:
                break
    _w(wine, buf, name.encode("latin1") + b"\x00")
    wine.trace[-1] += f" {name!r}"
    return unique


@win32("KERNEL32", "WritePrivateProfileStringA")
def write_private_profile_string_a(wine, section, entry, string, filename):
    """profile.c WritePrivateProfileStringA -> W: the same profile cache the 16-bit calls use
    (kstate write_profile), in neww's copy of the file for the run. A NULL file is win.ini."""
    opt = lambda ptr: read_str(wine, ptr) if ptr else None
    name = opt(filename) or b"win.ini"
    ax, _dx, _why = wine.write_profile(opt(section), opt(entry), opt(string), name)
    wine.trace[-1] += f" [{(opt(section) or b'').decode('latin1')}] {(opt(entry) or b'').decode('latin1')!r} in {name.decode('latin1')!r}"
    return ax


@win32("KERNEL32", "GetPrivateProfileIntA")
def get_private_profile_int_a(wine, section, entry, default, filename):
    """profile.c GetPrivateProfileIntA: the value as a number, else the default (INT). A NULL
    file is win.ini."""
    opt = lambda ptr: read_str(wine, ptr) if ptr else None
    name = opt(filename) or b"win.ini"
    if default & 0x80000000:
        default -= 1 << 32
    ax, _dx, _why = wine.profile_int(opt(section), opt(entry), default, name, mask=0xFFFFFFFF)
    wine.trace[-1] += f" [{(opt(section) or b'').decode('latin1')}] {(opt(entry) or b'').decode('latin1')!r} in {name.decode('latin1')!r}"
    return ax


@win32("USER32", "GetSystemMetrics")
def get_system_metrics(wine, index):
    """win32u sysparams.c get_system_metrics, the same table GetSystemMetrics16 answers from."""
    if index & 0x80000000:
        index -= 1 << 32
    ax, _dx, why = wine._system_metrics(index)
    if why:
        return why.replace("USER.179 GetSystemMetrics", "USER32!GetSystemMetrics")
    value = ax - 0x10000 if ax & 0x8000 else ax
    wine.trace[-1] += f" {index} -> {value}"
    return value & 0xFFFFFFFF


@win32("KERNEL32", "GetPrivateProfileStringA")
def get_private_profile_string_a(wine, section, entry, default, buf, length, filename):
    """profile.c GetPrivateProfileStringA -> W -> PROFILE_GetString, the same profile cache as
    the 16-bit call; the answer is the length copied. A NULL file is win.ini."""
    opt = lambda ptr: read_str(wine, ptr) if ptr else None
    name = opt(filename) or b"win.ini"
    ax, _dx, why = wine.profile_string(opt(section), opt(entry), opt(default), (buf, 0), length, name,
                                       put=lambda data: _w(wine, buf, data))
    if why:
        return why
    wine.trace[-1] += f" [{(opt(section) or b'').decode('latin1')}] {(opt(entry) or b'').decode('latin1')!r} in {name.decode('latin1')!r}"
    return ax


# ntdll unix/system.c get_cpuinfo fills user_shared_data->ProcessorFeatures from CPUID. The
# CPU here is Unicorn's i386, and these are the answers for it: no FDIV errata, no x87
# emulation, CMPXCHG8B, MMX, SSE, RDTSC and SSE2. Another feature stops until a run asks.
PROCESSOR_FEATURES = {0: 0, 1: 0, 2: 1, 3: 1, 6: 1, 8: 1, 10: 1}


@win32("KERNEL32", "IsProcessorFeaturePresent")
def is_processor_feature_present(wine, feature):
    """kernelbase IsProcessorFeaturePresent -> RtlIsProcessorFeaturePresent: the shared
    data's ProcessorFeatures entry, FALSE past PROCESSOR_FEATURE_MAX (64)."""
    if feature >= 64:
        return 0
    if feature not in PROCESSOR_FEATURES:
        return f"KERNEL32!IsProcessorFeaturePresent({feature}): neww has no answer for this feature yet"
    return PROCESSOR_FEATURES[feature]


@win32("KERNEL32", "GetCurrentDirectoryA")
def get_current_directory_a(wine, length, buf):
    """kernelbase GetCurrentDirectoryA: neww's current directory, C:\\TBK (wine.BIN_DIR). The
    length without the NUL when it fits, else the size needed with it."""
    from .wine import BIN_DIR
    text = BIN_DIR.encode("latin1")
    if length <= len(text):
        return len(text) + 1
    _w(wine, buf, text + b"\x00")
    wine.trace[-1] += f" {BIN_DIR!r}"
    return len(text)


@win32("KERNEL32", "GetLogicalDrives")
def get_logical_drives(wine):
    """kernelbase GetLogicalDrives: a bit per drive. neww's disk is drive C: alone."""
    return 1 << 2


def _upper_ansi(raw):
    """CharUpperBuffA in code page 1252, a character for a character (ß and ÿ stay)."""
    out = bytearray()
    for b in raw:
        ch = bytes([b]).decode("cp1252", "replace")
        up = ch.upper()
        try:
            enc = up.encode("cp1252")
        except UnicodeEncodeError:
            enc = bytes([b])
        out += enc if len(enc) == 1 and len(up) == 1 else bytes([b])
    return bytes(out)


@win32("USER32", "CharUpperA")
def char_upper_a(wine, ptr):
    """user32 CharUpperA: a pointer whose high word is 0 is one character, answered upper
    case; else the string is made upper case in place and the pointer answered."""
    if not ptr >> 16:
        return _upper_ansi(bytes([ptr & 0xFF]))[0]
    raw = read_str(wine, ptr, 0x100000)
    _w(wine, ptr, _upper_ansi(raw))
    return ptr


@win32("KERNEL32", "GetDriveTypeA")
def get_drive_type_a(wine, root):
    """kernelbase GetDriveTypeW: DRIVE_FIXED (3) for C:, DRIVE_NO_ROOT_DIR (1) for a drive
    neww does not have. NULL is the current drive, C:."""
    path = read_str(wine, root).decode("latin1") if root else "C:\\"
    wine.trace[-1] += f" {path!r}"
    return 3 if path[:1].upper() == "C" and path[1:2] in (":", "") else 1


@win32("KERNEL32", "GetFileAttributesA")
def get_file_attributes_a(wine, name_ptr):
    """kernelbase GetFileAttributesW: FILE_ATTRIBUTE_DIRECTORY (10h) for one of neww's
    directories, FILE_ATTRIBUTE_ARCHIVE (20h) for a file neww's disk has, else
    INVALID_FILE_ATTRIBUTES with ERROR_FILE_NOT_FOUND, or ERROR_PATH_NOT_FOUND when the
    folder is not there either. The same answers as INT 21h 4300h."""
    path = read_str(wine, name_ptr).decode("latin1")
    wine.trace[-1] += f" {path!r}"
    if directory_exists(wine, path):
        return 0x10
    if wine.file_exists(path):
        return 0x20
    folder = wine.full_path(path).rsplit("\\", 1)[0]
    _error(wine, 2 if directory_exists(wine, folder or "C:\\") else 3)
    return 0xFFFFFFFF


# win32u sysparams.c: the first monitor added gets handle 1 (++monitor_count). neww has one,
# 1024x768 at 0,0 (METRICS[0], METRICS[1]), with no taskbar, so its work area is all of it.
PRIMARY_MONITOR = 1
MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 1, 2


@win32("USER32", "MonitorFromPoint")
def monitor_from_point(wine, x, y, flags):
    """NtUserMonitorFromPoint -> get_monitor_from_rect of a 1x1 rectangle: the monitor it is
    on, else with MONITOR_DEFAULTTOPRIMARY or MONITOR_DEFAULTTONEAREST the only one, else 0."""
    from .wine import METRICS
    sx = x - (1 << 32) if x & 0x80000000 else x
    sy = y - (1 << 32) if y & 0x80000000 else y
    if 0 <= sx < METRICS[0] and 0 <= sy < METRICS[1]:
        return PRIMARY_MONITOR
    return PRIMARY_MONITOR if flags & (MONITOR_DEFAULTTOPRIMARY | MONITOR_DEFAULTTONEAREST) else 0


@win32("USER32", "GetMonitorInfoA")
def get_monitor_info_a(wine, monitor, info):
    """user32 GetMonitorInfoA: cbSize must be MONITORINFO (40) or MONITORINFOEXA (72). The
    monitor rectangle, the work area and MONITORINFOF_PRIMARY; the EX form adds the device
    name, \\\\.\\DISPLAY1."""
    from .wine import METRICS
    if monitor != PRIMARY_MONITOR:
        return 0
    size = struct.unpack("<I", wine.read_linear(info, 4))[0]
    if size not in (40, 72):
        return 0
    rect = struct.pack("<iiii", 0, 0, METRICS[0], METRICS[1])
    _w(wine, info + 4, rect + rect + struct.pack("<I", 1))
    if size == 72:
        _w(wine, info + 40, b"\\\\.\\DISPLAY1".ljust(32, b"\x00"))
    return 1


# ---------------------------------------------------------------- Global / Local memory

# kernelbase memory.c: a fixed block is a heap pointer; a moveable one is a handle, the
# address of the ptr field of a mem_entry { WORD flags; BYTE lock; BYTE pad; void *ptr; },
# so a handle is 4 mod 8 and a heap pointer (8-aligned) never is.
LMEM_MOVEABLE, LMEM_ZEROINIT, LMEM_MODIFY, LMEM_DISCARDABLE = 0x2, 0x40, 0x80, 0xF00
MEM_ENTRIES = 0x2000


def _mem(wine):
    st = _process(wine)
    if not hasattr(st, "mem_entries"):
        heap = _find_heap(wine, st.process_heap)
        st.mem_entries = heap.alloc(MEM_ENTRIES * 8)
        st.mem = {}          # handle -> [ptr, lock, size]
        st.mem_free = []
        st.mem_next = 0
    return st


def _is_handle(wine, h):
    return h & 7 == 4 and h in _mem(wine).mem


def _put_entry(wine, h, entry):
    _w(wine, h - 4, struct.pack("<HBBI", 0x1 | 0x2, min(entry[1], 255), 0, entry[0]))


def _local_alloc(wine, flags, size):
    st = _mem(wine)
    heap = _find_heap(wine, st.process_heap)
    if not flags & LMEM_MOVEABLE:
        ptr = heap.alloc(size)
        if not ptr:
            _error(wine, ERROR_NOT_ENOUGH_MEMORY)
        return ptr
    if st.mem_free:
        index = st.mem_free.pop()
    elif st.mem_next < MEM_ENTRIES:
        index, st.mem_next = st.mem_next, st.mem_next + 1
    else:
        _error(wine, ERROR_NOT_ENOUGH_MEMORY)
        return 0
    h = st.mem_entries + 8 * index + 4
    ptr = heap.alloc(size) if size else 0
    st.mem[h] = [ptr, 0, size]
    _put_entry(wine, h, st.mem[h])
    return h


@win32("KERNEL32", "GlobalAlloc")
def global_alloc(wine, flags, size):
    """GlobalAlloc -> LocalAlloc; a fixed block of 0 bytes is made 1 byte. neww's heap blocks
    are always zero, which covers GMEM_ZEROINIT."""
    if not flags & LMEM_MOVEABLE and not size:
        size = 1
    return _local_alloc(wine, flags, size)


@win32("KERNEL32", "LocalAlloc")
def local_alloc(wine, flags, size):
    return _local_alloc(wine, flags, size)


@win32("KERNEL32", "GlobalLock")
def global_lock(wine, h):
    """LocalLock: a pointer is itself; a handle's lock count goes up and its block is the
    answer (NULL, ERROR_DISCARDED, for a discarded one)."""
    if not h:
        return 0
    if _is_handle(wine, h):
        entry = _mem(wine).mem[h]
        if not entry[0]:
            _error(wine, 0x10D)   # ERROR_DISCARDED
            return 0
        if entry[1] < 255:
            entry[1] += 1
        _put_entry(wine, h, entry)
        return entry[0]
    return h


@win32("KERNEL32", "LocalLock")
def local_lock(wine, h):
    return global_lock(wine, h)


@win32("KERNEL32", "GlobalUnlock")
def global_unlock(wine, h):
    """GlobalUnlock: TRUE for a pointer; for a handle LocalUnlock, the lock count down and
    TRUE while it is still locked, else FALSE with ERROR_SUCCESS, or ERROR_NOT_LOCKED."""
    if not _is_handle(wine, h):
        return 1
    entry = _mem(wine).mem[h]
    if not entry[1]:
        _error(wine, 158)   # ERROR_NOT_LOCKED
        return 0
    if entry[1] < 255:
        entry[1] -= 1
    _put_entry(wine, h, entry)
    if entry[1]:
        return 1
    _error(wine, 0)
    return 0


@win32("KERNEL32", "LocalUnlock")
def local_unlock(wine, h):
    if not _is_handle(wine, h):
        _error(wine, 158)
        return 0
    return global_unlock(wine, h)


@win32("KERNEL32", "GlobalFree")
def global_free(wine, h):
    """LocalFree: NULL when freed, the handle back (ERROR_INVALID_HANDLE) when not."""
    st = _mem(wine)
    heap = _find_heap(wine, st.process_heap)
    if _is_handle(wine, h):
        entry = st.mem.pop(h)
        if entry[0]:
            heap.release(entry[0])
        st.mem_free.append((h - 4 - st.mem_entries) // 8)
        return 0
    if h and heap.release(h):
        return 0
    if h:
        _error(wine, ERROR_INVALID_HANDLE)
    return h


@win32("KERNEL32", "LocalFree")
def local_free(wine, h):
    return global_free(wine, h)


@win32("KERNEL32", "GlobalSize")
def global_size(wine, h):
    """LocalSize: the block's size, 0 for a discarded one or a bad handle."""
    st = _mem(wine)
    if _is_handle(wine, h):
        entry = st.mem[h]
        return entry[2] if entry[0] else 0
    size = _find_heap(wine, st.process_heap).size(h)
    if size is None:
        _error(wine, ERROR_INVALID_HANDLE)
        return 0
    return size


@win32("KERNEL32", "LocalSize")
def local_size(wine, h):
    return global_size(wine, h)


@win32("KERNEL32", "GlobalHandle")
def global_handle(wine, ptr):
    """LocalHandle: the handle a block belongs to, the pointer itself for a fixed block."""
    st = _mem(wine)
    if _is_handle(wine, ptr):
        return ptr
    for h, entry in st.mem.items():
        if entry[0] == ptr:
            return h
    if _find_heap(wine, st.process_heap).size(ptr) is not None:
        return ptr
    _error(wine, ERROR_INVALID_HANDLE)
    return 0


@win32("KERNEL32", "GlobalReAlloc")
def global_realloc(wine, h, size, flags):
    """GlobalReAlloc -> LocalReAlloc for the cases a run reaches: a size change of a fixed
    block (moving only with GMEM_MOVEABLE) or of a handle's block (in place while locked
    unless GMEM_MOVEABLE). GMEM_MODIFY and discarding stop."""
    if flags & (LMEM_MODIFY | LMEM_DISCARDABLE) or not size:
        return f"KERNEL32!GlobalReAlloc({h:#x}, {size:#x}, {flags:#x}): GMEM_MODIFY, discarding or size 0, which neww does not do yet"
    st = _mem(wine)
    heap = st.process_heap
    in_place = HEAP_REALLOC_IN_PLACE_ONLY
    if _is_handle(wine, h):
        entry = st.mem[h]
        hflags = in_place if entry[1] and not flags & LMEM_MOVEABLE else 0
        ptr = k32_heap_realloc(wine, heap, hflags, entry[0], size) if entry[0] else _find_heap(wine, heap).alloc(size)
        if not ptr:
            return 0
        entry[0], entry[2] = ptr, size
        _put_entry(wine, h, entry)
        return h
    hflags = 0 if flags & LMEM_MOVEABLE else in_place
    return k32_heap_realloc(wine, heap, hflags, h, size)
