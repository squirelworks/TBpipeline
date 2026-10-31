#!/usr/bin/env python3
"""Call TB80BMP ordinal 3, TBKBITMAP, and stop at the first external call.

TBKBITMAP is segment 3 offset 0x3E0. It pushes its two arguments and
calls 0x1FA2. That function's first far call, at 0x1FCD, was the contract
the first version of this probe stopped on with the selector unbound.

The probe now applies TB80BMP's own NE relocations. A far call into
another TB80BMP segment is followed: that segment is loaded and the call
runs. A call to an imported ordinal or name is a gate: the run stops there
and names the module, the ordinal, and the words on the stack. It is not
answered. A return to the probe is the other way out, and the registers
and the object it was handed are printed.

It is a real-mode probe, not a boot. The instruction count stays 2000.

  python3 -m tbpipeline_bf.nehost.bmp_bitmap [--stream picture.bin]

The log of the first run is bmp_bitmap.txt beside this file. That file is
a record and this probe does not rewrite it.
"""

import os
import struct
import sys
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_DX,
    UC_X86_REG_ES, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

HERE = Path(__file__).resolve().parent
DLL = Path(os.environ.get("TBK_UNPACKED") or HERE.parent / "bin") / "TB80BMP.DLL"

ENTRY = 0x3E0
SEG = 3
DGROUP = 27
COUNT = 2000

# Real-mode layout. Segments are loaded from FIRST_PARA up, each on a
# paragraph. The stack and the gates sit above them.
FIRST_PARA = 0x1000
LAST_PARA = 0x8000
STACK_PARA = 0x9000
STACK_TOP = 0x4000
GATE_PARA = 0x9800
RETURN_OFF = 0xFFF

OBJ = 0x3000
STREAM = 0x3200
DATA_MIN = 0x4000


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


class NE:
    """The parts of an NE image this probe reads: segments, relocs, imports."""

    def __init__(self, blob):
        self.blob = blob
        self.ne = _u16(blob, 0x3C)
        self.nseg = _u16(blob, self.ne + 0x1C)
        self.segtab = self.ne + _u16(blob, self.ne + 0x22)
        self.shift = _u16(blob, self.ne + 0x32) or 9
        self.modref = self.ne + _u16(blob, self.ne + 0x28)
        self.imptab = self.ne + _u16(blob, self.ne + 0x2A)
        self.nmod = _u16(blob, self.ne + 0x1E)

    def record(self, index):
        return struct.unpack_from("<HHHH", self.blob, self.segtab + (index - 1) * 8)

    def segment(self, index):
        sec, ln, fl, alloc = self.record(index)
        ln = ln or (0x10000 if sec else 0)
        raw = bytearray(self.blob[(sec << self.shift):(sec << self.shift) + ln])
        return raw, max(alloc, len(raw), 0x10), fl

    def relocs(self, index):
        sec, ln, fl, alloc = self.record(index)
        if not fl & 0x0100 or not sec:
            return []
        at = (sec << self.shift) + (ln or 0x10000)
        count = _u16(self.blob, at)
        return [struct.unpack_from("<BBHHH", self.blob, at + 2 + n * 8) for n in range(count)]

    def module(self, index):
        if index < 1 or index > self.nmod:
            return f"module{index}"
        at = self.imptab + _u16(self.blob, self.modref + 2 * (index - 1))
        return self.blob[at + 1:at + 1 + self.blob[at]].decode("latin1", "replace")

    def import_name(self, offset):
        at = self.imptab + offset
        return self.blob[at + 1:at + 1 + self.blob[at]].decode("latin1", "replace")


class Probe:
    def __init__(self, blob, seg=SEG, entry=ENTRY, dgroup=DGROUP, stream=b"BM" + bytes(0x1E), count=COUNT):
        self.image = NE(blob)
        self.seg, self.entry, self.dgroup, self.count = seg, entry, dgroup, count
        self.stream = stream
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        self.para = {}
        self.data = {}
        self.gates = []
        self.stop = None
        self.fault = ""

    def load(self):
        at = FIRST_PARA
        for index in range(1, self.image.nseg + 1):
            raw, size, fl = self.image.segment(index)
            if index == self.dgroup:
                size = max(size, DATA_MIN)
                raw += bytes(size - len(raw))
            if at + ((size + 15) >> 4) > LAST_PARA:
                raise ValueError(f"segment {index} does not fit below {LAST_PARA:#x}:0")
            self.para[index] = at
            self.data[index] = raw
            at += (size + 15) >> 4
        for index in self.para:
            for rec in self.image.relocs(index):
                self._fix(index, *rec)
        for index, raw in self.data.items():
            self.uc.mem_write(self.para[index] << 4, bytes(raw))

    def _target(self, fl, t1, t2):
        """(seg, off) for a reloc target. A gate for imports, None to skip."""
        kind = fl & 3
        if kind == 0:
            if t1 == 0xFF or t1 not in self.para:
                return self._gate(f"internal movable entry {t2}" if t1 == 0xFF else f"internal segment {t1}")
            return self.para[t1], t2
        if kind == 1:
            return self._gate(f"{self.image.module(t1)}.{t2}")
        if kind == 2:
            return self._gate(f"{self.image.module(t1)}.{self.image.import_name(t2)}")
        return None

    def _gate(self, name):
        if name not in self.gates:
            self.gates.append(name)
        return GATE_PARA, self.gates.index(name)

    def _fix(self, index, atype, fl, disp, t1, t2):
        target = self._target(fl, t1, t2)
        if target is None:
            return
        raw = self.data[index]
        seen = set()
        while disp not in seen and disp + 2 <= len(raw):
            seen.add(disp)
            nxt = _u16(raw, disp)
            if atype == 3 and disp + 4 <= len(raw):
                off = target[1] + (nxt if fl & 4 else 0)
                struct.pack_into("<HH", raw, disp, off & 0xFFFF, target[0])
            elif atype == 2:
                struct.pack_into("<H", raw, disp, target[0])
            elif atype == 5:
                struct.pack_into("<H", raw, disp, (target[1] + (nxt if fl & 4 else 0)) & 0xFFFF)
            if fl & 4 or nxt == 0xFFFF:
                break
            disp = nxt

    def _on_code(self, uc, address, size, user):
        if address >> 4 < GATE_PARA or address >= (GATE_PARA << 4) + 0x1000:
            return
        off = address - (GATE_PARA << 4)
        sp = uc.reg_read(UC_X86_REG_SP)
        words = struct.unpack("<8H", bytes(uc.mem_read((STACK_PARA << 4) + sp, 16)))
        regs = {"ax": uc.reg_read(UC_X86_REG_AX), "dx": uc.reg_read(UC_X86_REG_DX)}
        if off == RETURN_OFF:
            self.stop = ("returned", None, sp, words, regs)
        else:
            self.stop = ("gate", self.gates[off], sp, words, regs)
        uc.emu_stop()

    def run(self):
        self.load()
        dpara = self.para[self.dgroup]
        self.uc.mem_write((dpara << 4) + OBJ, bytes(0x40))
        self.uc.mem_write((dpara << 4) + STREAM, self.stream[:0xE00])
        frame = struct.pack("<HHHH", RETURN_OFF, GATE_PARA, OBJ, STREAM)
        sp = STACK_TOP - len(frame)
        self.uc.mem_write((STACK_PARA << 4) + sp, frame)
        self.uc.reg_write(UC_X86_REG_CS, self.para[self.seg])
        self.uc.reg_write(UC_X86_REG_DS, dpara)
        self.uc.reg_write(UC_X86_REG_ES, dpara)
        self.uc.reg_write(UC_X86_REG_SS, STACK_PARA)
        self.uc.reg_write(UC_X86_REG_SP, sp)
        self.uc.reg_write(UC_X86_REG_IP, self.entry)
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)
        try:
            self.uc.emu_start((self.para[self.seg] << 4) + self.entry, 0, count=self.count)
        except UcError as exc:
            self.fault = str(exc)
        return self.stop

    def where(self):
        cs = self.uc.reg_read(UC_X86_REG_CS)
        ip = self.uc.reg_read(UC_X86_REG_IP)
        seg = next((i for i, p in self.para.items() if p == cs), None)
        return f"segment {seg} {ip:#x}" if seg else f"{cs:#x}:{ip:#x}"

    def lines(self):
        out = [f"TB80BMP TBKBITMAP seg {self.seg}:{self.entry:#x}"]
        if self.stop and self.stop[0] == "gate":
            _, name, sp, words, regs = self.stop
            out.append(f"stopped at import {name}")
            out.append(f"  stack sp {sp:#x} {' '.join(f'{w:04x}' for w in words)}")
        elif self.stop:
            _, _, sp, words, regs = self.stop
            obj = bytes(self.uc.mem_read((self.para[self.dgroup] << 4) + OBJ, 0x40))
            out.append(f"returned ax={regs['ax']:#06x} dx={regs['dx']:#06x}")
            out.append(f"  object {obj.hex()}")
        elif self.fault:
            out.append(f"fault at {self.where()}: {self.fault}")
        else:
            out.append(f"instruction count {self.count} reached at {self.where()}")
        return out


def main():
    stream = b"BM" + bytes(0x1E)
    if "--stream" in sys.argv:
        stream = Path(sys.argv[sys.argv.index("--stream") + 1]).read_bytes()
    if not DLL.is_file():
        print(f"no TB80BMP.DLL in {DLL.parent}. Set TBK_UNPACKED to the --b directory.", file=sys.stderr)
        return 2
    probe = Probe(DLL.read_bytes(), stream=stream)
    probe.run()
    print("\n".join(probe.lines()))
    return 0 if probe.stop else 1


if __name__ == "__main__":
    sys.exit(main())
