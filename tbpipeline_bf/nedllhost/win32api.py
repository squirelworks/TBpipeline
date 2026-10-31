"""The Win32 calls TB80W32.DLL makes, answered by name.

Each answer is the documented Win32 behavior for the arguments seen, on
a Windows 98 machine with ToolBook in C:\\TOOLBOOK. A call with no
documented answer for its arguments raises Unanswered and the run stops.
"""

import struct

from .win32 import SYSTEM_HANDLES, WIN32, Unanswered

# Memory comes from one bump arena: nothing is freed, and HeapSize reads
# the size kept before each block.

HEAP32 = 0x20000000
HEAP32_SIZE = 0x01000000
EXE_HANDLE = 0x00400000
COMMAND_LINE = b"C:\\TOOLBOOK\\TB80RTM.EXE fixture.tbk"


def _api(dll, name, pop):
    def register(fn):
        WIN32[(dll, name)] = (pop, fn)
        return fn
    return register


def _mem(host):
    """The bump arena, mapped on first use."""
    if not getattr(host, "heap32", None):
        host.uc.mem_map(HEAP32, HEAP32_SIZE)
        host.heap32 = {"next": HEAP32 + 0x10, "handles": 0x100, "last_error": 0}
    return host.heap32


def _alloc(host, size, align=8):
    mem = _mem(host)
    at = (mem["next"] + 8 + align - 1) & ~(align - 1)
    if at + size > HEAP32 + HEAP32_SIZE:
        return 0
    host.uc.mem_write(at - 4, struct.pack("<I", size))
    mem["next"] = at + size
    return at


def _static(host, key, data):
    mem = _mem(host)
    if key not in mem:
        at = _alloc(host, len(data))
        host.uc.mem_write(at, data)
        mem[key] = at
    return mem[key]


def _handle(host):
    mem = _mem(host)
    mem["handles"] += 4
    return mem["handles"]


def _cstr(host, at, limit=0x1000):
    if not at:
        return b""
    raw = bytes(host.uc.mem_read(at, limit))
    return raw.split(b"\x00", 1)[0]


def _copy_out(host, at, data, size):
    """Copy data and a NUL into a buffer of size bytes. Returns the count."""
    if not at or size <= 0:
        return 0
    data = data[:size - 1]
    host.uc.mem_write(at, data + b"\x00")
    return len(data)


@_api("KERNEL32", "GetVersion", 0)
def _get_version(host, args):
    # Windows 98: the 9x bit in the high word, minor 10, major 4.
    return 0xC0000A04


@_api("KERNEL32", "GetModuleHandleA", 4)
def _get_module_handle(host, args):
    if not args[0]:
        return EXE_HANDLE
    name = _cstr(host, args[0]).decode("latin1").upper().rsplit("\\", 1)[-1]
    stem = name[:-4] if name.endswith((".DLL", ".EXE")) else name
    if stem in SYSTEM_HANDLES:
        return SYSTEM_HANDLES[stem]
    for mod in host.pe32.values():
        if mod["path"].upper().rsplit("/", 1)[-1].startswith(stem + "."):
            return mod["base"]
    return 0


@_api("KERNEL32", "GetProcAddress", 8)
def _get_proc_address(host, args):
    handle, name = args[0], args[1]
    what = name & 0xFFFF if name < 0x10000 else _cstr(host, name).decode("latin1")
    for dll, value in SYSTEM_HANDLES.items():
        if value == handle:
            return host._api32_stub(dll, what)
    for mod in host.pe32.values():
        if mod["base"] == handle:
            rva = (mod["ords"] if isinstance(what, int) else mod["names"]).get(what)
            return mod["base"] + rva if rva else 0
    return 0


@_api("KERNEL32", "GetCommandLineA", 0)
def _get_command_line(host, args):
    return _static(host, "cmdline", COMMAND_LINE + b"\x00")


@_api("KERNEL32", "GetEnvironmentStrings", 0)
def _get_env(host, args):
    return _static(host, "env", b"\x00\x00")


@_api("KERNEL32", "GetEnvironmentStringsW", 0)
def _get_env_w(host, args):
    # Windows 98 has no Unicode environment block.
    return 0


@_api("KERNEL32", "FreeEnvironmentStringsA", 4)
def _free_env(host, args):
    return 1


@_api("KERNEL32", "FreeEnvironmentStringsW", 4)
def _free_env_w(host, args):
    return 1


@_api("KERNEL32", "GetStartupInfoA", 4)
def _get_startup_info(host, args):
    host.uc.mem_write(args[0], struct.pack("<I", 68) + bytes(64))
    return 0


@_api("KERNEL32", "GetStdHandle", 4)
def _get_std_handle(host, args):
    # A GUI process has no console handles.
    return 0xFFFFFFFF


@_api("KERNEL32", "GetFileType", 4)
def _get_file_type(host, args):
    return 0          # FILE_TYPE_UNKNOWN


@_api("KERNEL32", "SetHandleCount", 4)
def _set_handle_count(host, args):
    return args[0]


@_api("KERNEL32", "GetACP", 0)
def _get_acp(host, args):
    return 1252


@_api("KERNEL32", "GetOEMCP", 0)
def _get_oemcp(host, args):
    return 437


@_api("KERNEL32", "GetCPInfo", 8)
def _get_cp_info(host, args):
    # MaxCharSize 1, DefaultChar '?', no lead bytes: a single-byte page.
    host.uc.mem_write(args[1], struct.pack("<I", 1) + b"?\x00" + bytes(12))
    return 1


@_api("KERNEL32", "GetLastError", 0)
def _get_last_error(host, args):
    return _mem(host)["last_error"]


@_api("KERNEL32", "HeapCreate", 12)
def _heap_create(host, args):
    return _handle(host)


@_api("KERNEL32", "GetProcessHeap", 0)
def _get_process_heap(host, args):
    return _static(host, "process_heap", bytes(4))


@_api("KERNEL32", "HeapDestroy", 4)
def _heap_destroy(host, args):
    return 1


@_api("KERNEL32", "HeapAlloc", 12)
def _heap_alloc(host, args):
    return _alloc(host, args[2])


@_api("KERNEL32", "HeapFree", 12)
def _heap_free(host, args):
    return 1


@_api("KERNEL32", "HeapSize", 12)
def _heap_size(host, args):
    return struct.unpack("<I", bytes(host.uc.mem_read(args[2] - 4, 4)))[0]


@_api("KERNEL32", "HeapReAlloc", 16)
def _heap_realloc(host, args):
    old = args[2]
    size = struct.unpack("<I", bytes(host.uc.mem_read(old - 4, 4)))[0]
    new = _alloc(host, args[3])
    if new:
        host.uc.mem_write(new, bytes(host.uc.mem_read(old, min(size, args[3]))))
    return new


@_api("KERNEL32", "VirtualAlloc", 16)
def _virtual_alloc(host, args):
    addr, size = args[0], args[1]
    if addr:
        return addr       # committing pages of an earlier reservation
    return _alloc(host, size, 0x1000)


@_api("KERNEL32", "VirtualFree", 12)
def _virtual_free(host, args):
    return 1


@_api("KERNEL32", "GetModuleFileNameA", 12)
def _get_module_file_name(host, args):
    handle = args[0]
    name = "C:\\TOOLBOOK\\TB80RTM.EXE"
    for mod in host.pe32.values():
        if mod["base"] == handle:
            name = "C:\\TOOLBOOK\\" + mod["path"].replace("\\", "/").rsplit("/", 1)[-1].upper()
    return _copy_out(host, args[1], name.encode("latin1"), args[2])


@_api("WOW32", "WOWGetVDMPointerFix", 12)
def _wow_get_vdm_pointer_fix(host, args):
    # (vp, cb, fProtectedMode): a 16:16 pointer to its linear address.
    return host._linear(args[0])


@_api("WOW32", "WOWGetVDMPointerUnfix", 4)
def _wow_get_vdm_pointer_unfix(host, args):
    return 0


LOCALE = {
    0x0001: "0409",          # LOCALE_ILANGUAGE
    0x0002: "English (United States)",
    0x0003: "ENU",           # LOCALE_SABBREVLANGNAME
    0x0007: "USA",
    0x000B: "437",           # LOCALE_IDEFAULTCODEPAGE
    0x000E: ".",             # LOCALE_SDECIMAL
    0x000F: ",",             # LOCALE_STHOUSAND
    0x1001: "English",       # LOCALE_SENGLANGUAGE
    0x1002: "United States",
    0x1004: "1252",          # LOCALE_IDEFAULTANSICODEPAGE
}


@_api("KERNEL32", "GetLocaleInfoA", 16)
def _get_locale_info(host, args):
    lcid, kind, buf, size = args[:4]
    text = LOCALE.get(kind & 0xFFFF)
    if text is None or lcid & 0x3FF not in (0x09, 0x00):
        raise Unanswered(f"lcid {lcid:#x} type {kind:#x}")
    data = text.encode("latin1") + b"\x00"
    if size == 0:
        return len(data)
    if size < len(data):
        return 0
    host.uc.mem_write(buf, data)
    return len(data)


@_api("KERNEL32", "GetSystemDefaultLCID", 0)
def _get_system_lcid(host, args):
    return 0x0409


@_api("KERNEL32", "GetUserDefaultLCID", 0)
def _get_user_lcid(host, args):
    return 0x0409


def _path_answer(host, buf, size, text):
    """The Win32 path calls: the length copied, or the size needed."""
    data = text.encode("latin1")
    if size <= len(data):
        return len(data) + 1
    host.uc.mem_write(buf, data + b"\x00")
    return len(data)


@_api("KERNEL32", "GetTempPathA", 8)
def _get_temp_path(host, args):
    return _path_answer(host, args[1], args[0], "C:\\WINDOWS\\TEMP\\")


@_api("KERNEL32", "GetWindowsDirectoryA", 8)
def _get_windows_directory(host, args):
    return _path_answer(host, args[0], args[1], "C:\\WINDOWS")


@_api("KERNEL32", "GetSystemDirectoryA", 8)
def _get_system_directory(host, args):
    return _path_answer(host, args[0], args[1], "C:\\WINDOWS\\SYSTEM")


@_api("KERNEL32", "lstrlenA", 4)
def _lstrlen(host, args):
    return len(_cstr(host, args[0], 0x10000))


@_api("KERNEL32", "lstrcpyA", 8)
def _lstrcpy(host, args):
    host.uc.mem_write(args[0], _cstr(host, args[1], 0x10000) + b"\x00")
    return args[0]


@_api("KERNEL32", "lstrcpynA", 12)
def _lstrcpyn(host, args):
    if args[2]:
        _copy_out(host, args[0], _cstr(host, args[1], 0x10000), args[2])
    return args[0]


@_api("KERNEL32", "lstrcatA", 8)
def _lstrcat(host, args):
    head = _cstr(host, args[0], 0x10000)
    host.uc.mem_write(args[0] + len(head), _cstr(host, args[1], 0x10000) + b"\x00")
    return args[0]


def _compare(one, two):
    return (one > two) - (one < two)


@_api("KERNEL32", "lstrcmpiA", 8)
def _lstrcmpi(host, args):
    return _compare(_cstr(host, args[0]).lower(), _cstr(host, args[1]).lower())


@_api("KERNEL32", "lstrcmpA", 8)
def _lstrcmp(host, args):
    return _compare(_cstr(host, args[0]), _cstr(host, args[1]))


@_api("KERNEL32", "SetLastError", 4)
def _set_last_error(host, args):
    _mem(host)["last_error"] = args[0]
    return 0


# One process and one thread: a mutex is always free to its only owner,
# and a wait on it is satisfied at once.

@_api("KERNEL32", "CreateMutexA", 12)
def _create_mutex(host, args):
    return _handle(host)


@_api("KERNEL32", "OpenMutexA", 12)
def _open_mutex(host, args):
    return _handle(host)


@_api("KERNEL32", "ReleaseMutex", 4)
def _release_mutex(host, args):
    return 1


@_api("KERNEL32", "WaitForSingleObject", 8)
def _wait_for_single_object(host, args):
    return 0          # WAIT_OBJECT_0


@_api("KERNEL32", "CloseHandle", 4)
def _close_handle(host, args):
    return 1


@_api("KERNEL32", "GetCurrentProcess", 0)
def _get_current_process(host, args):
    return 0xFFFFFFFF


@_api("KERNEL32", "GetCurrentProcessId", 0)
def _get_current_process_id(host, args):
    return 0x10


@_api("KERNEL32", "GetCurrentThreadId", 0)
def _get_current_thread_id(host, args):
    return 0x14


@_api("KERNEL32", "MultiByteToWideChar", 24)
def _mb_to_wc(host, args):
    cp, flags, src, count, dst, size = args[:6]
    text = _cstr(host, src, 0x10000) + b"\x00" if count == 0xFFFFFFFF else bytes(host.uc.mem_read(src, count))
    wide = text.decode("cp1252", "replace").encode("utf-16-le")
    if size == 0:
        return len(wide) // 2
    if size * 2 < len(wide):
        return 0
    host.uc.mem_write(dst, wide)
    return len(wide) // 2


@_api("KERNEL32", "WideCharToMultiByte", 32)
def _wc_to_mb(host, args):
    cp, flags, src, count, dst, size = args[:6]
    if count == 0xFFFFFFFF:
        raw = bytes(host.uc.mem_read(src, 0x2000))
        end = next(i for i in range(0, len(raw), 2) if raw[i:i + 2] == b"\x00\x00")
        raw = raw[:end + 2]
    else:
        raw = bytes(host.uc.mem_read(src, count * 2))
    text = raw.decode("utf-16-le").encode("cp1252", "replace")
    if size == 0:
        return len(text)
    if size < len(text):
        return 0
    host.uc.mem_write(dst, text)
    return len(text)


@_api("KERNEL32", "GetTempFileNameA", 16)
def _get_temp_file_name(host, args):
    path, prefix, unique, buf = args[:4]
    mem = _mem(host)
    if not unique:
        mem["temp"] = mem.get("temp", 0) + 1
        unique = mem["temp"]
    folder = _cstr(host, path).decode("latin1")
    if folder and not folder.endswith("\\"):
        folder += "\\"
    name = f"{folder}{_cstr(host, prefix).decode('latin1')[:3]}{unique & 0xFFFF:X}.TMP"
    host.uc.mem_write(buf, name.encode("latin1") + b"\x00")
    host.task_log.append(f"temp file {name}")
    return unique & 0xFFFF


# The host's 16-bit handles are the 32-bit ones, zero-extended, as Wine's
# WOW32 maps them for windows, menus, DCs and GDI objects.

@_api("WOW32", "WOWHandle32", 8)
def _wow_handle32(host, args):
    return args[0] & 0xFFFF


@_api("WOW32", "WOWHandle16", 8)
def _wow_handle16(host, args):
    return args[0] & 0xFFFF
