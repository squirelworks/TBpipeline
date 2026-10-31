"""Run the linked sandbox. A gate is a far call into Windows."""

import struct
import time
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (
    UC_X86_INS_OUT,
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CS, UC_X86_REG_CX, UC_X86_REG_DI, UC_X86_REG_DS,
    UC_X86_REG_BP, UC_X86_REG_DX, UC_X86_REG_ES, UC_X86_REG_FPCW, UC_X86_REG_FPSW, UC_X86_REG_FPTAG, UC_X86_REG_IP, UC_X86_REG_SI, UC_X86_REG_SP, UC_X86_REG_SS,
)

REGISTERS = {
    "ax": UC_X86_REG_AX, "bx": UC_X86_REG_BX, "cx": UC_X86_REG_CX, "dx": UC_X86_REG_DX,
    "si": UC_X86_REG_SI, "di": UC_X86_REG_DI, "sp": UC_X86_REG_SP,
    "ds": UC_X86_REG_DS, "es": UC_X86_REG_ES, "ss": UC_X86_REG_SS,
    "fpcw": UC_X86_REG_FPCW, "fpsw": UC_X86_REG_FPSW, "fptag": UC_X86_REG_FPTAG,
}

from .image import Sandbox
from .wine import SYSTEM
from .ne import Segment


# The cap stays. A run that ends on it says so.
TIMEOUT_US = 15_000_000

# PDB16 in Wine include/wine/winbase16.h, filled as task.c TASK_Create does.
PSP_SIZE = 0x110
# Fields Wine fills that neww has nothing for. A read of one stops the run.
PSP_UNFILLED = (
    (0x05, 0x0A, "dispatcher at 0x05, Wine's far call to KERNEL.DOS3Call"),
)

# Wine task.c GetDOSEnvironment16: the host's environment strings, a 0, WORD 1, then this name.
# neww copies no host environment, so the strings are none: one 0 ends the empty list.
ENV_PROGRAM_NAME = b"C:\\WINDOWS\\SYSTEM\\KRNL386.EXE\x00"


def _descriptor(base, limit, access):
    raw = bytearray(8)
    raw[0] = limit & 0xFF
    raw[1] = (limit >> 8) & 0xFF
    raw[2] = base & 0xFF
    raw[3] = (base >> 8) & 0xFF
    raw[4] = (base >> 16) & 0xFF
    raw[5] = access & 0xFF
    raw[6] = (limit >> 16) & 0x0F
    raw[7] = (base >> 24) & 0xFF
    return bytes(raw)


class Args:
    def __init__(self, machine):
        self.machine = machine

    def __call__(self, n):
        uc = self.machine.uc
        sp = uc.reg_read(UC_X86_REG_SP)
        ss = uc.reg_read(UC_X86_REG_SS)
        return self.machine.word(ss, sp + 4 + n * 2)

    def string(self, n):
        return self.machine.string(self(n + 1), self(n))

    def regs(self, name):
        # A register contract's stub leaves DX alone. Other stubs load the ordinal into DX.
        return self.machine.uc.reg_read(REGISTERS[name])

    def word(self, sel, offset):
        return self.machine.word(sel, offset)


class Machine:
    def __init__(self, root, book=None):
        self.box = Sandbox(root).load()
        self.box.wine.book = Path(book) if book else None
        self.uc = None
        self.stop = ""
        self.calls = 0
        self.trampoline = None
        self.pending = None

    def _read(self, seg, offset, size):
        # Once the CPU runs, the guest's memory is the truth, not the loaded image.
        if self.uc is not None:
            return bytes(self.uc.mem_read(seg.base + offset, size))
        return bytes(seg.data[offset:offset + size])

    def word(self, sel, offset):
        seg = self.box.selectors.get(sel)
        if seg is None or offset + 2 > len(seg.data):
            return 0
        return struct.unpack("<H", self._read(seg, offset, 2))[0]

    def string(self, sel, offset):
        seg = self.box.selectors.get(sel)
        if seg is None or offset >= len(seg.data):
            return ""
        raw = self._read(seg, offset, min(128, len(seg.data) - offset))
        return raw.split(b"\x00", 1)[0].decode("latin1", "replace")

    def run(self, limit=1_000_000):
        exe = self.box.exe
        if exe is None:
            self.stop = "no executable"
            return self
        for image in [exe] + [img for img in self.box.images.values() if img is not exe]:
            if image.packed:
                # An iterated segment loads as zeros here. Running it executes empty memory.
                self.stop = (
                    f"packed image {Path(image.path).name}: {len(image.packed)} of {len(image.segments)} "
                    f"segments have the iterated flag, first is segment {image.packed[0]}. "
                    "neww does not unpack. --b must hold the unpacked images"
                )
                return self
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        flat = self._selector(0, 0xFFFF, 0x9A)
        for seg in self.box.selectors.values():
            size = (max(len(seg.data), 1) + 0xFFF) & ~0xFFF
            self.uc.mem_map(seg.base, size)
            self.uc.mem_write(seg.base, bytes(seg.data))
            access = 0x92 if seg.flags & 1 else 0x9A
            limit_b = 0xFFFF if len(seg.data) >= 0x10000 else max(len(seg.data) - 1, 0)
            self.uc.mem_write(seg.selector, _descriptor(seg.base, limit_b, access))
        self.box.wine.allocate = self._allocate
        self.box.wine.size = self._size
        self.box.wine.owner = self._owner
        self.box.wine.write = self._write_guest
        self.uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        code = exe.segments[exe.entry_seg - 1]
        data = exe.segments[exe.auto - 1]
        psp = self._psp()
        self._modules()
        # Wine ne_module.c NE_StartTask: the handle of a moveable DGROUP is selector - 1.
        instance = data.selector - 1 if data.flags & 0x0010 else data.selector
        names, rows, why = self._dlls_to_init()
        self.box.wine.task = {
            "psp": psp, "instance": instance, "dgroup": data.selector,
            "dlls": names, "dll_init": rows, "dll_stop": why,
        }
        self.trampoline = self._trampoline(rows) if rows else None
        self.pending = None
        gdtr_at = 0xF0E0
        self.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, flat & 0xFF, (flat >> 8) & 0xFF,
        ]))
        # Wine ne_module.c NE_StartTask: SP is the header's, or the stack segment's
        # minsize plus the NE stack size, made even. The stack sits below the local heap.
        sp = exe.sssp & 0xFFFF
        if not sp:
            ss_seg = exe.segments[(exe.sssp >> 16) - 1] if exe.sssp >> 16 else data
            sp = ss_seg.minsize + exe.stack
        sp &= ~1
        if not 0 < sp <= len(data.data):
            self.stop = f"stack top {sp:#x} is outside DGROUP ({len(data.data):#x} bytes)"
            return self

        def word(value):
            return [value & 0xFF, (value >> 8) & 0xFF]

        # Registers at entry are NE_StartTask's: AX 0, BX stack size, CX heap size,
        # SI previous instance (none), DI this instance, BP 0, ES the PSP, DS and SS DGROUP.
        blob = bytes([
            0xB8, *word(data.selector), 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, *word(sp),
            0xB8, *word(psp), 0x8E, 0xC0,
            0xBB, *word(exe.stack), 0xB9, *word(exe.heap),
            0x31, 0xF6, 0xBF, *word(instance), 0x31, 0xED, 0x31, 0xC0,
            0xEA, exe.entry_ip & 0xFF, (exe.entry_ip >> 8) & 0xFF,
            code.selector & 0xFF, (code.selector >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF020, blob)
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        started = time.monotonic()
        try:
            self.uc.emu_start(0xF000, 0, timeout=TIMEOUT_US, count=limit)
        except UcError as exc:
            if not self.stop:
                self.stop = f"{exc} {self.where()}"
        else:
            if not self.stop:
                # There is no address to return to, so a quiet end is a cap.
                cs = self.uc.reg_read(UC_X86_REG_CS)
                ip = self.uc.reg_read(UC_X86_REG_IP)
                if time.monotonic() - started >= TIMEOUT_US / 1e6:
                    cap = f"{TIMEOUT_US // 1_000_000} second cap"
                else:
                    cap = f"instruction cap {limit:,}"
                self.stop = f"{cap} {self.where()} with no gate call pending, after {self.calls} calls"
        return self

    def where(self, cs=None, ip=None):
        """CS:IP, then the module, segment, and nearest export at or below it."""
        if cs is None:
            cs = self.uc.reg_read(UC_X86_REG_CS)
            ip = self.uc.reg_read(UC_X86_REG_IP)
        text = f"at {cs:#x}:{ip:#x}"
        seg = self.box.selectors.get(cs)
        for image in self.box.images.values():
            if image.synthetic or seg not in image.segments:
                continue
            text += f" in {image.name} segment {seg.index} +{ip:#x}"
            best = None
            for ordinal, ent in image.entries.items():
                if ent.segment == seg.index and ent.offset <= ip and (best is None or ent.offset > best[1].offset):
                    best = (ordinal, ent)
            if best:
                ordinal, ent = best
                name = image.names.get(ordinal, f"@{ordinal}")
                text += f", {name}+{ip - ent.offset:#x} (ordinal {ordinal})"
            break
        else:
            if seg is self.box.trap:
                text += " in the trap segment"
        return text

    def _write_guest(self, sel, offset, data):
        seg = self.box.selectors.get(sel)
        if seg is None or offset + len(data) > len(seg.data):
            return
        self.uc.mem_write(seg.base + offset, data)

    def _owner(self, sel):
        """The NE file a selector's block belongs to, as GetExePtr finds a module from a handle.

        A segment of the file, or its module handle.
        """
        for image in self.box.images.values():
            if image.synthetic:
                continue
            if any(seg.selector == sel for seg in image.segments) or self.box.wine.modules.get(image.name) == sel:
                return image.path
        return None

    def _modules(self):
        """A module handle per NE file, in Wine's load order: the executable, then each DLL as loaded.

        Wine's handle is the selector of the NE_MODULE block build_module makes. neww makes
        the block but not its contents, so a guest read of it stops.
        """
        order = [self.box.exe]
        seen = set()

        def walk(image):
            for name in image.modules:
                dll = self.box.images.get(name)
                if dll is None or dll.synthetic or dll is self.box.exe or name in seen:
                    continue
                seen.add(name)
                order.append(dll)
                walk(dll)

        walk(self.box.exe)
        for image in order:
            sel = self._allocate(0x60)
            self.box.wine.modules[image.name] = sel
            base = self.box.selectors[sel].base
            self.uc.hook_add(UC_HOOK_MEM_READ, self._module_read, (image.name, base), base, base + 0x5F)
        # NE_RegisterModule puts each new module at the head of the list.
        self.box.wine.first_module = self.box.wine.modules[order[-1].name]

    def _size(self, sel):
        """GlobalSize16 of the block behind a selector."""
        seg = self.box.selectors.get(sel)
        return len(seg.data) if seg is not None else None

    def _allocate(self, size):
        """Map size bytes behind consecutive data selectors, 64K apart in linear memory.

        Returns the first selector. Selector i covers base + i * 0x10000, the
        __AHINCR tiling Wine's SELECTOR_AllocBlock gives a block over 64K.
        """
        span = (size + 0xFFF) & ~0xFFF
        base = self.box.linear
        self.box.linear += span
        self.uc.mem_map(base, span)
        first = None
        for i in range((size + 0xFFFF) // 0x10000):
            left = size - i * 0x10000
            seg = Segment(0, 1, bytearray(min(left, 0x10000)))
            sel = self.box._selector()
            seg.selector = sel
            seg.base = base + i * 0x10000
            self.box.selectors[sel] = seg
            self.uc.mem_write(sel, _descriptor(seg.base, left - 1, 0x92))
            first = sel if first is None else first
        return first

    def _dlls_to_init(self):
        """ToolBook DLLs the executable loads, with init code, in Wine NE_InitializeDLLs order.

        Returns (names, rows, stop). A row is (name, cs, ip, ds, heap, instance), the
        registers ne_segment.c NE_InitDLL and NE_GetDLLInitParams give LibMain.
        """
        names, seen = [], set()

        def walk(image):
            for name in image.modules:
                dll = self.box.images.get(name)
                # System modules are gates, not DLLs neww loaded.
                if dll is None or dll is self.box.exe or name in seen or name in SYSTEM or dll.synthetic:
                    continue
                seen.add(name)
                walk(dll)
                # NE_InitDLL: only a library with an entry point is called.
                if dll.entry_seg and dll.flags & 0x8000:
                    names.append(name)

        walk(self.box.exe)
        rows = []
        for name in names:
            dll = self.box.images[name]
            if not (dll.flags & 0x0001 and dll.auto):
                return names, [], (
                    f"KERNEL.91 InitTask: {name} has no SINGLEDATA DGROUP, so Wine NE_GetDLLInitParams "
                    "passes its module handle in DI. neww has no module handles"
                )
            seg = dll.segments[dll.auto - 1]
            instance = seg.selector - 1 if seg.flags & 0x0010 else seg.selector
            code = dll.segments[dll.entry_seg - 1]
            rows.append((name, code.selector, dll.entry_ip, seg.selector, dll.heap, instance))
        return names, rows, None

    def _trampoline(self, rows):
        """Code that calls each LibMain with Wine NE_InitDLL's registers, then OUT 0xE6.

        CX heap, DI instance, DS = ES = the DLL's DGROUP, the rest 0. Wine points BP at
        the saved BP in its relay frame. Here BP points at the caller's BP, pushed.
        """
        code = bytearray()
        for _name, cs, ip, ds, heap, instance in rows:
            code += bytes([0xB9, heap & 0xFF, heap >> 8, 0xBF, instance & 0xFF, instance >> 8])
            code += bytes([0xB8, ds & 0xFF, ds >> 8, 0x8E, 0xD8, 0x8E, 0xC0])
            code += bytes([0x31, 0xC0, 0x31, 0xDB, 0x31, 0xD2, 0x31, 0xF6])
            code += bytes([0x55, 0x89, 0xE5, 0x9A, ip & 0xFF, ip >> 8, cs & 0xFF, cs >> 8, 0x5D])
        # OUT 0xE6, then pop es ; pop ds ; retf from the frame _dlls_done builds.
        code += bytes([0xE6, 0xE6, 0x07, 0x1F, 0xCB])
        base = self.box.linear
        self.box.linear += 0x1000
        self.uc.mem_map(base, 0x1000)
        self.uc.mem_write(base, bytes(code))
        return self._selector(base, len(code) - 1, 0x9A)

    def _dlls_done(self, uc):
        """OUT 0xE6: every LibMain returned. Answer InitTask and return to its caller."""
        saved = self.pending
        self.pending = None
        if saved is None:
            self.stop = f"out 0xe6 with no InitTask pending {self.where()}"
            uc.emu_stop()
            return
        if uc.reg_read(UC_X86_REG_SS) != saved["ss"]:
            self.stop = f"LibMain returned on another stack segment {self.where()}"
            uc.emu_stop()
            return
        ax, dx, _why = self.box.wine.init_task_answer(self.word)
        registers = dict(self.box.wine.registers)
        registers.pop("push")
        es = registers.pop("es")
        uc.reg_write(UC_X86_REG_AX, ax)
        uc.reg_write(UC_X86_REG_DX, dx)
        for name, value in registers.items():
            uc.reg_write(REGISTERS[name], value & 0xFFFF)
        uc.reg_write(UC_X86_REG_BP, saved["bp"])
        # The guest pops ES and the caller's DS, then the retf returns to the caller with
        # one zero word pushed, as InitTask16's stack16_push leaves it.
        sp = saved["sp"]
        frame = struct.pack("<HH", es, saved["ds"]) + saved["ret"] + b"\x00\x00"
        self._write_guest(saved["ss"], sp - 6, frame)
        uc.reg_write(UC_X86_REG_SP, sp - 6)

    def _psp(self):
        """The task's PDB16, as Wine task.c TASK_Create fills it. Returns its selector."""
        sel = self._allocate(PSP_SIZE)
        pdb = bytearray(PSP_SIZE)
        struct.pack_into("<H", pdb, 0x00, 0x20CD)
        pdb[0x18:0x2C] = b"\xFF" * 20
        struct.pack_into("<H", pdb, 0x32, 20)
        struct.pack_into("<HH", pdb, 0x34, 0x18, sel)
        # TASK_Create: environment = SELECTOROF(GetDOSEnvironment16()).
        struct.pack_into("<H", pdb, 0x2C, self._environment())
        # The command line is what follows the program name: the book from --c, by name.
        book = self.box.wine.book
        line = book.name.encode("latin1", "replace")[:127] if book else b""
        pdb[0x80] = len(line)
        pdb[0x81:0x81 + len(line)] = line
        self._write_guest(sel, 0, bytes(pdb))
        base = self.box.selectors[sel].base
        for start, end, _what in PSP_UNFILLED:
            self.uc.hook_add(UC_HOOK_MEM_READ, self._psp_read, (base, start, end), base + start, base + end - 1)
        return sel

    def _environment(self):
        """The DOS environment block, a GMEM_FIXED block whose handle is its selector."""
        if self.box.wine.environment is None:
            block = b"\x00" + struct.pack("<H", 1) + ENV_PROGRAM_NAME
            sel = self._allocate((len(block) + 0x1F) & ~0x1F)
            self._write_guest(sel, 0, block)
            self.box.wine.environment = sel
        return self.box.wine.environment

    def _module_read(self, uc, access, address, size, value, user):
        name, base = user
        if self.stop:
            return
        self.stop = (
            f"module database of {name} read at +{address - base:#x} {self.where()}: "
            "Wine's NE_MODULE block is built by build_module, and neww has only the handle"
        )
        uc.emu_stop()

    def _psp_read(self, uc, access, address, size, value, user):
        base, start, end = user
        if self.stop or not (base + start <= address < base + end):
            return
        what = next(text for s, e, text in PSP_UNFILLED if s == start)
        self.stop = f"PSP {what}, read {self.where()}: neww has nothing to put there"
        uc.emu_stop()

    def _selector(self, base, limit, access):
        sel = self.box._selector()
        self.uc.mem_write(sel, _descriptor(base, limit, access))
        return sel

    def _out(self, uc, port, size, value, user):
        if port == 0xE6:
            self._dlls_done(uc)
            return
        if port == 0xE5:
            slot = uc.reg_read(UC_X86_REG_DX)
            traps = self.box.traps
            text = traps[slot] if slot < len(traps) else f"trap {slot}"
            self.stop = f"not linked: {text}. A ToolBook call with no target is a stop, not a gate"
            uc.emu_stop()
            return
        if port not in (0xE4, 0xE7):
            return
        cs = uc.reg_read(UC_X86_REG_CS)
        if port == 0xE7:
            # A register contract's stub: the OUT is the stub's first instruction.
            ordinal = uc.reg_read(UC_X86_REG_IP) // 8
        else:
            ordinal = uc.reg_read(UC_X86_REG_DX)
        module = self.box.gates.get((cs, ordinal))
        if module is None:
            self.stop = f"out {cs:#x} dx={ordinal:#x}"
            uc.emu_stop()
            return
        self.calls += 1
        self.box.wine.registers = None
        ax, dx, why = self.box.wine.answer(module, ordinal, Args(self))
        if self.box.wine.usable(module, ordinal) is None:
            # No usable contract: stop on the OUT. Nothing is popped, AX and DX keep the guest's values.
            self.stop = why
            uc.emu_stop()
            return
        if why:
            # A stop answers nothing. The guest's registers stay as the call left them.
            self.stop = why
            uc.emu_stop()
            return
        uc.reg_write(UC_X86_REG_AX, ax & 0xFFFF)
        registers = dict(self.box.wine.registers or {})
        slot = self.box.slots.get((module, ordinal))
        if slot is None:
            uc.reg_write(UC_X86_REG_DX, dx & 0xFFFF)
        if slot is not None:
            # A register contract sets DX only when it names it.
            # The stub's tail loads ES and DS from these words. Unchanged unless the contract sets them.
            es = registers.pop("es", uc.reg_read(UC_X86_REG_ES))
            ds = registers.pop("ds", uc.reg_read(UC_X86_REG_DS))
            self._write_guest(cs, slot, struct.pack("<HH", es, ds))
        if "init_dlls" in registers:
            # The gate's retf goes to the trampoline instead of the caller.
            ss = uc.reg_read(UC_X86_REG_SS)
            sp = uc.reg_read(UC_X86_REG_SP)
            self.pending = {
                "ss": ss, "sp": sp, "ds": uc.reg_read(UC_X86_REG_DS), "bp": uc.reg_read(UC_X86_REG_BP),
                "ret": self._read(self.box.selectors[ss], sp, 4),
            }
            self._write_guest(ss, sp, struct.pack("<HH", 0, self.trampoline))
            registers = {}
        for name, value in registers.items():
            if name != "push":
                uc.reg_write(REGISTERS[name], value & 0xFFFF)
        if "push" in registers:
            # A word under the return address: after the retf, SS:SP points at it.
            ss = uc.reg_read(UC_X86_REG_SS)
            sp = uc.reg_read(UC_X86_REG_SP)
            ret = self._read(self.box.selectors[ss], sp, 4)
            self._write_guest(ss, sp - 2, ret + struct.pack("<H", registers["push"]))
            uc.reg_write(UC_X86_REG_SP, sp - 2)
        if self.calls > 400:
            self.stop = "call limit"
            uc.emu_stop()

    def _unmapped(self, uc, access, address, size, value, user):
        self.stop = f"unmapped {address:#x}"
        return False
