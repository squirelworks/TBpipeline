"""Batch 3, the DOS and KERNEL pieces the run reached once TB80NET.EXE ran: OpenFile's
OF_PARSE, the disk transfer area and FindFirst/FindNext, INT 2Fh's MSCDEX drive check,
AnsiToOem and OemToAnsi, and TEMP in the DOS environment. Each test names the Wine function
it follows. No ToolBook bytes.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne
from tests.test_neww_batch1_handlers import DATA, put, wine
from tests.test_neww_batch2 import by_name, reg

INT21 = bytes([0xCD, 0x21])


def run_dos(before, data=b"", files=()):
    """TB80RTM.EXE running `before` with DGROUP holding data, in a directory with files."""
    from tbpipeline_neww.machine import Machine
    with tempfile.TemporaryDirectory() as d:
        for name, content in files:
            (Path(d) / name).write_bytes(content)
        neww_ne.exit_program_with(d, before, [], data=bytes(data).ljust(0x100, b"\x00"))
        host = Machine(d)
        host.run(limit=100_000)
    return host


def mov(reg_name, value):
    op = {"ax": 0xB8, "cx": 0xB9, "dx": 0xBA, "bx": 0xBB, "si": 0xBE, "di": 0xBF}[reg_name]
    return bytes([op, value & 0xFF, value >> 8])


def store_ax(addr):
    return bytes([0xA3, addr & 0xFF, addr >> 8])


def store_flags(addr):
    # pushf ; pop ax ; mov [addr], ax
    return bytes([0x9C, 0x58]) + store_ax(addr)


def dgroup_word(host, off):
    return host.word(host.box.exe.segments[1].selector, off)


class FullPath(unittest.TestCase):
    """GetFullPathNameA with neww's current directory, C:\\TBK."""

    def test_relative_name(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine.full_path("nida81.tbk"), "C:\\TBK\\nida81.tbk")

    def test_dot_dot_and_slashes(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine.full_path("C:/x/../y.tbk"), "C:\\y.tbk")

    def test_rooted_name_takes_the_current_drive(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine.full_path("\\a\\b"), "C:\\a\\b")

    def test_other_drive_relative_is_its_root(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine.full_path("d:foo"), "D:\\foo")


class OfParse(unittest.TestCase):
    """file.c OpenFile16: OF_PARSE fills the OFSTRUCT with the full path, opens nothing, returns 0."""

    def test_parse(self):
        w = wine()
        w.trace.append("KERNEL.74 OpenFile")
        ax, dx, why = w._open_file("book.tbk", DATA, 0x100, 0x0100)
        self.assertEqual((ax, why), (0, None))
        ofs = w.memory.read(DATA, 0x100, 136)
        self.assertEqual((ofs[0], ofs[1], struct.unpack_from("<H", ofs, 2)[0]), (136, 1, 0))
        self.assertEqual(ofs[8:8 + 16], b"C:\\TBK\\book.tbk\x00")
        self.assertEqual(w.files, {})


class FindFiles(unittest.TestCase):
    """int21.c INT21_FindFirst / INT21_FindNext into the DTA, and AH=1Ah / 2Fh."""

    def test_default_dta_is_the_psp_command_tail(self):
        host = run_dos(bytes([0xB4, 0x2F]) + INT21)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(reg(host, "bx"), 0x80)
        self.assertEqual(reg(host, "es"), host.box.wine.task["psp"])

    def test_set_dta_then_get(self):
        code = mov("dx", 0x60) + bytes([0xB4, 0x1A]) + INT21 + bytes([0xB4, 0x2F]) + INT21
        host = run_dos(code)
        self.assertEqual(reg(host, "bx"), 0x60)
        self.assertEqual(reg(host, "es"), host.box.exe.segments[1].selector)

    def find_code(self):
        # DTA at DS:60h ; FindFirst DS:10h attr 0 ; [40h] = AX, [42h] = flags ; FindNext ; [44h], [46h]
        return (mov("dx", 0x60) + bytes([0xB4, 0x1A]) + INT21
                + mov("dx", 0x10) + mov("cx", 0) + bytes([0xB4, 0x4E]) + INT21 + store_ax(0x40) + store_flags(0x42)
                + bytes([0xB4, 0x4F]) + INT21 + store_ax(0x44) + store_flags(0x46))

    def test_first_match_fills_the_dta(self):
        host = run_dos(self.find_code(), b"\x00" * 0x10 + b"*.TXT\x00", files=[("ABC.TXT", b"12345")])
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(dgroup_word(host, 0x40), 0)
        self.assertEqual(dgroup_word(host, 0x42) & 1, 0)
        ds = host.box.exe.segments[1].selector
        dta = bytes(host.word(ds, 0x60 + i) & 0xFF for i in range(0x2B))
        self.assertEqual(dta[0], 2)                              # drive C:
        self.assertEqual(dta[1:12], b"????????TXT")             # the FCB mask
        self.assertEqual(dta[0x15], 0x20)                       # FILE_ATTRIBUTE_ARCHIVE
        self.assertEqual(struct.unpack_from("<I", dta, 0x1A)[0], 5)
        self.assertEqual(dta[0x1E:0x26], b"ABC.TXT\x00")

    def test_next_with_no_more_is_error_18(self):
        host = run_dos(self.find_code(), b"\x00" * 0x10 + b"*.TXT\x00", files=[("ABC.TXT", b"1")])
        self.assertEqual(dgroup_word(host, 0x44), 18)
        self.assertEqual(dgroup_word(host, 0x46) & 1, 1)

    def test_no_match_is_error_18_with_carry(self):
        # Wine's FindFirst falls through to FindNext, whose failure is ERROR_NO_MORE_FILES.
        host = run_dos(self.find_code(), b"\x00" * 0x10 + b"OBJ0.TMP\x00")
        self.assertEqual(dgroup_word(host, 0x40), 18)
        self.assertEqual(dgroup_word(host, 0x42) & 1, 1)

    def test_fcb_mask(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine.fcb_mask("obj*.t?p"), "OBJ?????T?P")
        self.assertEqual(Wine.fcb_mask("A.B.C"), None)
        self.assertEqual(Wine.fcb_mask("LONGERNAME.TXT"), None)


class Int2f(unittest.TestCase):
    """int2f.c MSCDEX_Handler: neww has no CD-ROM drive."""

    def test_drive_check(self):
        host = run_dos(mov("ax", 0x150B) + mov("cx", 2) + bytes([0xCD, 0x2F]))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((reg(host, "bx"), dgroup_word(host, 0)), (0xADAD, 0))

    def test_drive_check_answers_false(self):
        host = run_dos(mov("ax", 0x150B) + mov("cx", 2) + bytes([0xCD, 0x2F]) + bytes([0x89, 0xC6]))
        self.assertEqual(reg(host, "si"), 0)

    def test_installation_check_counts_no_drive(self):
        host = run_dos(mov("ax", 0x1500) + mov("bx", 7) + bytes([0xCD, 0x2F]))
        self.assertEqual(reg(host, "bx"), 0)

    def test_other_function_stops(self):
        host = run_dos(mov("ax", 0x1600) + bytes([0xCD, 0x2F]))
        self.assertEqual(host.stop, "INT 2Fh AX=0x1600: this DOSVM_Int2fHandler function is not in neww yet")


class CodePages(unittest.TestCase):
    """keyboard.c AnsiToOem16 and OemToAnsi16: CharToOemA / OemToCharA, then -1."""

    def test_ansi_to_oem(self):
        w = wine()
        src = put(w, 0x10, "")
        w.memory.write(DATA, 0x10, b"Caf\xe9\x00")
        ax, _dx, why, _calls = by_name(w, "KEYBOARD", "AnsiToOem", src, (DATA, 0x40))
        self.assertEqual((ax, why), (0xFFFF, None))
        self.assertEqual(w.memory.read(DATA, 0x40, 5), b"Caf\x82\x00")

    def test_oem_to_ansi(self):
        w = wine()
        w.memory.write(DATA, 0x10, b"Caf\x82\x00")
        ax, _dx, why, _calls = by_name(w, "KEYBOARD", "OemToAnsi", (DATA, 0x10), (DATA, 0x40))
        self.assertEqual(ax, 0xFFFF)
        self.assertEqual(w.memory.read(DATA, 0x40, 5), b"Caf\xe9\x00")

    def test_in_place(self):
        w = wine()
        src = put(w, 0x10, "nida81.tbk")
        by_name(w, "KEYBOARD", "AnsiToOem", src, src)
        self.assertEqual(w.memory.read(DATA, 0x10, 11), b"nida81.tbk\x00")


class Environment(unittest.TestCase):
    """GetDOSEnvironment16's strings: TEMP and TMP, which every Wine prefix sets."""

    def test_temp_is_set(self):
        from tbpipeline_neww.machine import ENV_STRINGS
        self.assertEqual(ENV_STRINGS, (b"TEMP=C:\\WINDOWS\\TEMP", b"TMP=C:\\WINDOWS\\TEMP"))


if __name__ == "__main__":
    unittest.main()
