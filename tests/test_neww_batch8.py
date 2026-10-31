"""Batch 8: what the Logic Families book needed. Handlers run on fake memory
(tests/test_neww_batch2.py's harness). No ToolBook bytes."""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA
from tests.test_neww_batch2 import by_name, window_wine


class LoadMenuIndirect(unittest.TestCase):
    """user.c LoadMenuIndirect16: MENUITEMTEMPLATEHEADER, then parse_menu_resource."""

    def setUp(self):
        self.w = window_wine()

    def put(self, raw):
        self.w.memory.write(DATA, 0x100, raw)
        return (DATA, 0x100)

    def test_popup_with_one_item(self):
        # version 0, offset 0; "&File" popup (MF_POPUP | MF_END) holding "E&xit" id 1 (MF_END).
        raw = struct.pack("<HH", 0, 0) + struct.pack("<H", 0x0090) + b"&File\0" \
            + struct.pack("<HH", 0x0080, 1) + b"E&xit\0"
        hmenu, _dx, stop, _ = by_name(self.w, "USER", "LoadMenuIndirect", self.put(raw))
        self.assertIsNone(stop)
        self.assertNotEqual(hmenu, 0)
        self.assertEqual(by_name(self.w, "USER", "GetMenuItemCount", hmenu)[0], 1)
        sub = by_name(self.w, "USER", "GetSubMenu", hmenu, 0)[0]
        self.assertEqual(by_name(self.w, "USER", "GetMenuItemID", sub, 0)[0], 1)

    def test_version_not_zero_is_zero(self):
        raw = struct.pack("<HH", 1, 0) + b"\0" * 8
        self.assertEqual(by_name(self.w, "USER", "LoadMenuIndirect", self.put(raw))[:3], (0, 0, None))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- a disk that works

class Disk(unittest.TestCase):
    """neww's disk as a working Windows shows it: long names with short aliases, books found
    by name beside the book, and the Win32 system DLLs in the system directory."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from tbpipeline_neww.wine import Wine
        self.bin = Path(tempfile.mkdtemp())
        self.books = Path(tempfile.mkdtemp())
        (self.bin / "TB80R.SBK").write_bytes(b"sys")
        self.book = self.books / "LogicFamilies.tbk"
        self.book.write_bytes(b"lf")
        (self.books / "nida81.tbk").write_bytes(b"nida")
        (self.books / "Logic Fun.txt").write_bytes(b"x")
        self.w = Wine(str(self.bin))
        self.w.book = self.book

    def test_short_alias_as_windows_makes_it(self):
        from tbpipeline_neww.wine import short_alias
        self.assertEqual(short_alias("LOGICFAMILIES.TBK", {}), "LOGICF~1.TBK")
        self.assertEqual(short_alias("LOGICFAMILIES.TBK", {"LOGICF~1.TBK": 1}), "LOGICF~2.TBK")
        self.assertEqual(short_alias("A B.C.TEXT", {}), "ABC~1.TEX")

    def test_long_name_and_alias_both_open_the_book(self):
        self.assertEqual(self.w.resolve("C:\\TBK\\LogicFamilies.tbk"), self.book)
        self.assertEqual(self.w.dos_name(self.book), "LOGICF~1.TBK")
        self.assertEqual(self.w.resolve("C:\\TBK\\LOGICF~1.TBK"), self.book)

    def test_another_book_beside_the_book(self):
        self.assertEqual(self.w.resolve("C:\\TBK\\nida81.tbk"), self.books / "nida81.tbk")
        self.assertIsNone(self.w.resolve("C:\\TBK\\other.tbk"))
        self.assertEqual(self.w.resolve("C:\\TBK\\tb80r.sbk"), self.bin / "TB80R.SBK")

    def test_find_entries_show_short_names_only(self):
        names = [n for n, _size, _t in self.w._find_entries()]
        self.assertIn("LOGICF~1.TBK", names)
        self.assertIn("NIDA81.TBK", names)
        self.assertNotIn("LOGICFAMILIES.TBK", names)

    def test_system_dlls_are_in_the_system_directory_only(self):
        found = self.w.resolve("C:\\WINDOWS\\SYSTEM\\kernel32.dll")
        self.assertIsNotNone(found)
        self.assertEqual(found.read_bytes()[:2], b"MZ")
        self.assertIsNotNone(self.w.resolve("C:\\WINDOWS\\SYSTEM32\\USER32.DLL"))
        self.assertIsNone(self.w.resolve("C:\\TBK\\kernel32.dll"))
        self.assertTrue(self.w.file_exists("C:\\WINDOWS\\SYSTEM\\GDI32.DLL"))


class CommandLine(unittest.TestCase):
    def test_long_book_name_is_passed_short(self):
        # The shell gives a 16-bit program the short name of a long one.
        import tempfile
        from pathlib import Path
        from tbpipeline_neww.machine import Machine
        from tests.test_neww_task_entry import program
        d = tempfile.mkdtemp()
        program(d, b"")
        book = Path(d) / "LogicFamilies.tbk"
        book.write_bytes(b"")
        host = Machine(d, book).run(limit=5000)
        from unicorn.x86_const import UC_X86_REG_ES
        es = host.uc.reg_read(UC_X86_REG_ES)
        line = bytes(host.word(es, 0x80 + i) & 0xFF for i in range(13))
        self.assertEqual(line, b"\x0cLOGICF~1.TBK")


# ---------------------------------------------------------------- Win32 calls

class Win32Calls(unittest.TestCase):
    def setUp(self):
        from tests.test_neww_win32 import Kernel32
        self.w = Kernel32().wine()
        from tbpipeline_neww.win32 import WIN32
        self.call = lambda module, name, *a: WIN32[(module, name)](self.w, *a)

    def put(self, addr, raw):
        self.w.write_linear(addr, raw)
        return addr

    def test_private_profile_round_trip(self):
        sec, key, val, ini = (self.put(0x1000, b"Lesson\0"), self.put(0x1010, b"Window\0"),
                              self.put(0x1020, b"42\0"), self.put(0x1030, b"NIDAREC.INI\0"))
        self.assertEqual(self.call("KERNEL32", "WritePrivateProfileStringA", sec, key, val, ini), 1)
        self.assertEqual(self.call("KERNEL32", "GetPrivateProfileIntA", sec, key, 7, ini), 42)
        other = self.put(0x1040, b"Other\0")
        self.assertEqual(self.call("KERNEL32", "GetPrivateProfileIntA", sec, other, 0xFFFFFFFF, ini), 0xFFFFFFFF)
        n = self.call("KERNEL32", "GetPrivateProfileStringA", sec, key, self.put(0x1050, b"d\0"), 0x1100, 0x20, ini)
        self.assertEqual((n, self.w.read_linear(0x1100, 3)), (2, b"42\0"))

    def test_system_metrics_and_monitor(self):
        self.assertEqual(self.call("USER32", "GetSystemMetrics", 0), 1024)
        self.assertEqual(self.call("USER32", "MonitorFromPoint", 512, 384, 0), 1)
        self.assertEqual(self.call("USER32", "MonitorFromPoint", 5000, 384, 0), 0)
        self.assertEqual(self.call("USER32", "MonitorFromPoint", 5000, 384, 1), 1)
        self.put(0x1200, struct.pack("<I", 40))
        self.assertEqual(self.call("USER32", "GetMonitorInfoA", 1, 0x1200), 1)
        self.assertEqual(struct.unpack("<IiiiiiiiiI", self.w.read_linear(0x1200, 40))[1:],
                         (0, 0, 1024, 768, 0, 0, 1024, 768, 1))

    def test_drive_and_files(self):
        self.assertEqual(self.call("KERNEL32", "GetLogicalDrives"), 4)
        self.assertEqual(self.call("KERNEL32", "GetDriveTypeA", self.put(0x1000, b"C:\\\0")), 3)
        self.assertEqual(self.call("KERNEL32", "GetDriveTypeA", self.put(0x1000, b"D:\\\0")), 1)
        self.assertEqual(self.call("KERNEL32", "GetFileAttributesA", self.put(0x1000, b"C:\\WINDOWS\0")), 0x10)
        self.assertEqual(self.call("KERNEL32", "GetFileAttributesA", self.put(0x1000, b"C:\\WINDOWS\\SYSTEM\\KERNEL32.DLL\0")), 0x20)
        self.assertEqual(self.call("KERNEL32", "GetFileAttributesA", self.put(0x1000, b"C:\\NONE\\X.DLL\0")), 0xFFFFFFFF)
        self.assertEqual(self.w.w32.last_error, 3)
        self.assertEqual(self.call("KERNEL32", "GetCurrentDirectoryA", 0x100, 0x1100), 6)
        self.assertEqual(self.w.read_linear(0x1100, 7), b"C:\\TBK\0")
        self.assertEqual(self.call("KERNEL32", "GetCurrentDirectoryA", 3, 0x1100), 7)

    def test_char_upper_and_cpu_features(self):
        self.assertEqual(self.call("USER32", "CharUpperA", ord("e")), ord("E"))
        p = self.put(0x40001000, "straße é\0".encode("cp1252"))
        self.assertEqual(self.call("USER32", "CharUpperA", p), p)
        self.assertEqual(self.w.read_linear(p, 8), "STRAßE É".encode("cp1252"))
        self.assertEqual(self.call("KERNEL32", "IsProcessorFeaturePresent", 0), 0)
        self.assertEqual(self.call("KERNEL32", "IsProcessorFeaturePresent", 10), 1)
        self.assertEqual(self.call("KERNEL32", "IsProcessorFeaturePresent", 70), 0)

    def test_global_memory(self):
        fixed = self.call("KERNEL32", "GlobalAlloc", 0, 0x28)
        self.assertEqual(fixed % 8, 0)
        self.assertEqual(self.call("KERNEL32", "GlobalLock", fixed), fixed)
        self.assertEqual(self.call("KERNEL32", "GlobalUnlock", fixed), 1)
        self.assertEqual(self.call("KERNEL32", "GlobalSize", fixed), 0x28)
        h = self.call("KERNEL32", "GlobalAlloc", 2, 0x10)
        self.assertEqual(h % 8, 4)
        p = self.call("KERNEL32", "GlobalLock", h)
        # The handle is the address of the entry's ptr field.
        self.assertEqual(struct.unpack("<I", self.w.read_linear(h, 4))[0], p)
        self.assertEqual(self.call("KERNEL32", "GlobalHandle", p), h)
        self.assertEqual(self.call("KERNEL32", "GlobalUnlock", h), 0)
        self.assertEqual(self.call("KERNEL32", "GlobalReAlloc", h, 0x100, 2), h)
        self.assertEqual(self.call("KERNEL32", "GlobalSize", h), 0x100)
        self.assertEqual(self.call("KERNEL32", "GlobalFree", h), 0)
        self.assertEqual(self.call("KERNEL32", "GlobalFree", fixed), 0)


# ---------------------------------------------------------------- selectors and DPMI

class Selectors(unittest.TestCase):
    """selector.c and int31.c on fake descriptors."""

    def setUp(self):
        self.w = window_wine()
        table = {0x100: (0x2000, 0xFFFF, 0x9A)}
        nxt = [0x3000]

        class Hooks:
            def info(self, sel):
                return table.get(sel)

            def set(self, sel, base, limit, access):
                table[sel] = (base, limit, access)

            def new(self):
                nxt[0] += 8
                table[nxt[0]] = (0, 0, 0x92)
                return nxt[0]

            def free(self, sel):
                table.pop(sel)
        self.table = table
        self.w.selectors = Hooks()

    def call(self, name, *a):
        return by_name(self.w, "KERNEL", name, *a)

    def test_alloc_set_get_free(self):
        sel = self.call("AllocSelector", 0)[0]
        self.assertEqual(self.call("SetSelectorBase", sel, (0x4001, 0x00E8))[0], sel)
        self.assertEqual(self.call("SetSelectorLimit", sel, (0, 0x27))[0], sel)
        self.assertEqual(self.call("GetSelectorBase", sel)[:2], (0x00E8, 0x4001))
        self.assertEqual(self.call("GetSelectorLimit", sel)[:2], (0x27, 0))
        self.assertEqual(self.call("FreeSelector", sel)[0], 0)
        self.assertEqual(self.call("FreeSelector", sel)[0], sel)

    def test_alloc_copies_and_presto_chango_swaps_code_and_data(self):
        copy = self.call("AllocSelector", 0x100)[0]
        self.assertEqual(self.table[copy], (0x2000, 0xFFFF, 0x9A))
        self.assertEqual(self.call("PrestoChangoSelector", 0x100, copy)[0], copy)
        self.assertEqual(self.table[copy], (0x2000, 0xFFFF, 0x92))

    def test_dpmi_base_and_limit(self):
        from tbpipeline_neww.selector16 import int31
        regs = {"ax": 0x0007, "bx": 0x100, "cx": 0x4001, "dx": 0x00E8}
        self.w.trace.append("x")
        self.assertEqual(int31(self.w, regs.get), ({"eflags_cf": 0}, None))
        regs.update(ax=0x0008, cx=0, dx=3)
        int31(self.w, regs.get)
        self.assertEqual(self.table[0x100], (0x400100E8, 3, 0x9A))
        regs.update(ax=0x0006)
        self.assertEqual(int31(self.w, regs.get)[0], {"cx": 0x4001, "dx": 0x00E8, "eflags_cf": 0})
        regs.update(bx=0x777)
        self.assertEqual(int31(self.w, regs.get)[0], {"ax": 0x8022, "eflags_cf": 1})


# ---------------------------------------------------------------- PE imports

class PeImports(unittest.TestCase):
    def test_a_pe_import_in_bin_loads_first(self):
        # loader.c: fixup_imports loads OTHER.DLL, then process_attach runs its DllMain first.
        from tests import neww_pe
        from tests.test_neww_win32 import Asm, load_library, run, strings, dword
        code = Asm()
        load_library(code, 0x10, 0x100)
        tiny = neww_pe.build(imports=(("OTHER.dll", ("Add",)), ("KERNEL32.dll", ("GetVersion",))))
        host = run(code, strings(x10="TINY.DLL"), [("TINY.DLL", tiny), ("OTHER.DLL", neww_pe.build("OTHER"))])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertNotEqual(dword(host, 0x100), 0)
        mains = [t for t in host.box.wine.trace if t.endswith("DllMain(PROCESS_ATTACH)")]
        self.assertEqual(mains, ["  OTHER DllMain(PROCESS_ATTACH)", "  TINY DllMain(PROCESS_ATTACH)"])


# ---------------------------------------------------------------- the real books

class LogicFamilies(unittest.TestCase):
    def test_first_page_shows_the_picture_from_nida81(self):
        # TBK_BIN, and TBK_BOOK2: the Logic Families book under its long name, with
        # nida81.tbk beside it. Its first page goes to page P0 of nida81.tbk, whose picture
        # draws, and no error box shows.
        import os
        from pathlib import Path
        from tests.binpath import bin_or_skip
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80F32L.dll", "TB80RMT.DLL")
        book = os.environ.get("TBK_BOOK2")
        if not book or not (Path(book).parent / "nida81.tbk").exists():
            raise unittest.SkipTest("TBK_BOOK2 is not set, or has no nida81.tbk beside it")
        from tbpipeline_neww.machine import Machine
        host = Machine(str(root), book)
        host.call_limit = 50000
        host.run(limit=50000 * 1000)
        trace = host.box.wine.trace
        print(f"\nneww stop: {host.stop} after {len(trace)} trace lines")
        self.assertEqual([t for t in trace if t.startswith("USER.1 MessageBox")], [])
        self.assertTrue(any("OpenFile 'C:\\\\TBK\\\\nida81.tbk' -> " in t for t in trace))
        self.assertTrue(any(t.startswith("GDI.439 StretchDIBits") for t in trace))
