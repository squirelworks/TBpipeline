"""COMPOBJ's class lookup, GUID strings and task allocator, which TB80OCX uses to find an
ActiveX control (#227: actxexpl, Quizbldr, tb80x, tb80web). Wine 2528aff2
dlls/compobj.dll16/compobj.c and dlls/combase/combase.c."""

import struct
import unittest

from tests.test_neww_batch1_handlers import Args, DATA
from tests.test_neww_batch2 import by_name, window_wine

GUID, OUT, PPV, RIID, STR = 0x10, 0x30, 0x34, 0x40, 0x60
# {EAB22AC3-30C1-11CF-A7EB-0000C05BAE0B}, the class TB80OCX asks for in actxexpl.
CLSID = struct.pack("<IHH", 0xEAB22AC3, 0x30C1, 0x11CF) + bytes.fromhex("a7eb0000c05bae0b")
CLSID_TEXT = "{EAB22AC3-30C1-11CF-A7EB-0000C05BAE0B}"
IID_IMALLOC = struct.pack("<IHH", 2, 0, 0) + bytes.fromhex("c000000000000046")


def far(off):
    return (DATA, off)


def dword(w, off):
    return struct.unpack("<I", w.memory.read(DATA, off, 4))[0]


def hresult(out):
    ax, dx, stop, _ = out
    return (dx << 16 | ax), stop


class Base(unittest.TestCase):
    def setUp(self):
        self.w = window_wine()
        self.w.gate_address = lambda module, ordinal: (0x1DB0, 8 * ordinal)
        self.w.memory.write(DATA, GUID, CLSID)

    def call(self, name, *args):
        return by_name(self.w, "COMPOBJ", name, *args, regs={"ax": 0x1234, "dx": 0x5678})

    def method(self, ordinal, this, *rest):
        values = list(rest[::-1]) + [(this >> 16, this & 0xFFFF)]
        ax, dx, stop = self.w.answer("COMPOBJ", ordinal, Args(self.w.memory, values, {"ax": 0x1234, "dx": 0x5678}))
        return ax, dx, stop


class Strings(Base):
    def test_string_from_guid2(self):
        # compobj.c:661: CHARS_IN_GUID, the string and its NUL.
        ax, _dx, stop, _ = self.call("StringFromGUID2", far(GUID), far(STR), 39)
        self.assertEqual((ax, stop), (39, None))
        self.assertEqual(self.w.memory.read(DATA, STR, 39), CLSID_TEXT.encode() + b"\0")

    def test_string_from_guid2_too_small_is_0(self):
        ax, _dx, stop, _ = self.call("StringFromGUID2", far(GUID), far(STR), 38)
        self.assertEqual((ax, stop), (0, None))


class ClassLookup(Base):
    def test_unregistered_class_is_regdb_e_classnotreg(self):
        # compobj.c:713-716, and *ppv NULL first (:692).
        self.w.memory.write(DATA, PPV, b"\xff" * 4)
        hr, stop = hresult(self.call("CoGetClassObject", far(GUID), (0, 1), (0, 0), far(RIID), far(PPV)))
        self.assertEqual((hr, stop), (0x80040154, None))
        self.assertEqual(dword(self.w, PPV), 0)

    def test_without_inproc_server_is_e_notimpl(self):
        hr, stop = hresult(self.call("CoGetClassObject", far(GUID), (0, 4), (0, 0), far(RIID), far(PPV)))
        self.assertEqual((hr, stop), (0x80004001, None))

    def test_prog_id_of_an_unregistered_class(self):
        # combase.c:306 open_key_for_clsid: no CLSID key is REGDB_E_CLASSNOTREG.
        hr, stop = hresult(self.call("ProgIDFromCLSID", far(GUID), far(OUT)))
        self.assertEqual((hr, stop), (0x80040154, None))

    def test_registered_class_stops_by_name(self):
        from tbpipeline_neww.shell16 import HKEY_CLASSES_ROOT, _reg
        reg = _reg(self.w)
        reg.walk(reg.key(HKEY_CLASSES_ROOT), f"CLSID\\{CLSID_TEXT}\\InprocServer", True).default = b"X.DLL"
        _hr, stop = hresult(self.call("CoGetClassObject", far(GUID), (0, 1), (0, 0), far(RIID), far(PPV)))
        self.assertIn("DllGetClassObject", stop)


class Allocator(Base):
    def malloc(self):
        hr, stop = hresult(self.call("CoGetMalloc", (0, 1), far(OUT)))
        self.assertEqual((hr, stop), (0, None))
        return dword(self.w, OUT)

    def test_string_from_clsid_before_any_allocator_stops(self):
        # CoMemAlloc (:313) on a NULL compobj_malloc: Wine faults, so neww stops by name.
        _hr, stop = hresult(self.call("StringFromCLSID", far(GUID), far(OUT)))
        self.assertIn("compobj_malloc is NULL", stop)

    def test_get_malloc_is_one_object_with_more_references(self):
        # compobj.c:282: made once, then AddRef'd.
        from tbpipeline_neww import ole16
        first = self.malloc()
        self.assertEqual(self.malloc(), first)
        self.assertEqual(ole16._com(self.w)[first]["ref"], 2)
        vtable = struct.unpack("<I", self.w.memory.read(first >> 16, 0, 4))[0]
        alloc = struct.unpack("<HH", self.w.memory.read(vtable >> 16, 4 * 3, 4))
        self.assertEqual(alloc, (8 * 503, 0x1DB0))

    def test_string_from_clsid_with_the_allocator(self):
        # compobj.c:441: 40 bytes from CoMemAlloc, the string in them.
        self.malloc()
        hr, stop = hresult(self.call("StringFromCLSID", far(GUID), far(OUT)))
        self.assertEqual((hr, stop), (0, None))
        ptr = dword(self.w, OUT)
        self.assertEqual(self.w.memory.read(ptr >> 16, ptr & 0xFFFF, 39), CLSID_TEXT.encode() + b"\0")
        self.assertEqual(self.method(506, self.malloc(), (ptr >> 16, ptr & 0xFFFF))[:2], (40, 0))

    def test_alloc_realloc_free(self):
        m = self.malloc()
        ax, dx, stop = self.method(503, m, (0, 10))
        self.assertIsNone(stop)
        block = dx << 16 | ax
        self.w.memory.write(block >> 16, 0, b"0123456789")
        self.assertEqual(self.method(506, m, (dx, ax))[:2], (10, 0))
        ax, dx, stop = self.method(504, m, (block >> 16, 0), (0, 20))
        self.assertIsNone(stop)
        grown = dx << 16 | ax
        self.assertEqual(self.w.memory.read(grown >> 16, 0, 10), b"0123456789")
        self.assertEqual(self.method(506, m, (dx, ax))[:2], (20, 0))
        # Realloc to 0 frees and is NULL (:202); the block is no longer one it handed out.
        self.assertEqual(self.method(504, m, (dx, ax), (0, 0)), (0, 0, None))
        self.assertIn("did not hand out", self.method(505, m, (dx, ax))[2])

    def test_query_interface_did_alloc_heap_minimize(self):
        m = self.malloc()
        self.w.memory.write(DATA, RIID, IID_IMALLOC)
        self.assertEqual(self.method(500, m, far(RIID), far(PPV)), (0, 0, None))
        self.assertEqual(dword(self.w, PPV), m)
        self.w.memory.write(DATA, RIID, b"\x01" * 16)
        self.assertEqual(self.method(500, m, far(RIID), far(PPV))[:2], (0x0002, 0x8004))   # OLE_E_ENUM_NOMORE
        self.assertEqual(self.method(507, m, (0, 0))[0], 0xFFFF)
        self.assertEqual(self.method(508, m)[:2], (0, 0))

    def test_uninitialize_releases_the_allocator(self):
        from tbpipeline_neww import ole16
        m = self.malloc()
        ax, dx, stop, _ = self.call("CoUninitialize")
        self.assertIsNone(stop)
        self.assertNotIn(m, ole16._com(self.w))
        self.assertIn("NULL interface", self.call("CoUninitialize")[2])

    def test_method_rows_are_cdecl(self):
        from tbpipeline_neww.wine import row_for
        self.assertTrue(row_for("COMPOBJ", 503).caller_pops)
        self.assertFalse(row_for("COMPOBJ", 4).caller_pops)


if __name__ == "__main__":
    unittest.main()
