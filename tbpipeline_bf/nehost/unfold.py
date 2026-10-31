#!/usr/bin/env python3
"""Win16 stub host for OPTLOADER self-loading NE images.

OPTLOADER is the SLR packer. The static unpacker is unpack_optloader.py,
a standalone port of moralrecordings' optloader.py:
https://github.com/moralrecordings/win16-debug

The stub unpacks itself, then LoadAppSeg expands every other segment. This host
runs that stub.

TB80RTM and the other ToolBook 16-bit binaries are self-loading NE files
(flag 0x0800). Windows is supposed to load segment 1 and call BootApp; that
stub unpacks itself, then LoadAppSeg expands every other segment. This host
is that contract and nothing else: a 16-bit protected-mode CPU, the twelve
KERNEL ordinals the loader resolves, and a dump of each segment it unfolds.

BootApp is segment 1 offset 0x169 (far, retf 4). The second argument is the
selector of an in-memory NE header whose segment table entries are 10 bytes,
the extra word being the live selector. LoadAppSeg is the far routine the
stub calls at 0x4bd after it has unpacked itself.

This is not a book runtime. USER, GDI, VBX and the universal thunk are absent
on purpose.
"""

import argparse
import os
import struct
import sys

try:
    from unicorn import (
        Uc,
        UcError,
        UC_ARCH_X86,
        UC_MODE_16,
        UC_HOOK_CODE,
        UC_HOOK_INSN,
        UC_HOOK_MEM_UNMAPPED,
        UC_HOOK_INTR,
    )
    from unicorn.x86_const import (
        UC_X86_INS_OUT,
        UC_X86_REG_AX,
        UC_X86_REG_BX,
        UC_X86_REG_CX,
        UC_X86_REG_DX,
        UC_X86_REG_SI,
        UC_X86_REG_DI,
        UC_X86_REG_BP,
        UC_X86_REG_SP,
        UC_X86_REG_IP,
        UC_X86_REG_CS,
        UC_X86_REG_DS,
        UC_X86_REG_ES,
        UC_X86_REG_SS,
        UC_X86_REG_CR0,
        UC_X86_REG_EFLAGS,
    )
except ModuleNotFoundError:
    raise SystemExit(
        "unicorn is not installed. It is the 16-bit CPU this host runs on.\n"
        "Install it with:  python -m pip install unicorn"
    )

AHINCR = 8
BOOTAPP = 0x169
LOADAPPSEG = 0x4BD
STOP_PORT = 0x00F0
API_PORT = 0x00E0
TRACE_LIMIT = 12

# KERNEL ordinals the segment-1 resolver walks, in the order it stores them
# at loader offset 0x9A4. Names are the Win16 krnl386 exports.
KERNEL_ORDINALS = {
    15: "GlobalAlloc",
    16: "GlobalReAlloc",
    17: "GlobalFree",
    18: "GlobalLock",
    50: "GetProcAddress",
    102: "DOS3Call",
    110: "PatchCodeHandle",
    132: "GetWinFlags",
    170: "AllocCStoDSAlias",
    176: "FreeSelector",
    184: "GlobalDOSAlloc",
    185: "GlobalDOSFree",
    196: "SelectorAccessRights",
}


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def _descriptor(base, limit, access, flags=0):
    raw = bytearray(8)
    raw[0] = limit & 0xFF
    raw[1] = (limit >> 8) & 0xFF
    raw[2] = base & 0xFF
    raw[3] = (base >> 8) & 0xFF
    raw[4] = (base >> 16) & 0xFF
    raw[5] = access & 0xFF
    raw[6] = ((limit >> 16) & 0x0F) | ((flags & 0x0F) << 4)
    raw[7] = (base >> 24) & 0xFF
    return bytes(raw)


class Arena:
    """16-bit selectors. Selector value increments by __AHINCR (8)."""

    def __init__(self, uc, gdt_base):
        self.uc = uc
        self.gdt_base = gdt_base
        self.next_index = 1
        self.linear = 0x200000
        self.segs = {}
        self.handles = {}

    def map(self, base, size, data=b""):
        size = (size + 0xFFF) & ~0xFFF
        self.uc.mem_map(base, max(size, 0x1000))
        if data:
            self.uc.mem_write(base, data)

    def alloc_selector(self, size, access=0x92, data=b"", fixed_base=None):
        size = 0x10000 if size in (0, 0x10000) else size
        if fixed_base is None:
            base = self.linear
            self.linear += (max(size, 1) + 0xFFF) & ~0xFFF
            self.map(base, size)
        else:
            base = fixed_base
        if data:
            self.uc.mem_write(base, data[:size])
        index = self.next_index
        self.next_index += 1
        selector = index * AHINCR
        limit = 0xFFFF if size >= 0x10000 else size - 1
        self._write_descriptor(index, base, limit, access)
        self.segs[selector] = {"base": base, "limit": limit, "access": access, "size": size}
        return selector

    def _write_descriptor(self, index, base, limit, access, flags=0):
        self.uc.mem_write(self.gdt_base + index * 8, _descriptor(base, limit, access, flags))

    def set_access(self, selector, access):
        info = self.segs[selector]
        info["access"] = access
        self._write_descriptor(selector // AHINCR, info["base"], info["limit"], access)

    def alias(self, selector, access=0x92):
        info = self.segs[selector]
        return self.alloc_selector(info["size"], access, fixed_base=info["base"])

    def grow(self, selector, size):
        """GlobalReAlloc of a moveable segment: same selector, new base, bytes kept."""
        info = self.segs[selector]
        size = min(0x10000, size)
        if size <= info["size"]:
            return True
        keep = bytes(self.uc.mem_read(info["base"], info["size"]))
        base = self.linear
        self.linear += (size + 0xFFF) & ~0xFFF
        self.map(base, size, keep)
        info["base"], info["size"] = base, size
        info["limit"] = 0xFFFF if size >= 0x10000 else size - 1
        self._write_descriptor(selector // AHINCR, base, info["limit"], info["access"])
        return True

    def read(self, selector, offset, size):
        info = self.segs[selector]
        return bytes(self.uc.mem_read(info["base"] + offset, size))

    def write(self, selector, offset, data):
        info = self.segs[selector]
        self.uc.mem_write(info["base"] + offset, data)

    def alloc_handle(self, size, data=b"", access=0x92):
        selector = self.alloc_selector(max(size, 1), access, data)
        self.handles[selector] = selector
        return selector


class Host:
    def __init__(self, path, trace=False, book=None):
        self.path = path
        self.trace = trace
        self.book = book
        self.book_bytes = open(book, "rb").read() if book else b""
        self.file = open(path, "rb").read()
        self.calls = []
        self.opens = []
        self.dos_files = {0: self.file, 3: self.file}
        self.next_handle = 4
        self.pc_ring = []
        self.stopped = False
        self.dos_log = 0
        if self.file[:2] != b"MZ":
            raise SystemExit("not an MZ image")
        self.ne = _u16(self.file, 0x3C)
        if self.file[self.ne:self.ne + 2] != b"NE":
            raise SystemExit("not an NE image")
        self.flags = _u16(self.file, self.ne + 0x0C)
        if not self.flags & 0x0800:
            raise SystemExit("NE self-loading flag is not set")
        self.nseg = _u16(self.file, self.ne + 0x1C)
        self.shift = _u16(self.file, self.ne + 0x32)
        self.segoff = _u16(self.file, self.ne + 0x22)

    def segment_record(self, index):
        return struct.unpack_from("<HHHH", self.file, self.ne + self.segoff + index * 8)

    def build(self):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        self.arena = Arena(self.uc, 0)
        # Flat 16-bit code/data covering the low megabyte, used by the
        # bootstrap and by the API stubs. Guest segments live above 2MB.
        self.flat_code = self.arena.alloc_selector(0x10000, 0x9A, fixed_base=0)
        self.flat_data = self.arena.alloc_selector(0x10000, 0x92, fixed_base=0)
        self.stack = self.arena.alloc_selector(0x8000, 0x92)
        self.thunk = self.arena.alloc_selector(0x1000, 0x9A)
        self._write_thunks()
        self.loader = self._load_segment_1()
        self.module = self._build_module()
        self._apply_boot_relocs()
        self.uc.hook_add(UC_HOOK_INSN, self._on_out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.last = (0, 0, b"")
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)

    def _write_thunks(self):
        # One stub per ordinal: mov dx, ord; out API_PORT, al; retf N
        # GetProcAddress and AllocCStoDSAlias share this page.
        blob = bytearray(0x1000)
        self.stub_at = {}
        for ordinal in list(KERNEL_ORDINALS) + [1]:
            at = ordinal * 8
            blob[at:at + 8] = bytes([
                0xBA, ordinal & 0xFF, (ordinal >> 8) & 0xFF,
                0xE6, API_PORT & 0xFF,
                0xCA, 0x00, 0x00,
            ])
            self.stub_at[ordinal] = at
        # retf immediate is patched per ordinal when we know the arg bytes.
        self.arena.write(self.thunk, 0, bytes(blob))
        self._patch_ret(15, 6)    # GlobalAlloc(word, long)
        self._patch_ret(16, 8)    # GlobalReAlloc(word, long, word)
        self._patch_ret(17, 2)    # GlobalFree(word)
        self._patch_ret(18, 2)    # GlobalLock(word)
        self._patch_ret(50, 4)    # ordinal GetProcAddress used by the boot resolver
        self._plant(0x40, 0xE4, 6)
        self.named_proc = 0x40
        self._patch_ret(102, 0)   # DOS3Call, registers
        self._patch_ret(110, 2)   # PatchCodeHandle(word)
        self._patch_ret(132, 0)   # GetWinFlags()
        self._patch_ret(170, 2)   # AllocCStoDSAlias(word)
        self._patch_ret(176, 2)   # FreeSelector(word)
        self._patch_ret(184, 4)   # GlobalDOSAlloc(long)
        self._patch_ret(185, 2)   # GlobalDOSFree(word)
        self._patch_ret(196, 6)   # SelectorAccessRights(word, word, word)
        # DOS3Call is a register call. A mov dx,ord stub would destroy the
        # seek offset and the read pointer, so it has its own port.
        self._plant(0x30, 0xE3, 0)
        self.stub_at[102] = 0x30

    def _patch_ret(self, ordinal, nbytes):
        at = self.stub_at[ordinal]
        raw = bytearray(self.arena.read(self.thunk, at, 8))
        raw[6] = nbytes & 0xFF
        raw[7] = (nbytes >> 8) & 0xFF
        self.arena.write(self.thunk, at, bytes(raw))

    def _load_segment_1(self):
        off, size, flags, alloc = self.segment_record(0)
        alloc = 0x10000 if alloc == 0 else alloc
        blob = bytearray(alloc)
        blob[:size] = self.file[(off << self.shift):(off << self.shift) + size]
        return self.arena.alloc_selector(alloc, 0x9A, bytes(blob))

    def _build_module(self):
        # In-memory NE: file header, then a 10-byte segment table. The extra
        # word is the live selector, which BootApp and LoadAppSeg fill in.
        header = bytearray(self.file[self.ne:self.ne + 0x40])
        entries = bytearray()
        for i in range(self.nseg):
            off, size, flags, alloc = self.segment_record(i)
            entries += struct.pack("<HHHHH", off, size, flags, alloc, 0)
        # Keep the file's module-ref and imported-name tables. LoadAppSeg
        # resolves fixups through them; a stub table makes it abort the write.
        modtab = _u16(self.file, self.ne + 0x28)
        imptab = _u16(self.file, self.ne + 0x2A)
        name_end = max(modtab, imptab) + 0x800
        names = self.file[self.ne + min(modtab, imptab):self.ne + name_end]
        table_at = 0x40
        names_at = table_at + len(entries)
        struct.pack_into("<H", header, 0x22, table_at)
        struct.pack_into("<H", header, 0x28, names_at + (modtab - min(modtab, imptab)))
        struct.pack_into("<H", header, 0x2A, names_at + (imptab - min(modtab, imptab)))
        image = bytearray(names_at + len(names))
        image[:0x40] = header
        image[table_at:table_at + len(entries)] = entries
        image[names_at:names_at + len(names)] = names
        selector = self.arena.alloc_selector(len(image), 0x92, bytes(image))
        # Segment 1 is already resident. Publish its selector in the table.
        self.arena.write(selector, table_at + 8, struct.pack("<H", self.loader))
        return selector

    def _apply_boot_relocs(self):
        off, size, flags, alloc = self.segment_record(0)
        file_off = off << self.shift
        count = _u16(self.file, file_off + size)
        rel = self.file[file_off + size + 2:file_off + size + 2 + count * 8]
        for i in range(count):
            addr, flag, disp, tgt1, tgt2 = struct.unpack_from("<BBHHH", rel, i * 8)
            if addr == 2 and flag == 0:
                self.arena.write(self.loader, disp, struct.pack("<H", self.loader))
            elif addr == 3 and flag == 1 and tgt2 == 170:
                far = struct.pack("<HH", self.stub_at[170], self.thunk)
                self.arena.write(self.loader, disp, far)
            elif addr == 5 and flag == 1 and tgt2 == 114:
                self.arena.write(self.loader, disp, struct.pack("<H", AHINCR))
            else:
                print(f"unhandled boot reloc addr={addr:#x} fl={flag:#x} at {disp:#x}", file=sys.stderr)
        far = struct.pack("<HH", self.stub_at[50], self.thunk)
        self.arena.write(self.loader, 0x14, far)
        self._plant(0x10, 0xE1, 6)
        self._plant(0x24, 0xE2, 4)
        self.arena.write(self.loader, 0x10, struct.pack("<HH", 0x10, self.thunk))
        self.arena.write(self.loader, 0x24, struct.pack("<HH", 0x24, self.thunk))

    def _plant(self, at, port, retn):
        stub = bytes([0xE6, port & 0xFF, 0xCA, retn & 0xFF, (retn >> 8) & 0xFF])
        self.arena.write(self.thunk, at, stub)

    def _plant_handshake(self):
        self._plant(0x10, 0xE1, 6)
        self._plant(0x24, 0xE2, 4)
        self.arena.write(self.loader, 0x10, struct.pack("<HH", 0x10, self.thunk))
        self.arena.write(self.loader, 0x24, struct.pack("<HH", 0x24, self.thunk))

    def _on_out(self, uc, port, size, value, user):
        if port == STOP_PORT:
            self.stopped = True
            uc.emu_stop()
            return
        if port == 0xE1:
            handle = self.arena.alloc_handle(0x10000)
            uc.reg_write(UC_X86_REG_AX, handle)
            uc.reg_write(UC_X86_REG_DX, handle)
            self.calls.append("AllocSeg")
            return
        if port == 0xE2:
            self.calls.append("OwnSeg")
            return
        if port == 0xE4:
            self._named_proc()
            return
        if port == 0xE3:
            self.calls.append("DOS3Call")
            if self.trace and self.calls.count("DOS3Call") <= TRACE_LIMIT:
                print("  api DOS3Call")
            self._dos_dispatch()
            return
        if port != API_PORT:
            return
        ordinal = uc.reg_read(UC_X86_REG_DX)
        if ordinal == 1 and getattr(self, "opening", False):
            self._startup_thunk()
            return
        name = KERNEL_ORDINALS.get(ordinal, f"ord{ordinal}")
        self.calls.append(name)
        if self.trace and self.calls.count(name) <= TRACE_LIMIT:
            print(f"  api {name}")
        handler = getattr(self, "_k_" + name, None)
        if handler:
            handler()
        else:
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)

    def _on_intr(self, uc, intno, user):
        if intno == 0x21:
            self._dos_dispatch()
            return
        cs, ip, raw = self.last
        print(
            f"  fault int {intno:#x} after {cs:#x}:{ip:#x} {raw.hex()} "
            f"ax={uc.reg_read(UC_X86_REG_AX):#x} ds={uc.reg_read(UC_X86_REG_DS):#x} "
            f"es={uc.reg_read(UC_X86_REG_ES):#x} ss:sp={uc.reg_read(UC_X86_REG_SS):#x}:{uc.reg_read(UC_X86_REG_SP):#x}",
            file=sys.stderr,
        )
        self.stopped = True
        uc.emu_stop()

    def _on_unmapped(self, uc, access, address, size, value, user):
        print(f"unmapped {address:#x} cs:ip {uc.reg_read(UC_X86_REG_CS):#x}:{uc.reg_read(UC_X86_REG_IP):#x}", file=sys.stderr)
        return False

    def _on_code(self, uc, address, size, user):
        cs = uc.reg_read(UC_X86_REG_CS)
        info = self.arena.segs.get(cs)
        offset = address - info["base"] if info else address
        try:
            raw = bytes(uc.mem_read(address, min(size, 8))) if info else b""
        except Exception:
            raw = b""
        self.last = (cs, offset, raw)
        if self.trace:
            self.pc_ring.append((cs, address))
            del self.pc_ring[:-8]

    def _arg(self, n):
        # Far call frame, callee has not pushed bp. n=0 is the first argument.
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = self.uc.reg_read(UC_X86_REG_SP)
        return _u16(self.arena.read(ss, sp + 4 + n * 2, 2), 0)

    def _k_GetProcAddress(self):
        ordinal = self._arg(0)
        name = KERNEL_ORDINALS.get(ordinal, f"ord{ordinal}")
        if self.trace:
            print(f"    GetProcAddress {name}")
        if ordinal == 50:
            at = self.named_proc
        else:
            at = self.stub_at.get(ordinal, self.stub_at[1])
        self.uc.reg_write(UC_X86_REG_AX, at)
        self.uc.reg_write(UC_X86_REG_DX, self.thunk)

    def _named_proc(self):
        name_off = self._arg(0)
        name_sel = self._arg(1)
        raw = self.arena.read(name_sel, name_off, 64)
        name = raw.split(b"\x00", 1)[0].decode("latin1", "replace")
        ordinal = next((n for n, text in KERNEL_ORDINALS.items() if text.lower() == name.lower()), None)
        at = self.stub_at.get(ordinal, self.stub_at[1])
        self.uc.reg_write(UC_X86_REG_AX, at)
        self.uc.reg_write(UC_X86_REG_DX, self.thunk)
        self.calls.append("name:" + name)

    def _k_AllocCStoDSAlias(self):
        src = self._arg(0)
        alias = self.arena.alias(src, 0x92)
        self.uc.reg_write(UC_X86_REG_AX, alias)

    def _k_FreeSelector(self):
        self.uc.reg_write(UC_X86_REG_AX, 0)

    def _k_GlobalAlloc(self):
        # pascal (word flags, long size): arg0 = size lo, arg1 = size hi, arg2 = flags
        size = self._arg(0) | (self._arg(1) << 16)
        handle = self.arena.alloc_handle(size or 1)
        self.uc.reg_write(UC_X86_REG_AX, handle)
        self.uc.reg_write(UC_X86_REG_DX, 0)

    def _k_GlobalReAlloc(self):
        # pascal (word handle, long size, word flags): handle is the furthest arg.
        handle = self._arg(3)
        if handle not in self.arena.segs:
            handle = self._arg(0) if self._arg(0) in self.arena.segs else self.arena.alloc_handle(0x100)
        self.uc.reg_write(UC_X86_REG_AX, handle)
        self.uc.reg_write(UC_X86_REG_DX, 0)

    def _k_GlobalFree(self):
        self.uc.reg_write(UC_X86_REG_AX, 0)

    def _k_GlobalLock(self):
        handle = self._arg(0)
        self.uc.reg_write(UC_X86_REG_AX, 0)
        self.uc.reg_write(UC_X86_REG_DX, handle)

    def _k_GlobalDOSAlloc(self):
        size = self._arg(0) | (self._arg(1) << 16)
        handle = self.arena.alloc_handle(size or 1)
        self.uc.reg_write(UC_X86_REG_AX, handle)
        self.uc.reg_write(UC_X86_REG_DX, handle)

    def _k_GlobalDOSFree(self):
        self.uc.reg_write(UC_X86_REG_AX, 0)

    def _k_GetWinFlags(self):
        # WF_PMODE | WF_CPU386 | WF_ENHANCED. No coprocessor bit: the loader
        # patches a different path when 0x400 is set.
        self.uc.reg_write(UC_X86_REG_AX, 0x0025)

    def _k_PatchCodeHandle(self):
        self.uc.reg_write(UC_X86_REG_AX, self._arg(0))

    def _k_SelectorAccessRights(self):
        selector = self._arg(0)
        rights = self._arg(1)
        if selector in self.arena.segs and rights:
            self.arena.set_access(selector, 0x90 | (rights & 0x0F) | 0x02)
        self.uc.reg_write(UC_X86_REG_AX, rights)

    def _k_DOS3Call(self):
        self._dos_dispatch()

    def _dos_dispatch(self):
        uc = self.uc
        ah = (uc.reg_read(UC_X86_REG_AX) >> 8) & 0xFF
        al = uc.reg_read(UC_X86_REG_AX) & 0xFF
        if self.trace and self.dos_log < 16:
            print(
                f"  dos ah={ah:#04x} ax={uc.reg_read(UC_X86_REG_AX):#x} "
                f"bx={uc.reg_read(UC_X86_REG_BX):#x} cx={uc.reg_read(UC_X86_REG_CX):#x} "
                f"dx={uc.reg_read(UC_X86_REG_DX):#x} ds={uc.reg_read(UC_X86_REG_DS):#x}",
                file=sys.stderr,
            )
            self.dos_log += 1
        if ah == 0x3D:
            path = self._ds_string(uc.reg_read(UC_X86_REG_DX))
            self.opens.append(path)
            print(f"  open {path}", file=sys.stderr)
            handle = self.next_handle
            self.next_handle += 1
            blob = self.book_bytes if path.lower().endswith(".tbk") else b""
            self.dos_files[handle] = blob
            uc.reg_write(UC_X86_REG_AX, handle)
            self._clear_carry()
            return
        if ah == 0x30:
            uc.reg_write(UC_X86_REG_AX, 0x0005)
            self._clear_carry()
            return
        if ah == 0x3F:
            handle = uc.reg_read(UC_X86_REG_BX)
            count = uc.reg_read(UC_X86_REG_CX)
            offset = self._file_pos(handle)
            blob = self.dos_files.get(handle, b"")
            chunk = blob[offset:offset + count]
            self._write_dsdx(chunk)
            self._file_seek(handle, offset + len(chunk))
            uc.reg_write(UC_X86_REG_AX, len(chunk))
            self._clear_carry()
            return
        if ah == 0x42:
            handle = uc.reg_read(UC_X86_REG_BX)
            pos = uc.reg_read(UC_X86_REG_DX) | (uc.reg_read(UC_X86_REG_CX) << 16)
            blob = self.dos_files.get(handle, b"")
            origin = al
            cur = self._file_pos(handle)
            if origin == 0:
                new = pos
            elif origin == 1:
                new = cur + pos
            else:
                new = len(blob) + struct.unpack("<i", struct.pack("<I", pos))[0]
            self._file_seek(handle, new)
            uc.reg_write(UC_X86_REG_AX, new & 0xFFFF)
            uc.reg_write(UC_X86_REG_DX, (new >> 16) & 0xFFFF)
            self._clear_carry()
            return
        if ah == 0x3E:
            self._clear_carry()
            uc.reg_write(UC_X86_REG_AX, 0)
            return
        self.calls.append(f"dos{ah:02x}")
        uc.reg_write(UC_X86_REG_AX, 0)
        self._clear_carry()

    def _file_pos(self, handle):
        return getattr(self, "pos", {}).get(handle, 0)

    def _file_seek(self, handle, pos):
        if not hasattr(self, "pos"):
            self.pos = {}
        self.pos[handle] = pos

    def _write_dsdx(self, chunk):
        if not chunk:
            return
        ds = self.uc.reg_read(UC_X86_REG_DS)
        dx = self.uc.reg_read(UC_X86_REG_DX)
        self.arena.write(ds, dx, chunk)

    def _clear_carry(self):
        self.uc.reg_write(UC_X86_REG_EFLAGS, self.uc.reg_read(UC_X86_REG_EFLAGS) & ~1)

    def _set_carry(self):
        self.uc.reg_write(UC_X86_REG_EFLAGS, self.uc.reg_read(UC_X86_REG_EFLAGS) | 1)

    def run(self):
        self.build()
        uc = self.uc
        # Real-mode bootstrap. CS base is zero until LGDT and a far jump
        # load the protected-mode descriptor cache; writing CS from Python
        # does not.
        gdtr_at = 0xF0E0
        gdtr = struct.pack("<HI", 0xFFFF, 0)
        uc.mem_write(gdtr_at, gdtr)
        stop = 0xF100
        uc.mem_write(stop, bytes([0xE6, STOP_PORT & 0xFF, 0xF4]))
        call = bytes([
            0xB8, self.module & 0xFF, (self.module >> 8) & 0xFF,
            0x50,
            0x31, 0xC0,
            0x50,
            0xB8, self.flat_code & 0xFF, (self.flat_code >> 8) & 0xFF,
            0x50,
            0xB8, stop & 0xFF, (stop >> 8) & 0xFF,
            0x50,
            0xEA, BOOTAPP & 0xFF, (BOOTAPP >> 8) & 0xFF,
            self.loader & 0xFF, (self.loader >> 8) & 0xFF,
        ])
        uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0,
            0x66, 0x83, 0xC8, 0x01,
            0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, self.flat_code & 0xFF, (self.flat_code >> 8) & 0xFF,
        ]))
        uc.mem_write(0xF020, bytes([
            0xB8, self.stack & 0xFF, (self.stack >> 8) & 0xFF,
            0x8E, 0xD0,
            0xBC, 0xFE, 0x7F,
            0xB8, self.flat_data & 0xFF, (self.flat_data >> 8) & 0xFF,
            0x8E, 0xD8,
            0x8E, 0xC0,
        ]) + call)
        uc.reg_write(UC_X86_REG_CS, 0)
        uc.reg_write(UC_X86_REG_IP, 0xF000)
        uc.reg_write(UC_X86_REG_SS, 0)
        uc.reg_write(UC_X86_REG_SP, 0x800)
        try:
            uc.emu_start(0xF000, 0, timeout=60_000_000, count=20_000_000)
        except UcError as exc:
            print(f"cpu stop: {exc}", file=sys.stderr)
            print(f"  at {uc.reg_read(UC_X86_REG_CS):#x}:{uc.reg_read(UC_X86_REG_IP):#x}", file=sys.stderr)
        ax = uc.reg_read(UC_X86_REG_AX)
        self.boot_ax = ax
        self.loaded = []
        self.failed = []
        if not self.book:
            self.loaded = self._sweep_loadappseg()
        return ax

    def _call_far(self, selector, offset, args):
        """Far call selector:offset. args are pushed left to right, as Pascal does."""
        uc = self.uc
        stop = 0xF100
        blob = bytearray()
        for word in args:
            blob += bytes([0xB8, word & 0xFF, (word >> 8) & 0xFF, 0x50])
        blob += bytes([
            0xB8, self.flat_code & 0xFF, (self.flat_code >> 8) & 0xFF, 0x50,
            0xB8, stop & 0xFF, (stop >> 8) & 0xFF, 0x50,
            0xEA, offset & 0xFF, (offset >> 8) & 0xFF,
            selector & 0xFF, (selector >> 8) & 0xFF,
        ])
        uc.mem_write(0xF200, bytes(blob))
        uc.ctl_remove_cache(0xF200, 0xF200 + len(blob))
        # Do not write CS or SS here. Unicorn keeps the descriptor cache from
        # the guest's own far return, and a host write throws it away.
        uc.reg_write(UC_X86_REG_IP, 0xF200)
        uc.reg_write(UC_X86_REG_SP, 0x7FFE)
        self.stopped = False
        try:
            uc.emu_start(0xF200, 0, timeout=20_000_000, count=2_000_000)
        except UcError as exc:
            return None, str(exc)
        if not self.stopped:
            return None, "ran off the end"
        return uc.reg_read(UC_X86_REG_AX), None

    def _sweep_loadappseg(self):
        """BootApp only unfolds preload segments. Ask LoadAppSeg for the rest."""
        filled = []
        failed = []
        print(
            f"  sweep cs={self.uc.reg_read(UC_X86_REG_CS):#x} ip={self.uc.reg_read(UC_X86_REG_IP):#x}",
            file=sys.stderr,
        )
        for segnum in range(2, self.nseg + 1):
            before = self._nonzero(segnum)
            if before <= 16:
                # BootApp's selector walk sets the allocated bit. LoadAppSeg
                # treats that as already resident and will not read the file.
                entry_at = 0x40 + (segnum - 1) * 10
                flags = struct.unpack_from("<H", self.arena.read(self.module, entry_at + 4, 2))[0]
                self.arena.write(self.module, entry_at + 4, struct.pack("<H", flags & ~0x0006))
            ax, err = self._call_far(self.loader, LOADAPPSEG, (self.module, 0, segnum))
            after = self._nonzero(segnum)
            if err:
                failed.append((segnum, err))
                if self.trace:
                    print(f"  seg{segnum:03d} fault {err}", file=sys.stderr)
                continue
            if after > before or after > 16:
                filled.append(segnum)
            elif self.trace:
                print(f"  seg{segnum:03d} ax={ax:#x} still empty", file=sys.stderr)
        self.failed = failed
        return filled

    def _nonzero(self, segnum):
        entry = self.arena.read(self.module, 0x40 + (segnum - 1) * 10, 10)
        handle = struct.unpack_from("<H", entry, 8)[0]
        alloc = struct.unpack_from("<H", entry, 6)[0] or 0x10000
        if handle not in self.arena.segs:
            return 0
        blob = self.arena.read(handle, 0, min(alloc, self.arena.segs[handle]["size"]))
        return sum(1 for b in blob if b)

    def _ds_string(self, offset):
        ds = self.uc.reg_read(UC_X86_REG_DS)
        if ds not in self.arena.segs:
            return ""
        raw = self.arena.read(ds, offset, 128)
        return raw.split(b"\x00", 1)[0].decode("latin1", "replace")

    def _startup_thunk(self):
        """The entry's InitTask and GetVersion fixups both landed on ordinal 1."""
        self.startup_calls = getattr(self, "startup_calls", 0) + 1
        uc = self.uc
        if self.startup_calls == 1:
            self.calls.append("InitTask")
            uc.reg_write(UC_X86_REG_AX, 1)
            uc.reg_write(UC_X86_REG_BX, 0x80)
            uc.reg_write(UC_X86_REG_CX, 0x1000)
            uc.reg_write(UC_X86_REG_DX, 1)
            uc.reg_write(UC_X86_REG_SI, self.module)
            uc.reg_write(UC_X86_REG_DI, 0)
            uc.reg_write(UC_X86_REG_ES, self.psp)
            return
        if self.startup_calls == 2:
            self.calls.append("GetVersion")
            uc.reg_write(UC_X86_REG_AX, 0x0A03)
            return
        self.calls.append("ord1")
        uc.reg_write(UC_X86_REG_AX, 1)

    def _selector(self, segnum):
        entry = self.arena.read(self.module, 0x40 + (segnum - 1) * 10, 10)
        return struct.unpack_from("<H", entry, 8)[0]

    def open_book(self):
        """Jump to the NE entry with the book path in the PSP command tail."""
        dgroup = self._selector(0x8B)
        code = self._selector(2)
        info = self.arena.segs[code]
        self.arena.set_access(code, 0x9A)
        self.arena._write_descriptor(code // AHINCR, info["base"], 0xFFFF, 0x9A)
        print(f"  entry sel={code:#x} base={info['base']:#x} dgroup={dgroup:#x}", file=sys.stderr)
        tail = (" " + os.path.basename(self.book)).encode("ascii") + b"\r"
        psp = bytearray(0x100)
        psp[0x80] = len(tail) - 1
        psp[0x81:0x81 + len(tail)] = tail
        self.psp = self.arena.alloc_selector(0x100, 0x92, bytes(psp))
        self.opening = True
        self.startup_calls = 0
        self.demand = []
        for segnum in (13, 42, 138):
            entry_at = 0x40 + (segnum - 1) * 10
            self.arena.write(self.module, entry_at + 4, struct.pack("<H", 0))
            ax, err = self._call_far(self.loader, LOADAPPSEG, (self.module, 0, segnum))
            sel = self._selector(segnum)
            if sel in self.arena.segs:
                info = self.arena.segs[sel]
                self.arena.set_access(sel, 0x9A)
                self.arena._write_descriptor(sel // AHINCR, info["base"], 0xFFFF, 0x9A)
            self.demand.append((segnum, sel, err or "ok"))
            print(f"  preload seg{segnum:03d} sel={sel:#x} {err or 'ok'}", file=sys.stderr)
        blob = bytes([
            0xB8, dgroup & 0xFF, (dgroup >> 8) & 0xFF,
            0x8E, 0xD8,
            0x8E, 0xD0,
            0xBC, 0x00, 0x40,
            0xEA, 0x5A, 0x03, code & 0xFF, (code >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF300, blob)
        self.uc.ctl_remove_cache(0xF300, 0xF300 + len(blob))
        self.uc.reg_write(UC_X86_REG_IP, 0xF300)
        self.stopped = False
        self.fault = ""
        try:
            self.uc.emu_start(0xF300, 0, timeout=15_000_000, count=1_000_000)
        except UcError as exc:
            self.fault = str(exc)
        else:
            self.fault = "stopped" if self.stopped else "ran off the end"
        cs, ip, raw = self.last
        return cs, ip, raw

    def dump(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        table = 0x40
        written = 0
        for i in range(self.nseg):
            entry = self.arena.read(self.module, table + i * 10, 10)
            off, size, flags, alloc, handle = struct.unpack("<HHHHH", entry)
            if not handle or handle not in self.arena.segs:
                continue
            alloc = 0x10000 if alloc == 0 else alloc
            blob = self.arena.read(handle, 0, alloc)
            path = os.path.join(outdir, f"seg{i + 1:03d}.bin")
            open(path, "wb").write(blob)
            written += 1
        return written


def main():
    parser = argparse.ArgumentParser(description="Unfold an OPTLOADER NE image by running BootApp")
    parser.add_argument("image")
    parser.add_argument("-o", "--out", default="nehost_out")
    parser.add_argument("--book", help="TBK path to pass in the command tail")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    host = Host(args.image, trace=args.trace, book=args.book)
    print(f"{os.path.basename(args.image)}: {host.nseg} segments, self-load flag set")
    ax = host.run()
    print(f"BootApp returned ax={ax:#x}, api calls={len(host.calls)}")
    print(f"LoadAppSeg filled {len(host.loaded)} segments, {len(host.failed)} faults")
    if host.failed[:8]:
        print("  first faults: " + ", ".join(f"{n}:{e}" for n, e in host.failed[:8]))
    if host.calls:
        tally = {}
        for name in host.calls:
            tally[name] = tally.get(name, 0) + 1
        print("  " + ", ".join(f"{k}={v}" for k, v in tally.items()))
    written = host.dump(args.out)
    print(f"wrote {written} unfolded segments to {args.out}")
    if args.book:
        cs, ip, raw = host.open_book()
        print(f"entry stopped at {cs:#x}:{ip:#x} {raw.hex()} ({host.fault})")
        print(f"opens: {host.opens or 'none'}")
        note = os.path.join(args.out, "PASS03.txt")
        open(note, "w").write(
            f"book {args.book}\n"
            f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}\n"
            f"opens {host.opens}\n"
            f"calls {host.calls[-40:]}\n"
        )
    return 0 if ax else 1


if __name__ == "__main__":
    sys.exit(main())
