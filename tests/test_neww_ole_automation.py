"""What ToolBook's TB80OLE needs of OLE2DISP and of a 32-bit FreeLibrary at Lesson Exit (#233).

INITIALIZEOLEREMOTE makes an automation object with CreateDispTypeInfo and CreateStdDispatch,
and UNINITIALIZEOLEREMOTE releases it. Wine's 16-bit pair are stubs (dlls/ole2disp.dll16/
ole2disp.c:477, :489) that leave the out pointer NULL, so neww makes the objects as oleaut32
does in 32 bits. Then OleUninitialize, and FreeLibrary32W unloads TB80F32L with
DllMain(DLL_PROCESS_DETACH). Each test names the Wine 2528aff2 function it checks.
"""

import struct
import unittest

from tests.test_neww_batch1_handlers import Args, DATA
from tests.test_neww_batch2 import by_name, window_wine

PTINFO, PUNK, PPV, RIID, IDATA = 0x10, 0x14, 0x18, 0x20, 0x40


def far(off):
    return (DATA, off)


def ptr_at(w, off):
    return struct.unpack("<I", w.memory.read(DATA, off, 4))[0]


def method(w, ordinal, this, *rest):
    """A cdecl COM method: the interface pointer is pushed last, so it is arg(0)."""
    values = list(rest[::-1]) + [(this >> 16, this & 0xFFFF)]
    return w.answer("OLE2DISP", ordinal, Args(w.memory, values))


class Cdecl(unittest.TestCase):
    def test_method_rows_leave_the_pop_to_the_caller(self):
        from tbpipeline_neww.wine import row_for
        self.assertTrue(row_for("OLE2DISP", 502).caller_pops)
        self.assertFalse(row_for("OLE2DISP", 31).caller_pops)


class Automation(unittest.TestCase):
    def setUp(self):
        from tbpipeline_neww import ole16
        self.ole16 = ole16
        self.w = window_wine()
        self.w.gate_address = lambda module, ordinal: (0x1DB0, 8 * ordinal)

    def iid(self, value):
        self.w.memory.write(DATA, RIID, value)
        return far(RIID)

    def type_info(self):
        ax, dx, stop, _ = by_name(self.w, "OLE2DISP", "CreateDispTypeInfo", far(IDATA), 0, 0x409, far(PTINFO))
        self.assertEqual((ax, dx, stop), (0, 0, None))
        return ptr_at(self.w, PTINFO)

    def ref(self, ptr):
        return self.ole16._com(self.w)[ptr]["ref"]

    def test_create_disp_type_info_makes_one_reference(self):
        # typelib.c:8669: S_OK and a new ITypeInfo in *pptinfo.
        info = self.type_info()
        self.assertNotEqual(info, 0)
        self.assertEqual(self.ref(info), 1)

    def test_its_vtable_points_at_the_method_gates(self):
        info = self.type_info()
        vt = struct.unpack("<I", self.w.read(info >> 16, info & 0xFFFF, 4))[0]
        release = struct.unpack("<HH", self.w.read(vt >> 16, (vt & 0xFFFF) + 8, 4))
        self.assertEqual((release[1], release[0]), self.w.gate_address("OLE2DISP", 502))

    def test_create_std_dispatch_addrefs_the_type_info(self):
        # dispatch.c:450: *ppunk is the inner unknown; :473 ITypeInfo_AddRef.
        info = self.type_info()
        ax, _dx, stop, _ = by_name(self.w, "OLE2DISP", "CreateStdDispatch", (0, 0), far(0x80),
                                   (info >> 16, info & 0xFFFF), far(PUNK))
        self.assertEqual((ax, stop), (0, None))
        self.assertNotEqual(ptr_at(self.w, PUNK), 0)
        self.assertEqual(self.ref(info), 2)

    def test_create_std_dispatch_without_this_is_e_invalidarg(self):
        info = self.type_info()
        ax, dx, _stop, _ = by_name(self.w, "OLE2DISP", "CreateStdDispatch", (0, 0), (0, 0),
                                   (info >> 16, info & 0xFFFF), far(PUNK))
        self.assertEqual(ax | dx << 16, 0x80070057)

    def test_releasing_the_dispatch_releases_the_type_info(self):
        # dispatch.c:424: at 0 the inner Release releases the type info it holds.
        info = self.type_info()
        by_name(self.w, "OLE2DISP", "CreateStdDispatch", (0, 0), far(0x80), (info >> 16, info & 0xFFFF), far(PUNK))
        self.assertEqual(method(self.w, 502, info)[0], 1)           # the caller's own reference
        punk = ptr_at(self.w, PUNK)
        self.assertEqual(method(self.w, 532, punk), (0, 0, None))
        self.assertNotIn(info, self.ole16._com(self.w))

    def test_inner_query_interface(self):
        info = self.type_info()
        by_name(self.w, "OLE2DISP", "CreateStdDispatch", (0, 0), far(0x80), (info >> 16, info & 0xFFFF), far(PUNK))
        punk = ptr_at(self.w, PUNK)
        self.assertEqual(method(self.w, 530, punk, self.iid(self.ole16.IID_IDISPATCH), far(PPV)), (0, 0, None))
        self.assertEqual(ptr_at(self.w, PPV), punk - 4)
        self.assertEqual(method(self.w, 531, punk)[0], 3)
        ax, dx, stop = method(self.w, 530, punk, self.iid(self.ole16._iid(1)), far(PPV))
        self.assertEqual((ax | dx << 16, stop, ptr_at(self.w, PPV)), (0x80004002, None, 0))

    def test_type_info_query_interface(self):
        # typelib.c:5653: IUnknown and ITypeInfo are the object, with a reference.
        info = self.type_info()
        self.assertEqual(method(self.w, 500, info, self.iid(self.ole16.IID_IUNKNOWN), far(PPV)), (0, 0, None))
        self.assertEqual((ptr_at(self.w, PPV), self.ref(info)), (info, 2))
        ax, dx, _stop = method(self.w, 500, info, self.iid(self.ole16.IID_IDISPATCH), far(PPV))
        self.assertEqual(ax | dx << 16, 0x80004002)

    def test_a_method_neww_lacks_stops_by_name(self):
        info = self.type_info()
        stop = method(self.w, 503, info, far(PPV))[2]
        self.assertIn("ITypeInfo::GetTypeAttr", stop)


class OleUninitialize(unittest.TestCase):
    """dlls/ole32/ole2.c:218 OleUninitialize: one fewer, never below 0; void."""

    def test_it_counts_down_to_e_fail_for_the_clipboard(self):
        w = window_wine()
        by_name(w, "OLE2", "OleInitialize", (0, 0))
        by_name(w, "OLE2", "OleUninitialize", regs={"dx": 0})
        by_name(w, "OLE2", "OleUninitialize", regs={"dx": 0})
        self.assertEqual(w.ole_inits[w.htask], 0)
        self.assertEqual(by_name(w, "OLE2", "OleFlushClipboard")[0], 0x4005)

    def test_it_leaves_ax(self):
        w = window_wine()
        ax, _dx, stop, _ = by_name(w, "OLE2", "OleUninitialize", regs={"ax": 0x1234, "dx": 0})
        self.assertEqual((ax, stop), (0x1234, None))


class UnloadPe(unittest.TestCase):
    """dlls/ntdll/loader.c:4137 LdrUnloadDll: MODULE_DecRefCount (:4105) down the imports,
    process_detach (:1833) in reverse initialization order, MODULE_FlushModrefs (:4074)."""

    def module(self, st, name, refs, deps=()):
        from tbpipeline_neww import win32

        class Pe:
            entry = 0x100
        m = win32.Module(name, 0x1000_0000, "C:\\TBK\\" + name + ".DLL", Pe())
        m.refs, m.deps, m.attached = refs, list(deps), True
        st.modules[name] = m
        st.init_order.append(m)
        return m

    def run_unload(self, top):
        from tbpipeline_neww import win32
        w = window_wine()
        st = win32.state(w)
        mods = top(st)
        gen = win32.unload_pe(w, mods[0])
        called = []
        try:
            call = next(gen)
            while True:
                called.append(call[1])
                call = gen.send(1)
        except StopIteration as done:
            result = done.value
        return st, mods, w.trace, called, result

    def test_detach_runs_last_loaded_first_and_both_go(self):
        def top(st):
            dep = self.module(st, "TB80RMT", 1)
            return [self.module(st, "TB80F32L", 1, [dep]), dep]
        st, _mods, trace, called, result = self.run_unload(top)
        self.assertEqual(result, 1)
        self.assertEqual([t for t in trace if "DllMain" in t],
                         ["  TB80F32L DllMain(PROCESS_DETACH)", "  TB80RMT DllMain(PROCESS_DETACH)"])
        self.assertEqual(called[0][1:], [0, 0])                      # DLL_PROCESS_DETACH, NULL
        self.assertEqual((st.modules, st.init_order), ({}, []))

    def test_an_import_still_used_elsewhere_stays(self):
        def top(st):
            dep = self.module(st, "TB80RMT", 2)
            return [self.module(st, "TB80F32L", 1, [dep]), dep]
        st, mods, trace, _called, _result = self.run_unload(top)
        self.assertEqual(list(st.modules), ["TB80RMT"])
        self.assertEqual(mods[1].refs, 1)
        self.assertNotIn("  TB80RMT DllMain(PROCESS_DETACH)", trace)


if __name__ == "__main__":
    unittest.main()
