"""Batch 2: what the real run needed to get past the GDI failure and on to WinExec.

Prolog fixups on exported entries, the WH_CBT hook, local heap compaction and
growth, INT 21h, the GDI object layer and the USER window layer. Each test
checks against the Wine function its docstring names. No ToolBook bytes: the
NE files are built by tests/neww_ne.py, and handlers run on fake memory.
"""

import struct
import tempfile
import unittest

from tests import neww_ne
from tests.test_neww_batch1_handlers import Args, DATA, NUL, put, wine


def by_name(w, module, name, *values, reply=None, regs=None):
    """Answer a call by its spec name. A guest call gets reply(call) -> (ax, dx), (0, 0) by
    default. Returns (ax, dx, stop, calls made)."""
    from tbpipeline_neww.guest import GuestCalls
    from tbpipeline_neww.handlers import spec_types
    ordinal = spec_types(module, name)[0]
    w.registers = None
    ax, dx, stop = w.answer(module, ordinal, Args(w.memory, values, regs))
    made = []
    request = (w.registers or {}).get("guest")
    if isinstance(request, GuestCalls):
        pending, results = list(request.calls), []
        while pending:
            call = pending.pop(0)
            made.append(call)
            got = reply(call) if reply else (0, 0)
            results.append(got)
            if request.after:
                more = request.after(len(results) - 1, *got)
                if isinstance(more, str):
                    return 0, 0, more, made
                pending.extend(more or [])
        out = request.finish(results)
        ax, dx, stop = out[0], out[1], (out[2] if len(out) > 2 else None)
    return ax, dx, stop, made


def window_wine():
    """A Wine with fake memory, blocks from 0x200 up, and one module, the task's."""
    w = wine()
    nxt = [0x200]

    def allocate(size):
        sel = nxt[0]
        nxt[0] += 8 * ((size + 0xFFFF) // 0x10000)
        return sel
    w.allocate = allocate
    w.size = lambda sel: 0x10000
    w.owner = lambda sel: None
    w.exe_name = "TB80RTM"
    w._exe_ptr = lambda handle: 0x100 if handle else 0
    return w


PROC = 0x0120_0040
INST = 0x500


def register(w, name="TBKMain", proc=PROC):
    cls = put(w, 0x20, name)
    w.memory.write(DATA, 0x100, struct.pack("<HIhhHHHHII", 3, proc, 0, 4, INST, 0, 0, 6, 0, DATA << 16 | 0x20))
    return by_name(w, "USER", "RegisterClass", (DATA, 0x100))[0], cls


# ---------------------------------------------------------------- prologs

class Prologs(unittest.TestCase):
    """ne_segment.c NE_FixupSegmentPrologs."""

    def load(self, code, flags, module_flags=None):
        from tbpipeline_neww.image import Sandbox
        with tempfile.TemporaryDirectory() as d:
            blob = neww_ne.build("TBTEST", [(0x0000, code, []), (0x0001, b"\x00" * 64, [])],
                                 entries=[(1, 1, 0, "F")], auto=2, exe=False, entry_flags={1: flags})
            if module_flags is not None:
                blob = bytearray(blob)
                struct.pack_into("<H", blob, 0x40 + 0x0C, module_flags)
            neww_ne.write(d, "TBTEST.DLL", blob)
            box = Sandbox(d).load()
        image = box.images["TBTEST"]
        return bytes(image.segments[0].data[:3]), image.segments[1].selector

    def test_shared_data_entry_gets_mov_ax_dgroup(self):
        # mov ax, ds ; nop with entry flags 0x03: mov ax, DGROUP.
        code, dgroup = self.load(b"\x8C\xD8\x90\xCB", 0x03)
        self.assertEqual(code, bytes([0xB8, dgroup & 0xFF, dgroup >> 8]))

    def test_push_ds_pop_ax_is_patched_too(self):
        code, dgroup = self.load(b"\x1E\x58\x90\xCB", 0x03)
        self.assertEqual(code, bytes([0xB8, dgroup & 0xFF, dgroup >> 8]))

    def test_exported_without_shared_data_keeps_mov_ax_ds(self):
        # Flags 0x01 in a SINGLEDATA module: only push ds ; pop ax becomes mov ax, ds.
        self.assertEqual(self.load(b"\x1E\x58\x90\xCB", 0x01, module_flags=0x8001)[0], b"\x8C\xD8\x90")

    def test_multipledata_export_becomes_nops(self):
        self.assertEqual(self.load(b"\x8C\xD8\x90\xCB", 0x01, module_flags=0x8002)[0], b"\x90\x90\x90")

    def test_no_nop_no_patch(self):
        self.assertEqual(self.load(b"\x8C\xD8\x55\xCB", 0x03)[0], b"\x8C\xD8\x55")


# ---------------------------------------------------------------- local heap

class LocalHeapGrowth(unittest.TestCase):
    """local.c LOCAL_GetBlock: LOCAL_Compact, then LOCAL_GrowHeap."""

    def setUp(self):
        self.w = wine()
        self.sizes = {DATA: 0x200}
        self.w.size = lambda sel: self.sizes.get(sel & ~7)
        self.w.resize = lambda sel, size, old: self.sizes.__setitem__(sel & ~7, size)
        self.assertEqual(self.w.local_init(DATA, 0x20, 0x1F0, DATA), 1)
        word = lambda sel, off: struct.unpack("<H", self.w.memory.read(sel, off, 2))[0]
        self.heap = self.w.local_heap(DATA, word)

    def test_compaction_moves_a_moveable_block_down(self):
        heap = self.heap
        m1 = heap.alloc(0x0002, 0x40)
        m2 = heap.alloc(0x0002, 0x40)
        before = heap.w(m2)
        self.w.memory.write(DATA, before, b"KEEPME")
        heap.free(m1)
        fixed = heap.alloc(0, heap.free_space() + 0x20)
        self.assertNotEqual(fixed, 0)
        self.assertLess(heap.w(m2), before)
        self.assertEqual(self.w.memory.read(DATA, heap.w(m2), 6), b"KEEPME")
        # Compaction was enough: the segment did not grow.
        self.assertEqual(self.sizes[DATA], 0x200)

    def test_growth_to_64k(self):
        # More than the heap holds: the old last free block takes the new room.
        block = self.heap.alloc(0, 0x400)
        self.assertNotEqual(block, 0)
        self.assertEqual(self.sizes[DATA], 0x10000)
        self.assertGreaterEqual(self.heap.free_space(), 0x10000 - 0x800)

    def test_full_64k_heap_answers_0(self):
        self.sizes[DATA] = 0xFFF8
        self.assertEqual(self.heap.alloc(0, 0x400), 0)

    def test_local_notify_procedure_stops(self):
        from tbpipeline_neww.local import Stop
        info = self.heap.info()
        self.w.memory.write(DATA, info + 0x1E, struct.pack("<I", 0x01230045))
        m1 = self.heap.alloc(0x0002, 0x40)
        self.heap.alloc(0x0002, 0x40)
        self.heap.free(m1)
        with self.assertRaises(Stop):
            self.heap.alloc(0, self.heap.free_space() + 0x20)


# ---------------------------------------------------------------- INT 21h

def run_with(before):
    from tbpipeline_neww.machine import Machine
    with tempfile.TemporaryDirectory() as d:
        neww_ne.exit_program_with(d, before, [])
        host = Machine(d)
        host.run()
    return host


def reg(host, name):
    from tbpipeline_neww.machine import REGISTERS
    return host.uc.reg_read(REGISTERS[name])


INT21 = bytes([0xCD, 0x21])


class Int21(unittest.TestCase):
    """int21.c DOSVM_Int21Handler, reached by INT 21h and by DOS3Call."""

    def test_get_vector_loads_es_from_the_gdt(self):
        # mov ax, 3505h ; int 21h ; mov dx, es:[bx]: the default vector is Wine's stub.
        host = run_with(bytes([0xB8, 0x05, 0x35]) + INT21 + bytes([0x26, 0x8B, 0x17]))
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(reg(host, "es"), host.box.wine.int_stubs)
        self.assertEqual(reg(host, "dx"), 0xEBE6)

    def test_set_then_get_vector(self):
        # mov dx, 1234h ; mov ax, 2500h ; int 21h ; mov ax, 3500h ; int 21h ; mov dx, bx
        code = bytes([0xBA, 0x34, 0x12, 0xB8, 0x00, 0x25]) + INT21 + bytes([0xB8, 0x00, 0x35]) + INT21
        host = run_with(code + bytes([0x89, 0xDA]))
        self.assertEqual(reg(host, "dx"), 0x1234)
        self.assertEqual(host.box.wine.pm_vectors[0][1], 0x1234)

    def test_dos_version_is_getversion16s(self):
        # mov ax, 3000h ; int 21h ; mov dx, ax: AL 6, AH 22, from GetVersion16's DOS 6.22.
        host = run_with(bytes([0xB8, 0x00, 0x30]) + INT21 + bytes([0x89, 0xC2]))
        self.assertEqual(reg(host, "dx"), 0x1606)
        self.assertEqual(reg(host, "cx"), 0x3456)

    def test_date_is_the_host_date(self):
        import time
        host = run_with(bytes([0xB8, 0x00, 0x2A]) + INT21 + bytes([0x89, 0xCE]))
        self.assertIn(reg(host, "si"), (time.localtime().tm_year, time.localtime().tm_year + 1))

    def test_function_not_in_neww_stops_and_names_it(self):
        host = run_with(bytes([0xB8, 0x00, 0x3D]) + INT21)
        self.assertEqual(host.stop, "INT 21h AH=0x3d (AX=0x3d00): this DOSVM_Int21Handler function is not in neww yet")

    def test_other_interrupt_stops(self):
        host = run_with(bytes([0xCD, 0x10]))
        self.assertTrue(host.stop.startswith("INT 0x10 at 0x8:0x2"), host.stop)

    def test_cpu_fault_keeps_its_named_form(self):
        from tests.test_neww_full_run import NAMED
        # mov ax, 0 ; mov ds, ax ; mov ax, [0]: a null selector read faults.
        host = run_with(bytes([0xB8, 0x00, 0x00, 0x8E, 0xD8, 0xA1, 0x00, 0x00]))
        self.assertRegex(host.stop, NAMED)

    def test_getversion_dx_is_dos_622(self):
        from tbpipeline_neww.wine import Wine
        self.assertEqual(Wine(".").answer("KERNEL", 3, None), (0x0A03, 0x0616, None))


# ---------------------------------------------------------------- GDI

class Gdi(unittest.TestCase):
    """win32u dibdrv and gdiobj, the paths the run reaches."""

    def setUp(self):
        self.w = window_wine()

    def call(self, name, *values):
        return by_name(self.w, "GDI", name, *values)[0]

    def mono(self):
        dc = self.call("CreateCompatibleDC", 0)
        bitmap = self.call("CreateCompatibleBitmap", dc, 8, 8)
        self.call("SelectObject", dc, bitmap)
        return dc, bitmap

    def test_stock_objects_are_32_plus_n(self):
        self.assertEqual(self.call("GetStockObject", 0), 32)
        self.assertEqual(self.call("GetStockObject", 5), 37)

    def test_memory_dc_bitmap_is_monochrome(self):
        dc, bitmap = self.mono()
        self.assertEqual(self.call("GetObject", bitmap, 14, (DATA, 0x300)), 14)
        width, height, _wb, planes, bpp = struct.unpack("<xxHHHBB", self.w.memory.read(DATA, 0x300, 10))
        self.assertEqual((width, height, planes, bpp), (8, 8, 1, 1))

    def test_whiteness_then_setpixel_red_is_black_on_mono(self):
        dc, _ = self.mono()
        self.call("PatBlt", dc, 0, 0, 8, 8, (0x00FF, 0x0062))
        self.assertEqual(by_name(self.w, "GDI", "GetPixel", dc, 3, 3)[:2], (0xFFFF, 0x00FF))
        # dibdrv_SetPixel: nearest color table entry, and the color it stands for comes back.
        self.assertEqual(by_name(self.w, "GDI", "SetPixel", dc, 1, 1, (0, 0x00FF))[:2], (0, 0))
        self.assertEqual(self.call("GetPixel", dc, 1, 1), 0)

    def test_light_gray_brush_on_mono_is_black_unless_it_is_the_bk_color(self):
        # get_pixel_color with mono_fixup: not black, not white, not the background: !bk pixel.
        dc, _ = self.mono()
        brush = self.call("CreateSolidBrush", (0x00C0, 0xC0C0))
        self.call("SelectObject", dc, brush)
        self.call("PatBlt", dc, 0, 0, 8, 8, (0x00F0, 0x0021))
        self.assertEqual(self.call("GetPixel", dc, 0, 0), 0)
        # The background color itself is its own nearest entry, white for light gray.
        self.call("SetBkColor", dc, (0x00C0, 0xC0C0))
        self.call("PatBlt", dc, 0, 0, 8, 8, (0x00F0, 0x0021))
        self.assertEqual(by_name(self.w, "GDI", "GetPixel", dc, 0, 0)[:2], (0xFFFF, 0x00FF))

    def test_color_to_mono_blt_matches_the_bk_color(self):
        screen = self.call("CreateDC", put(self.w, 0x10, "DISPLAY"), NUL, NUL, NUL)
        color_dc = self.call("CreateCompatibleDC", screen)
        self.call("SelectObject", color_dc, self.call("CreateCompatibleBitmap", screen, 4, 4))
        self.call("SelectObject", color_dc, self.call("GetStockObject", 0))
        self.call("PatBlt", color_dc, 0, 0, 4, 4, (0x00F0, 0x0021))
        dc, _ = self.mono()
        self.call("SetBkColor", dc, (0x00FF, 0xFFFF))
        self.call("BitBlt", dc, 0, 0, 4, 4, color_dc, 0, 0, (0x00CC, 0x0020))
        self.assertEqual(by_name(self.w, "GDI", "GetPixel", dc, 1, 1)[:2], (0xFFFF, 0x00FF))

    def test_select_returns_the_previous_object_and_delete_frees(self):
        dc, bitmap = self.mono()
        pen = self.call("CreatePen", 0, 1, (0, 0))
        self.assertEqual(self.call("SelectObject", dc, pen), 32 + 7)
        self.assertEqual(self.call("DeleteDC", dc), 1)
        self.assertEqual(self.call("DeleteObject", bitmap), 1)
        self.assertEqual(self.call("IsGDIObject", bitmap), 0)


# ---------------------------------------------------------------- USER windows

def names(calls):
    from tbpipeline_neww.user_wnd import MESSAGE_NAMES
    return [MESSAGE_NAMES.get(c.words[1], hex(c.words[1])) for c in calls]


class Windows(unittest.TestCase):
    """win32u window.c create_window and the messages it sends, in Wine's order."""

    def setUp(self):
        self.w = window_wine()
        self.atom, self.cls = register(self.w)

    def create(self, reply=None, style=(0x10CF, 0)):
        return by_name(self.w, "USER", "CreateWindow", self.cls, put(self.w, 0x40, "Book"), style,
                       10, 20, 300, 200, 0, 0, INST, NUL,
                       reply=reply or (lambda c: (1, 0) if c.words[1:2] == [0x81] else (0, 0)))

    def test_register_class_gives_an_atom(self):
        self.assertGreaterEqual(self.atom, 0xC000)
        self.assertEqual(register(self.w)[0], 0)

    def test_create_window_message_order(self):
        hwnd, _dx, stop, calls = self.create()
        self.assertIsNone(stop)
        self.assertEqual(hwnd, 0x22)
        got = names(calls)
        self.assertEqual(got[:4], ["WM_GETMINMAXINFO", "WM_NCCREATE", "WM_NCCALCSIZE", "WM_CREATE"])
        self.assertEqual(got[4:6], ["WM_SHOWWINDOW", "WM_WINDOWPOSCHANGING"])
        self.assertEqual(got[-2:], ["WM_SIZE", "WM_MOVE"])
        # The window procedure is called with DS = ES = SS and AX the window's hInstance.
        self.assertEqual(calls[0].regs["ax"], INST)
        self.assertEqual(calls[0].regs["ds"], calls[0].regs["es"])

    def test_nccreate_false_destroys(self):
        hwnd, _dx, _stop, calls = self.create(reply=lambda c: (0, 0))
        self.assertEqual(hwnd, 0)
        self.assertIn("WM_NCDESTROY", names(calls))

    def test_window_rect(self):
        hwnd = self.create(style=(0x00CF, 0))[0]
        by_name(self.w, "USER", "GetWindowRect", hwnd, (DATA, 0x300))
        self.assertEqual(struct.unpack("<hhhh", self.w.memory.read(DATA, 0x300, 8)), (10, 20, 310, 220))

    def test_cbt_hook_is_called_first_with_createwnd(self):
        self.w.hooks[6] = (0x00010001, 0x0130_0010)
        seen = {}

        def reply(c):
            if (c.cs, c.ip) == (0x0130, 0x0010):
                if c.words[0] != 3:
                    # HCBT_ACTIVATE, from ShowWindow's activation.
                    seen.setdefault("other", []).append(c.words[0])
                    return 0, 0
                # The structures live only while the hook runs.
                lpcs, after = struct.unpack("<IH", self.w.memory.read(c.words[2], c.words[3], 6))
                seen["after"] = after
                seen["cs"] = self.w.memory.read(lpcs >> 16, lpcs & 0xFFFF, 0x1A)
                return 0, 0
            return (1, 0) if c.words[1] == 0x81 else (0, 0)
        hwnd, _dx, _stop, calls = self.create(reply=reply)
        hook = calls[0]
        self.assertEqual((hook.cs, hook.ip), (0x0130, 0x0010))
        code, wparam = hook.words[:2]
        self.assertEqual((code, wparam), (3, hwnd))
        after, cs16 = seen["after"], seen["cs"]
        params, inst, menu, parent, cy, cx, y, x, style = struct.unpack("<IHHHhhhhI", cs16[:22])
        self.assertEqual((inst, cx, cy, x, y, style, after), (INST, 300, 200, 10, 20, 0x10CF0000, 0))
        self.assertEqual(names(calls[1:3]), ["WM_GETMINMAXINFO", "WM_NCCREATE"])
        self.assertEqual(seen["other"], [5])

    def test_cbt_hook_can_refuse(self):
        self.w.hooks[6] = (0x00010001, 0x0130_0010)
        hwnd, _dx, _stop, calls = self.create(reply=lambda c: (1, 0) if (c.cs, c.ip) == (0x0130, 0x0010) else (0, 0))
        self.assertEqual((hwnd, len(calls)), (0, 1))
        self.assertEqual(by_name(self.w, "USER", "IsWindow", 0x22)[0], 0)

    def test_unhook(self):
        self.w.hooks[6] = (0x00010001, 0x0130_0010)
        self.assertEqual(by_name(self.w, "USER", "UnhookWindowsHookEx", (0x0001, 0x0001))[0], 1)
        self.assertEqual(by_name(self.w, "USER", "UnhookWindowsHookEx", (0x0001, 0x0001))[0], 0)
        self.w.hooks[6] = (0x00010002, 0x0130_0010)
        self.assertEqual(by_name(self.w, "USER", "UnhookWindowsHook", 5, (0x0130, 0x0011))[0], 0)
        self.assertEqual(by_name(self.w, "USER", "UnhookWindowsHook", 5, (0x0130, 0x0010))[0], 1)

    def test_post_then_peek(self):
        hwnd = self.create()[0]
        by_name(self.w, "USER", "PostMessage", hwnd, 0x400, 7, (0, 9))
        ax, _dx, _stop, _calls = by_name(self.w, "USER", "PeekMessage", (DATA, 0x300), 0, 0, 0, 1)
        self.assertEqual(ax, 1)
        got_hwnd, msg, wp, lp = struct.unpack("<HHHI", self.w.memory.read(DATA, 0x300, 10))
        self.assertEqual((got_hwnd, msg, wp, lp), (hwnd, 0x400, 7, 9))


if __name__ == "__main__":
    unittest.main()
