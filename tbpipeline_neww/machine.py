"""Run the linked sandbox. A gate is a far call into Windows."""

import struct

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (
    UC_X86_INS_OUT,
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_IP,
    UC_X86_REG_SP, UC_X86_REG_SS,
)

from .image import Sandbox


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
    def __init__(self, root):
        self.box = Sandbox(root).load()
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
        self.uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        code = exe.segments[exe.entry_seg - 1]
        data = exe.segments[exe.auto - 1]
        gdtr_at = 0xF0E0
        self.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, flat & 0xFF, (flat >> 8) & 0xFF,
        ]))
        sp = len(data.data) - 2
        blob = bytes([
            0xB8, data.selector & 0xFF, (data.selector >> 8) & 0xFF, 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, sp & 0xFF, (sp >> 8) & 0xFF,
            0xEA, exe.entry_ip & 0xFF, (exe.entry_ip >> 8) & 0xFF,
            code.selector & 0xFF, (code.selector >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF020, blob)
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        try:
            self.uc.emu_start(0xF000, 0, timeout=15_000_000, count=limit)
        except UcError as exc:
            if not self.stop:
                self.stop = str(exc)
        else:
            if not self.stop:
                self.stop = "returned"
        return self

    def _selector(self, base, limit, access):
        sel = self.box._selector()
        self.uc.mem_write(sel, _descriptor(base, limit, access))
        return sel

    def _out(self, uc, port, size, value, user):
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
