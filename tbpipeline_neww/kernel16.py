"""KERNEL, from Wine dlls/krnl386.exe16 at WINE_COMMIT, for the loaded spec rows.

Each handler names the Wine function it follows. Where Wine reads the host
(files, the registry, the time), neww's host is the --b directory and an
in-memory store that starts empty, and the docstring says so.
"""

import struct
from pathlib import Path

from .handlers import handles, segptr, signed
from .local import ARENA_HEADER_SIZE, LMEM_DISCARDED, LMEM_MOVEABLE, LMEM_ZEROINIT, MOVEABLE_PREFIX, LocalHeap, Stop as LocalStop

HFILE_ERROR = 0xFFFF
LMEM_MODIFY = 0x0080
GMEM_MOVEABLE = 0x0002
GMEM_DISCARDABLE = 0x0100
GMEM_MODIFY = 0x0080
# Wine global.c: GLOBAL_MAX_ALLOC_SIZE.
GLOBAL_MAX_ALLOC_SIZE = 0x00FF0000
WINDOWS_DIR = "C:\\WINDOWS"
# GetFreeSpace16 is GlobalMemoryStatus' dwAvailVirtual. neww's address space is its 16 MB of
# linear memory, and that is the answer, not the host's.
FREE_SPACE = 0x00F00000


def cstr(wine, sel, off, limit=0x10000):
    """The NUL-terminated string at sel:off, as bytes. b"" for a null pointer."""
    if not sel:
        return b""
    out = bytearray()
    while len(out) < limit:
        chunk = wine.read(sel, off + len(out), min(256, limit - len(out)))
        if not chunk:
            break
        cut = chunk.find(b"\x00")
        if cut >= 0:
            out += chunk[:cut]
            break
        out += chunk
    return bytes(out)


def far(wine, ptr):
    """A SEGPTR as (selector, offset)."""
    return ptr >> 16, ptr & 0xFFFF


# ---------------------------------------------------------------- strings, kernel.c

@handles("KERNEL", 88)
def lstrcpy(wine, arg):
    """kernel.c lstrcpy16(SEGPTR dst, LPCSTR src): returns dst."""
    dst = segptr(arg(2), arg(3))
    src = cstr(wine, arg(1), arg(0))
    wine.write(dst >> 16, dst & 0xFFFF, src + b"\x00")
    return dst & 0xFFFF, dst >> 16, None


@handles("KERNEL", 89)
def lstrcat(wine, arg):
    """kernel.c lstrcat16(SEGPTR dst, LPCSTR src): strcat, returns dst."""
    dst = segptr(arg(2), arg(3))
    sel, off = far(wine, dst)
    have = cstr(wine, sel, off)
    wine.write(sel, off + len(have), cstr(wine, arg(1), arg(0)) + b"\x00")
    return dst & 0xFFFF, dst >> 16, None


@handles("KERNEL", 90)
def lstrlen(wine, arg):
    """kernel.c lstrlen16: lstrlenA, 0 for NULL."""
    return len(cstr(wine, arg(1), arg(0))) & 0xFFFF, 0, None


@handles("KERNEL", 353)
def lstrcpyn(wine, arg):
    """kernel.c lstrcpyn16(SEGPTR dst, LPCSTR src, INT16 n): lstrcpynA, at most n - 1 chars and a NUL."""
    n = signed(arg(0))
    dst = segptr(arg(3), arg(4))
    if n <= 0:
        # lstrcpynA with n 0 copies nothing and returns dst.
        return dst & 0xFFFF, dst >> 16, None
    src = cstr(wine, arg(2), arg(1), n)[:n - 1]
    wine.write(dst >> 16, dst & 0xFFFF, src + b"\x00")
    return dst & 0xFFFF, dst >> 16, None


@handles("KERNEL", 348)
def hmemcpy(wine, arg):
    """kernel.c hmemcpy16(dst, src, LONG count): memcpy over huge pointers. Void."""
    count = segptr(arg(0), arg(1))
    if count & 0x80000000 or count == 0:
        return arg.regs("ax"), 0, None
    src = (arg(3), arg(2))
    dst = (arg(5), arg(4))
    data = wine.read(src[0], src[1], count)
    if len(data) != count:
        return 0, 0, f"KERNEL.348 hmemcpy {count:#x} bytes from {src[0]:#x}:{src[1]:#x}: not all of it is in a block neww has"
    wine.write_huge(dst[0], dst[1], data)
    return arg.regs("ax"), 0, None


@handles("KERNEL", 207)
def is_dbcs_lead_byte(wine, arg):
    """IsDBCSLeadByte16 is IsDBCSLeadByte: the ANSI code page is 1252, which has no lead bytes."""
    return 0, 0, None


# ---------------------------------------------------------------- local heap, local.c

def _local_heap(wine, arg):
    return wine.local_heap(arg.regs("ds"), arg.word)


@handles("KERNEL", 8)
def local_lock(wine, arg):
    """local.c LocalLock16 -> LOCAL_InternalLock: a moveable block's lock goes up (not past 0xFE),
    and the answer is its address. A fixed block is its handle."""
    heap = _local_heap(wine, arg)
    handle = arg(0)
    if handle & 3 == 2:
        lock = arg.word(heap.ds, handle + 2) >> 8
        if lock == 0xFF:
            # LMEM_DISCARDED: the address is 0.
            return 0, heap.ds, None
        if lock < 0xFE:
            wine.write(heap.ds, handle + 3, bytes([lock + 1]))
        return heap.w(handle), heap.ds, None
    return handle, heap.ds if handle else 0, None


@handles("KERNEL", 9)
def local_unlock(wine, arg):
    """local.c LocalUnlock16: a moveable block's new lock count, FALSE for fixed or unlocked."""
    heap = _local_heap(wine, arg)
    handle = arg(0)
    if handle & 3 != 2:
        return 0, 0, None
    lock = arg.word(heap.ds, handle + 2) >> 8
    if lock in (0, 0xFF):
        return 0, 0, None
    wine.write(heap.ds, handle + 3, bytes([lock - 1]))
    return lock - 1, 0, None


@handles("KERNEL", 10)
def local_size(wine, arg):
    """local.c LocalSize16: the arena's next minus the block's address."""
    heap = _local_heap(wine, arg)
    handle = arg(0)
    if not handle:
        return 0, 0, None
    if handle & 3 == 2:
        handle = heap.w(handle)
        if not handle:
            return 0, 0, None
        arena = handle - MOVEABLE_PREFIX - ARENA_HEADER_SIZE
    else:
        arena = handle - ARENA_HEADER_SIZE
    return (heap.w(arena + 2) - handle) & 0xFFFF, 0, None


@handles("KERNEL", 11)
def local_handle(wine, arg):
    """local.c LocalHandle16: the handle entry whose address is addr, else addr itself."""
    heap = _local_heap(wine, arg)
    info = heap.info()
    if info is None:
        return 0, 0, f"KERNEL.11 LocalHandle: no local heap in DS {heap.ds:#x}, Wine's ERR"
    addr = arg(0)
    table = heap.w(info + 0x14)
    while table:
        count = heap.w(table)
        entry = table + 2
        for _ in range(count):
            if heap.w(entry) == addr:
                return entry, 0, None
            entry += 4
        table = heap.w(entry)
    return addr, 0, None


@handles("KERNEL", 6)
def local_realloc(wine, arg):
    """local.c LocalReAlloc16(handle, size, flags), for the paths that do not compact.

    LMEM_MODIFY, size 0 (free or discard), a shrink, a grow into a free next arena, and a move
    to a new block are Wine's. Where Wine would compact the heap to find room, neww stops.
    """
    heap = _local_heap(wine, arg)
    handle, size, flags = arg(2), arg(1), arg(0)
    if not handle:
        return 0, 0, None
    moveable = handle & 3 == 2
    if moveable and arg.word(heap.ds, handle + 2) >> 8 == 0xFF and heap.w(handle) == 0 and arg.word(heap.ds, handle + 2) & 0xFF != LMEM_DISCARDED >> 8:
        return 0, 0, None
    if heap.info() is None:
        return 0, 0, None
    try:
        if moveable:
            entry_flags = arg.word(heap.ds, handle + 2) & 0xFF
            if entry_flags == LMEM_DISCARDED >> 8:
                size = 5 if size <= 4 else size
                block = heap.get_block(size + MOVEABLE_PREFIX, flags)
                if not block:
                    return 0, 0, None
                heap.put(handle, block + MOVEABLE_PREFIX)
                wine.write(heap.ds, handle + 2, b"\x00\x00")
                heap.put(block, handle)
                return handle, 0, None
            block = heap.w(handle) - MOVEABLE_PREFIX
            if block & 3 or heap.w(block) != handle:
                return 0, 0, None
        else:
            block = handle
        if flags & LMEM_MODIFY:
            if moveable:
                wine.write(heap.ds, handle + 2, bytes([(flags & 0x0F00) >> 8]))
            return handle, 0, None
        if not size:
            lock = arg.word(heap.ds, handle + 2) >> 8 if moveable else 0
            if flags & LMEM_MOVEABLE:
                if not moveable:
                    return heap.free(handle), 0, None
                if lock == 0:
                    heap.free_arena(block - ARENA_HEADER_SIZE)
                    heap.put(handle, 0)
                    wine.write(heap.ds, handle + 2, bytes([LMEM_DISCARDED >> 8]))
                    return handle, 0, None
                return 0, 0, None
            if flags == 0 and moveable and lock == 0:
                return heap.free(handle), 0, None
            return 0, 0, None
        arena = block - ARENA_HEADER_SIZE
        size = 5 if size <= 4 else size
        if moveable:
            size += MOVEABLE_PREFIX
        nxt = heap.w(arena + 2)
        oldsize = nxt - arena - ARENA_HEADER_SIZE
        nextarena = (block + size + 3) & ~3
        if nextarena <= nxt:
            heap.shrink_arena(arena, nextarena - arena)
            return handle, 0, None
        if (heap.w(nxt) & 3) == 0 and nextarena <= heap.w(nxt + 2):
            return 0, 0, f"KERNEL.6 LocalReAlloc({handle:#x}, {arg(1):#x}): Wine grows into the next free arena (LOCAL_GrowArenaUpward), which neww has not ported"
        if not flags & LMEM_MOVEABLE:
            if not moveable or arg.word(heap.ds, handle + 2) >> 8:
                return 0, 0, None
        new = heap.get_block(size, flags)
        if not new:
            return 0, 0, f"KERNEL.6 LocalReAlloc({handle:#x}, {arg(1):#x}): no free block, and Wine would compact the heap"
        data = arg.machine._read(arg.machine.box.selectors[heap.ds], block, oldsize)
        wine.write(heap.ds, new, data)
        heap.free_arena(arena)
        if moveable:
            heap.put(handle, new + MOVEABLE_PREFIX)
            new = handle
        return (0 if size == oldsize else new), 0, None
    except LocalStop as why:
        return 0, 0, f"KERNEL.6 LocalReAlloc({handle:#x}, {arg(1):#x}): {why}"


# ---------------------------------------------------------------- global heap, global.c

@handles("KERNEL", 19)
def global_unlock(wine, arg):
    """global.c GlobalUnlock16: the lock count goes down if not 0, and the new count is the answer."""
    sel = wine.selector_of(arg(0))
    if sel is None:
        return 0, 0, None
    count = wine.locks.get(sel, 0)
    if count:
        count -= 1
        wine.locks[sel] = count
    return count, 0, None


@handles("KERNEL", 21)
def global_handle(wine, arg):
    """global.c GlobalHandle16(sel): MAKELONG(arena handle, selector). 0 for an invalid one."""
    sel = wine.selector_of(arg(0))
    if sel is None:
        return 0, 0, None
    handle = wine.handle_of(sel)
    return handle, sel, None


@handles("KERNEL", 22)
def global_flags(wine, arg):
    """global.c GlobalFlags16: the lock count, GMEM_DISCARDABLE if the block is. Never discarded here."""
    sel = wine.selector_of(arg(0))
    if sel is None:
        return 0, 0, None
    flags = wine.heap.get(wine.handle_of(sel), (0, 0, 0))[2]
    return (wine.locks.get(sel, 0) & 0xFF) | (GMEM_DISCARDABLE if flags & GMEM_DISCARDABLE else 0), 0, None


@handles("KERNEL", 25)
def global_compact(wine, arg):
    """global.c GlobalCompact16: GLOBAL_MAX_ALLOC_SIZE, whatever is asked."""
    return GLOBAL_MAX_ALLOC_SIZE & 0xFFFF, GLOBAL_MAX_ALLOC_SIZE >> 16, None


@handles("KERNEL", 169)
def get_free_space(wine, arg):
    """global.c GetFreeSpace16: GlobalMemoryStatus' dwAvailVirtual. neww's is FREE_SPACE."""
    return FREE_SPACE & 0xFFFF, FREE_SPACE >> 16, None


@handles("KERNEL", 197)
def global_fix(wine, arg):
    """global.c GlobalFix16: the lock count goes up, and the answer is the selector."""
    sel = wine.selector_of(arg(0))
    if sel is None:
        return 0, 0, None
    wine.locks[sel] = wine.locks.get(sel, 0) + 1
    return sel, 0, None


@handles("KERNEL", 111)
def global_wire(wine, arg):
    """global.c GlobalWire16 is WIN16_GlobalLock16."""
    ax, dx, why = wine._global_lock(arg(0), arg.regs("ds"))
    wine.registers = None
    return ax, dx, why


@handles("KERNEL", 112)
def global_unwire(wine, arg):
    """global.c GlobalUnWire16: !GlobalUnlock16."""
    ax, _dx, _why = global_unlock(wine, arg)
    return (0 if ax else 1), 0, None


@handles("KERNEL", 164)
def global_lru_newest(wine, arg):
    """global.c GlobalLRUNewest16: the handle, unchanged. Wine moves nothing."""
    return arg(0), 0, None


@handles("KERNEL", 16)
def global_realloc(wine, arg):
    """global.c GlobalReAlloc16(handle, DWORD size, flags), as GLOBAL_ReAlloc does it here.

    GMEM_MODIFY changes the flags. A new size moves the bytes into a block of the new size at
    the same handle: neww maps a new block and points the handle's selectors at it.
    """
    handle, flags = arg(3), arg(0)
    size = segptr(arg(1), arg(2))
    sel = wine.selector_of(handle)
    if sel is None:
        return 0, 0, None
    old = wine.heap.get(wine.handle_of(sel))
    if flags & GMEM_MODIFY:
        if old:
            wine.heap[wine.handle_of(sel)] = (old[0], old[1], (old[2] & ~GMEM_MOVEABLE) | (flags & GMEM_MOVEABLE))
        return handle, 0, None
    if size == 0:
        return 0, 0, f"KERNEL.16 GlobalReAlloc({handle:#x}, 0): Wine discards the block, and neww has no discarded blocks"
    if size > 0x100000:
        return 0, 0, f"KERNEL.16 GlobalReAlloc({handle:#x}, {size:#x}): over 1M"
    why = resize_block(wine, handle, size)
    if why:
        return 0, 0, f"KERNEL.16 GlobalReAlloc({handle:#x}, {(size + 0x1F) & ~0x1F:#x}): {why}"
    return handle, 0, None


def resize_block(wine, handle, size):
    """GLOBAL_ReAlloc's new size: the block's bytes at the same selector, rounded to 32 bytes.
    Returns None, or why it could not."""
    sel = wine.selector_of(handle)
    size = (size + 0x1F) & ~0x1F
    oldsize = wine._global_size(handle)
    if wine.resize is None:
        return "no CPU to map the block"
    why = wine.resize(sel, size, oldsize)
    if why:
        return why
    key = wine.handle_of(sel)
    prev = wine.heap.get(key, (sel, oldsize, 0))
    wine.heap[key] = (sel, size, prev[2])
    return None


# ---------------------------------------------------------------- selectors, selector.c

@handles("KERNEL", 334, 335)
def is_bad_ptr(wine, arg):
    """selector.c IsBadReadPtr16 / IsBadWritePtr16 -> IsBadHuge*Ptr16: TRUE unless the selector is a
    block and offset + size - 1 is inside it. size 0 is never bad."""
    size = arg(0)
    ptr = segptr(arg(1), arg(2))
    if not size:
        return 0, 0, None
    sel, off = far(wine, ptr)
    total = wine.size(sel) if sel else None
    if total is None or off + size - 1 >= total:
        return 1, 0, None
    return 0, 0, None


@handles("KERNEL", 336)
def is_bad_code_ptr(wine, arg):
    """selector.c IsBadCodePtr16: TRUE unless the selector is a code segment and the offset is in it."""
    ptr = segptr(arg(0), arg(1))
    sel, off = far(wine, ptr)
    if not wine.is_code(sel):
        return 1, 0, None
    return (0 if off < wine.size(sel) else 1), 0, None


@handles("KERNEL", 337)
def is_bad_string_ptr(wine, arg):
    """selector.c IsBadStringPtr16(ptr, size): TRUE unless the string, or size bytes of it, is in the block."""
    size = arg(0)
    sel, off = far(wine, segptr(arg(1), arg(2)))
    total = wine.size(sel) if sel else None
    if total is None or off >= total:
        return 1, 0, None
    text = cstr(wine, sel, off, total - off)
    length = min(len(text) + 1, size)
    return (1 if off + length - 1 >= total else 0), 0, None


# ---------------------------------------------------------------- tasks and modules

@handles("KERNEL", 51)
def make_proc_instance(wine, arg):
    """task.c MakeProcInstance16(func, hInstance).

    NULL func is NULL. Wine always uses the DS the call came with. When that DS belongs to a
    library, there is no thunk and func is the answer. Otherwise Wine allocates an 8-byte thunk
    (TASK_AllocThunk) holding `mov ax, DS ; jmp far func`, and the answer is its address.
    """
    func = segptr(arg(1), arg(2))
    if not func >> 16:
        return 0, 0, None
    ds = arg.regs("ds")
    owner = wine.owner(wine.selector_of(ds) or ds)
    if owner is not None and wine.is_dll(owner):
        return func & 0xFFFF, func >> 16, None
    sel, off = wine.alloc_thunk()
    wine.write(sel, off, bytes([0xB8, ds & 0xFF, ds >> 8, 0xEA]) + struct.pack("<HH", func & 0xFFFF, func >> 16))
    return off, sel, None


@handles("KERNEL", 52)
def free_proc_instance(wine, arg):
    """task.c FreeProcInstance16: frees Wine's thunk. neww made none. Void."""
    return arg.regs("ax"), 0, None


@handles("KERNEL", 54)
def get_instance_data(wine, arg):
    """task.c GetInstanceData16(instance, buffer, len): copy from the instance's DGROUP to DS."""
    instance, buffer, length = arg(2), arg(1), signed(arg(0))
    sel = wine.selector_of(instance)
    if sel is None or length <= 0:
        return 0, 0, None
    if buffer + length >= 0x10000:
        length = 0x10000 - buffer
    wine.write(arg.regs("ds"), buffer, wine.read(sel, buffer, length))
    return length, 0, None


@handles("KERNEL", 133)
def get_exe_ptr(wine, arg):
    """task.c GetExePtr: the module that owns the handle, 0 if none."""
    return wine._exe_ptr(arg(0)), 0, None


@handles("KERNEL", 48)
def get_module_usage(wine, arg):
    """ne_module.c GetModuleUsage16: the module's count. Each module neww loaded is used once."""
    return (1 if wine._exe_ptr(arg(0)) else 0), 0, None


@handles("KERNEL", 320)
def is_task(wine, arg):
    """task.c IsTask16: TRUE for a TDB. neww's one task handle is the only one."""
    return (1 if arg(0) and arg(0) == wine.htask else 0), 0, None


@handles("KERNEL", 96)
def free_library(wine, arg):
    """ne_module.c FreeLibrary16 -> NE_FreeModule. neww never unloads a module, so the count
    goes nowhere. Void."""
    return arg.regs("ax"), 0, None


@handles("KERNEL", 107)
def set_error_mode(wine, arg):
    """task.c SetErrorMode16: SetErrorMode, which returns the previous mode."""
    prev = wine.error_mode
    wine.error_mode = arg(0)
    return prev, 0, None


@handles("KERNEL", 199)
def set_handle_count(wine, arg):
    """file.c SetHandleCount16 is SetHandleCount, which returns its argument."""
    return arg(0), 0, None


@handles("KERNEL", 29)
def yield_(wine, arg):
    """task.c Yield16. One task, nothing to yield to. Void."""
    return arg.regs("ax"), 0, None


@handles("KERNEL", 115)
def output_debug_string(wine, arg):
    """kernel.c OutputDebugString16. The string goes to the trace. Void."""
    wine.trace[-1] += f" {cstr(wine, arg(1), arg(0), 256).decode('latin1')!r}"
    return arg.regs("ax"), 0, None


@handles("KERNEL", 137)
def fatal_app_exit(wine, arg):
    """task.c FatalAppExit16: Wine shows the message and ends the task. The run ends there."""
    text = cstr(wine, arg(1), arg(0), 256).decode("latin1")
    return 0, 0, f"KERNEL.137 FatalAppExit({arg(2):#x}, {text!r}): the task ends"


# ---------------------------------------------------------------- directories

def _copy_out(wine, sel, off, count, text):
    """GetWindowsDirectoryA-style: copy when it fits and return the length, else the size needed."""
    raw = text.encode("latin1")
    if count > len(raw):
        wine.write(sel, off, raw + b"\x00")
        return len(raw)
    return len(raw) + 1


@handles("KERNEL", 134)
def get_windows_directory(wine, arg):
    """file.c GetWindowsDirectory16 is GetWindowsDirectoryA. neww's windows directory is C:\\WINDOWS."""
    return _copy_out(wine, arg(2), arg(1), arg(0), WINDOWS_DIR), 0, None


@handles("KERNEL", 135)
def get_system_directory(wine, arg):
    """file.c GetSystemDirectory16: the windows directory and \\SYSTEM. On success the NUL is not counted."""
    path = WINDOWS_DIR + "\\SYSTEM"
    count = arg(0)
    if arg(2) and count >= len(path) + 1:
        wine.write(arg(2), arg(1), path.encode() + b"\x00")
        return len(path), 0, None
    return len(path) + 1, 0, None


@handles("KERNEL", 136)
def get_drive_type(wine, arg):
    """file.c GetDriveType16(drive number): C: is neww's one drive, DRIVE_FIXED (3). Any other drive
    has no root, which Wine turns into DRIVE_UNKNOWN (0)."""
    return (3 if arg(0) == 2 else 0), 0, None


# ---------------------------------------------------------------- files

@handles("KERNEL", 83)
def lcreat(wine, arg):
    """file.c _lcreat16(path, attr) -> _lcreat: creates or truncates a file for writing.

    neww does not write the host. A created file lives in memory for the run, under its
    base name, and later opens of that name read it.
    """
    path = cstr(wine, arg(2), arg(1), 260).decode("latin1")
    return wine.create_file(path), 0, None


@handles("KERNEL", 86)
def lwrite(wine, arg):
    """file.c _lwrite16(file, buffer, count) -> _hwrite16. Count 0 truncates at the position."""
    return wine.write_file(arg(3), arg(2), arg(1), arg(0))


@handles("KERNEL", 350)
def hwrite(wine, arg):
    """file.c _hwrite16(file, buffer, LONG count): returns the count written, HFILE_ERROR as -1."""
    ax, dx, why = wine.write_file(arg(4), arg(3), arg(2), segptr(arg(0), arg(1)))
    if ax == HFILE_ERROR and not why:
        return 0xFFFF, 0xFFFF, None
    return ax, dx, why


@handles("KERNEL", 349)
def hread(wine, arg):
    """file.c WIN16_hread(file, SEGPTR buffer, LONG count): reads into a huge buffer. -1 on error."""
    handle = arg(4)
    entry = wine.files.get(handle)
    if entry is None:
        return 0xFFFF, 0xFFFF, None
    count = segptr(arg(0), arg(1))
    chunk = entry[2][entry[3]:entry[3] + count]
    entry[3] += len(chunk)
    if chunk:
        wine.write_huge(arg(3), arg(2), chunk)
    return len(chunk) & 0xFFFF, len(chunk) >> 16, None


@handles("KERNEL", 97)
def get_temp_file_name(wine, arg):
    """file.c GetTempFileName16(drive, prefix, unique, buffer) -> GetTempFileNameA.

    The temporary path is neww's C:\\WINDOWS\\TEMP. With unique 0, Wine tries names until it
    creates one that does not exist. neww's files are in memory, so the first free one is it.
    """
    buf = (arg(1), arg(0))
    unique = arg(2)
    prefix = cstr(wine, arg(4), arg(3), 260).decode("latin1")
    stem = ("~" + prefix)[:4] if prefix else "~"
    number = unique or 1
    while True:
        name = f"{WINDOWS_DIR}\\TEMP\\{stem}{number & 0xFFFF:X}.TMP"
        if unique or not wine.file_exists(name):
            break
        number += 1
    if not unique:
        wine.create_file(name, keep_open=False)
    wine.write(buf[0], buf[1], name.encode("latin1") + b"\x00")
    return number & 0xFFFF, 0, None


# ---------------------------------------------------------------- profiles

def _opt(wine, sel, off):
    """A string argument, or None for a NULL pointer."""
    return cstr(wine, sel, off) if (sel or off) else None


@handles("KERNEL", 128)
def get_private_profile_string(wine, arg):
    """file.c GetPrivateProfileString16(section, entry, default, buffer, len, file)."""
    return wine.profile_string(
        _opt(wine, arg(10), arg(9)), _opt(wine, arg(8), arg(7)), _opt(wine, arg(6), arg(5)),
        (arg(4), arg(3)), arg(2), _opt(wine, arg(1), arg(0)) or b"win.ini",
    )


@handles("KERNEL", 58)
def get_profile_string(wine, arg):
    """file.c GetProfileString16: GetPrivateProfileString16 of win.ini."""
    return wine.profile_string(
        _opt(wine, arg(8), arg(7)), _opt(wine, arg(6), arg(5)), _opt(wine, arg(4), arg(3)),
        (arg(2), arg(1)), arg(0), b"win.ini",
    )


@handles("KERNEL", 127)
def get_private_profile_int(wine, arg):
    """file.c GetPrivateProfileInt16(section, entry, INT16 default, file) -> GetPrivateProfileIntA."""
    return wine.profile_int(_opt(wine, arg(6), arg(5)), _opt(wine, arg(4), arg(3)), signed(arg(2)),
                            _opt(wine, arg(1), arg(0)) or b"win.ini")


@handles("KERNEL", 57)
def get_profile_int(wine, arg):
    """file.c GetProfileInt16: GetPrivateProfileInt16 of win.ini."""
    return wine.profile_int(_opt(wine, arg(4), arg(3)), _opt(wine, arg(2), arg(1)), signed(arg(0)), b"win.ini")


@handles("KERNEL", 129)
def write_private_profile_string(wine, arg):
    """file.c WritePrivateProfileString16(section, entry, string, file). Kept in memory for the run."""
    return wine.write_profile(_opt(wine, arg(7), arg(6)), _opt(wine, arg(5), arg(4)), _opt(wine, arg(3), arg(2)),
                              _opt(wine, arg(1), arg(0)) or b"win.ini")


@handles("KERNEL", 59)
def write_profile_string(wine, arg):
    """file.c WriteProfileString16: WritePrivateProfileString16 of win.ini."""
    return wine.write_profile(_opt(wine, arg(5), arg(4)), _opt(wine, arg(3), arg(2)), _opt(wine, arg(1), arg(0)), b"win.ini")
