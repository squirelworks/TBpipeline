"""32-bit DLLs behind the Windows 95/NT generic thunks.

TB80W16 reaches TB80W32.DLL, a PE DLL, through the KERNEL generic thunks
(krnl386.exe16.spec 513 to 518). This mixin answers KERNEL.513
LoadLibraryEx32W and KERNEL.515 GetProcAddress32W. LoadLibraryEx32W
maps the PE at its image base in the same CPU, gives it a flat 32-bit
code and data selector, a stack and a TEB, and runs its entry point
with DLL_PROCESS_ATTACH, as Wine's LoadLibraryEx32W16
(dlls/krnl386.exe16/thunk.c:2495) does through LoadLibraryExA.

Its imports from KERNEL32, USER32 and the rest bind to 8-byte stubs,
`mov edx, id; out 0xE1, al; ret`. The OUT is answered by name from
WIN32. A name with no answer stops the run and is quoted; it never
returns a made-up value. Each answer is its own change and cites the
Wine function it follows.

Entering 32-bit code needs segment loads, and the host cannot load a
segment register in protected mode, so the switch is made in the guest.
Slot 0 of the selector the call came through is never an ordinal; it
becomes a far jump to ENTRY32, which loads the selectors, takes ESP and
the target from a parameter block, calls the target, and ends in
`out 0xE2, al`. The host saves the 16-bit context before the jump and
restores it at that OUT. Both transfers stop the CPU and hand the run
loop a `jump`.
"""

import os
import struct

from ..nehost.pass04 import EXE_PATH

from unicorn import UcError
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_EAX, UC_X86_REG_EDX,
    UC_X86_REG_ESP, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

PORT_API32 = 0xE1
PORT_RETURN32 = 0xE2

# Linear layout of the 32-bit side. TB80W32's image base is 0x10000000.
STUBS32 = 0x0F000000      # 8 bytes per imported name
TEB = 0x0F010000
ENTRY32 = 0x0F011000
PARAMS32 = 0x0F011100     # ESP, target
LOW32 = 0x0F000000
LOW32_SIZE = 0x20000
STACK32 = 0x0F100000
STACK32_SIZE = 0x100000

DLL_PROCESS_ATTACH = 1

# Win32 system DLLs. Windows has them mapped before any task runs, so
# LoadLibraryEx32W returns their handle without a file. Their calls are
# the stubs WIN32 answers.
SYSTEM_HANDLES = {"KERNEL32": 0x7FE00000, "USER32": 0x7FE10000, "GDI32": 0x7FE20000,
                  "ADVAPI32": 0x7FE30000, "WOW32": 0x7FE40000}

# (dll, name) -> (argument bytes popped, handler). handler(self, args)
# returns EAX. A name missing here stops the run, and so does a handler
# that raises Unanswered for arguments it has no documented answer for.
WIN32 = {}


class Unanswered(Exception):
    pass


# The Windows version the 32-bit side reports: Wine's for an application
# with no manifest (Wine commit 2528aff2). ntdll starts from WIN10
# (dlls/ntdll/version.c:483), and kernelbase's init_current_version
# (dlls/kernelbase/version.c:197) reports windows8_version_info,
# { 6, 2, 9200 } (version.c:130), unless a manifest or a PE header of
# 6.3 or later says otherwise. TB80W32 has neither.
WIN_MAJOR, WIN_MINOR, WIN_BUILD, VER_PLATFORM_WIN32_NT = 6, 2, 9200, 2


def _get_version(host, args):
    # GetVersion(void), stdcall, pops 0. Wine's kernelbase GetVersion
    # (dlls/kernelbase/version.c:1462):
    #   result = MAKELONG( MAKEWORD( major, minor ), (platform ^ 2) << 14 );
    #   if (platform == VER_PLATFORM_WIN32_NT) result |= LOWORD(build) << 16;
    result = (WIN_MAJOR | (WIN_MINOR << 8)) | (((VER_PLATFORM_WIN32_NT ^ 2) << 14) << 16)
    return result | ((WIN_BUILD & 0xFFFF) << 16)


WIN32[("KERNEL32", "GetVersion")] = (0, _get_version)


ERROR_MOD_NOT_FOUND = 126
TEB_LAST_ERROR = 0x34


def _cstr32(host, at, limit=260):
    """A NUL-terminated ANSI string in 32-bit linear memory."""
    blob = bytes(host.uc.mem_read(at, limit))
    return blob.split(b"\0", 1)[0].decode("latin1")


def _get_module_handle_a(host, args):
    # GetModuleHandleA(lpModuleName), stdcall, pops 4. Wine's kernelbase
    # GetModuleHandleA (dlls/kernelbase/loader.c:336) is GetModuleHandleExA
    # with GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT. For a name,
    # GetModuleHandleExW (loader.c:386) asks ntdll's LdrGetDllHandleEx
    # (dlls/ntdll/loader.c:3539), which adds ".dll" when the name has no
    # extension (append_dll_ext, loader.c:785) and finds a loaded module
    # by its base name, ignoring case. A name with a path is matched here
    # by its base name too; Wine resolves the path first. Not loaded: NULL, and
    # STATUS_DLL_NOT_FOUND becomes ERROR_MOD_NOT_FOUND in the TEB.
    # NULL asks for the process image, Peb->ImageBaseAddress. This
    # process is 16-bit and has no 32-bit image here, so NULL is not
    # answered.
    if not args[0]:
        raise Unanswered("NULL: the process has no 32-bit image")
    name = _cstr32(host, args[0]).replace("/", "\\").rsplit("\\", 1)[-1]
    if "." not in name:
        name += ".dll"
    name = name.upper()
    for dll, handle in SYSTEM_HANDLES.items():
        if name == dll + ".DLL":
            return handle
    for mod in getattr(host, "pe32", {}).values():
        if os.path.basename(mod["path"]).upper() == name:
            return mod["base"]
    host.uc.mem_write(TEB + TEB_LAST_ERROR, struct.pack("<I", ERROR_MOD_NOT_FOUND))
    return 0


WIN32[("KERNEL32", "GetModuleHandleA")] = (4, _get_module_handle_a)


ERROR_PROC_NOT_FOUND = 127


def _get_proc_address(host, args):
    # GetProcAddress(hModule, lpProcName), stdcall, pops 8. Wine's
    # kernelbase get_proc_address (dlls/kernelbase/loader.c:66): a name
    # when lpProcName >> 16 is not 0, else the ordinal in its low word,
    # looked up by ntdll's LdrGetProcedureAddress (dlls/ntdll/loader.c:2066).
    # A handle that is no loaded module is STATUS_DLL_NOT_FOUND
    # (ERROR_MOD_NOT_FOUND); a missing export is STATUS_PROCEDURE_NOT_FOUND
    # (ERROR_PROC_NOT_FOUND). Either way the result is NULL.
    # A system DLL has no image here: its export is a stub that WIN32
    # answers by name when it is called, as GetProcAddress32W (#151) does.
    # A NULL hModule means the process image, which a 16-bit process
    # doesn't have here, so it is not answered.
    hmod, proc = args[0], args[1]
    if not hmod:
        raise Unanswered("NULL hModule: the process has no 32-bit image")
    what = _cstr32(host, proc) if proc >> 16 else proc & 0xFFFF
    system = next((d for d, h in SYSTEM_HANDLES.items() if h == hmod), None)
    if system:
        return host._api32_stub(system, what)
    mod = next((m for m in getattr(host, "pe32", {}).values() if m["base"] == hmod), None)
    if mod is None:
        error = ERROR_MOD_NOT_FOUND
    else:
        rva = (mod["names"] if isinstance(what, str) else mod["ords"]).get(what)
        if rva:
            return mod["base"] + rva
        error = ERROR_PROC_NOT_FOUND
    host.uc.mem_write(TEB + TEB_LAST_ERROR, struct.pack("<I", error))
    return 0


WIN32[("KERNEL32", "GetProcAddress")] = (8, _get_proc_address)


# Address space for 32-bit reservations (heaps, VirtualAlloc), above the
# DLL images at 0x10000000 and below the system DLL handles. Reservations
# start on 64K boundaries, as Windows' allocation granularity puts them.
ARENA32, ARENA32_END = 0x20000000, 0x7F000000
ERROR_NOT_ENOUGH_MEMORY = 8


def _reserve32(host, size):
    """Map size bytes (rounded to 64K) at the next 64K boundary; its base, or 0 when out of room.

    Unicorn has no reserved-but-uncommitted pages, so the whole
    reservation is mapped readable and writable.
    """
    size = (size + 0xFFFF) & ~0xFFFF
    base = getattr(host, "next32", ARENA32)
    if not size or base + size > ARENA32_END:
        return 0
    host.uc.mem_map(base, size)
    host.next32 = base + size
    host.regions32 = getattr(host, "regions32", {})
    host.regions32[base] = size
    return base


def _heap_create(host, args):
    # HeapCreate(flOptions, dwInitialSize, dwMaximumSize), stdcall, pops 12.
    # Wine's kernelbase HeapCreate (dlls/kernelbase/memory.c:740) is
    # RtlCreateHeap(flags, NULL, max_size, init_size), and NULL becomes
    # ERROR_NOT_ENOUGH_MEMORY. RtlCreateHeap (dlls/ntdll/heap.c:1499), in a
    # 32-bit process:
    #   commit = ROUND_SIZE(commit, INITIAL_COMMIT_ALIGN - 1)   (0x1000)
    #   if (!total) total = ROUND_SIZE(commit + 1, REGION_ALIGN - 1)
    #   if (!commit) commit = REGION_ALIGN
    #   total = min(max(total, commit), 0xffff0000)
    # and allocate_region reserves total bytes; the heap's handle is the
    # region's base. Nothing here allocates from it yet: HeapAlloc is its
    # own answer.
    _, init_size, max_size = args[0], args[1], args[2]
    commit = (init_size + 0xFFF) & ~0xFFF
    total = max_size or ((commit + 1 + 0xFFFF) & ~0xFFFF)
    commit = commit or 0x10000
    total = min(max(total, commit), 0xFFFF0000)
    heap = _reserve32(host, total)
    if not heap:
        host.uc.mem_write(TEB + TEB_LAST_ERROR, struct.pack("<I", ERROR_NOT_ENOUGH_MEMORY))
    return heap


WIN32[("KERNEL32", "HeapCreate")] = (12, _heap_create)


MEM_COMMIT, MEM_RESERVE, MEM_RESET = 0x1000, 0x2000, 0x80000
ERROR_INVALID_PARAMETER = 87
ERROR_INVALID_ADDRESS = 487


def _virtual_alloc(host, args):
    # VirtualAlloc(lpAddress, dwSize, flAllocationType, flProtect), stdcall,
    # pops 16. Wine's kernelbase VirtualAlloc (dlls/kernelbase/memory.c:421)
    # is NtAllocateVirtualMemory on the current process, NULL on failure.
    # NtAllocateVirtualMemory (dlls/ntdll/unix/virtual.c:4850) refuses a
    # size of 0 (STATUS_INVALID_PARAMETER); allocate_virtual_memory
    # (virtual.c:4712) refuses a type with none of MEM_COMMIT, MEM_RESERVE
    # or MEM_RESET the same way. With no address it reserves the size
    # rounded to a page, at 64K granularity, committing it too when
    # MEM_COMMIT is set. MEM_COMMIT alone on an address rounds it down to
    # a page and commits inside the view that holds it, or fails with
    # STATUS_NOT_MAPPED_VIEW (ERROR_INVALID_ADDRESS).
    # Here every reserved page is already mapped read/write, so a commit
    # only checks the range lies in a reservation and the protection is
    # not applied. Reserving at a given address and MEM_RESET are not
    # answered yet.
    addr, size, kind = args[0], args[1], args[2]
    error = 0
    if not size or not kind & (MEM_COMMIT | MEM_RESERVE | MEM_RESET):
        error = ERROR_INVALID_PARAMETER
    elif kind & MEM_RESET:
        raise Unanswered("MEM_RESET")
    elif addr and kind & MEM_RESERVE:
        raise Unanswered(f"MEM_RESERVE at {addr:#x}")
    elif not addr:
        base = _reserve32(host, (size + 0xFFF) & ~0xFFF)
        if base:
            return base
        error = ERROR_NOT_ENOUGH_MEMORY
    else:
        base = addr & ~0xFFF
        end = (addr + size + 0xFFF) & ~0xFFF
        for start, length in getattr(host, "regions32", {}).items():
            if start <= base and end <= start + length:
                return base
        error = ERROR_INVALID_ADDRESS
    host.uc.mem_write(TEB + TEB_LAST_ERROR, struct.pack("<I", error))
    return 0


WIN32[("KERNEL32", "VirtualAlloc")] = (16, _virtual_alloc)


# Wine runs a 16-bit program in winevdm. kernelbase's create_vdm_process
# (dlls/kernelbase/process.c:378) starts it as
#   L"%s --app-name \"%s\" %s", winevdm, ImagePathName, CommandLine
# where winevdm is C:\windows\syswow64\winevdm.exe when the caller is
# 64-bit or WoW64 (a stock 64-bit Wine) and C:\windows\system32\ on a
# 32-bit-only Wine. This takes the 64-bit Wine.
WINEVDM = "C:\\windows\\syswow64\\winevdm.exe"


def _command_line(host):
    """The process command line: winevdm's, around the task's own."""
    task = f"{EXE_PATH} {os.path.basename(host.book)}"
    return f'{WINEVDM} --app-name "{EXE_PATH}" {task}'


def _get_command_line_a(host, args):
    # GetCommandLineA(void), stdcall, pops 0. Wine's kernelbase
    # GetCommandLineA (dlls/kernelbase/process.c:1346) returns command_lineA,
    # the ANSI copy of the process parameters' CommandLine, made once; the
    # same pointer every call. The 32-bit side of this 16-bit task is
    # winevdm's process, so that is winevdm's command line. The task's own
    # command line is its file name (EXE_PATH, as KERNEL.49 answers) and
    # the book, as the PSP tail carries it.
    if not getattr(host, "command_line32", 0):
        text = _command_line(host).encode("latin1") + b"\0"
        at = _reserve32(host, len(text))
        if not at:
            raise Unanswered("no room for the command line")
        host.uc.mem_write(at, text)
        host.command_line32 = at
    return host.command_line32


WIN32[("KERNEL32", "GetCommandLineA")] = (0, _get_command_line_a)


# The process environment, as "NAME=value" strings. This host gives the
# guest no variables, as KERNEL.131 GetDOSEnvironment already answers on
# the 16-bit side, so the block is the terminator alone.
ENVIRONMENT = []


def _environment_block_w():
    """Wine's ProcessParameters->Environment: each string and its NUL in
    UTF-16, then one more NUL. get_env_length (dlls/kernelbase/process.c:1456)
    counts that last NUL, so an empty environment is one WCHAR."""
    return b"".join(v.encode("utf-16-le") + b"\0\0" for v in ENVIRONMENT) + b"\0\0"


def _heap_blocks(host):
    """Blocks handed out as if from the process heap, each in its own
    reservation: the environment copies. HeapFree gives them back."""
    if not hasattr(host, "heap_blocks32"):
        host.heap_blocks32 = set()
    return host.heap_blocks32


def _get_environment_strings_w(host, args):
    # GetEnvironmentStringsW(void), stdcall, pops 0. Wine's kernelbase
    # GetEnvironmentStringsW (dlls/kernelbase/process.c:1555) copies
    # get_env_length(Environment) WCHARs into a new block from the process
    # heap and returns it, or NULL when the allocation fails. Each call is a
    # new copy, which FreeEnvironmentStringsW gives back. The copy goes in
    # its own reservation here; there is no process heap yet.
    block = _environment_block_w()
    at = _reserve32(host, len(block))
    if at:
        host.uc.mem_write(at, block)
        _heap_blocks(host).add(at)
    return at


WIN32[("KERNEL32", "GetEnvironmentStringsW")] = (0, _get_environment_strings_w)


def _get_environment_strings_a(host, args):
    # GetEnvironmentStrings(void), stdcall, pops 0. kernelbase.spec:530
    # exports it as GetEnvironmentStringsA, and kernel32 forwards both
    # names there (kernel32.spec:676-677). Wine's GetEnvironmentStringsA (dlls/kernelbase/process.c:1535)
    # converts the same get_env_length(Environment) WCHARs with
    # WideCharToMultiByte(CP_ACP) into a new block from the process heap,
    # or returns NULL. The ANSI code page is 1252 here (Wine's default for
    # an English locale); a character it lacks becomes '?', the default
    # character. An empty environment is one NUL byte.
    block = _environment_block_w().decode("utf-16-le").encode("cp1252", "replace")
    at = _reserve32(host, len(block))
    if at:
        host.uc.mem_write(at, block)
        _heap_blocks(host).add(at)
    return at


WIN32[("KERNEL32", "GetEnvironmentStrings")] = (0, _get_environment_strings_a)
WIN32[("KERNEL32", "GetEnvironmentStringsA")] = (0, _get_environment_strings_a)


def _free_environment_strings(host, args):
    # FreeEnvironmentStringsA/W(ptr), stdcall, pops 4. kernelbase.spec:403
    # exports the A name as FreeEnvironmentStringsW, which is
    # HeapFree(GetProcessHeap(), 0, ptr) (dlls/kernelbase/process.c:1702).
    # RtlFreeHeap (dlls/ntdll/heap.c:2078) returns TRUE for NULL; a pointer
    # that is no block of the heap is STATUS_INVALID_PARAMETER, so FALSE
    # with ERROR_INVALID_PARAMETER. A freed block's reservation is unmapped.
    ptr = args[0]
    if not ptr:
        return 1
    blocks = _heap_blocks(host)
    if ptr not in blocks:
        host.uc.mem_write(TEB + TEB_LAST_ERROR, struct.pack("<I", ERROR_INVALID_PARAMETER))
        return 0
    blocks.discard(ptr)
    host.uc.mem_unmap(ptr, host.regions32.pop(ptr))
    return 1


WIN32[("KERNEL32", "FreeEnvironmentStringsA")] = (4, _free_environment_strings)
WIN32[("KERNEL32", "FreeEnvironmentStringsW")] = (4, _free_environment_strings)


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


class PE:
    """The parts of a PE image the loader reads."""

    def __init__(self, data):
        self.data = data
        pe = _u32(data, 0x3C)
        opt = pe + 24
        self.base = _u32(data, opt + 28)
        self.size = _u32(data, opt + 56)
        self.headers = _u32(data, opt + 60)
        self.entry = _u32(data, opt + 16)
        self.dirs = [struct.unpack_from("<II", data, opt + 96 + 8 * i) for i in range(16)]
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        at = opt + struct.unpack_from("<H", data, pe + 20)[0]
        self.sections = []
        for i in range(nsec):
            vsize, va, rsize, raw = struct.unpack_from("<IIII", data, at + i * 40 + 8)
            self.sections.append((va, vsize, raw, rsize))

    def image(self):
        blob = bytearray(self.size)
        blob[:self.headers] = self.data[:self.headers]
        for va, vsize, raw, rsize in self.sections:
            chunk = self.data[raw:raw + min(rsize, vsize or rsize)]
            blob[va:va + len(chunk)] = chunk
        return blob

    @staticmethod
    def cstr(blob, at):
        return bytes(blob[at:blob.index(b"\x00", at)]).decode("latin1")

    def imports(self, blob):
        """(dll, name or ordinal, IAT rva) rows."""
        rva, _ = self.dirs[1]
        rows = []
        while rva:
            oft, _, _, name, ft = struct.unpack_from("<IIIII", blob, rva)
            if not name:
                break
            dll = self.cstr(blob, name).upper().rsplit(".", 1)[0]
            at = oft or ft
            n = 0
            while True:
                value = _u32(blob, at + 4 * n)
                if not value:
                    break
                what = value & 0xFFFF if value & 0x80000000 else self.cstr(blob, value + 2)
                rows.append((dll, what, ft + 4 * n))
                n += 1
            rva += 20
        return rows

    def exports(self, blob):
        """name -> rva and ordinal -> rva."""
        rva, _ = self.dirs[0]
        if not rva:
            return {}, {}
        base, nfunc, nname, funcs, names, ords = struct.unpack_from("<IIIIII", blob, rva + 16)
        by_ord = {base + i: _u32(blob, funcs + 4 * i) for i in range(nfunc)}
        by_name = {}
        for i in range(nname):
            name = self.cstr(blob, _u32(blob, names + 4 * i))
            by_name[name] = _u32(blob, funcs + 4 * struct.unpack_from("<H", blob, ords + 2 * i)[0])
        return by_name, by_ord


class Win32:
    """Mixin for Pass06. Needs arena, uc, and the run loop's jump."""

    jump = None

    def _win32_setup(self):
        if getattr(self, "pe32", None) is not None:
            return
        self.pe32 = {}
        self.api32 = []
        self.frames32 = []
        self.uc.mem_map(LOW32, LOW32_SIZE)
        self.uc.mem_map(STACK32, STACK32_SIZE)
        self.code32 = self.arena.alloc_selector(0x10000, 0x9A, fixed_base=0)
        self.data32 = self.arena.alloc_selector(0x10000, 0x92, fixed_base=0)
        for sel in (self.code32, self.data32):
            info = self.arena.segs[sel]
            # Base 0, 4 GB, 4K granularity, 32-bit.
            self.arena._write_descriptor(sel // 8, 0, 0xFFFFF, info["access"], 0xC)
        self.fs32 = self.arena.alloc_selector(0x1000, 0x92, fixed_base=TEB)
        top = STACK32 + STACK32_SIZE
        # NT_TIB: no exception handler, the stack, and the TEB's own address.
        self.uc.mem_write(TEB, struct.pack("<III", 0xFFFFFFFF, top, STACK32) + bytes(12) + struct.pack("<I", TEB))
        d, f = self.data32, self.fs32
        self.uc.mem_write(ENTRY32, bytes([
            0x66, 0xB8, d & 0xFF, d >> 8, 0x8E, 0xD8, 0x8E, 0xC0, 0x8E, 0xD0,
            0x66, 0xB8, f & 0xFF, f >> 8, 0x8E, 0xE0,
            0x8B, 0x25]) + struct.pack("<I", PARAMS32) + bytes([
            0xFF, 0x15]) + struct.pack("<I", PARAMS32 + 4) + bytes([
            0xE6, PORT_RETURN32, 0xF4,
        ]))

    # -- loading -------------------------------------------------------

    def _pe_path(self, name):
        """The file LoadLibraryEx32W names, from the unpacked directory."""
        base = name.replace("/", "\\").rsplit("\\", 1)[-1]
        low = base.lower()
        wanted = {low} if "." in low else {low + ".dll"}
        root = os.environ.get("TBK_UNPACKED", "")
        try:
            listing = os.listdir(root)
        except OSError:
            return None
        hit = next((f for f in listing if f.lower() in wanted), None)
        return os.path.join(root, hit) if hit else None

    def _pe_load(self, path):
        self._win32_setup()
        key = path.upper()
        if key in self.pe32:
            return self.pe32[key]
        pe = PE(open(path, "rb").read())
        blob = pe.image()
        for dll, what, iat in pe.imports(blob):
            struct.pack_into("<I", blob, iat, self._api32_stub(dll, what))
        size = (pe.size + 0xFFF) & ~0xFFF
        self.uc.mem_map(pe.base, size)
        self.uc.mem_write(pe.base, bytes(blob))
        names, ords = pe.exports(blob)
        mod = {"base": pe.base, "entry": pe.base + pe.entry, "names": names, "ords": ords, "path": path}
        self.pe32[key] = mod
        return mod

    def _api32_stub(self, dll, what):
        ident = len(self.api32)
        self.api32.append((dll, what))
        at = STUBS32 + 8 * ident
        self.uc.mem_write(at, bytes([0xBA]) + struct.pack("<I", ident) + bytes([0xE6, PORT_API32, 0xC3]))
        return at

    # -- KERNEL.513 ----------------------------------------------------

    def _kernel_proc(self, ordinal):
        if ordinal == 517:
            return self._call_proc32()
        if ordinal == 518:
            return self._call_proc_ex32()
        if ordinal == 515:
            return self._get_proc_address32()
        if ordinal != 513:
            return super()._kernel_proc(ordinal)
        # LoadLibraryEx32W(lpszLibFile, hFile, dwFlags), Pascal, pops 12.
        # Wine returns LoadLibraryExA's HMODULE, the image base, or 0.
        name = self._string(self._word(5), self._word(4))
        stem = name.upper().replace("/", "\\").rsplit("\\", 1)[-1].rsplit(".", 1)[0]
        if stem in SYSTEM_HANDLES:
            self._win32_setup()
            self._dx_ax(SYSTEM_HANDLES[stem])
            return True
        path = self._pe_path(name)
        if not path:
            self._dx_ax(0)
            return True
        mod = self._pe_load(path)
        if mod.get("attached"):
            self._dx_ax(mod["base"])
            return True

        def attached(eax):
            # DllMain returning FALSE fails the load, and Wine returns 0.
            mod["attached"] = bool(eax)
            self._dx_ax(mod["base"] if eax else 0)

        self._call32(mod["entry"], [mod["base"], DLL_PROCESS_ATTACH, 0], attached)
        return True

    def _call_proc_ex32(self):
        # CallProcEx32W(nParams, fAddressConvert, lpProc32, p1, ..., pn).
        # Wine's spec line (dlls/krnl386.exe16/krnl386.exe16.spec:426) is
        # `518 varargs _CallProcEx32W(long long long) CallProcEx32W16`: it is
        # cdecl, so it pops nothing and the caller cleans up. Its
        # CallProcEx32W16 (dlls/krnl386.exe16/thunk.c:2609) reads at most 32
        # parameters left to right, maps p(i+1) with MapSL when bit i of the
        # mask is set, and WOW_CallProc32W16 calls lpProc32 (stdcall, or
        # cdecl with CPEX_DEST_CDECL, the top bit of nParams) and returns
        # EAX in DX:AX. A NULL lpProc32 returns 0.
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = self.uc.reg_read(UC_X86_REG_SP)
        n, convert, proc = struct.unpack("<III", self.arena.read(ss, (sp + 4) & 0xFFFF, 12))
        n = min(32, n & 0x7FFFFFFF)
        if not proc:
            self._dx_ax(0)
            return True
        params = list(struct.unpack(f"<{n}I", self.arena.read(ss, (sp + 16) & 0xFFFF, 4 * n)))
        for i in range(n):
            if convert & (1 << i):
                params[i] = self._linear(params[i])
        self._call32(proc, params, self._dx_ax)
        return True

    def _call_proc32(self):
        # CallProc32W(p1, ..., pn, lpProc32, fAddressConvert, nParams).
        # Wine's spec line (dlls/krnl386.exe16/krnl386.exe16.spec:425, Wine
        # commit 2528aff2) is
        # `517 varargs CallProc32W(long long long) CallProc32W16`, but
        # CallProc32W16 (dlls/krnl386.exe16/thunk.c:2574) pops for the
        # caller: stack16_pop((3 + nrofargs) * sizeof(DWORD)). The pop table
        # says 0 and the pop happens here, because the size depends on
        # nParams. The caller pushed p1 first, so the list starts at pn: it
        # reads it upwards, maps the i-th one with MapSL when bit i of the
        # mask is set, and stores it at args[n - i - 1] to undo the Pascal
        # order. WOW_CallProc32W16 (thunk.c:2557) returns 0 for a NULL
        # lpProc32, or calls it and returns EAX in DX:AX. At most 32
        # parameters are read, the size of Wine's args array.
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = self.uc.reg_read(UC_X86_REG_SP)
        n, convert, proc = struct.unpack("<III", self.arena.read(ss, (sp + 4) & 0xFFFF, 12))
        n = min(32, n & 0x7FFFFFFF)
        raw = struct.unpack(f"<{n}I", self.arena.read(ss, (sp + 16) & 0xFFFF, 4 * n))
        args = [0] * n
        for i, value in enumerate(raw):
            args[n - i - 1] = self._linear(value) if convert & (1 << i) else value
        ret = self.arena.read(ss, sp, 4)
        dest = (sp + 4 * (3 + n)) & 0xFFFF
        self.arena.write(ss, dest, ret)
        self.uc.reg_write(UC_X86_REG_SP, dest)
        if not proc:
            self._dx_ax(0)
            return True
        self._call32(proc, args, self._dx_ax)
        return True

    def _linear(self, far):
        """MapSL: a 16:16 pointer's linear address. NULL stays NULL."""
        if not far:
            return 0
        info = self.arena.segs.get(far >> 16)
        return (info["base"] if info else 0) + (far & 0xFFFF)

    def _get_proc_address32(self):
        # GetProcAddress32W(hModule, lpszProc), Pascal, pops 8. Wine's
        # GetProcAddress32W16 is GetProcAddress: the export's address, by
        # name or by an ordinal in the low word, or 0. A Win32 system DLL
        # has no image here; its export is a stub WIN32 answers by name.
        noff, nseg = self._word(0), self._word(1)
        hmod = self._word(2) | (self._word(3) << 16)
        what = noff if nseg == 0 else self._string(nseg, noff)
        system = next((d for d, h in SYSTEM_HANDLES.items() if h == hmod), None)
        if system:
            self._win32_setup()
            self._dx_ax(self._api32_stub(system, what))
            return True
        mod = next((m for m in getattr(self, "pe32", {}).values() if m["base"] == hmod), None)
        if mod is None:
            rva = None
        elif nseg == 0:
            rva = mod["ords"].get(noff)
        else:
            rva = mod["names"].get(what)
        self._dx_ax(mod["base"] + rva if rva else 0)
        return True

    def _dx_ax(self, value):
        self.uc.reg_write(UC_X86_REG_AX, value & 0xFFFF)
        self.uc.reg_write(UC_X86_REG_DX, (value >> 16) & 0xFFFF)

    # -- running 32-bit code ------------------------------------------

    def _call32(self, target, params, done):
        """Stop, then run target(params) as stdcall and hand EAX to done."""
        self.jump = lambda: self._enter32(target, params, done)
        self.uc.emu_stop()

    def _enter32(self, target, params, done):
        uc = self.uc
        cs = uc.reg_read(UC_X86_REG_CS)
        saved = uc.context_save()
        top = self.frames32[-1][2] - 0x40 if self.frames32 else STACK32 + STACK32_SIZE - 0x40
        esp = top - 4 * len(params)
        uc.mem_write(esp, b"".join(struct.pack("<I", p & 0xFFFFFFFF) for p in params))
        uc.mem_write(PARAMS32, struct.pack("<II", esp, target))
        self.frames32.append((saved, done, esp))
        # Slot 0 of the call's selector: jmp far code32:ENTRY32.
        self.arena.write(cs, 0, bytes([0x66, 0xEA]) + struct.pack("<IH", ENTRY32, self.code32))
        return 0

    def _leave32(self):
        saved, done, _ = self.frames32.pop()
        eax = self.uc.reg_read(UC_X86_REG_EAX)
        self.uc.context_restore(saved)
        done(eax)
        return self.uc.reg_read(UC_X86_REG_IP)

    def _on_out(self, uc, port, size, value, user):
        if port == PORT_RETURN32:
            self.jump = self._leave32
            uc.emu_stop()
            return
        if port == PORT_API32:
            self._api32(uc.reg_read(UC_X86_REG_EDX))
            return
        super()._on_out(uc, port, size, value, user)

    def _api32(self, ident):
        uc = self.uc
        dll, what = self.api32[ident]
        esp = uc.reg_read(UC_X86_REG_ESP)
        name = f"{dll}.{what}"
        self.last32 = name
        answer = WIN32.get((dll, what))
        if answer is None:
            self.fault = f"win32 {name}"
            uc.emu_stop()
            return
        pop, handler = answer
        args = struct.unpack("<8I", bytes(uc.mem_read(esp + 4, 32)))
        try:
            eax = handler(self, args)
        except Unanswered as exc:
            self.fault = f"win32 {name} {exc}"
            uc.emu_stop()
            return
        if pop:
            ret = bytes(uc.mem_read(esp, 4))
            uc.mem_write(esp + pop, ret)
            uc.reg_write(UC_X86_REG_ESP, esp + pop)
        uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_EDX, 0)


# STARTUPINFOA is 68 bytes.
STARTUPINFOA_SIZE = 68
STARTF_USESHOWWINDOW = 0x1
SW_SHOWNORMAL = 1
INVALID_HANDLE_VALUE = 0xFFFFFFFF


def _startup_info_a(host):
    """Wine's startup_infoA, made once at process attach by
    copy_startup_info (dlls/kernel32/kernel_main.c:87) from the process
    parameters. A 16-bit program started as `wine PROGRAM.EXE` goes through
    start.exe /exec (dlls/ntdll/unix/env.c:1936), whose wmain
    (programs/start/start.c:571) calls CreateProcessW with dwFlags
    STARTF_USESHOWWINDOW, wShowWindow SW_SHOWNORMAL and no title, desktop
    or std handles. create_process_params (dlls/kernelbase/process.c:176)
    then makes the title the program's own path, before create_vdm_process
    swaps the image for winevdm, and leaves the desktop empty. An empty
    string still converts to an allocated "" (RtlUnicodeStringToAnsiString,
    dlls/ntdll/rtlstr.c:637), so lpDesktop is not NULL. With no
    STARTF_USESTDHANDLES the three handles are INVALID_HANDLE_VALUE."""
    if not getattr(host, "startup_info32", None):
        title = EXE_PATH.encode("latin1") + b"\0"
        at = _reserve32(host, len(title) + 1)
        if not at:
            raise Unanswered("no room for the startup strings")
        host.uc.mem_write(at, title + b"\0")
        desktop = at + len(title)
        host.startup_info32 = struct.pack(
            "<IIIIIIIIIIIIHHIIII",
            STARTUPINFOA_SIZE, 0, desktop, at,     # cb, lpReserved, lpDesktop, lpTitle
            0, 0, 0, 0,                            # dwX, dwY, dwXSize, dwYSize
            0, 0, 0,                               # dwX/YCountChars, dwFillAttribute
            STARTF_USESHOWWINDOW, SW_SHOWNORMAL,   # dwFlags, wShowWindow
            0, 0,                                  # cbReserved2, lpReserved2
            INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE)
    return host.startup_info32


def _get_startup_info_a(host, args):
    # GetStartupInfoA(LPSTARTUPINFOA), stdcall, pops 4 (kernel32.spec:836).
    # Wine's (dlls/kernel32/kernel_main.c:82) is `*info = startup_infoA;`:
    # the same struct, and so the same string pointers, every call.
    try:
        host.uc.mem_write(args[0], _startup_info_a(host))
    except UcError:
        raise Unanswered(f"info {args[0]:#x} not writable")
    return 0
WIN32[("KERNEL32", "GetStartupInfoA")] = (4, _get_startup_info_a)

from . import win32api  # noqa: E402,F401  registers answers this module does not already have
