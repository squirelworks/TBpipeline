"""Run the linked sandbox. A gate is a far call into Windows."""

import struct
import time
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (
    UC_X86_INS_OUT,
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_IP,
    UC_X86_REG_SP, UC_X86_REG_SS,
)

from .image import Sandbox
from .ne import Segment


# The cap stays. A run that ends on it says so.
TIMEOUT_US = 15_000_000

# PDB16 in Wine include/wine/winbase16.h, filled as task.c TASK_Create does.
PSP_SIZE = 0x110
# Fields Wine fills that neww has nothing for. A read of one stops the run.
PSP_UNFILLED = (
    (0x05, 0x0A, "dispatcher at 0x05, Wine's far call to KERNEL.DOS3Call"),
    (0x2C, 0x2E, "environment at 0x2C, Wine's GetDOSEnvironment16 selector"),
)


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
        if name == "ax":
            return self.machine.uc.reg_read(UC_X86_REG_AX)
        return 0


class Machine:
    def __init__(self, root, book=None):
        self.box = Sandbox(root).load()
        self.box.wine.book = Path(book) if book else None
        self.uc = None
        self.stop = ""
        self.calls = 0

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
        self.box.wine.write = self._write_guest
        self.uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        code = exe.segments[exe.entry_seg - 1]
        data = exe.segments[exe.auto - 1]
        psp = self._psp()
        # Wine ne_module.c NE_StartTask: the handle of a moveable DGROUP is selector - 1.
        instance = data.selector - 1 if data.flags & 0x0010 else data.selector
        gdtr_at = 0xF0E0
        self.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, flat & 0xFF, (flat >> 8) & 0xFF,
        ]))
        sp = len(data.data) - 2

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

    def _psp(self):
        """The task's PDB16, as Wine task.c TASK_Create fills it. Returns its selector."""
        sel = self._allocate(PSP_SIZE)
        pdb = bytearray(PSP_SIZE)
        struct.pack_into("<H", pdb, 0x00, 0x20CD)
        pdb[0x18:0x2C] = b"\xFF" * 20
        struct.pack_into("<H", pdb, 0x32, 20)
        struct.pack_into("<HH", pdb, 0x34, 0x18, sel)
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
        if port == 0xE5:
            slot = uc.reg_read(UC_X86_REG_DX)
            traps = self.box.traps
            text = traps[slot] if slot < len(traps) else f"trap {slot}"
            self.stop = f"not linked: {text}. A ToolBook call with no target is a stop, not a gate"
            uc.emu_stop()
            return
        if port != 0xE4:
            return
        cs = uc.reg_read(UC_X86_REG_CS)
        ordinal = uc.reg_read(UC_X86_REG_DX)
        module = self.box.gates.get((cs, ordinal))
        if module is None:
            self.stop = f"out {cs:#x} dx={ordinal:#x}"
            uc.emu_stop()
            return
        self.calls += 1
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
        uc.reg_write(UC_X86_REG_DX, dx & 0xFFFF)
        if self.calls > 400:
            self.stop = "call limit"
            uc.emu_stop()

    def _unmapped(self, uc, access, address, size, value, user):
        self.stop = f"unmapped {address:#x}"
        return False
