#!/usr/bin/env python3
"""Pass 04: run the already-unpacked TB80RTM and pass it a book.

The packed loader's GetProcAddress fixups are what killed pass 03. This
binds the NE reloc records itself, then jumps to segment 2:0x35A with the
book name in the PSP command tail. An unresolved far call is logged and
skipped so the trace shows the next thing the entry asks for.
"""

import os
import re
import struct
import sys

from .unfold import AHINCR, Arena, _u16
from .win16stack import POP

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16
from unicorn import UC_HOOK_INSN, UC_HOOK_INTR, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (
    UC_X86_INS_OUT,
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_SP, UC_X86_REG_IP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_EFLAGS,
)

API_PORT = 0xE0
# Modules that are part of Windows itself. LoadLibrary finds them loaded.
SYSTEM_MODULES = {"KERNEL", "USER", "GDI", "KEYBOARD", "SYSTEM", "SOUND", "DISPLAY", "MOUSE"}
INITTASK = 91
OF_PARSE = 0x0100
OF_EXIST = 0x4000
OF_REOPEN = 0x8000

# Names other than *.ini the entry opens that TBK_INI may answer. The
# pass 06 log has C:\TOOLBOOK\TB80enu, with no extension, between the
# two rounds of TB80.INI opens. What the file should hold is not known.
SUPPLIED = {"tb80enu"}


REGS = (
    ("ax", UC_X86_REG_AX), ("bx", UC_X86_REG_BX), ("cx", UC_X86_REG_CX), ("dx", UC_X86_REG_DX),
    ("si", UC_X86_REG_SI), ("di", UC_X86_REG_DI), ("ds", UC_X86_REG_DS), ("es", UC_X86_REG_ES),
)


def last_call_line(call):
    """The last Windows call the entry made, and the registers it got back."""
    if not call:
        return "last call none"
    module, ordinal, cs, ip, words, regs, defaulted = call
    stack = " ".join(f"{w:04x}" for w in words)
    back = " ".join(f"{k}={v:04x}" for k, v in regs.items())
    tag = " (AX = 1 default)" if defaulted else ""
    return f"last call {module}.{ordinal} from {cs:#06x}:{ip:#06x} stack {stack} -> {back}{tag}"


def ax1_line(module, ordinal, words, cs, ip):
    """One line of 02_launch.txt for a call that got the AX = 1 default."""
    stack = " ".join(f"{w:04x}" for w in words)
    return f"ax=1 {module}.{ordinal} from {cs:#06x}:{ip:#06x} stack {stack}"


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
        self.open_styles = []
        self.skipped = []
        self.misses = []
        self.named = []
        self.calls = []
        self._args = b""
        self.files = {}
        self.pos = {}
        self.heap = {}
        self.local = {}
        self.mods = {}
        self.hrsrc = {}
        self.next_hrsrc = 1
        self.next_handle = 4
        self.exe_inst = 0
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
        self.sites = {}
        self.callers = {}
        self.caller = None
        self.ax1 = []
        self.last_call = None
        self.pending = None
        self.modnames = self._module_names()
        auto = _u16(self.file, self.ne + 0x0E)
        heap = _u16(self.file, self.ne + 0x10)
        stack = _u16(self.file, self.ne + 0x12)
        self.stack_top = 0x4000
        for i in range(self.nseg):
            off, size, flags, alloc = self.record(i)
            alloc = 0x10000 if alloc == 0 else alloc
            if i + 1 == auto:
                alloc = min(0x10000, alloc + heap + stack)
                self.stack_top = alloc
            blob = bytearray(alloc if alloc < 0x10000 else 0x10000)
            raw = self.file[(off << self.shift):(off << self.shift) + size]
            blob[:len(raw)] = raw[:len(blob)]
            access = 0x9A if not (flags & 1) else 0x92
            sel = self.arena.alloc_selector(len(blob), access, bytes(blob))
            self.segs[i + 1] = sel
        self._thunks()
        self._relocs()
        auto = _u16(self.file, self.ne + 0x0E)
        self.exe_inst = self.segs.get(auto, 0)
        self._index_module(self.exe_inst, self.file, "TB80RTM")
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
        # One slot per ordinal through 511. Slot 266 is USER.SetMessageQueue;
        # stopping at 199 left that call in the zero fill, and the RETF pad
        # returned into segment 13 at the LES (0xCBEA) with a frame of 0xCB.
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
                self._note_call(sel, disp, fl, t1, t2)
            elif atype == 5 and stub is not None:
                self.arena.write(sel, disp, struct.pack("<H", stub))
            disp = nxt

    def _module_names(self):
        nmod = _u16(self.file, self.ne + 0x1E)
        modref = _u16(self.file, self.ne + 0x28)
        imp = _u16(self.file, self.ne + 0x2A)
        names = []
        for i in range(nmod):
            at = self.ne + imp + _u16(self.file, self.ne + modref + 2 * i)
            n = self.file[at]
            names.append(self.file[at + 1:at + 1 + n].decode("ascii", "replace"))
        return names

    def _note_call(self, sel, disp, fl, module, ordinal):
        if not fl & 1 or disp < 1 or module < 1 or module > len(self.modnames):
            return
        if self.arena.read(sel, disp - 1, 1) != b"\x9a":
            return
        name = self.modnames[module - 1]
        self.callers[(sel, (disp + 4) & 0xFFFF)] = (name, ordinal)
        pop = POP.get(name, {}).get(ordinal)
        if pop is None:
            return
        self.sites[(sel, (disp + 4) & 0xFFFF)] = (name, ordinal, pop)

    def _pushed(self, sel, ret_ip):
        if sel not in self.arena.segs or ret_ip < 2:
            return 0
        start = max(0, ret_ip - 24)
        buf = self.arena.read(sel, start, ret_ip - start)
        call = 5 if len(buf) >= 5 and buf[-5] == 0x9A else 0
        if not call:
            return 0
        end = len(buf) - call
        run = 0
        one = set(range(0x50, 0x58)) | {0x06, 0x0E, 0x16, 0x1E}
        while end > 0:
            op = buf[end - 1]
            if op in one:
                run += 2
                end -= 1
                continue
            if end >= 2 and buf[end - 2] == 0x6A:
                run += 2
                end -= 2
                continue
            if end >= 3 and buf[end - 3] == 0x68:
                run += 2
                end -= 3
                continue
            if end >= 3 and buf[end - 3] == 0xFF and ((buf[end - 2] >> 3) & 7) == 6 and (buf[end - 2] >> 6) == 1:
                run += 2
                end -= 3
                continue
            if end >= 4 and buf[end - 4] == 0xFF and ((buf[end - 3] >> 3) & 7) == 6:
                modrm = buf[end - 3]
                mod = modrm >> 6
                rm = modrm & 7
                if mod == 2 or (mod == 0 and rm == 6):
                    run += 2
                    end -= 4
                    continue
            break
        return run

    def _fix_ret(self, ordinal):
        uc = self.uc
        ss = uc.reg_read(UC_X86_REG_SS)
        sp = uc.reg_read(UC_X86_REG_SP)
        ret_ip, ret_cs = struct.unpack("<HH", self.arena.read(ss, sp, 4))
        site = self.sites.get((ret_cs, ret_ip))
        pop = site[2] if site else self._pushed(ret_cs, ret_ip)
        self.pending = site
        self.caller = (ret_cs, ret_ip)
        # Snapshot arguments first. Sliding the return address overwrites
        # the words it lands on, and the handlers read them after this.
        self._args = self.arena.read(ss, (sp + 4) & 0xFFFF, 32)
        # Unicorn translates the thunk before this hook returns, so a
        # rewritten retf immediate stays 0. Move the return address past
        # the Pascal arguments and let the baked-in retf 0 pop it.
        if pop:
            ret = self.arena.read(ss, sp, 4)
            dest = (sp + pop) & 0xFFFF
            self.arena.write(ss, dest, ret)
            uc.reg_write(UC_X86_REG_SP, dest)

    def _word(self, n):
        if self._args and (n + 1) * 2 <= len(self._args):
            return _u16(self._args, n * 2)
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = self.uc.reg_read(UC_X86_REG_SP)
        return _u16(self.arena.read(ss, sp + 4 + n * 2, 2), 0)

    def _galloc(self, size, zero):
        size = size or 1
        if size > 0xFFFF:
            size = 0xFFFF
        blob = bytes(size) if zero else b""
        sel = self.arena.alloc_selector(size, 0x92, blob)
        self.heap[sel] = size
        return sel

    def _kernel_heap(self, ordinal):
        """GlobalAlloc/Lock/Free. A fake 0000:0001 pointer was written through the GDT."""
        uc = self.uc
        if ordinal == 15:
            size = self._word(0) | (self._word(1) << 16)
            flags = self._word(2)
            handle = self._galloc(size, flags & 0x40)
            uc.reg_write(UC_X86_REG_AX, handle)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 16:
            handle = self._word(3)
            size = self._word(1) | (self._word(2) << 16)
            flags = self._word(0)
            old = self.heap.get(handle, 0)
            new = self._galloc(size, flags & 0x40)
            if old and handle in self.arena.segs:
                self.arena.write(new, 0, self.arena.read(handle, 0, min(old, size or 1)))
            uc.reg_write(UC_X86_REG_AX, new)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 17:
            self.heap.pop(self._word(0), None)
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 18:
            handle = self._word(0)
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, handle if handle in self.heap else 0)
            return True
        if ordinal == 19:
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        if ordinal == 21:
            # GlobalHandle: AX is the handle, DX the selector, and here they
            # are one value. TB80UTL keeps DX as a heap's selector; DX = 0
            # left TB80BAS allocating with DS = 0.
            sel = self._word(0)
            known = sel if sel in self.arena.segs else 0
            uc.reg_write(UC_X86_REG_AX, known)
            uc.reg_write(UC_X86_REG_DX, known)
            return True
        if ordinal == 20:
            size = self.heap.get(self._word(0), 0)
            uc.reg_write(UC_X86_REG_AX, size & 0xFFFF)
            uc.reg_write(UC_X86_REG_DX, (size >> 16) & 0xFFFF)
            return True
        if ordinal == 5:
            return self._local_alloc(self._word(1), self._word(0))
        if ordinal == 6:
            return self._local_realloc(self._word(2), self._word(1), self._word(0))
        if ordinal == 7:
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        if ordinal == 8:
            uc.reg_write(UC_X86_REG_AX, self._word(0))
            return True
        if ordinal == 9:
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        if ordinal == 10:
            ds = uc.reg_read(UC_X86_REG_DS)
            heap = self.local.get(ds, {})
            uc.reg_write(UC_X86_REG_AX, heap.get("sizes", {}).get(self._word(0), 0))
            return True
        if ordinal in (23, 24):
            # LockSegment / UnlockSegment. -1 means the current data segment.
            seg = self._word(0)
            if seg == 0xFFFF:
                seg = uc.reg_read(UC_X86_REG_DS)
            uc.reg_write(UC_X86_REG_AX, seg if ordinal == 23 else 0)
            return True
        return False

    def _local_init(self, seg, start, end):
        info = self.arena.segs.get(seg)
        if not info:
            return False
        limit = info["size"]
        if start == 0:
            # Borland passes (ds, 0, heapSize). The heap sits after the statics.
            heap = end or 0x100
            start = max(0, limit - heap)
            end = limit
        end = min(end or limit, limit)
        start = min(start, end)
        self.local[seg] = {"start": start, "end": end, "next": start, "sizes": {}}
        return True

    def _local_heap(self, seg):
        if seg not in self.local:
            info = self.arena.segs.get(seg)
            if not info:
                return None
            self._local_init(seg, 0, min(info["size"], 0x1000))
        return self.local[seg]

    def _local_alloc(self, flags, size):
        uc = self.uc
        ds = uc.reg_read(UC_X86_REG_DS)
        heap = self._local_heap(ds)
        if heap is None or size == 0:
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        at = (heap["next"] + 3) & ~3
        if at + size > heap["end"] and not self._local_grow(ds, heap, at + size):
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        if flags & 0x40:
            self.arena.write(ds, at, b"\x00" * size)
        heap["sizes"][at] = size
        heap["next"] = at + size
        uc.reg_write(UC_X86_REG_AX, at)
        uc.reg_write(UC_X86_REG_DX, 0)
        return True

    def _local_grow(self, seg, heap, need):
        """Windows grows a full DGROUP up to 64K before LocalAlloc fails.

        TB80BAS's NE header asks for a small heap. Without the grow it fell
        back to the task's DS, wrote its record there, and read it back
        through its own DS as zeros.
        """
        info = self.arena.segs[seg]
        if heap["end"] != info["size"] or need > 0x10000:
            return False
        self.arena.grow(seg, (need + 0xFFF) & ~0xFFF)
        heap["end"] = self.arena.segs[seg]["size"]
        # The descriptor moved, and DS or ES still caches the old base.
        # Unicorn loads a segment register written from the host as a
        # real-mode paragraph, so the guest has to reload it: the thunk's
        # retf goes through a stub that does, then returns to the caller.
        if seg in (self.uc.reg_read(UC_X86_REG_DS), self.uc.reg_read(UC_X86_REG_ES)):
            self._return_through_reload()
        return True

    def _return_through_reload(self):
        if not getattr(self, "reload_sel", 0):
            stub = bytes([
                0x50,              # push ax
                0x8C, 0xD8,        # mov ax, ds
                0x8E, 0xD8,        # mov ds, ax
                0x8C, 0xC0,        # mov ax, es
                0x8E, 0xC0,        # mov es, ax
                0x58,              # pop ax
                0xCB,              # retf
            ])
            self.reload_sel = self.arena.alloc_selector(0x10, 0x9A, stub)
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = (self.uc.reg_read(UC_X86_REG_SP) - 4) & 0xFFFF
        self.arena.write(ss, sp, struct.pack("<HH", 0, self.reload_sel))
        self.uc.reg_write(UC_X86_REG_SP, sp)

    def _local_realloc(self, handle, size, flags):
        uc = self.uc
        ds = uc.reg_read(UC_X86_REG_DS)
        heap = self._local_heap(ds)
        old = heap["sizes"].get(handle, 0) if heap else 0
        if not self._local_alloc(flags, size or 1):
            return True
        new = uc.reg_read(UC_X86_REG_AX)
        if old and new and ds in self.arena.segs:
            self.arena.write(ds, new, self.arena.read(ds, handle, min(old, size or 1)))
        return True

    def _kernel_file(self, ordinal):
        uc = self.uc
        if ordinal == 74:
            style = self._word(0)
            path = self._string(self._word(4), self._word(3))
            if style & OF_REOPEN:
                # The name is the szPathName an earlier OpenFile left in
                # the OFSTRUCT; lpFileName is not read.
                path = self._string(self._word(2), (self._word(1) + 8) & 0xFFFF)
            self.opens.append(path)
            self.open_styles.append((path, style))
            print(f"  open {path}", file=sys.stderr, flush=True)
            full = path if path[1:2] == ":" else "C:\\TOOLBOOK\\" + path.lstrip("\\")
            if style & OF_PARSE:
                # Windows only qualifies the name. Nothing is opened.
                self._ofstruct(full, 0)
                uc.reg_write(UC_X86_REG_AX, 0)
                return True
            handle = self._take_file(path)
            self._ofstruct(full, 0 if handle is not None else 2)
            if handle is not None and style & OF_EXIST:
                # Opened and closed again; the handle is only a success flag.
                self.files.pop(handle, None)
                self.pos.pop(handle, None)
            uc.reg_write(UC_X86_REG_AX, handle if handle is not None else 0xFFFF)
            return True
        if ordinal == 85:
            path = self._string(self._word(2), self._word(1))
            self.opens.append(path)
            print(f"  lopen {path}", file=sys.stderr, flush=True)
            handle = self._take_file(path)
            uc.reg_write(UC_X86_REG_AX, handle if handle is not None else 0xFFFF)
            return True
        if ordinal == 82:
            handle = self._word(3)
            count = self._word(0)
            blob = self.files.get(handle, b"")
            pos = self.pos.get(handle, 0)
            chunk = blob[pos:pos + count]
            self.pos[handle] = pos + len(chunk)
            if chunk:
                self.arena.write(self._word(2), self._word(1), chunk)
            uc.reg_write(UC_X86_REG_AX, len(chunk))
            return True
        if ordinal == 84:
            handle = self._word(3)
            pos = self._word(1) | (self._word(2) << 16)
            origin = self._word(0)
            blob = self.files.get(handle, b"")
            cur = self.pos.get(handle, 0)
            if origin == 0:
                new = pos
            elif origin == 1:
                new = cur + struct.unpack("<i", struct.pack("<I", pos))[0]
            else:
                new = len(blob) + struct.unpack("<i", struct.pack("<I", pos))[0]
            self.pos[handle] = new
            uc.reg_write(UC_X86_REG_AX, new & 0xFFFF)
            uc.reg_write(UC_X86_REG_DX, (new >> 16) & 0xFFFF)
            return True
        if ordinal == 81:
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        return False

    def _ofstruct(self, full, error):
        """OpenFile's OFSTRUCT: cBytes, fFixedDisk, nErrCode, 4 reserved,
        szPathName[128]. The runtime reads the name back from it."""
        seg, off = self._word(2), self._word(1)
        if seg not in self.arena.segs:
            return
        name = full.encode("latin1", "replace")[:127]
        self.arena.write(seg, off, struct.pack("<BBHI", 136, 1, error, 0) + name + b"\x00")

    def _take_file(self, path):
        low = path.lower().replace("/", "\\")
        if low.endswith((".tbk", ".sbk")):
            blob = self.book_bytes
        else:
            blob = self._ini_bytes(low)
        if blob is None:
            return None
        handle = self.next_handle
        self.next_handle += 1
        self.files[handle] = blob
        self.pos[handle] = 0
        return handle

    def _ini_bytes(self, low):
        """An INI from TBK_INI, matched by its file name. Unset means 0xFFFF.

        Read at the moment of the open, like TBK_UNPACKED for LoadLibrary.
        Only a name ending in .ini, or one of SUPPLIED, is looked for. The
        directory is the caller's; the host never writes an INI and never
        looks in /Toolbook/.
        """
        root = os.environ.get("TBK_INI", "")
        base = low.split("\\")[-1]
        if not root or not (base.endswith(".ini") or base in SUPPLIED) or not os.path.isdir(root):
            return None
        for entry in os.listdir(root):
            if entry.lower() == base:
                return open(os.path.join(root, entry), "rb").read()
        return None

    def _copy_to(self, seg, offset, text, limit):
        raw = text.encode("latin1", "replace")[: max(limit - 1, 0)] + b"\x00"
        if seg in self.arena.segs and raw:
            self.arena.write(seg, offset, raw[:limit or len(raw)])
        return len(raw) - 1

    def _index_module(self, handle, data, name):
        if not handle or handle in self.mods:
            return handle
        self.mods[handle] = {
            "name": name,
            "resources": self._parse_resources(data),
        }
        return handle

    def _parse_resources(self, data):
        ne = _u16(data, 0x3C)
        rsrc = _u16(data, ne + 0x24)
        if not rsrc:
            return []
        rt = ne + rsrc
        align = _u16(data, rt)
        i = rt + 2
        items = []
        while i + 8 <= len(data):
            tid, count = struct.unpack_from("<HH", data, i)
            if tid == 0:
                break
            i += 8
            rtype = self._res_table_id(data, rt, tid)
            for _ in range(count):
                if i + 12 > len(data):
                    return items
                off, length, flags, ident = struct.unpack_from("<HHHH", data, i)
                i += 12
                blob = data[(off << align):(off << align) + (length << align)]
                items.append({
                    "type": rtype,
                    "name": self._res_table_id(data, rt, ident),
                    "bytes": blob,
                })
        return items

    def _res_table_id(self, data, rt, ident):
        if ident & 0x8000:
            return ("int", ident & 0x7FFF)
        at = rt + ident
        if at >= len(data):
            return ("str", "")
        n = data[at]
        return ("str", data[at + 1:at + 1 + n].decode("latin1", "replace").lower())

    def _string_from_mod(self, mod, sid):
        """NE string table: block (id >> 4) + 1, sixteen counted strings."""
        if not mod:
            return None
        block = (sid >> 4) + 1
        index = sid & 0xF
        blob = None
        for item in mod.get("resources", []):
            if item["type"] == ("int", 6) and item["name"] == ("int", block):
                blob = item["bytes"]
                break
        if not blob:
            return None
        at = 0
        for i in range(16):
            if at >= len(blob):
                return None
            n = blob[at]
            at += 1
            raw = blob[at:at + n]
            at += n
            if i == index:
                return raw.decode("latin1", "replace")
        return None

    def _string_resource(self, hinst, sid):
        mod = self.mods.get(hinst)
        if mod is None:
            mod = self.mods.get(self.uc.reg_read(UC_X86_REG_DS))
        text = self._string_from_mod(mod, sid)
        if text:
            return text
        for other in self.mods.values():
            if other is mod:
                continue
            text = self._string_from_mod(other, sid)
            if text:
                return text
        return None

    def _res_arg(self, seg, off):
        # MAKEINTRESOURCE: a zero segment means the offset is the integer id.
        if seg == 0:
            return ("int", off)
        return ("str", self._string(seg, off).lower())

    def _library_bytes(self, name):
        base = name.replace("/", "\\").split("\\")[-1]
        low = base.lower()
        stem = low[:-4] if low.endswith(".dll") else low
        aliases = {
            "tb80enu": "TB80ENU1.DLL",
            "tb80enu1": "TB80ENU1.DLL",
            "tb80enu2": "TB80ENU2.DLL",
        }
        root = os.environ.get("TBK_UNPACKED", "")
        filename = aliases.get(stem)
        if filename is None and os.path.isdir(root):
            wanted = {low, stem + ".dll", stem + ".exe"}
            for entry in os.listdir(root):
                if entry.lower() in wanted:
                    filename = entry
                    break
        if not filename:
            return None, ""
        path = os.path.join(root, filename)
        if not os.path.isfile(path):
            return None, ""
        return open(path, "rb").read(), filename

    def _system_module(self, name):
        """The handle of a module Windows has loaded before any task runs.

        LoadLibrary("KERNEL") returns KERNEL's handle in Windows. There is
        no file behind these here, so the handle is a small selector and the
        module has no exports: GetProcAddress on it returns 0, the answer
        for the WOW thunk calls TB80W16 looks for on Windows 3.1.
        """
        stem = name.replace("/", "\\").split("\\")[-1].upper()
        stem = stem[:-4] if stem.endswith((".DLL", ".EXE")) else stem
        if stem not in SYSTEM_MODULES:
            return None
        for handle, mod in self.mods.items():
            if mod["name"] == stem:
                return handle
        handle = self.arena.alloc_selector(16, 0x92, b"\x00" * 16)
        self.mods[handle] = {"name": stem, "resources": [], "procs": {}, "ords": {}}
        return handle

    def _load_library(self, name):
        system = self._system_module(name)
        if system:
            return system
        for mod in self.mods.values():
            if mod["name"].lower() == name.lower():
                return next(h for h, m in self.mods.items() if m is mod)
        data, filename = self._library_bytes(name)
        if data is None:
            return 2
        handle = self.arena.alloc_selector(16, 0x92, b"\x00" * 16)
        self._index_module(handle, data, filename or name)
        return handle

    def _kernel_res(self, ordinal):
        """LoadLibrary plus the resource calls the language DLL is read through."""
        uc = self.uc
        if ordinal == 95:
            name = self._string(self._word(1), self._word(0))
            handle = self._load_library(name)
            print(f"  load {name!r} -> {handle:#x}", file=sys.stderr, flush=True)
            uc.reg_write(UC_X86_REG_AX, handle)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 60:
            mod = self.mods.get(self._word(4) or self.exe_inst)
            want_t = self._res_arg(self._word(1), self._word(0))
            want_n = self._res_arg(self._word(3), self._word(2))
            found = None
            if mod:
                for item in mod["resources"]:
                    if item["type"] == want_t and item["name"] == want_n:
                        found = item
                        break
            if found is None:
                uc.reg_write(UC_X86_REG_AX, 0)
                uc.reg_write(UC_X86_REG_DX, 0)
                return True
            self.hrsrc[self.next_hrsrc] = found
            uc.reg_write(UC_X86_REG_AX, self.next_hrsrc)
            uc.reg_write(UC_X86_REG_DX, 0)
            self.next_hrsrc += 1
            return True
        if ordinal == 64:
            item = self.hrsrc.get(self._word(0))
            if item is None:
                uc.reg_write(UC_X86_REG_AX, 0xFFFF)
                return True
            handle = self.next_handle
            self.next_handle += 1
            self.files[handle] = item["bytes"]
            self.pos[handle] = 0
            uc.reg_write(UC_X86_REG_AX, handle)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 61:
            item = self.hrsrc.get(self._word(0))
            if item is None:
                uc.reg_write(UC_X86_REG_AX, 0)
                return True
            sel = self._galloc(len(item["bytes"]) or 1, True)
            if item["bytes"]:
                self.arena.write(sel, 0, item["bytes"])
            uc.reg_write(UC_X86_REG_AX, sel)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 62:
            handle = self._word(0)
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, handle if handle in self.heap else 0)
            return True
        if ordinal == 63:
            uc.reg_write(UC_X86_REG_AX, 0)
            return True
        if ordinal == 65:
            item = self.hrsrc.get(self._word(0))
            size = len(item["bytes"]) if item else 0
            uc.reg_write(UC_X86_REG_AX, size & 0xFFFF)
            uc.reg_write(UC_X86_REG_DX, (size >> 16) & 0xFFFF)
            return True
        return False

    def _kernel_proc(self, ordinal):
        """Pointers must be null or a real thunk. AX=1 was called as 0000:0001."""
        uc = self.uc
        # IsBadCodePtr(lpfn). AX=1 is "bad": TB80BAS skipped its file
        # manager's handler and the book open failed.
        if ordinal == 336:
            off, sel = self._word(0), self._word(1)
            info = self.arena.segs.get(sel)
            good = info is not None and info["access"] & 0x08 and off <= info["limit"]
            uc.reg_write(UC_X86_REG_AX, 0 if good else 1)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        # WinExec(cmdline, show). TB80BAS starts the book file manager,
        # TB80NET.EXE, a second Win16 task that calls back into TB80BAS with
        # its window. This host runs one task, so the call is the wall.
        if ordinal == 166:
            cmd = self._string(self._word(2), self._word(1))
            self.fault = f"winexec {cmd!r} show {self._word(0)}"
            uc.emu_stop()
            return True
        if ordinal == 50:
            noff, nseg, hmod = self._word(0), self._word(1), self._word(2)
            mod = self.mods.get(hmod) or (self.mods.get(self.exe_inst) if hmod == 0 else None)
            if nseg == 0:
                hit = (mod or {}).get("ords", {}).get(noff)
            else:
                hit = (mod or {}).get("procs", {}).get(self._string(nseg, noff).lower())
            uc.reg_write(UC_X86_REG_AX, hit[0] if hit else 0)
            uc.reg_write(UC_X86_REG_DX, hit[1] if hit else 0)
            return True
        if ordinal == 52:
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal != 51:
            return False
        hinst = self._word(0)
        off, seg = self._word(1), self._word(2)
        ds = hinst if hinst in self.arena.segs else self.exe_inst
        if not getattr(self, "pi_sel", 0):
            self.pi_sel = self.arena.alloc_selector(0x1000, 0x9A, bytes(0x1000))
            self.pi_at = 0
        at = self.pi_at
        if not seg or at + 10 > 0x1000:
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        thunk = bytes([
            0xB8, ds & 0xFF, (ds >> 8) & 0xFF,
            0x8E, 0xD8,
            0xEA, off & 0xFF, (off >> 8) & 0xFF, seg & 0xFF, (seg >> 8) & 0xFF,
        ])
        self.arena.write(self.pi_sel, at, thunk)
        self.pi_at = at + 10
        uc.reg_write(UC_X86_REG_AX, at)
        uc.reg_write(UC_X86_REG_DX, self.pi_sel)
        return True

    def _user(self, ordinal):
        # lstrcmpi(lpsz1, lpsz2), Pascal, pop 8. AX = 1 said "greater" for
        # every pair: TB80NET never matched its command line "ToolBook".
        if ordinal == 471:
            one = self._cstring(self._word(3), self._word(2)).lower()
            two = self._cstring(self._word(1), self._word(0)).lower()
            self.uc.reg_write(UC_X86_REG_AX, (one > two) - (one < two) & 0xFFFF)
            self.uc.reg_write(UC_X86_REG_DX, 0)
            return True
        # LoadString(hinst, id, far buf, cch). The call sites push 10 bytes.
        # AX=1 left the buffer empty, so the caller treated the string as missing.
        if ordinal == 176:
            cch = self._word(0)
            off, seg = self._word(1), self._word(2)
            sid = self._word(3)
            text = self._string_resource(self._word(4), sid)
            if not text or cch < 1 or seg not in self.arena.segs:
                self.uc.reg_write(UC_X86_REG_AX, 0)
                self.uc.reg_write(UC_X86_REG_DX, 0)
                return True
            n = self._copy_to(seg, off, text, cch)
            print(f"  loadstring {sid:#x} {text[:48]!r}", file=sys.stderr, flush=True)
            self.uc.reg_write(UC_X86_REG_AX, n)
            self.uc.reg_write(UC_X86_REG_DX, 0)
            return True
        # MessageBox(hwnd, text, caption, type). AX=1 is IDOK: TB80UTL's
        # internal-error box says "Press OK to continue", so the runtime ran
        # on past its own assertion. The box is where the run stops.
        if ordinal == 1:
            kind = self._word(0)
            caption = self._string(self._word(2), self._word(1))
            text = self._box_text(self._word(4), self._word(3))
            self.fault = f"message box {caption!r} type {kind:#x}: {text!r}"
            self.uc.emu_stop()
            return True
        # wsprintf(out, fmt, ...) is cdecl, so the caller pops. AX=1 left
        # the buffer as it was, and the error box the runtime raised read
        # as garbage.
        if ordinal == 420:
            out = (self._word(1), self._word(0))
            fmt = self._box_text(self._word(3), self._word(2))
            text = self._wsprintf(fmt, 4).encode("latin1", "replace")[:1023]
            if out[0] in self.arena.segs:
                self.arena.write(out[0], out[1], text + b"\x00")
            self.uc.reg_write(UC_X86_REG_AX, len(text))
            self.uc.reg_write(UC_X86_REG_DX, 0)
            return True
        # GetSystemMetrics. 0x29 is SM_PENWINDOWS; a nonzero handle makes the
        # door call RegisterPenApp through a null pointer.
        if ordinal != 179:
            return False
        metric = self._word(0)
        value = {
            0: 800, 1: 600, 2: 16, 3: 16, 4: 19,
            5: 1, 6: 1, 7: 3, 8: 3,
            11: 32, 12: 32, 13: 32, 14: 32, 15: 18,
            16: 800, 17: 572, 19: 1, 20: 16, 21: 16,
            30: 18, 31: 18, 32: 4, 33: 4,
            41: 0, 42: 0, 43: 2,
        }.get(metric, 0)
        self.uc.reg_write(UC_X86_REG_AX, value)
        self.uc.reg_write(UC_X86_REG_DX, 0)
        return True

    def _keyboard(self, ordinal):
        # AnsiToOem(src, dst) and OemToAnsi(src, dst). AX=1 copied nothing,
        # and TB80BAS opened the book under whatever its stack buffer held.
        if ordinal not in (5, 6):
            return False
        codecs = ("cp1252", "cp437") if ordinal == 5 else ("cp437", "cp1252")
        dst, src = (self._word(1), self._word(0)), (self._word(3), self._word(2))
        text = self._string(*src).encode("latin1")
        out = bytearray()
        for ch in text:
            try:
                out += bytes([ch]).decode(codecs[0]).encode(codecs[1])
            except (UnicodeDecodeError, UnicodeEncodeError):
                out.append(ch)
        if dst[0] in self.arena.segs:
            self.arena.write(dst[0], dst[1], bytes(out) + b"\x00")
        self.uc.reg_write(UC_X86_REG_AX, 0xFFFF)
        self.uc.reg_write(UC_X86_REG_DX, 0)
        return True

    def _com_unk(self):
        """One IUnknown whose Query/AddRef/Release just return."""
        pair = getattr(self, "_com_pair", None)
        if pair:
            return pair
        code = self.arena.alloc_selector(16, 0x9A, b"\xb8\x01\x00\xcb" + bytes(12))
        vt = bytearray(24)
        for slot in range(6):
            struct.pack_into("<HH", vt, slot * 4, 0, code)
        vsel = self.arena.alloc_selector(len(vt), 0x92, bytes(vt))
        obj = struct.pack("<HHH", 0, vsel, 1) + bytes(10)
        osel = self.arena.alloc_selector(16, 0x92, obj)
        self._com_pair = (0, osel)
        return self._com_pair

    def _store(self, seg, off, data):
        info = self.arena.segs.get(seg)
        if not info or off + len(data) > info["size"]:
            return
        self.arena.write(seg, off, data)

    def _oleapi(self):
        """HRESULT 0. AX=1 made CreateDispTypeInfo fail and Release(NULL)."""
        mod, ordinal = self.pending[0], self.pending[1]
        uc = self.uc
        if mod == "OLE2DISP" and ordinal in (31, 32):
            off, seg = self._com_unk()
            self._store(self._word(1), self._word(0), struct.pack("<HH", off, seg))
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if (mod == "COMPOBJ" and ordinal == 5) or (mod == "OLE2DISP" and ordinal == 35):
            self._store(self._word(1), self._word(0), struct.pack("<I", 1))
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if (mod == "COMPOBJ" and ordinal == 6) or (mod == "OLE2DISP" and ordinal == 36):
            uc.reg_write(UC_X86_REG_AX, 0)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        return False

    def _kernel_string(self, ordinal):
        """Far-string helpers. A stub return of 1 was loaded as a selector."""
        uc = self.uc
        if ordinal == 88:
            dst_seg, dst_off = self._word(3), self._word(2)
            src = self._string(self._word(1), self._word(0))
            self._copy_to(dst_seg, dst_off, src, 0xFFFF)
            uc.reg_write(UC_X86_REG_AX, dst_off)
            uc.reg_write(UC_X86_REG_DX, dst_seg)
            return True
        if ordinal == 89:
            dst_seg, dst_off = self._word(3), self._word(2)
            dst = self._string(dst_seg, dst_off)
            src = self._string(self._word(1), self._word(0))
            self._copy_to(dst_seg, dst_off, dst + src, 0xFFFF)
            uc.reg_write(UC_X86_REG_AX, dst_off)
            uc.reg_write(UC_X86_REG_DX, dst_seg)
            return True
        if ordinal == 90:
            text = self._string(self._word(1), self._word(0))
            uc.reg_write(UC_X86_REG_AX, len(text))
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 47:
            uc.reg_write(UC_X86_REG_AX, self.segs[139])
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 49:
            seg, off = self._word(2), self._word(1)
            name = self._copy_to(seg, off, "C:\\TOOLBOOK\\TB80RTM.EXE", self._word(0) or 1)
            uc.reg_write(UC_X86_REG_AX, name)
            return True
        if ordinal in (134, 135):
            seg, off = self._word(2), self._word(1)
            path = "C:\\WINDOWS" if ordinal == 134 else "C:\\WINDOWS\\SYSTEM"
            n = self._copy_to(seg, off, path, self._word(0) or 1)
            uc.reg_write(UC_X86_REG_AX, n)
            uc.reg_write(UC_X86_REG_DX, 0)
            return True
        if ordinal == 137:
            msg = self._string(self._word(1), self._word(0))
            print(f"  fatal {msg!r}", file=sys.stderr, flush=True)
            self.fault = f"fatal {msg!r}"
            uc.emu_stop()
            return True
        return False

    def _import_stub(self, fl, module, target):
        # bits 0-1 == 3 is an OSFIXUP. Its chain can run through an import
        # site; writing a stub there replaces the import.
        if (fl & 3) == 3:
            return None
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
        before = len(self.ax1)
        self._answer(uc, ordinal)
        cs, ip = self.caller or (0, 0)
        module = self.callers.get((cs, ip), ("?", ordinal))[0]
        words = [_u16(self._args, n * 2) if (n + 1) * 2 <= len(self._args) else 0 for n in range(4)]
        regs = {name: uc.reg_read(reg) for name, reg in REGS}
        self.last_call = (module, ordinal, cs, ip, words, regs, len(self.ax1) > before)

    def _answer(self, uc, ordinal):
        self._fix_ret(ordinal)
        self.calls.append(ordinal)
        if len(self.calls) <= 16:
            print(f"  api ordinal {ordinal}", file=sys.stderr, flush=True)
        if ordinal == INITTASK and self.startup == 0:
            self.startup = 1
            # Windows' InitTask makes the PSP tail ASCIIZ. The C startup hands
            # ES:BX to WinMain as lpCmdLine, and TB80RTM's name parser stops
            # only at space, tab or NUL: with the CR it opened 'fixture.tbk\r'.
            tail = self.arena.read(self.psp, 0x81, 0x7F)
            if b"\r" in tail:
                self.arena.write(self.psp, 0x81 + tail.index(b"\r"), b"\x00")
            uc.reg_write(UC_X86_REG_AX, 1)
            uc.reg_write(UC_X86_REG_BX, 0x80)
            uc.reg_write(UC_X86_REG_CX, 0x1000)
            uc.reg_write(UC_X86_REG_DX, 1)
            uc.reg_write(UC_X86_REG_SI, 0)
            uc.reg_write(UC_X86_REG_DI, self.segs[139])
            uc.reg_write(UC_X86_REG_ES, self.psp)
            return
        if ordinal == 3 and (not self.pending or self.pending[0] == "KERNEL"):
            uc.reg_write(UC_X86_REG_AX, 0x0A03)
            return
        if self.pending and self.pending[0] == "TB80UTL" and ordinal == 3:
            self._strmgr()
            return
        if ordinal == 132:
            # Enhanced-mode 386: PMODE|CPU386|ENHANCED|80x87|PAGING.
            uc.reg_write(UC_X86_REG_AX, 0x0C25)
            uc.reg_write(UC_X86_REG_DX, 0)
            return
        if self.pending and self.pending[0] == "KERNEL" and ordinal == 1:
            self.fault = "FatalExit"
            uc.emu_stop()
            return
        if self.pending and self.pending[0] == "KERNEL" and ordinal == 4:
            # LocalInit(segment, start, end). start 0 means end is the size.
            seg = self._word(2) or uc.reg_read(UC_X86_REG_DS)
            self._local_init(seg, self._word(1), self._word(0))
            uc.reg_write(UC_X86_REG_AX, 1)
            return
        if self.pending and self.pending[0] == "KERNEL" and self._kernel_heap(ordinal):
            return
        if self.pending and self.pending[0] == "KERNEL" and self._kernel_file(ordinal):
            return
        if self.pending and self.pending[0] == "KERNEL" and self._kernel_string(ordinal):
            return
        if self.pending and self.pending[0] == "KERNEL" and self._kernel_res(ordinal):
            return
        if self.pending and self.pending[0] == "KERNEL" and self._kernel_proc(ordinal):
            return
        if self.pending and self.pending[0] == "USER" and self._user(ordinal):
            return
        if self.pending and self.pending[0] == "KEYBOARD" and self._keyboard(ordinal):
            return
        if self.pending and self.pending[0] in ("COMPOBJ", "OLE2", "OLE2DISP") and self._oleapi():
            return
        # KERNEL.102 is DOS3Call. The CRT exit path sets AH=4Ch and calls
        # it instead of int 21h when __WINFLAGS says protected mode. A
        # stub return made exit() fall into R6021.
        if self.pending and self.pending[0] == "KERNEL" and ordinal == 102:
            if ((uc.reg_read(UC_X86_REG_AX) >> 8) & 0xFF) == 0x4C:
                self._dos()
                return
        self._note_ax1(ordinal)
        uc.reg_write(UC_X86_REG_AX, 1)
        uc.reg_write(UC_X86_REG_DX, 0)

    def _note_ax1(self, ordinal):
        """Every far call that falls through to the AX = 1 default, as a line.

        The module comes from the reloc that named the call site, not from
        the pop table, so a call with no pop size is still named.
        """
        cs, ip = self.caller or (0, 0)
        module = self.callers.get((cs, ip), ("?", ordinal))[0]
        words = [_u16(self._args, n * 2) if (n + 1) * 2 <= len(self._args) else 0 for n in range(4)]
        self.ax1.append(ax1_line(module, ordinal, words, cs, ip))

    def _strmgr(self):
        """TB80UTL.3 GETSTRMGRSTRING. Pascal, five words.

        length is the last push. An empty first byte at DS:0x41F2 is the
        check that jumps to the CRT exit, so a missing table still has to
        leave a string there. 0x0FBD is the product-name id.
        """
        length = self._word(0) or 1
        seg, off = self._word(2), self._word(1)
        key = (self._word(4) << 16) | self._word(3)
        text = self._manager_string(key)
        self._copy_to(seg, off, text, length)
        self.uc.reg_write(UC_X86_REG_AX, 1 if text else 0)
        self.uc.reg_write(UC_X86_REG_DX, 0)

    def _manager_string(self, key):
        return {
            0x0FBD: "ToolBook II",
        }.get(key, "ToolBook")

    def _on_intr(self, uc, intno, user):
        if intno == 0x21:
            self._dos()
            return
        if intno == 3:
            uc.emu_stop()
            return
        # int 2Fh AX = 150Bh asks MSCDEX whether drive CX is a CD-ROM, and
        # BX = ADADh back says MSCDEX is there. There is no MSCDEX: like DOS
        # with nothing on the multiplex, every register comes back as it was.
        if intno == 0x2F and uc.reg_read(UC_X86_REG_AX) == 0x150B:
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
        self.fault = f"int {intno:#x}"
        uc.emu_stop()

    def _dos(self):
        uc = self.uc
        ah = (uc.reg_read(UC_X86_REG_AX) >> 8) & 0xFF
        if ah == 0x3D:
            path = self._string(uc.reg_read(UC_X86_REG_DS), uc.reg_read(UC_X86_REG_DX))
            self.opens.append(path)
            print(f"  open {path}", file=sys.stderr)
            handle = self._take_file(path)
            if handle is None:
                uc.reg_write(UC_X86_REG_AX, 2)
                uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) | 1)
                return
            uc.reg_write(UC_X86_REG_AX, handle)
            self._clear()
            return
        if ah == 0x30:
            uc.reg_write(UC_X86_REG_AX, 5)
            self._clear()
            return
        if ah == 0x4C:
            self.fault = f"dos exit {uc.reg_read(UC_X86_REG_AX) & 0xFF:#x}"
            uc.emu_stop()
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

    def _cstring(self, sel, offset):
        """The whole NUL-terminated string, to the end of the segment."""
        if sel not in self.arena.segs:
            return ""
        size = self.arena.segs[sel]["size"]
        if offset >= size:
            return ""
        raw = self.arena.read(sel, offset, size - offset)
        return raw.split(b"\x00", 1)[0].decode("cp1252", "replace")

    def _string(self, sel, offset):
        if sel not in self.arena.segs:
            return ""
        return self.arena.read(sel, offset, 128).split(b"\x00", 1)[0].decode("latin1", "replace")

    def _box_text(self, sel, offset):
        info = self.arena.segs.get(sel)
        if info is None:
            return ""
        size = max(0, min(512, info["limit"] + 1 - offset))
        return self.arena.read(sel, offset, size).split(b"\x00", 1)[0].decode("latin1", "replace")

    def _wsprintf(self, fmt, n):
        """Win16 wsprintf. Arguments are stack words from _word(n) up; %s is a far pointer."""
        out = []
        pos = 0
        for m in re.finditer(r"%(%|([-#0]*)(\d*)(?:\.(\d+))?(l?)([sdiuxXc]))", fmt):
            out.append(fmt[pos:m.start()])
            pos = m.end()
            if m.group(1) == "%":
                out.append("%")
                continue
            flags, width, prec, long_, kind = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
            if kind == "s":
                off, sel = self._word(n), self._word(n + 1)
                n += 2
                value = self._box_text(sel, off)
                if prec:
                    value = value[:int(prec)]
            elif kind == "c":
                value = chr(self._word(n) & 0xFF)
                n += 1
            else:
                raw = self._word(n)
                n += 1
                bits = 16
                if long_:
                    raw |= self._word(n) << 16
                    n += 1
                    bits = 32
                if kind in "di" and raw >> (bits - 1):
                    raw -= 1 << bits
                value = {"x": f"{raw:x}", "X": f"{raw:X}"}.get(kind, str(raw))
                if flags and "#" in flags and kind in "xX" and raw:
                    value = "0x" + value
            if width:
                if "-" in flags:
                    value = value.ljust(int(width))
                elif "0" in flags and kind not in "sc":
                    value = value.rjust(int(width), "0")
                else:
                    value = value.rjust(int(width))
            out.append(value)
        out.append(fmt[pos:])
        return "".join(out)

    def _clear(self):
        self.uc.reg_write(UC_X86_REG_EFLAGS, self.uc.reg_read(UC_X86_REG_EFLAGS) & ~1)

    def _make_psp(self):
        """The fake PSP. The book name is the command tail at 0x80, the way
        DOS hands WinExec arguments across. Every guest read of the tail is
        recorded in tail_reads as (cs, ip, offset), so a run says whether
        the entry ever looked at the book name.
        """
        tail = (" " + os.path.basename(self.book)).encode("ascii") + b"\r"
        psp = bytearray(0x100)
        psp[0x80] = len(tail) - 1
        psp[0x81:0x81 + len(tail)] = tail
        self.psp = self.arena.alloc_selector(0x100, 0x92, bytes(psp))
        self.tail_reads = []
        base = self.arena.segs[self.psp]["base"]
        self.uc.hook_add(UC_HOOK_MEM_READ, self._on_tail, None, base + 0x80, base + 0xFF)
        return self.psp

    def _on_tail(self, uc, access, address, size, value, user):
        cs = uc.reg_read(UC_X86_REG_CS)
        ip = uc.reg_read(UC_X86_REG_IP)
        offset = address - self.arena.segs[self.psp]["base"]
        if len(self.tail_reads) < 64:
            self.tail_reads.append((cs, ip, offset))

    def run(self):
        self.build()
        self._make_psp()
        dgroup = self.segs[139]
        code = self.segs[2]
        # The GDT lives at linear 0 and selector 0x80 is segment 14.
        # A GDTR image at 0x80 wiped that descriptor, so every call to
        # segment 14 faulted with #GP at the LES-era far call.
        gdtr_at = 0xF0E0
        gdtr = struct.pack("<HI", 0xFFFF, 0)
        self.uc.mem_write(gdtr_at, gdtr)
        blob = bytes([
            0xB8, dgroup & 0xFF, (dgroup >> 8) & 0xFF, 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, self.stack_top & 0xFF, (self.stack_top >> 8) & 0xFF,
            0xEA, 0x5A, 0x03, code & 0xFF, (code >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, self.flat & 0xFF, (self.flat >> 8) & 0xFF,
        ]))
        self.uc.mem_write(0xF020, blob)
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        self.fault = ""
        try:
            self.uc.emu_start(0xF000, 0, timeout=20_000_000, count=2_000_000)
        except UcError as exc:
            if not self.fault:
                self.fault = str(exc)
        else:
            if not self.fault:
                self.fault = "returned"
        return self.last


def main():
    if len(sys.argv) < 3:
        print("usage: python3 -m tbpipeline_bf.nehost.pass04 TB80RTM.EXE book.tbk", file=sys.stderr)
        return 2
    image = sys.argv[1]
    book = sys.argv[2]
    host = Pass04(image, book)
    cs, ip, raw = host.run()
    print(f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}")
    print(f"opens: {host.opens or 'none'}")
    print(f"skipped {len(host.skipped)} far calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
