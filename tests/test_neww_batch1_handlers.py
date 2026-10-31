"""The KERNEL, USER and SHELL handlers of the first spec batch, called through Wine.answer.

Each test builds the Pascal argument words the gate would read, in the spec's
order, and checks the answer against what Wine's function at WINE_COMMIT does.
Guest memory is a dict of selectors, so no binary and no CPU is needed.
"""

import struct
import tempfile
import unittest
from pathlib import Path


class Memory:
    """Selectors of 64K, read and written as the machine's callbacks are."""

    def __init__(self):
        self.segs = {}

    def seg(self, sel):
        return self.segs.setdefault(sel, bytearray(0x10000))

    def read(self, sel, off, n):
        return bytes(self.seg(sel)[off:off + n])

    def write(self, sel, off, data):
        self.seg(sel)[off:off + len(data)] = data

    def string(self, sel, off):
        data = self.seg(sel)
        return bytes(data[off:data.index(0, off)]).decode("latin1")


class Args:
    """Pascal arguments in spec order: int is a word, (sel, off) is a far pointer.

    The caller pushes left to right and a far pointer as segment then offset, so arg(0)
    is the offset or word pushed last.
    """

    def __init__(self, memory, values, regs=None):
        pushed = []
        for v in values:
            pushed += [v[0], v[1]] if isinstance(v, tuple) else [v]
        self.words = pushed[::-1]
        self.memory = memory
        self.reg = {"ax": 0x1234, "ds": 0x40, "ss": 0x48, "sp": 0x100, **(regs or {})}
        self.machine = self

    def __call__(self, n):
        return self.words[n]

    def regs(self, name):
        return self.reg[name]

    def word(self, sel, off):
        return struct.unpack("<H", self.memory.read(sel, off, 2))[0]

    def string(self, sel, off):
        return self.memory.string(sel, off)


NUL = (0, 0)
DATA = 0x50


def wine():
    from tbpipeline_neww.wine import Wine
    w = Wine(tempfile.mkdtemp())
    m = Memory()
    w.read, w.write = m.read, m.write
    w.memory = m
    return w


def put(w, off, text):
    w.memory.write(DATA, off, text.encode("latin1") + b"\x00")
    return (DATA, off)


def call(w, module, ordinal, *values, regs=None):
    return w.answer(module, ordinal, Args(w.memory, values, regs))


class Strings(unittest.TestCase):
    def test_lstrcpy_lstrcat_lstrlen(self):
        w = wine()
        src, more = put(w, 0x100, "Tool"), put(w, 0x120, "Book")
        ax, dx, stop = call(w, "KERNEL", 88, (DATA, 0x200), src)
        self.assertEqual((ax, dx, stop), (0x200, DATA, None))
        call(w, "KERNEL", 89, (DATA, 0x200), more)
        self.assertEqual(w.memory.string(DATA, 0x200), "ToolBook")
        self.assertEqual(call(w, "KERNEL", 90, (DATA, 0x200)), (8, 0, None))
        self.assertEqual(call(w, "KERNEL", 90, NUL), (0, 0, None))

    def test_lstrcpyn_keeps_room_for_the_nul(self):
        w = wine()
        src = put(w, 0x100, "abcdef")
        call(w, "KERNEL", 353, (DATA, 0x200), src, 4)
        self.assertEqual(w.memory.string(DATA, 0x200), "abc")

    def test_lstrcmpi_ignores_case_and_lstrcmp_does_not(self):
        w = wine()
        a, b = put(w, 0x100, "abc"), put(w, 0x120, "ABC")
        self.assertEqual(call(w, "USER", 471, a, b)[0], 0)
        self.assertNotEqual(call(w, "USER", 430, a, b)[0], 0)

    def test_ansi_upper_in_place(self):
        w = wine()
        s = put(w, 0x100, "nida81.tbk")
        self.assertEqual(call(w, "USER", 431, s)[:2], (0x100, DATA))
        self.assertEqual(w.memory.string(DATA, 0x100), "NIDA81.TBK")

    def test_wvsprintf(self):
        w = wine()
        w.size = lambda sel: 0x10000
        fmt = put(w, 0x100, "%s has %d pages, %04X")
        name = put(w, 0x140, "nida")
        w.memory.write(DATA, 0x180, struct.pack("<HHhH", name[1], name[0], -3, 0xBEEF))
        ax, _dx, stop = call(w, "USER", 421, (DATA, 0x200), fmt, (DATA, 0x180))
        self.assertIsNone(stop)
        self.assertEqual(w.memory.string(DATA, 0x200), "nida has -3 pages, BEEF")
        self.assertEqual(ax, len("nida has -3 pages, BEEF"))


class Atoms(unittest.TestCase):
    def test_add_find_name_delete(self):
        w = wine()
        name = put(w, 0x100, "TBK_Message")
        atom = call(w, "USER", 268, name)[0]
        self.assertGreaterEqual(atom, 0xC000)
        self.assertEqual(call(w, "USER", 270, put(w, 0x120, "tbk_message"))[0], atom)
        n = call(w, "USER", 271, atom, (DATA, 0x200), 32)[0]
        self.assertEqual(w.memory.string(DATA, 0x200), "TBK_Message")
        self.assertEqual(n, 11)
        self.assertEqual(call(w, "USER", 269, atom)[0], 0)
        self.assertEqual(call(w, "USER", 270, name)[0], 0)

    def test_integer_atom_is_itself(self):
        w = wine()
        self.assertEqual(call(w, "USER", 268, (0, 42))[0], 42)


class Profiles(unittest.TestCase):
    def setUp(self):
        self.w = wine()
        self.w.written["TB80.INI"] = bytearray(b"[Startup]\r\nPath = C:\\TBK\r\nCount=0x10\r\n")
        self.file = put(self.w, 0x10, "C:\\WINDOWS\\TB80.INI")

    def test_string_found_and_default(self):
        w = self.w
        sec, key, dflt = put(w, 0x40, "startup"), put(w, 0x60, "PATH"), put(w, 0x80, "none")
        ax = call(w, "KERNEL", 128, sec, key, dflt, (DATA, 0x200), 64, self.file)[0]
        self.assertEqual((w.memory.string(DATA, 0x200), ax), ("C:\\TBK", 6))
        call(w, "KERNEL", 128, sec, put(w, 0xA0, "Missing"), dflt, (DATA, 0x200), 64, self.file)
        self.assertEqual(w.memory.string(DATA, 0x200), "none")

    def test_int_reads_hex(self):
        w = self.w
        ax = call(w, "KERNEL", 127, put(w, 0x40, "Startup"), put(w, 0x60, "Count"), 7, self.file)[0]
        self.assertEqual(ax, 16)

    def test_write_then_read_back(self):
        w = self.w
        sec, key = put(w, 0x40, "New"), put(w, 0x60, "Key")
        self.assertEqual(call(w, "KERNEL", 129, sec, key, put(w, 0x80, "value"), self.file)[0], 1)
        call(w, "KERNEL", 128, sec, key, NUL, (DATA, 0x200), 64, self.file)
        self.assertEqual(w.memory.string(DATA, 0x200), "value")


class Registry(unittest.TestCase):
    def test_create_set_query(self):
        w = wine()
        root = (0x8000, 0x0000)  # HKEY_CLASSES_ROOT as a DWORD: high word, low word
        self.assertEqual(call(w, "SHELL", 2, root, put(w, 0x100, "ToolBook.Book"), (DATA, 0x300))[0], 0)
        hkey = struct.unpack("<I", w.memory.read(DATA, 0x300, 4))[0]
        self.assertEqual(call(w, "SHELL", 5, (hkey >> 16, hkey & 0xFFFF), put(w, 0x120, "shell"), (0, 1),
                              put(w, 0x140, "open"), (0, 4))[0], 0)
        w.memory.write(DATA, 0x310, struct.pack("<I", 64))
        self.assertEqual(call(w, "SHELL", 6, root, put(w, 0x160, "ToolBook.Book\\shell"),
                              (DATA, 0x200), (DATA, 0x310))[0], 0)
        self.assertEqual(w.memory.string(DATA, 0x200), "open")
        self.assertEqual(call(w, "SHELL", 1, root, put(w, 0x180, "Nothing"), (DATA, 0x300))[0], 2)


class Resources(unittest.TestCase):
    def ne_file(self, d):
        """An NE header with a resource table: one RT_BITMAP (2) id 7, one named type 'VERIFICATION'."""
        ne = 0x40
        rsrc = 0x40
        table = struct.pack("<H", 4)  # alignment shift
        table += struct.pack("<HHI", 0x8002, 1, 0) + struct.pack("<HHHHI", 0x10, 1, 0x30, 0x8007, 0)
        name_at = len(table) + 8 + 12 + 2
        table += struct.pack("<HHI", name_at, 1, 0) + struct.pack("<HHHHI", 0x11, 1, 0, 0x8001, 0)
        table += struct.pack("<H", 0) + bytes([12]) + b"VERIFICATION" + b"\x00"
        data = bytearray(0x200)
        data[0:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, ne)
        data[ne:ne + 2] = b"NE"
        struct.pack_into("<H", data, ne + 0x24, rsrc)
        struct.pack_into("<H", data, ne + 0x26, rsrc + len(table))
        data[ne + rsrc:ne + rsrc + len(table)] = table
        data[0x100:0x110] = b"B" * 16
        data[0x110:0x120] = b"V" * 16
        path = Path(d) / "T.DLL"
        path.write_bytes(bytes(data))
        return path

    def test_find_by_id_and_by_name(self):
        from tbpipeline_neww.resource import Resources as Table
        with tempfile.TemporaryDirectory() as d:
            t = Table(self.ne_file(d))
            bitmap = t.find(7, 2)
            self.assertEqual(bitmap, 0x40 + 2 + 8)
            self.assertEqual(t.bytes_of(bitmap), b"B" * 16)
            verify = t.find(1, "verification")
            self.assertEqual(t.bytes_of(verify), b"V" * 16)
            self.assertEqual(t.size(verify), 16)
            self.assertEqual(t.find(8, 2), 0)


class Throw(unittest.TestCase):
    def test_restores_the_catchbuf(self):
        w = wine()
        w.size = lambda sel: 0x10000
        buf = [0x1111, 0x22, 0x0F00, 0xBB, 0x51, 0xD1, 0x40, 0, 0x48]
        w.memory.write(DATA, 0x400, struct.pack("<9H", *buf))
        ax, _dx, stop = call(w, "KERNEL", 56, (DATA, 0x400), 5)
        self.assertEqual((ax, stop), (5, None))
        self.assertEqual(w.registers, {"sp": 0x0F06, "bp": 0xBB, "si": 0x51, "di": 0xD1, "ds": 0x40,
                                       "frame": (0x1111, 0x22)})

    def test_another_stack_stops(self):
        w = wine()
        w.size = lambda sel: 0x10000
        w.memory.write(DATA, 0x400, struct.pack("<9H", 0, 0, 0, 0, 0, 0, 0, 0, 0x99))
        self.assertIn("does not switch stacks", call(w, "KERNEL", 56, (DATA, 0x400), 5)[2])


class MakeProcInstance(unittest.TestCase):
    def test_task_ds_gets_a_thunk(self):
        w = wine()
        w.owner = lambda sel: "TB80RTM.EXE"
        w.is_dll = lambda path: False
        w.selector_of = lambda h: h
        w.alloc_code = lambda size: 0x70
        ax, dx, stop = call(w, "KERNEL", 51, (0x30, 0x1234), 0x40, regs={"ds": 0x40})
        self.assertEqual((dx, ax, stop), (0x70, 0, None))
        self.assertEqual(w.memory.read(0x70, 0, 8), bytes([0xB8, 0x40, 0x00, 0xEA, 0x34, 0x12, 0x30, 0x00]))

    def test_library_ds_is_the_function(self):
        w = wine()
        w.owner = lambda sel: "TB80ENU1.DLL"
        w.is_dll = lambda path: True
        w.selector_of = lambda h: h
        self.assertEqual(call(w, "KERNEL", 51, (0x30, 0x1234), 0x40)[:2], (0x1234, 0x30))


class StubValues(unittest.TestCase):
    def test_e_notimpl_stub_returns_its_constant(self):
        from tbpipeline_neww.wine import LOADED
        rows = [r for m in LOADED.values() for r in m.values() if r.value == (0x4001, 0x8000)]
        self.assertTrue(rows, "no row carries E_NOTIMPL")
        row = rows[0]
        w = wine()
        args = Args(w.memory, [0] * len(row.args))
        args.words = [0] * 32
        self.assertEqual(w.answer(row.module, row.ordinal, args), (0x4001, 0x8000, None))

    def test_no_stub_value_is_a_made_up_one(self):
        from tbpipeline_neww.spec_rows import SPEC_ROWS
        from tbpipeline_neww.specgen import CONSTANTS
        values = {v for rows in SPEC_ROWS.values() for _line, _void, v in rows if v is not None}
        self.assertTrue(values)
        for v in values:
            self.assertTrue(v in CONSTANTS.values() or isinstance(v, int), v)


if __name__ == "__main__":
    unittest.main()
