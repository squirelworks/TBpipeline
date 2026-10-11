#!/usr/bin/env python3
"""Pass 06: pass 04's entry, with ToolBook ordinals bound to real DLL code.

Windows ordinals still return from the thunk. TB80BAS, TB80RCR, TB80LNL,
TB80OLE, TB80UTL and TB80W16 ordinals jump to the segment:offset bind.py
resolved. The thunk now has a stub in every slot, so USER.266 does not
fall through zeros.
"""

import os
import struct
import sys

from tbpipeline.nehost.pass04 import Pass04, API_PORT
from tbpipeline.nehost.win16stack import POP
from .bind import DLLS, export_names, exports, modules, segment_bytes

from unicorn import UcError
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_SP, UC_X86_REG_IP,
    UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_CS,
)

INIT_ORDER = ["TB80RCR", "TB80LNL", "TB80OLE", "TB80W16", "TB80UTL", "TB80BAS"]

# KERNEL exports that are constants, not code. A type-5 fixup must receive
# the value; a thunk offset makes __WINFLAGS look like real mode.
EQUATES = {
    "KERNEL": {
        113: 3,       # __AHSHIFT
        114: 8,       # __AHINCR, matches the arena selector step
        178: 0x0C25,  # __WINFLAGS: PMODE|CPU386|ENHANCED|80x87|PAGING
    },
}

UNPACKED = "/workspace/artifacts/unpacked"


class Pass06(Pass04):
    def build(self):
        self.dlls = {}
        self.dll_segs = {}
        self.dll_calls = []
        self.dll_ready = set()
        self.dll_busy = set()
        self.dll_group = {}
        for mod, filename in DLLS.items():
            blob = open(os.path.join(UNPACKED, filename), "rb").read()
            self.dlls[mod] = (exports(blob), blob)
        super().build()
        self.modnames = modules(self.file, self.ne)
        procs, ords = self._export_procs_from(self.file, self.segs)
        if self.exe_inst in self.mods:
            self.mods[self.exe_inst]["procs"] = procs
            self.mods[self.exe_inst]["ords"] = ords

    def _export_procs(self, name, data):
        return self._export_procs_from(data, {
            seg: sel for (mod, seg), sel in self.dll_segs.items() if mod == name
        })

    def _export_procs_from(self, data, segs):
        table = exports(data)
        procs, ords = {}, {}
        for ename, ordinal in export_names(data):
            ent = table.get(ordinal)
            if not ent:
                continue
            seg, off = ent
            sel = segs.get(seg)
            if not sel:
                continue
            procs[ename.lower()] = (off, sel)
            ords[ordinal] = (off, sel)
        return procs, ords

    def _load_library(self, name):
        data, filename = self._library_bytes(name)
        if not data:
            return 2
        if not hasattr(self, "lib_by_file"):
            self.lib_by_file = {}
        key = filename.upper()
        if key in self.lib_by_file:
            return self.lib_by_file[key]
        modname = filename.rsplit(".", 1)[0].upper()
        if modname not in self.dlls:
            self.dlls[modname] = (exports(data), data)
        self._ensure_dll(modname)
        handle = self.dll_group.get(modname, 0)
        if not handle:
            return 2
        self.lib_by_file[key] = handle
        return handle

    def _thunks(self):
        blob = bytearray(0x1000)
        for ordinal in range(1, 512):
            at = ordinal * 8
            if at + 8 > len(blob):
                break
            blob[at:at + 8] = bytes([
                0xBA, ordinal & 0xFF, (ordinal >> 8) & 0xFF,
                0xE6, API_PORT, 0xCA, 0x00, 0x00,
            ])
        self.arena.write(self.thunk, 0, bytes(blob))

    def _relocs(self):
        self.modnames = modules(self.file, self.ne)
        super()._relocs()

    def _import_stub(self, fl, module, target):
        if fl & 1 and 1 <= module <= len(self.modnames):
            name = self.modnames[module - 1]
            hit = self._dll_entry(name, target)
            if hit:
                return hit
        return super()._import_stub(fl, module, target)

    def _dll_entry(self, name, ordinal):
        if name not in self.dlls or ordinal not in self.dlls[name][0]:
            return None
        self._ensure_dll(name)
        seg, offset = self.dlls[name][0][ordinal]
        sel = self.dll_segs.get((name, seg))
        if sel is None:
            return None
        self.dll_calls.append((name, ordinal, sel, offset))
        return offset, sel

    def _ensure_dll(self, name):
        if name in self.dll_ready or name in self.dll_busy:
            return
        self.dll_busy.add(name)
        self._alloc_dll(name)
        self._reloc_dll(name)
        self._patch_entries(name)
        self.dll_ready.add(name)

    def _alloc_dll(self, name):
        data = self.dlls[name][1]
        ne = struct.unpack_from("<H", data, 0x3C)[0]
        nseg = struct.unpack_from("<H", data, ne + 0x1C)[0]
        segoff = struct.unpack_from("<H", data, ne + 0x22)[0]
        shift = struct.unpack_from("<H", data, ne + 0x32)[0]
        auto = struct.unpack_from("<H", data, ne + 0x0E)[0]
        heap = struct.unpack_from("<H", data, ne + 0x10)[0]
        for i in range(nseg):
            off, size, flags, alloc = struct.unpack_from("<HHHH", data, ne + segoff + i * 8)
            raw = data[(off << shift):(off << shift) + size]
            mem = 0x10000 if alloc == 0 else alloc
            if i + 1 == auto and heap:
                mem = min(0x10000, mem + heap)
            mem = max(mem, len(raw), 1)
            blob = bytearray(mem if mem < 0x10000 else 0x10000)
            blob[:len(raw)] = raw[:len(blob)]
            access = 0x92 if flags & 1 else 0x9A
            sel = self.arena.alloc_selector(len(blob), access, bytes(blob))
            self.dll_segs[(name, i + 1)] = sel
        self.dll_group[name] = self.dll_segs.get((name, auto), 0)
        handle = self._index_module(self.dll_group[name], data, name)
        if handle:
            procs, ords = self._export_procs(name, data)
            self.mods[handle]["procs"] = procs
            self.mods[handle]["ords"] = ords

    def _reloc_dll(self, name):
        data = self.dlls[name][1]
        ne = struct.unpack_from("<H", data, 0x3C)[0]
        modnames = modules(data, ne)
        nseg = struct.unpack_from("<H", data, ne + 0x1C)[0]
        segoff = struct.unpack_from("<H", data, ne + 0x22)[0]
        shift = struct.unpack_from("<H", data, ne + 0x32)[0]
        for i in range(nseg):
            off, size, flags, alloc = struct.unpack_from("<HHHH", data, ne + segoff + i * 8)
            if not flags & 0x0100:
                continue
            base = off << shift
            raw = data[base:base + size]
            count = struct.unpack_from("<H", data, base + size)[0]
            sel = self.dll_segs[(name, i + 1)]
            for n in range(count):
                atype, fl, disp, t1, t2 = struct.unpack_from("<BBHHH", data, base + size + 2 + n * 8)
                if (fl & 3) == 3 or fl & 4:
                    continue
                seen = set()
                while disp not in (0, 0xFFFF) and disp not in seen and disp + 2 <= len(raw):
                    seen.add(disp)
                    nxt = struct.unpack_from("<H", raw, disp)[0]
                    self._fix_dll(name, sel, atype, fl, disp, t1, t2, modnames)
                    disp = nxt

    def _fix_dll(self, name, sel, atype, fl, disp, t1, t2, modnames):
        if atype == 2 and not fl & 1:
            self.arena.write(sel, disp, struct.pack("<H", self.dll_segs.get((name, t1), 0)))
            return
        if not fl & 1 or t1 < 1 or t1 > len(modnames):
            return
        mod = modnames[t1 - 1]
        equate = EQUATES.get(mod, {}).get(t2)
        if equate is not None and atype == 5:
            self.arena.write(sel, disp, struct.pack("<H", equate))
            return
        if mod in self.dlls and t2 in self.dlls[mod][0]:
            hit = self._dll_entry(mod, t2)
            if not hit:
                return
            if atype == 3:
                self.arena.write(sel, disp, struct.pack("<HH", hit[0], hit[1]))
            elif atype == 5:
                self.arena.write(sel, disp, struct.pack("<H", hit[0]))
            elif atype == 2:
                self.arena.write(sel, disp, struct.pack("<H", hit[1]))
            return
        stub = (t2 * 8) & 0xFFF
        if atype == 3:
            self.arena.write(sel, disp, struct.pack("<HH", stub, self.thunk))
            pop = POP.get(mod, {}).get(t2)
            if pop is not None and disp >= 1 and self.arena.read(sel, disp - 1, 1) == b"\x9a":
                self.sites[(sel, (disp + 4) & 0xFFFF)] = (mod, t2, pop)
        elif atype == 5:
            self.arena.write(sel, disp, struct.pack("<H", stub))

    def _patch_entries(self, name):
        dgroup = self.dll_group.get(name, 0)
        if not dgroup:
            return
        for seg, offset in self.dlls[name][0].values():
            self._patch_prologue(name, seg, offset, dgroup)
        # The NE entry is not in the export table. Windows still rewrites
        # its mov ax,ds prologue, then calls it with a foreign DS.
        data = self.dlls[name][1]
        ne = struct.unpack_from("<H", data, 0x3C)[0]
        ip, seg = struct.unpack_from("<HH", data, ne + 0x14)
        self._patch_prologue(name, seg, ip, dgroup)

    def _patch_prologue(self, name, seg, offset, dgroup):
        sel = self.dll_segs.get((name, seg))
        if sel is None or offset + 3 > self.arena.segs[sel]["size"]:
            return
        if self.arena.read(sel, offset, 3) in (b"\x8c\xd8\x90", b"\xb8\xff\xff"):
            self.arena.write(sel, offset, struct.pack("<BH", 0xB8, dgroup))

    def _bind(self, sel, atype, fl, disp, t1, t2):
        info = self.arena.segs[sel]
        seen = set()
        while disp not in (0, 0xFFFF) and disp not in seen and disp + (4 if atype == 3 else 2) <= info["size"]:
            seen.add(disp)
            nxt = int.from_bytes(self.arena.read(sel, disp, 2), "little")
            stub = self._import_stub(fl, t1, t2)
            if atype == 2 and not fl & 1:
                self.arena.write(sel, disp, struct.pack("<H", self.segs.get(t1, 0)))
            elif atype == 2 and fl & 1:
                target = stub[1] if isinstance(stub, tuple) else self.thunk
                self.arena.write(sel, disp, struct.pack("<H", target))
            elif atype == 3 and stub is not None:
                if isinstance(stub, tuple):
                    packed = struct.pack("<HH", stub[0], stub[1])
                else:
                    packed = struct.pack("<HH", stub, self.thunk)
                    self._note_call(sel, disp, fl, t1, t2)
                self.arena.write(sel, disp, packed)
            elif atype == 5 and stub is not None:
                name = self.modnames[t1 - 1] if fl & 1 and 1 <= t1 <= len(self.modnames) else ""
                equate = EQUATES.get(name, {}).get(t2)
                off = equate if equate is not None else (stub[0] if isinstance(stub, tuple) else stub)
                self.arena.write(sel, disp, struct.pack("<H", off))
            disp = nxt


    def run(self):
        self.build()
        tail = (" " + os.path.basename(self.book)).encode("ascii") + b"\r"
        psp = bytearray(0x100)
        psp[0x80] = len(tail) - 1
        psp[0x81:0x81 + len(tail)] = tail
        self.psp = self.arena.alloc_selector(0x100, 0x92, bytes(psp))
        dgroup = self.segs[139]
        code = self.segs[2]
        gdtr_at = 0xF0E0
        self.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
        self.uc.mem_write(0xF020, self._startup(dgroup, code))
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, self.flat & 0xFF, (self.flat >> 8) & 0xFF,
        ]))
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        self.fault = ""
        try:
            self.uc.emu_start(0xF000, 0, timeout=30_000_000, count=4_000_000)
        except UcError as exc:
            if not self.fault:
                self.fault = str(exc)
        else:
            if not self.fault:
                self.fault = "returned"
        return self.last

    def _startup(self, stack, code):
        """Set the EXE stack, call each DLL entry, then jump to the EXE."""
        blob = bytearray([
            0xB8, stack & 0xFF, (stack >> 8) & 0xFF, 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, self.stack_top & 0xFF, (self.stack_top >> 8) & 0xFF,
        ])
        for name in INIT_ORDER:
            if name not in self.dll_ready:
                continue
            data = self.dlls[name][1]
            ne = struct.unpack_from("<H", data, 0x3C)[0]
            ip, seg = struct.unpack_from("<HH", data, ne + 0x14)
            if not seg or (name, seg) not in self.dll_segs:
                continue
            sel = self.dll_segs[(name, seg)]
            dgroup = self.dll_group.get(name, 0)
            heap = struct.unpack_from("<H", data, ne + 0x10)[0]
            blob += bytes([
                0xBF, dgroup & 0xFF, (dgroup >> 8) & 0xFF,
                0xB9, heap & 0xFF, (heap >> 8) & 0xFF,
                0x33, 0xDB,
                0x33, 0xF6,
                0x9A, ip & 0xFF, (ip >> 8) & 0xFF, sel & 0xFF, (sel >> 8) & 0xFF,
            ])
        blob += bytes([0xEA, 0x5A, 0x03, code & 0xFF, (code >> 8) & 0xFF])
        return bytes(blob)



def main():
    host = Pass06(os.path.join(UNPACKED, "TB80RTM.EXE"), "/workspace/artifacts/courses/9e954d01.tbk")
    cs, ip, raw = host.run()
    used = sorted(set(host.dll_calls))
    print(f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}")
    print(f"opens: {host.opens or 'none'}")
    print(f"dll entries bound {len(used)}")
    out = os.path.join(os.path.dirname(__file__), "..", "nehost", "rtm - pass 06")
    out = os.path.normpath(out)
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "PASS06.txt"), "w").write(
        f"book /workspace/artifacts/courses/9e954d01.tbk\n"
        f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}\n"
        f"opens {host.opens}\n"
        f"dll entries bound {len(used)}\n"
        f"skipped {host.skipped[:12]}\n"
        f"calls {host.calls[:24]}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
