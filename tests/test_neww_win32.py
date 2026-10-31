"""Batch 4: Win32 from Win16. KERNEL.513-518 (Wine thunk.c's generic thunks), a 32-bit PE DLL
loaded and run as Wine's loader runs it, and the KERNEL32 and WOW32 functions it calls.

The PE file is built by tests/neww_pe.py and the NE files by tests/neww_ne.py. Each test names
the Wine function it checks. No ToolBook bytes.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne, neww_pe
from tests.test_neww_tasks import Asm, data_with, exe

KERNEL = 1
LOAD_LIBRARY_EX32W, GET_PROC_ADDRESS32W = 513, 515
CALL_PROC32W, CALL_PROC_EX32W = 517, 518
GLOBAL_ALLOC, GLOBAL_REALLOC, GLOBAL_LOCK = 15, 16, 18


def push32(code, value):
    """push dword imm32 in 16-bit code."""
    return code.emit(0x66, 0x68, *struct.pack("<I", value & 0xFFFFFFFF))


def push_mem32(code, addr):
    """The dword at DS:addr, high word first."""
    return code.emit(0xFF, 0x36, (addr + 2) & 0xFF, (addr + 2) >> 8, 0xFF, 0x36, addr & 0xFF, addr >> 8)


def store32(code, addr):
    """DX:AX to DS:addr."""
    code.store("ax", addr)
    return code.store("dx", addr + 2)


def load_library(code, name_at, result_at):
    code.push_ds().push(name_at)
    push32(code, 0)
    push32(code, 0)
    code.call(KERNEL, LOAD_LIBRARY_EX32W)
    return store32(code, result_at)


def get_proc(code, module_at, name_at, result_at):
    push_mem32(code, module_at)
    code.push_ds().push(name_at)
    code.call(KERNEL, GET_PROC_ADDRESS32W)
    return store32(code, result_at)


def call_proc(code, proc_at, args, mask, result_at):
    """CallProc32W: the arguments in order, then proc, mask and count. args are ints or
    ("ds", off) far pointers."""
    for a in args:
        if isinstance(a, tuple):
            code.push_ds().push(a[1])
        else:
            push32(code, a)
    push_mem32(code, proc_at)
    push32(code, mask)
    push32(code, len(args))
    code.call(KERNEL, CALL_PROC32W)
    return store32(code, result_at)


def run(code, data, dlls=(), limit=400_000):
    from tbpipeline_neww.machine import Machine
    code.exit(0)
    with tempfile.TemporaryDirectory() as d:
        exe(d, "TB80RTM.EXE", "TB80RTM", code, data)
        for filename, blob in dlls:
            (Path(d) / filename).write_bytes(blob)
        host = Machine(d)
        host.run(limit=limit)
    return host


def dword(host, off):
    sel = host.box.exe.segments[1].selector
    return host.word(sel, off) | host.word(sel, off + 2) << 16


def strings(**at):
    return data_with(0x400, {int(k[1:], 16): v for k, v in at.items()})


class Rows(unittest.TestCase):
    """spec32_rows.py: a stdcall function pops 4 bytes an argument, 8 for an int64 or double."""

    def test_pops(self):
        from tbpipeline_neww.win32 import spec_row
        self.assertEqual(spec_row("KERNEL32", "GetTempPathA").pop, 8)
        self.assertEqual(spec_row("KERNEL32", "GetVersion").pop, 0)
        self.assertEqual(spec_row("USER32", "wsprintfA").pop, 0)
        self.assertEqual(spec_row("WOW32", "WOWCallback16Ex").pop, 20)

    def test_noname_row_is_found_by_ordinal_only(self):
        from tbpipeline_neww.win32 import spec_row
        self.assertIsNone(spec_row("KERNEL32", "K32WOWCallback16Ex"))
        self.assertEqual(spec_row("KERNEL32", 55).name, "K32WOWCallback16Ex")

    def test_rows_come_from_the_spec_files(self):
        import os
        import subprocess
        from tbpipeline_neww.spec32_rows import SPEC32_ROWS
        from tbpipeline_neww.specgen import WIN32_SPEC_FILES, entries32
        from tbpipeline_neww.wine import WINE_COMMIT
        src = os.environ.get("WINE_SRC")
        if not src:
            self.skipTest("WINE_SRC is not set")
        for module, spec in WIN32_SPEC_FILES.items():
            text = subprocess.run(["git", "-C", src, "show", f"{WINE_COMMIT}:{spec}"],
                                  capture_output=True, text=True, encoding="latin1", check=True).stdout
            self.assertEqual(SPEC32_ROWS[module], entries32(text), module)


class Loading(unittest.TestCase):
    """thunk.c LoadLibraryEx32W16 -> LoadLibraryExA: ntdll loader.c maps the DLL at its base,
    binds its imports and calls DllMain(DLL_PROCESS_ATTACH)."""

    def program(self):
        code = Asm()
        load_library(code, 0x10, 0x100)
        get_proc(code, 0x100, 0x20, 0x104)
        get_proc(code, 0x100, 0x30, 0x108)
        get_proc(code, 0x100, 0x40, 0x10C)
        return code

    def data(self):
        return strings(x10="TINY.DLL", x20="Add", x30="Ver", x40="Missing")

    def test_load_and_find(self):
        host = run(self.program(), self.data(), [("TINY.DLL", neww_pe.build())])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dword(host, 0x100), neww_pe.BASE)
        self.assertEqual(dword(host, 0x104), neww_pe.BASE + neww_pe.ADD)
        self.assertEqual(dword(host, 0x108), neww_pe.BASE + neww_pe.VER)
        # GetProcAddress of a name the DLL does not export is NULL.
        self.assertEqual(dword(host, 0x10C), 0)

    def test_dllmain_gets_process_attach(self):
        host = run(self.program(), self.data(), [("TINY.DLL", neww_pe.build())])
        self.assertEqual(struct.unpack("<I", host.uc.mem_read(neww_pe.BASE + neww_pe.DATA, 4))[0], 1)
        self.assertIn("  TINY DllMain -> 0x1", host.box.wine.trace)

    def test_taken_base_relocates(self):
        code = self.program()
        load_library(code, 0x50, 0x110)
        get_proc(code, 0x110, 0x30, 0x114)
        data = self.data()
        data[0x50:0x5A] = b"OTHER.DLL\x00"
        host = run(code, data, [("TINY.DLL", neww_pe.build()), ("OTHER.DLL", neww_pe.build("OTHER"))])
        self.assertEqual(host.stop, "dos exit 0x0")
        other = dword(host, 0x110)
        self.assertNotEqual(other, neww_pe.BASE)
        # The relocated DllMain stored its reason in its own data, not TINY's.
        self.assertEqual(struct.unpack("<I", host.uc.mem_read(other + neww_pe.DATA, 4))[0], 1)

    def test_missing_file_is_zero(self):
        code = Asm()
        load_library(code, 0x10, 0x100)
        host = run(code, strings(x10="NOPE.DLL"))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dword(host, 0x100), 0)
        self.assertEqual(host.box.wine.w32.last_error, 126)

    def test_builtin_module_and_its_functions(self):
        code = Asm()
        load_library(code, 0x10, 0x100)
        get_proc(code, 0x100, 0x20, 0x104)
        get_proc(code, 0x100, 0x30, 0x108)
        host = run(code, strings(x10="KERNEL32", x20="GetTempPathA", x30="NoSuchFunction"))
        self.assertEqual(host.stop, "dos exit 0x0")
        from tbpipeline_neww.win32 import HMODULE_BASE, STUB_BASE
        self.assertEqual(dword(host, 0x100), HMODULE_BASE)
        self.assertGreater(dword(host, 0x104), STUB_BASE)
        self.assertEqual(dword(host, 0x108), 0)

    def test_dllmain_false_stops(self):
        code = Asm()
        load_library(code, 0x10, 0x100)
        host = run(code, strings(x10="TINY.DLL"), [("TINY.DLL", neww_pe.build(fail=True))])
        self.assertIn("DllMain(DLL_PROCESS_ATTACH) answered FALSE", host.stop)


class Calls(unittest.TestCase):
    """CallProc32W16 and CallProcEx32W16 -> WOW_CallProc32W16: the 32-bit function runs and
    its EAX comes back in DX:AX."""

    def setup_code(self):
        code = Asm()
        load_library(code, 0x10, 0x100)
        get_proc(code, 0x100, 0x20, 0x104)
        get_proc(code, 0x100, 0x30, 0x108)
        get_proc(code, 0x100, 0x40, 0x10C)
        return code

    def data(self):
        return strings(x10="TINY.DLL", x20="Add", x30="Ver", x40="Pass2")

    def test_call_proc32w(self):
        code = self.setup_code()
        call_proc(code, 0x104, [40000, 30000], 0, 0x120)
        code.store("sp", 0x124)
        host = run(code, self.data(), [("TINY.DLL", neww_pe.build())])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dword(host, 0x120), 70000)

    def test_call_proc32w_pops_its_arguments(self):
        code = self.setup_code()
        code.store("sp", 0x130)
        call_proc(code, 0x104, [1, 2], 0, 0x120)
        code.store("sp", 0x134)
        host = run(code, self.data(), [("TINY.DLL", neww_pe.build())])
        sel = host.box.exe.segments[1].selector
        self.assertEqual(host.word(sel, 0x130), host.word(sel, 0x134))

    def test_import_from_kernel32(self):
        code = self.setup_code()
        call_proc(code, 0x108, [], 0, 0x120)
        host = run(code, self.data(), [("TINY.DLL", neww_pe.build())])
        self.assertEqual(host.stop, "dos exit 0x0")
        # version.c GetVersion under win31: 3.10, VER_PLATFORM_WIN32s.
        self.assertEqual(dword(host, 0x120), 0x80000A03)

    def test_mapped_pointer_argument(self):
        # Pass2(len, buf) calls GetTempPathA(len, buf); bit 0 of the mask is the last
        # argument pushed, buf, which MapSL makes linear.
        code = self.setup_code()
        call_proc(code, 0x10C, [0x40, ("ds", 0x200)], 1, 0x120)
        host = run(code, self.data(), [("TINY.DLL", neww_pe.build())])
        self.assertEqual(host.stop, "dos exit 0x0")
        sel = host.box.exe.segments[1].selector
        self.assertEqual(dword(host, 0x120), len("C:\\WINDOWS\\TEMP\\"))
        self.assertEqual(host._read_guest(sel, 0x200, 17), b"C:\\WINDOWS\\TEMP\\\x00")

    def test_call_proc_ex32w_caller_pops(self):
        code = self.setup_code()
        code.store("sp", 0x130)
        push32(code, 7)
        push32(code, 5)
        push_mem32(code, 0x104)
        push32(code, 0)
        push32(code, 2)
        code.call(KERNEL, CALL_PROC_EX32W)
        store32(code, 0x120)
        code.emit(0x83, 0xC4, 20)          # add sp, 20
        code.store("sp", 0x134)
        host = run(code, self.data(), [("TINY.DLL", neww_pe.build())])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dword(host, 0x120), 12)
        sel = host.box.exe.segments[1].selector
        self.assertEqual(host.word(sel, 0x130), host.word(sel, 0x134))

    def test_null_proc_is_zero(self):
        code = Asm()
        code.mov_ax(0x1234)
        call_proc(code, 0x104, [1], 0, 0x120)
        host = run(code, strings())
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dword(host, 0x120), 0)

    def test_import_wine_does_not_export_stops_by_name(self):
        code = self.setup_code()
        call_proc(code, 0x108, [], 0, 0x120)
        dll = neww_pe.build(imports=(("KERNEL32.dll", ("NoSuchExport", "GetTempPathA")),))
        host = run(code, self.data(), [("TINY.DLL", dll)])
        self.assertIn("KERNEL32!NoSuchExport: Wine's kernel32.spec exports no NoSuchExport", host.stop)

    def test_function_without_handler_stops_by_name(self):
        code = self.setup_code()
        call_proc(code, 0x108, [], 0, 0x120)
        dll = neww_pe.build(imports=(("KERNEL32.dll", ("GetTickCount", "GetTempPathA")),))
        host = run(code, self.data(), [("TINY.DLL", dll)])
        self.assertEqual(host.stop, "KERNEL32!GetTickCount: @ stdcall GetTickCount() has no neww handler yet")


class MovedBlock(unittest.TestCase):
    """Wine's 16-bit relay loads DS and ES from its frame on return, so a selector GlobalReAlloc
    moved is loaded again with the new base."""

    def test_ds_sees_the_moved_block(self):
        code = Asm()
        code.push(0x0002)
        push32(code, 0x100)
        code.call(KERNEL, GLOBAL_ALLOC).store("ax", 0x100)
        code.emit(0xFF, 0x36, 0x00, 0x01).call(KERNEL, GLOBAL_LOCK).store("dx", 0x102)
        # GlobalReAlloc(handle, 0x4000, GMEM_MOVEABLE) with DS the block: mov si, ds ;
        # mov ds, [0x102] ; the call ; mov word [0], 0x5678 ; mov ds, si
        code.emit(0xFF, 0x36, 0x00, 0x01)
        push32(code, 0x4000)
        code.push(0x0002)
        code.emit(0x8C, 0xDE, 0x8E, 0x1E, 0x02, 0x01)
        code.call(KERNEL, GLOBAL_REALLOC)
        code.emit(0xC7, 0x06, 0x00, 0x00, 0x78, 0x56, 0x8E, 0xDE)
        host = run(code, strings())
        self.assertEqual(host.stop, "dos exit 0x0")
        sel = host.word(host.box.exe.segments[1].selector, 0x102)
        self.assertEqual(host.word(sel, 0), 0x5678)


class Kernel32(unittest.TestCase):
    """KERNEL32 functions called directly, on a Wine with flat memory."""

    def wine(self):
        from tbpipeline_neww.wine import Wine
        w = Wine(tempfile.mkdtemp())
        mem = bytearray(0x10000)
        base = 0x40000000

        def read(addr, n):
            if 0x1000 <= addr < 0x11000:
                return bytes(mem[addr - 0x1000:addr - 0x1000 + n])
            return bytes(heap.get(addr + i, 0) for i in range(n))

        def write(addr, data):
            if 0x1000 <= addr < 0x11000:
                mem[addr - 0x1000:addr - 0x1000 + len(data)] = data
                return
            for i, b in enumerate(data):
                heap[addr + i] = b
        heap = {}
        w.read_linear, w.write_linear = read, write
        w.map_linear = lambda b, s: None
        w.setup32 = lambda: None
        w.trace.append("test")
        self.base = base
        return w

    def put(self, w, addr, raw):
        w.write_linear(addr, raw)
        return addr

    def test_heap(self):
        from tbpipeline_neww import kernel32 as k
        w = self.wine()
        heap = k.get_process_heap(w)
        a = k.k32_heap_alloc(w, heap, 0, 10)
        self.assertEqual(a % 8, 0)
        self.assertEqual(k.k32_heap_size(w, heap, 0, a), 10)
        w.write_linear(a, b"0123456789")
        b = k.k32_heap_realloc(w, heap, 0, a, 100)
        self.assertEqual(w.read_linear(b, 10), b"0123456789")
        self.assertEqual(k.k32_heap_realloc(w, heap, 0x10, b, 0x1000), 0)
        self.assertEqual(k.k32_heap_free(w, heap, 0, b), 1)
        self.assertEqual(k.k32_heap_free(w, heap, 0, 0), 1)
        self.assertEqual(k.k32_heap_size(w, heap, 0, b), 0xFFFFFFFF)

    def test_temp_path_and_file_name(self):
        from tbpipeline_neww import kernel32 as k
        from tbpipeline_neww.win32 import WIN32
        w = self.wine()
        self.assertEqual(WIN32[("KERNEL32", "GetTempPathA")](w, 0x100, 0x1000), 16)
        self.assertEqual(w.read_linear(0x1000, 17), b"C:\\WINDOWS\\TEMP\\\x00")
        # A buffer too small: the size needed, NUL included.
        self.assertEqual(WIN32[("KERNEL32", "GetTempPathA")](w, 4, 0x1100), 17)
        self.put(w, 0x1200, b"OBJ\x00")
        self.assertEqual(k.get_temp_file_name_a(w, 0x1000, 0x1200, 0, 0x1300), 1)
        self.assertEqual(w.read_linear(0x1300, 26), b"C:\\WINDOWS\\TEMP\\OBJ1.tmp\x00\x00")
        self.assertTrue(w.file_exists("C:\\WINDOWS\\TEMP\\OBJ1.tmp"))
        # The next one finds OBJ1 taken... after last + 1.
        self.assertEqual(k.get_temp_file_name_a(w, 0x1000, 0x1200, 0, 0x1300), 2)
        # A given number: that name, no file made.
        self.assertEqual(k.get_temp_file_name_a(w, 0x1000, 0x1200, 0xABC, 0x1300), 0xABC)
        self.assertEqual(w.read_linear(0x1300, 27), b"C:\\WINDOWS\\TEMP\\OBJABC.tmp\x00")
        self.assertFalse(w.file_exists("C:\\WINDOWS\\TEMP\\OBJABC.tmp"))
        self.put(w, 0x1400, b"C:\\NOWHERE\x00")
        self.assertEqual(k.get_temp_file_name_a(w, 0x1400, 0x1200, 0, 0x1300), 0)
        self.assertEqual(w.w32.last_error, k.ERROR_DIRECTORY)

    def test_locale(self):
        from tbpipeline_neww import kernel32 as k
        w = self.wine()
        self.assertEqual(k.get_locale_info_a(w, 0x400, 3, 0x1000, 4), 4)
        self.assertEqual(w.read_linear(0x1000, 4), b"ENU\x00")
        self.assertEqual(k.get_locale_info_a(w, 0x9, 3, 0, 0), 4)
        self.assertEqual(k.get_locale_info_a(w, 0x400, 3, 0x1000, 2), 0)
        self.assertEqual(w.w32.last_error, k.ERROR_INSUFFICIENT_BUFFER)
        self.assertIn("LCTYPE", k.get_locale_info_a(w, 0x400, 0x42, 0x1000, 4))

    def test_code_pages(self):
        from tbpipeline_neww import kernel32 as k
        w = self.wine()
        self.put(w, 0x1000, b"Caf\xe9\x81\x00")
        self.assertEqual(k.multi_byte_to_wide_char(w, 0, 0, 0x1000, 0xFFFFFFFF, 0, 0), 6)
        self.assertEqual(k.multi_byte_to_wide_char(w, 0, 0, 0x1000, 0xFFFFFFFF, 0x2000, 6), 6)
        self.assertEqual(w.read_linear(0x2000, 12), "Caf\u00e9\u0081\x00".encode("utf-16-le"))
        self.assertEqual(k.wide_char_to_multi_byte(w, 0, 0, 0x2000, 0xFFFFFFFF, 0x3000, 6, 0, 0), 6)
        self.assertEqual(w.read_linear(0x3000, 6), b"Caf\xe9\x81\x00")
        self.assertEqual(k.multi_byte_to_wide_char(w, 0, 0, 0x1000, 0xFFFFFFFF, 0x2000, 2), 0)
        cp = k.get_cp_info(w, 1252, 0x4000)
        self.assertEqual((cp, w.read_linear(0x4000, 6)), (1, b"\x01\x00\x00\x00?\x00"))

    def test_process(self):
        from tbpipeline_neww import kernel32 as k
        w = self.wine()
        self.assertEqual(k.get_version(w), 0x80000A03)
        self.assertEqual(k.get_module_file_name_a(w, 0, 0x1000, 0x100), len(k.WINEVDM))
        self.assertEqual(w.read_linear(0x1000, len(k.WINEVDM)), k.WINEVDM.encode())
        line = k.get_command_line_a(w)
        from tbpipeline_neww.win32 import read_str
        self.assertEqual(read_str(w, line), b'C:\\WINDOWS\\system32\\winevdm.exe --app-name "C:\\TBK\\TB80RTM.EXE" C:\\TBK\\TB80RTM.EXE')
        self.assertEqual(k.get_std_handle(w, 0xFFFFFFF5), 0)
        self.assertEqual(k.get_file_type(w, 0), 0)
        self.assertEqual(k.set_handle_count(w, 20), 20)

    def test_mutex(self):
        from tbpipeline_neww import kernel32 as k
        w = self.wine()
        self.put(w, 0x1000, b"m\x00")
        h = k.create_mutex_a(w, 0, 1, 0x1000)
        self.assertEqual(w.w32.last_error, 0)
        h2 = k.create_mutex_a(w, 0, 0, 0x1000)
        self.assertEqual(w.w32.last_error, k.ERROR_ALREADY_EXISTS)
        self.assertEqual(k.release_mutex(w, h), 1)
        self.assertEqual(k.release_mutex(w, h2), 0)
        self.assertEqual(k.wait_for_single_object(w, h2, 0xFFFFFFFF), 0)
        self.assertEqual(k.release_mutex(w, h), 1)
        self.assertEqual(k.open_mutex_a(w, 0, 0, 0x1000) > 0, True)
        self.put(w, 0x1100, b"other\x00")
        self.assertEqual(k.open_mutex_a(w, 0, 0, 0x1100), 0)
        self.assertEqual(k.close_handle(w, h), 1)
        self.assertEqual(k.close_handle(w, h), 0)

    def test_strings(self):
        from tbpipeline_neww import kernel32 as k
        w = self.wine()
        self.put(w, 0x1000, b"Hello\x00")
        self.put(w, 0x1100, b"hELLO\x00")
        self.assertEqual(k.lstrcmpi_a(w, 0x1000, 0x1100), 0)
        self.assertEqual(k.lstrlen_a(w, 0x1000), 5)
        k.lstrcpyn_a(w, 0x1200, 0x1000, 3)
        self.assertEqual(w.read_linear(0x1200, 3), b"He\x00")
        k.lstrcpy_a(w, 0x1300, 0x1000)
        k.lstrcat_a(w, 0x1300, 0x1100)
        self.assertEqual(w.read_linear(0x1300, 11), b"HellohELLO\x00")


class Wow32(unittest.TestCase):
    """wowthunk.c K32WOW*: MapSL, and the KERNEL global heap."""

    def test_vdm_pointer(self):
        from tbpipeline_neww import kernel32 as k
        w = Kernel32().wine()
        w.linear = lambda sel: 0x200000 if sel == 0x40 else None
        self.assertEqual(k.wow_get_vdm_pointer_fix(w, 0x400010, 4, 1), 0x200010)
        self.assertIn("real mode", k.wow_get_vdm_pointer(w, 0x400010, 4, 0))

    def test_handles(self):
        from tbpipeline_neww import kernel32 as k
        w = Kernel32().wine()
        self.assertEqual(k.wow_handle16(w, 0x12345678, 0), 0x5678)
        self.assertEqual(k.wow_handle32(w, 0x1234, 0), 0x1234)


class DosFiles(unittest.TestCase):
    """int21.c on file handles, INT21_FileAttributes, and OpenFile16's OF_REOPEN and OF_DELETE."""

    def test_attributes(self):
        from tests.test_neww_batch3_dos import INT21, dgroup_word, mov, run_dos, store_ax, store_flags
        code = mov("dx", 0x10) + mov("ax", 0x4300) + INT21 + store_ax(0x40) + store_flags(0x42)
        code += mov("dx", 0x20) + mov("ax", 0x4300) + INT21 + store_ax(0x44) + store_flags(0x46)
        code += mov("dx", 0x30) + mov("ax", 0x4300) + INT21 + store_ax(0x48) + store_flags(0x4A)
        data = bytearray(0x100)
        data[0x10:0x18] = b"ABC.TXT\x00"
        data[0x20:0x2C] = b"C:\\WINDOWS\\\x00"
        data[0x30:0x3E] = b"C:\\NONE\\X.TXT\x00"
        host = run_dos(code, data, files=[("ABC.TXT", b"1")])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((dgroup_word(host, 0x40), dgroup_word(host, 0x42) & 1), (0x20, 0))
        # A name ending in a backslash fails, as Wine's INT21_FileAttributes makes it.
        self.assertEqual((dgroup_word(host, 0x44), dgroup_word(host, 0x46) & 1), (2, 1))
        self.assertEqual((dgroup_word(host, 0x48), dgroup_word(host, 0x4A) & 1), (3, 1))

    def test_read_seek_close(self):
        from tests.test_neww_batch3_dos import INT21, dgroup_word, mov, store_ax, store_flags
        # _lopen("ABC.TXT", 0) through KERNEL.85 is a gate; INT 21h 3Dh is not in neww, so
        # open with OpenFile (KERNEL.74) and use the handle with INT 21h.
        open_file = bytes([0x1E, 0x68, 0x10, 0x00, 0x1E, 0x68, 0x80, 0x00, 0x68, 0x00, 0x00])
        code = open_file + neww_ne.call_far() + store_ax(0x40) + bytes([0x8B, 0xD8])  # mov bx, ax
        code += mov("cx", 0) + mov("dx", 2) + mov("ax", 0x4200) + INT21 + store_ax(0x42)
        code += mov("cx", 4) + mov("dx", 0x60) + bytes([0xB4, 0x3F]) + INT21 + store_ax(0x44)
        code += bytes([0xB4, 0x3E]) + INT21 + store_flags(0x46)
        code += bytes([0xB4, 0x3E]) + INT21 + store_ax(0x48) + store_flags(0x4A)
        data = bytearray(0x100)
        data[0x10:0x18] = b"ABC.TXT\x00"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ABC.TXT").write_bytes(b"0123456789")
            neww_ne.exit_program_with(d, code, [(3, 1, len(open_file) + 1, 1, 74)], data=bytes(data))
            from tbpipeline_neww.machine import Machine
            host = Machine(d)
            host.run(limit=100_000)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dgroup_word(host, 0x42), 2)
        self.assertEqual(dgroup_word(host, 0x44), 4)
        sel = host.box.exe.segments[1].selector
        self.assertEqual(host._read_guest(sel, 0x60, 4), b"2345")
        self.assertEqual(dgroup_word(host, 0x46) & 1, 0)
        self.assertEqual((dgroup_word(host, 0x48), dgroup_word(host, 0x4A) & 1), (6, 1))

    def test_reopen_and_delete(self):
        from tests.test_neww_batch1_handlers import DATA, wine
        w = wine()
        w.trace.append("KERNEL.74 OpenFile")
        handle = w.create_file("C:\\WINDOWS\\TEMP\\OBJ1.tmp")
        w.files.pop(handle)
        w._ofstruct(DATA, 0x100, "C:\\WINDOWS\\TEMP\\OBJ1.tmp")
        ax, _dx, why = w._open_file("", DATA, 0x100, 0x8012)
        self.assertIsNone(why)
        self.assertIn(ax, w.files)
        ax, _dx, why = w._open_file("", DATA, 0x100, 0x8200)
        self.assertEqual((ax, why), (1, None))
        self.assertFalse(w.file_exists("C:\\WINDOWS\\TEMP\\OBJ1.tmp"))

    def test_delete_never_touches_the_host(self):
        from tests.test_neww_batch1_handlers import DATA, wine
        w = wine()
        (Path(w.root) / "KEEP.TXT").write_bytes(b"x")
        w.trace.append("KERNEL.74 OpenFile")
        _ax, _dx, why = w._open_file("KEEP.TXT", DATA, 0x100, 0x0200)
        self.assertIn("neww deletes nothing on the host", why)
        self.assertTrue((Path(w.root) / "KEEP.TXT").exists())


if __name__ == "__main__":
    unittest.main()
