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
import time

from tbpipeline_bf.binpath import unpacked
from tbpipeline_bf.nehost.pass04 import Pass04, API_PORT, INITTASK, last_call_line
from tbpipeline_bf.nehost.win16stack import POP
from .bind import DLLS, export_names, exports, modules, segment_bytes
from .win32 import Win32
from .windows import Windows

from unicorn import UcError
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_SP, UC_X86_REG_IP, UC_X86_REG_EIP,
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

UNPACKED = str(unpacked())

# A Win16 task gives the CPU away on these when its queue is empty.
# WinExec returns to its caller only once the new task reaches one of them.
YIELDS = {("USER", 108), ("USER", 109), ("USER", 112), ("KERNEL", 29)}


# One run's budget, shared by every slice of it.
COUNT = 4_000_000      # instructions per slice
TIMEOUT = 30_000_000   # microseconds, for the whole run


class Pass06(Windows, Win32, Pass04):
    # Set by run and _run_tasks. The first task is the runtime. Unset, WinExec
    # of a missing file stays the wall instead of starting a task.
    tasks = None
    task = None
    task_log = None
    switch = None
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
        system = self._system_module(name)
        if system:
            return system
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
            if disp >= 1 and self.arena.read(sel, disp - 1, 1) == b"\x9a":
                self.callers[(sel, (disp + 4) & 0xFFFF)] = (mod, t2)
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

    def _kernel_proc(self, ordinal):
        # WinExec. An EXE in the unpacked directory is a second task in this
        # CPU. The caller gets its instance once that task yields. A missing
        # EXE falls through to the wall, which stops and quotes the command.
        if ordinal == 166 and self._win_exec():
            return True
        return super()._kernel_proc(ordinal)

    def _win_exec(self):
        cmd = self._string(self._word(2), self._word(1))
        show = self._word(0)
        name, _, tail = cmd.strip().partition(" ")
        path = self._task_file(name)
        tasks = self.tasks
        if not path or not tasks or any(t["file"] == os.path.basename(path).upper() for t in tasks):
            return False
        task = self._load_task(path, tail, show)
        tasks.append(task)
        if self.task_log is not None:
            self.task_log.append(f"winexec {cmd!r} started {task['name']} instance {task['inst']:#x}")
        self.uc.reg_write(UC_X86_REG_AX, task["inst"])
        self.uc.reg_write(UC_X86_REG_DX, 0)
        self.switch = task
        self.uc.emu_stop()
        return True

    def _task_file(self, name):
        name = name.rsplit("\\", 1)[-1].upper()
        if "." not in name:
            name += ".EXE"
        try:
            listing = os.listdir(UNPACKED)
        except OSError:
            return None
        hit = next((f for f in listing if f.upper() == name), None)
        return os.path.join(UNPACKED, hit) if hit else None

    def _load_task(self, path, tail, show):
        """Map an NE EXE beside the runtime and bind its imports.

        Pass04's loader reads the image from self.file, so it is swapped in
        for the reloc pass. Imports into the ToolBook DLLs bind to the copies
        already loaded, which is what makes the two tasks share TB80BAS.
        """
        with open(path, "rb") as fh:
            data = fh.read()
        ne = struct.unpack_from("<H", data, 0x3C)[0]
        nseg = struct.unpack_from("<H", data, ne + 0x1C)[0]
        segoff = struct.unpack_from("<H", data, ne + 0x22)[0]
        shift = struct.unpack_from("<H", data, ne + 0x32)[0]
        auto, heap, stack = struct.unpack_from("<HHH", data, ne + 0x0E)
        ip, cs = struct.unpack_from("<HH", data, ne + 0x14)
        segs, top = {}, 0x4000
        for i in range(nseg):
            off, size, flags, alloc = struct.unpack_from("<HHHH", data, ne + segoff + i * 8)
            alloc = 0x10000 if alloc == 0 else alloc
            if i + 1 == auto:
                alloc = min(0x10000, alloc + heap + stack)
                top = alloc & 0xFFFE
            blob = bytearray(alloc if alloc < 0x10000 else 0x10000)
            raw = data[(off << shift):(off << shift) + size]
            blob[:len(raw)] = raw[:len(blob)]
            access = 0x9A if not (flags & 1) else 0x92
            segs[i + 1] = self.arena.alloc_selector(len(blob), access, bytes(blob))
        saved = (self.file, self.ne, self.nseg, self.shift, self.segoff, self.segs, self.modnames)
        self.file, self.ne, self.nseg, self.shift, self.segoff, self.segs = data, ne, nseg, shift, segoff, segs
        try:
            self._relocs()
        finally:
            self.file, self.ne, self.nseg, self.shift, self.segoff, self.segs, self.modnames = saved
        name = os.path.basename(path).rsplit(".", 1)[0].upper()
        inst = segs[auto]
        self._index_module(inst, data, name)
        procs, ords = self._export_procs_from(data, segs)
        self.mods[inst]["procs"] = procs
        self.mods[inst]["ords"] = ords
        # WinExec hands over the arguments without the program name or the
        # blanks before them, the way Windows builds the new task's tail.
        text = tail.strip().encode("latin1")
        psp = bytearray(0x100)
        psp[0x80] = len(text)
        psp[0x81:0x81 + len(text) + 1] = text + b"\r"
        psp = self.arena.alloc_selector(0x100, 0x92, bytes(psp))
        # InitTask's register contract: BX stack, CX heap, DI instance,
        # SI previous instance, ES the PSP, DS = SS = DGROUP.
        start = bytes([
            0xB8, psp & 0xFF, psp >> 8, 0x8E, 0xC0,
            0xB8, inst & 0xFF, inst >> 8, 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, top & 0xFF, top >> 8,
            0xBB, stack & 0xFF, stack >> 8,
            0xB9, heap & 0xFF, heap >> 8,
            0xBF, inst & 0xFF, inst >> 8,
            0x33, 0xF6,
            0xEA, ip & 0xFF, ip >> 8, segs[cs] & 0xFF, segs[cs] >> 8,
        ])
        return {
            "name": name, "file": os.path.basename(path).upper(), "inst": inst,
            "psp": psp, "show": show, "stack": stack, "ctx": None, "init": False,
            "start": self.arena.alloc_selector(len(start), 0x9A, start),
        }

    def _calling_module(self):
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = self.uc.reg_read(UC_X86_REG_SP)
        ip, cs = struct.unpack("<HH", self.arena.read(ss, sp, 4))
        return self.callers.get((cs, ip), ("?", 0))[0]

    def _answer(self, uc, ordinal):
        task = self.task
        tasks = self.tasks
        if task is None or not tasks or task is tasks[0]:
            return super()._answer(uc, ordinal)
        module = self._calling_module()
        if (module, ordinal) == ("KERNEL", INITTASK) and not task["init"]:
            self._fix_ret(ordinal)
            self.calls.append(ordinal)
            task["init"] = True
            # The same ASCIIZ tail the runtime's InitTask gets.
            line = self.arena.read(task["psp"], 0x81, 0x7F)
            if b"\r" in line:
                self.arena.write(task["psp"], 0x81 + line.index(b"\r"), b"\x00")
            uc.reg_write(UC_X86_REG_AX, 1)
            uc.reg_write(UC_X86_REG_BX, 0x81)
            uc.reg_write(UC_X86_REG_CX, task["stack"])
            uc.reg_write(UC_X86_REG_DX, task["show"])
            uc.reg_write(UC_X86_REG_SI, 0)
            uc.reg_write(UC_X86_REG_DI, task["inst"])
            return
        if (module, ordinal) in YIELDS:
            # The queue is empty, so the task blocks here. Nothing answers
            # the call until a message is delivered to it.
            self._fix_ret(ordinal)
            self.calls.append(ordinal)
            if self.task_log is not None:
                self.task_log.append(f"{task['name']} yielded at {module}.{ordinal}")
            self.switch = tasks[0]
            uc.emu_stop()
            return
        super()._answer(uc, ordinal)

    def _switch(self):
        target, self.switch = self.switch, None
        self.task["ctx"] = self.uc.context_save()
        self.task["exe_inst"] = self.exe_inst
        self.task = target
        self.exe_inst = target.get("exe_inst") or target["inst"]
        if target["ctx"] is not None:
            self.uc.context_restore(target["ctx"])
            return self.uc.reg_read(UC_X86_REG_EIP)
        # A fresh task starts from its own code selector, and its start code
        # loads the segment registers.
        return self._dispatch(target["start"], 0)

    def _dispatch(self, sel, off, ds=0):
        """IP to resume at so that the guest far-jumps to sel:off with DS = ds.

        Segment registers cannot be loaded from the host in protected mode.
        The run stopped inside the thunk or a module stub, so slot 0 of the
        current CS is a far jump to the dispatcher, which loads DS from its
        own data and jumps through its own far pointer. The code never
        changes, only the data, so no translated block goes stale.
        """
        if not getattr(self, "dispatcher", 0):
            code = bytes([
                0x2E, 0xA1, 0x44, 0x00,         # mov ax, cs:[0x44]
                0x8E, 0xD8,                     # mov ds, ax
                0x2E, 0xFF, 0x2E, 0x40, 0x00,   # jmp far cs:[0x40]
            ])
            self.dispatcher = self.arena.alloc_selector(0x80, 0x9A, code.ljust(0x80, b"\x00"))
        cs = self.uc.reg_read(UC_X86_REG_CS)
        if cs != self.thunk and cs not in getattr(self, "stub_module", {}):
            self.fault = f"cannot leave {cs:#x}: stopped outside the thunk"
            return 0
        self.arena.write(self.dispatcher, 0x40, struct.pack("<HHH", off, sel, ds))
        self.arena.write(cs, 0, bytes([0xEA, 0, 0, self.dispatcher & 0xFF, self.dispatcher >> 8]))
        return 0

    def _begin_tasks(self):
        if self.tasks:
            return
        self.tasks = [{"name": "TB80RTM", "file": "TB80RTM.EXE", "inst": self.exe_inst, "ctx": None}]
        self.task = self.tasks[0]
        self.task_log = []
        self.switch = None

    def run(self):
        self.build()
        self._make_psp()
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
        self._begin_tasks()
        self._run_from(0xF000)
        return self.last

    def _run_tasks(self, begin):
        """Run from begin until no task is left to switch to.

        Tests enter here. A real run() uses the same loop.
        """
        self.fault = ""
        self.tasks = None
        self._begin_tasks()
        self._run_from(begin)

    def _run_from(self, begin):
        """Run until a stop. A stop that leaves a jump (entering or leaving
        32-bit code) or a task switch runs on from where that puts CS:IP."""
        self.jump = None
        self.switch = None
        self.spent = 0
        self._slice(begin)
        while not self.fault and (self.jump is not None or self.switch is not None):
            if self.switch is not None:
                ip = self._switch()
            else:
                go, self.jump = self.jump, None
                ip = go()
            if self.fault:
                break
            # Unicorn's 16-bit emu_start takes a real-mode address and sets
            # IP to begin - CS * 16, whatever the descriptor base is.
            self._slice((self.uc.reg_read(UC_X86_REG_CS) << 4) + ip)
        if not self.fault:
            self.fault = "returned"
        elif self.task is not None and self.tasks and self.task is not self.tasks[0]:
            self.fault = f"{self.task['name']}: {self.fault}"

    def _slice(self, begin):
        micros = TIMEOUT - self.spent
        if micros <= 0:
            self.fault = self.fault or "timeout"
            return
        began = time.monotonic()
        try:
            self.uc.emu_start(begin, 0, timeout=micros, count=COUNT)
        except UcError as exc:
            if not self.fault:
                self.fault = str(exc)
        self.spent += int((time.monotonic() - began) * 1_000_000)

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
    from pathlib import Path
    root = Path(UNPACKED)
    book = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    image = root / "TB80RTM.EXE"
    if book is None or not book.is_file() or not image.is_file():
        print("usage: python3 -m tbpipeline_bf.nedllhost.pass06 book.tbk", file=sys.stderr)
        print("TBK_UNPACKED is the directory that holds TB80RTM.EXE", file=sys.stderr)
        return 2
    host = Pass06(str(image), str(book))
    cs, ip, raw = host.run()
    used = sorted(set(host.dll_calls))
    print(f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}")
    print(f"opens: {host.opens or 'none'}")
    print(last_call_line(host.last_call))
    print(f"dll entries bound {len(used)}")
    for line in host.task_log or ():
        print(f"task: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
