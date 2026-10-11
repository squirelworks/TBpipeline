#!/usr/bin/env python3
"""Pass 04: run the already-unpacked TB80RTM and pass it a book.

The packed loader's GetProcAddress fixups are what killed pass 03. This
binds the NE reloc records itself, then jumps to segment 2:0x35A with the
book name in the PSP command tail. An unresolved far call is logged and
skipped so the trace shows the next thing the entry asks for.
"""

import os
import struct
import sys

from .unfold import AHINCR, Arena, _u16

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16
from unicorn import UC_HOOK_INSN, UC_HOOK_INTR, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (
    UC_X86_INS_OUT,
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_SP, UC_X86_REG_IP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_EFLAGS,
)

API_PORT = 0xE0
INITTASK = 91


class Pass04:
    def __init__(self, image, book):
        self.file = open(image, "rb").read()
        self.book = book
        self.book_bytes = open(book, "rb").read()
        self.ne = _u16(self.file, 0x3C)
        self.nseg = _u16(self.file, self.ne + 0x1C)
        self.shift = _u16(self.file, self.ne + 0x32)
        self.segoff = _u16(self.file, self.ne + 0x22)
        self.opens = []
        self.skipped = []
        self.misses = []
        self.named = []
        self.calls = []
        self.files = {}
        self.pos = {}
        self.next_handle = 4
        self.last = (0, 0, b"")
        self.startup = 0

    def record(self, index):
        return struct.unpack_from("<HHHH", self.file, self.ne + self.segoff + index * 8)

    def build(self):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        self.arena = Arena(self.uc, 0)
        self.flat = self.arena.alloc_selector(0x10000, 0x9A, fixed_base=0)
        self.thunk = self.arena.alloc_selector(0x1000, 0x9A)
        self.segs = {}
        for i in range(self.nseg):
            off, size, flags, alloc = self.record(i)
            alloc = 0x10000 if alloc == 0 else alloc
            blob = bytearray(alloc)
            raw = self.file[(off << self.shift):(off << self.shift) + size]
            blob[:len(raw)] = raw
            access = 0x9A if not (flags & 1) else 0x92
            sel = self.arena.alloc_selector(alloc, access, bytes(blob))
            self.segs[i + 1] = sel
        self._thunks()
        self._relocs()
        entry = self.arena.read(self.segs[2], 0x35A, 8)
        print(f"entry bytes {entry.hex()} thunk {self.thunk:#x}", file=sys.stderr, flush=True)
        self.uc.hook_add(UC_HOOK_INSN, self._on_out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)

    def _on_unmapped(self, uc, access, address, size, value, user):
        print(
            f"  unmapped {address:#x} at {uc.reg_read(UC_X86_REG_CS):#x}:{uc.reg_read(UC_X86_REG_IP):#x}",
            file=sys.stderr, flush=True,
        )
        self.last = (uc.reg_read(UC_X86_REG_CS), uc.reg_read(UC_X86_REG_IP), b"")
        if len(self.misses) >= 8:
            return False
        page = address & ~0xFFF
        self.misses.append(address)
        try:
            uc.mem_map(page, 0x1000)
        except UcError:
            pass
        uc.mem_write(page, b"\xcb" * 0x1000)
        return True

    def _thunks(self):
        blob = bytearray(0x1000)
        for ordinal in range(1, 200):
            at = ordinal * 8
            blob[at:at + 8] = bytes([
                0xBA, ordinal & 0xFF, (ordinal >> 8) & 0xFF,
                0xE6, API_PORT, 0xCA, 0x00, 0x00,
            ])
        self.arena.write(self.thunk, 0, bytes(blob))

    def _relocs(self):
        for i in range(self.nseg):
            off, size, flags, alloc = self.record(i)
            if not flags & 0x0100:
                continue
            base = off << self.shift
            count = _u16(self.file, base + size)
            sel = self.segs[i + 1]
            for n in range(count):
                atype, fl, disp, t1, t2 = struct.unpack_from(
                    "<BBHHH", self.file, base + size + 2 + n * 8
                )
                self._bind(sel, atype, fl, disp, t1, t2)

    def _bind(self, sel, atype, fl, disp, t1, t2):
        info = self.arena.segs[sel]
        seen = set()
        while disp not in (0, 0xFFFF) and disp not in seen and disp + 2 <= info["size"]:
            seen.add(disp)
            nxt = _u16(self.arena.read(sel, disp, 2), 0)
            stub = self._import_stub(fl, t1, t2)
            if atype == 2 and not fl & 1:
                self.arena.write(sel, disp, struct.pack("<H", self.segs.get(t1, 0)))
            elif atype == 2 and fl & 1:
                self.arena.write(sel, disp, struct.pack("<H", self.thunk))
            elif atype == 3 and stub is not None:
                self.arena.write(sel, disp, struct.pack("<HH", stub, self.thunk))
            elif atype == 5 and stub is not None:
                self.arena.write(sel, disp, struct.pack("<H", stub))
            disp = nxt

    def _import_stub(self, fl, module, target):
        if fl & 2:
            name = self._import_name(target)
            if name and name not in self.named and len(self.named) < 12:
                self.named.append(name)
            return 8
        if fl & 1:
            return (target * 8) & 0xFFF
        return None

    def _import_name(self, offset):
        imptab = _u16(self.file, self.ne + 0x2A)
        at = self.ne + imptab + offset
        if at >= len(self.file):
            return ""
        n = self.file[at]
        return self.file[at + 1:at + 1 + n].decode("latin1", "replace")

    def _on_code(self, uc, address, size, user):
        cs = uc.reg_read(UC_X86_REG_CS)
        info = self.arena.segs.get(cs)
        offset = address - info["base"] if info else address
        try:
            raw = bytes(uc.mem_read(address, min(size, 6)))
        except Exception:
            raw = b""
        self.last = (cs, offset, raw)

    def _on_out(self, uc, port, size, value, user):
        if port != API_PORT:
            return
        ordinal = uc.reg_read(UC_X86_REG_DX)
        self.calls.append(ordinal)
        if len(self.calls) <= 16:
            print(f"  api ordinal {ordinal}", file=sys.stderr, flush=True)
        if ordinal == INITTASK and self.startup == 0:
            self.startup = 1
            uc.reg_write(UC_X86_REG_AX, 1)
            uc.reg_write(UC_X86_REG_BX, 0x80)
            uc.reg_write(UC_X86_REG_CX, 0x1000)
            uc.reg_write(UC_X86_REG_DX, 1)
            uc.reg_write(UC_X86_REG_SI, self.segs[1])
            uc.reg_write(UC_X86_REG_DI, 0)
            uc.reg_write(UC_X86_REG_ES, self.psp)
            return
        if ordinal == 3:
            uc.reg_write(UC_X86_REG_AX, 0x0A03)
            return
        uc.reg_write(UC_X86_REG_AX, 1)
        uc.reg_write(UC_X86_REG_DX, 0)

    def _on_intr(self, uc, intno, user):
        if intno == 0x21:
            self._dos()
            return
        cs = uc.reg_read(UC_X86_REG_CS)
        ip = uc.reg_read(UC_X86_REG_IP)
        info = self.arena.segs.get(cs)
        raw = self.arena.read(cs, ip, 5) if info else b""
        self.last = (cs, ip, raw)
        if raw[:1] == b"\x9a" and len(self.skipped) < 12:
            target = struct.unpack_from("<HH", raw, 1)
            self.skipped.append((cs, ip, target))
            print(f"  skip call {target[1]:#x}:{target[0]:#x} from {cs:#x}:{ip:#x}", file=sys.stderr, flush=True)
            uc.reg_write(UC_X86_REG_IP, ip + 5)
            uc.reg_write(UC_X86_REG_AX, 1)
            return
        print(f"  fault int {intno:#x} at {cs:#x}:{ip:#x} {raw.hex()}", file=sys.stderr, flush=True)
        uc.emu_stop()

    def _dos(self):
        uc = self.uc
        ah = (uc.reg_read(UC_X86_REG_AX) >> 8) & 0xFF
        if ah == 0x3D:
            path = self._string(uc.reg_read(UC_X86_REG_DS), uc.reg_read(UC_X86_REG_DX))
            self.opens.append(path)
            print(f"  open {path}", file=sys.stderr)
            handle = self.next_handle
            self.next_handle += 1
            self.files[handle] = self.book_bytes if path.lower().endswith(".tbk") else b""
            uc.reg_write(UC_X86_REG_AX, handle)
            self._clear()
            return
        if ah == 0x30:
            uc.reg_write(UC_X86_REG_AX, 5)
            self._clear()
            return
        if ah == 0x3F:
            handle = uc.reg_read(UC_X86_REG_BX)
            count = uc.reg_read(UC_X86_REG_CX)
            blob = self.files.get(handle, b"")
            pos = self.pos.get(handle, 0)
            chunk = blob[pos:pos + count]
            self.pos[handle] = pos + len(chunk)
            ds = uc.reg_read(UC_X86_REG_DS)
            if chunk and ds in self.arena.segs:
                self.arena.write(ds, uc.reg_read(UC_X86_REG_DX), chunk)
            uc.reg_write(UC_X86_REG_AX, len(chunk))
            self._clear()
            return
        if ah == 0x42:
            handle = uc.reg_read(UC_X86_REG_BX)
            pos = uc.reg_read(UC_X86_REG_DX) | (uc.reg_read(UC_X86_REG_CX) << 16)
            self.pos[handle] = pos
            uc.reg_write(UC_X86_REG_AX, pos & 0xFFFF)
            uc.reg_write(UC_X86_REG_DX, (pos >> 16) & 0xFFFF)
            self._clear()
            return
        self.calls.append(f"dos{ah:02x}")
        uc.reg_write(UC_X86_REG_AX, 0)
        self._clear()

    def _string(self, sel, offset):
        if sel not in self.arena.segs:
            return ""
        return self.arena.read(sel, offset, 128).split(b"\x00", 1)[0].decode("latin1", "replace")

    def _clear(self):
        self.uc.reg_write(UC_X86_REG_EFLAGS, self.uc.reg_read(UC_X86_REG_EFLAGS) & ~1)

    def run(self):
        self.build()
        tail = (" " + os.path.basename(self.book)).encode("ascii") + b"\r"
        psp = bytearray(0x100)
        psp[0x80] = len(tail) - 1
        psp[0x81:0x81 + len(tail)] = tail
        self.psp = self.arena.alloc_selector(0x100, 0x92, bytes(psp))
        dgroup = self.segs[139]
        code = self.segs[2]
        gdtr = struct.pack("<HI", 0xFFFF, 0)
        self.uc.mem_write(0x80, gdtr)
        blob = bytes([
            0xB8, dgroup & 0xFF, (dgroup >> 8) & 0xFF, 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, 0x00, 0x40,
            0xEA, 0x5A, 0x03, code & 0xFF, (code >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, 0x80, 0x00,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, self.flat & 0xFF, (self.flat >> 8) & 0xFF,
        ]))
        self.uc.mem_write(0xF020, blob)
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        try:
            self.uc.emu_start(0xF000, 0, timeout=15_000_000, count=400_000)
        except UcError as exc:
            self.fault = str(exc)
        else:
            self.fault = "returned"
        return self.last


def main():
    image = sys.argv[1]
    book = sys.argv[2]
    host = Pass04(image, book)
    cs, ip, raw = host.run()
    print(f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}")
    print(f"opens: {host.opens or 'none'}")
    print(f"skipped {len(host.skipped)} far calls")
    out = os.path.join(os.path.dirname(__file__), "rtm - pass 05")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "PASS05.txt"), "w").write(
        f"book {book}\nstopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}\n"
        f"opens {host.opens}\nskipped {host.skipped[:20]}\n"
        f"names {host.named}\ncalls {host.calls[:40]}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
