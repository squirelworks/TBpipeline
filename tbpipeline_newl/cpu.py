"""Run TB80RTM. ToolBook code is real. Windows is the layer."""

import struct
import time
from collections import deque
from pathlib import Path

from unicorn import (
    Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_BLOCK, UC_HOOK_INSN, UC_HOOK_MEM_READ,
    UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE,
)
from unicorn.x86_const import (
    UC_X86_INS_OUT, UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CS,
    UC_X86_REG_CX, UC_X86_REG_DI, UC_X86_REG_DX, UC_X86_REG_ES,
    UC_X86_REG_IP, UC_X86_REG_SI, UC_X86_REG_SP, UC_X86_REG_SS,
)

from .layer import EQUATES, TABLES, Gap, Layer, Refused
from .ne import load as ne_load
from .ne import imported_modules

TIMEOUT_US = 15_000_000

SYSTEM = ("KERNEL", "USER", "GDI", "SHELL", "KEYBOARD", "WIN87EM", "COMMDLG", "TOOLHELP", "COMPOBJ", "OLE2")


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


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


class Cpu:
    def __init__(self, root, book=None):
        self.root = Path(root)
        self.layer = Layer(book)
        self.selectors = {}
        self.gates = {}
        self.next_index = 1
        self.linear = 0x200000
        self.linked = 0
        self.uc = None
        self.stop = ""
        self.exe = None
        self.glock = {}
        self.packed = []  # self-loading files in --b whose segments are still packed
        self.ignored = []  # system-module files found in --b and not loaded
        self.recent = deque(maxlen=20)  # (cs, ip) of the last basic blocks
        self.blocks = {}  # linear base -> {"handle", "selector", "size", "written"}
        self._load()

    def _selector(self):
        sel = self.next_index * 8
        self.next_index += 1
        return sel

    def _load(self):
        images = {}
        for path in sorted(self.root.glob("*.EXE")) + sorted(self.root.glob("*.DLL")) + sorted(self.root.glob("*.exe")) + sorted(self.root.glob("*.dll")):
            try:
                images[path.name.upper()] = self._image(path)
            except ValueError:
                continue
        by_name = {}
        for image in images.values():
            if image["name"] in SYSTEM:
                # A KERNEL.EXE in --b is not Windows. System modules are the layer.
                self.ignored.append(image["path"])
                continue
            by_name[image["name"]] = image
            if image["name"] == "TB80RTM":
                self.exe = image
        if self.exe is None:
            exes = [img for img in images.values() if img["path"].upper().endswith(".EXE")]
            self.exe = exes[0] if exes else None
        self.images = by_name
        # A self-loading image (NE flag 0x0800) keeps its segments packed until
        # its own loader runs. newl does not run it, so those bytes are not code.
        self.packed = sorted(Path(img["path"]).name for img in by_name.values() if img["ne_flags"] & 0x0800)
        self._gates()
        self._place()
        self._link()

    def _image(self, path):
        data, ne = ne_load(path)
        shift = _u16(data, ne + 0x32)
        nseg = _u16(data, ne + 0x1C)
        segtab = ne + _u16(data, ne + 0x22)
        csip = struct.unpack_from("<I", data, ne + 0x14)[0]
        segments = []
        fixups = []
        for i in range(nseg):
            sector, size, flags, alloc = struct.unpack_from("<HHHH", data, segtab + i * 8)
            alloc = 0x10000 if alloc == 0 else alloc
            raw_size = 0x10000 if size == 0 else size
            start = sector << shift
            blob = bytearray(min(alloc, 0x10000))
            if not flags & 0x0008:
                chunk = data[start:start + raw_size]
                blob[:len(chunk)] = chunk[:len(blob)]
            segments.append({"index": i + 1, "flags": flags, "data": blob, "selector": 0, "base": 0})
            if flags & 0x0100 and raw_size and start + raw_size + 2 <= len(data):
                base = start
                count = _u16(data, base + raw_size)
                pos = base + raw_size + 2
                for _ in range(count):
                    if pos + 8 > len(data):
                        break
                    atype, fl, disp, t1, t2 = struct.unpack_from("<BBHHH", data, pos)
                    pos += 8
                    fixups.append((i + 1, atype, fl, disp, t1, t2))
        restab = ne + _u16(data, ne + 0x26)
        n = data[restab]
        name = data[restab + 1:restab + 1 + n].decode("ascii", "replace").upper()
        entries, names = self._entries(data, ne)
        return {
            "path": str(path), "name": name or path.stem.upper(), "data": data, "ne": ne,
            "entry_seg": (csip >> 16) & 0xFFFF, "entry_ip": csip & 0xFFFF,
            "ne_flags": _u16(data, ne + 0x0C), "auto": _u16(data, ne + 0x0E), "heap": _u16(data, ne + 0x10), "stack": _u16(data, ne + 0x12),
            "modules": [m.upper() for m in imported_modules(data, ne)],
            "entries": entries, "names": names, "segments": segments, "fixups": fixups,
        }

    def _entries(self, data, ne):
        off = ne + _u16(data, ne + 4)
        end = off + _u16(data, ne + 6)
        ordinal = 1
        entries = {}
        while off < end:
            count = data[off]
            off += 1
            if count == 0:
                break
            seg = data[off]
            off += 1
            for _ in range(count):
                if seg == 0:
                    ordinal += 1
                    continue
                if seg == 0xFF:
                    seg_i = data[off + 3]
                    ip = _u16(data, off + 4)
                    off += 6
                    entries[ordinal] = (seg_i, ip)
                else:
                    ip = _u16(data, off + 1)
                    off += 3
                    entries[ordinal] = (seg, ip)
                ordinal += 1
        names = {}

        def walk(at):
            while at < len(data):
                n = data[at]
                if n == 0:
                    break
                text = data[at + 1:at + 1 + n].decode("latin1", "replace")
                ord_ = _u16(data, at + 1 + n)
                if ord_:
                    names.setdefault(ord_, text)
                at += 1 + n + 2

        walk(ne + _u16(data, ne + 0x26))
        nrest = struct.unpack_from("<I", data, ne + 0x2C)[0]
        if 0 < nrest < len(data):
            walk(nrest)
        return entries, names

    def _gates(self):
        wanted = {name: set() for name in SYSTEM}
        for image in self.images.values():
            for _seg, _atype, fl, _disp, t1, t2 in image["fixups"]:
                if not fl & 1 or fl & 2 or (fl & 3) == 3:
                    continue
                if not 1 <= t1 <= len(image["modules"]):
                    continue
                module = image["modules"][t1 - 1]
                if module in wanted and t2 not in EQUATES.get(module, {}):
                    wanted[module].add(t2)
        for module, ordinals in wanted.items():
            for ordinal in TABLES.get(module, {}):
                ordinals.add(ordinal)
            if not ordinals:
                continue
            hi = max(ordinals)
            blob = bytearray((hi + 1) * 8)
            for ordinal in ordinals:
                spec = TABLES.get(module, {}).get(ordinal)
                stub = bytearray(8)
                stub[0:5] = bytes([0xBA, ordinal & 0xFF, (ordinal >> 8) & 0xFF, 0xE6, 0xE4])
                if spec:
                    pop = spec[1]
                    stub[5:8] = bytes([0xCA, pop & 0xFF, (pop >> 8) & 0xFF])
                blob[ordinal * 8:(ordinal + 1) * 8] = stub
            seg = {"index": 1, "flags": 0, "data": blob, "selector": 0, "base": 0}
            self.images[module] = {"name": module, "synthetic": True, "segments": [seg], "fixups": [], "entries": {}, "names": {}}

    def _place(self):
        exe = self.exe
        for image in self.images.values():
            for seg in image["segments"]:
                if exe and image is exe and seg["index"] == exe["auto"]:
                    extra = exe["heap"] + exe["stack"]
                    exe["heap_at"] = len(seg["data"])
                    if len(seg["data"]) + extra < 0x10000:
                        seg["data"].extend(b"\x00" * extra)
                    exe["heap_end"] = min(len(seg["data"]) - max(exe["stack"], 0x100), 0xFF00)
                sel = self._selector()
                seg["selector"] = sel
                seg["base"] = self.linear
                self.linear += (max(len(seg["data"]), 16) + 0xFFF) & ~0xFFF
                self.selectors[sel] = seg
            if image.get("synthetic"):
                gate = image["segments"][0]
                for ordinal in range(len(gate["data"]) // 8):
                    if gate["data"][ordinal * 8] == 0xBA:
                        self.gates[(gate["selector"], ordinal)] = image["name"]

    def _link(self):
        for image in list(self.images.values()):
            if image.get("synthetic"):
                continue
            for fix in image["fixups"]:
                self._one(image, fix)

    def _one(self, image, fix):
        seg_i, atype, fl, disp, t1, t2 = fix
        if not 1 <= seg_i <= len(image["segments"]) or (fl & 3) == 3:
            return
        seg = image["segments"][seg_i - 1]
        kind, rest = self._target(image, atype, fl, t1, t2)
        for at in self._chain(seg, disp):
            if kind == "equate":
                self._write(seg, at, atype, rest, 0)
            elif kind == "code":
                other, index, offset = rest
                if not 1 <= index <= len(other["segments"]):
                    continue
                self._write(seg, at, atype, offset, other["segments"][index - 1]["selector"])
                self.linked += 1
            elif kind == "gate":
                module, ordinal = rest
                gate = self.images.get(module)
                if not gate or not gate.get("synthetic"):
                    continue
                self._write(seg, at, atype, ordinal * 8, gate["segments"][0]["selector"])
                self.linked += 1

    def _target(self, image, atype, fl, t1, t2):
        if not fl & 3:
            offset = 0 if atype == 2 else t2
            return "code", (image, t1, offset)
        if fl & 2:
            module = image["modules"][t1 - 1] if 1 <= t1 <= len(image["modules"]) else "?"
            other = self.images.get(module)
            if other and not other.get("synthetic"):
                name = self._iname(image, t2).upper()
                for ordinal, text in other["names"].items():
                    if text.upper() == name and ordinal in other["entries"]:
                        seg, off = other["entries"][ordinal]
                        return "code", (other, seg, off)
            return "gap", (module, t2)
        if not 1 <= t1 <= len(image["modules"]):
            return "gap", ("?", t2)
        module = image["modules"][t1 - 1]
        equated = EQUATES.get(module, {}).get(t2)
        if equated:
            return "equate", equated[1]
        other = self.images.get(module)
        if other and not other.get("synthetic") and t2 in other["entries"]:
            seg, off = other["entries"][t2]
            return "code", (other, seg, off)
        if other and other.get("synthetic"):
            return "gate", (module, t2)
        return "gap", (module, t2)

    def _iname(self, image, offset):
        data, ne = image["data"], image["ne"]
        imptab = _u16(data, ne + 0x2A)
        at = ne + imptab + offset
        if at >= len(data):
            return ""
        n = data[at]
        return data[at + 1:at + 1 + n].decode("latin1", "replace")

    def _chain(self, seg, disp):
        seen = set()
        blob = seg["data"]
        while disp not in (0, 0xFFFF) and disp not in seen and disp + 2 <= len(blob):
            seen.add(disp)
            nxt = _u16(blob, disp)
            yield disp
            disp = nxt

    def _write(self, seg, disp, atype, offset, selector):
        blob = seg["data"]
        if atype == 3 and disp + 4 <= len(blob):
            struct.pack_into("<HH", blob, disp, offset & 0xFFFF, selector & 0xFFFF)
        elif disp + 2 <= len(blob):
            value = selector if atype == 2 else offset
            struct.pack_into("<H", blob, disp, value & 0xFFFF)

    def run(self, limit=1_000_000):
        exe = self.exe
        if exe is None:
            self.stop = "no executable"
            return self
        if self.packed:
            self.stop = (f"packed {', '.join(self.packed)}: self-loading (NE flag 0x0800), and newl does not "
                         f"unpack. Unpack first: python3 -m tbpipeline_bf.nehost --unpack FILE -o FILE")
            return self
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        flat = self._map_selector(0, 0xFFFF, 0x9A)
        for seg in self.selectors.values():
            size = (max(len(seg["data"]), 1) + 0xFFF) & ~0xFFF
            self.uc.mem_map(seg["base"], size)
            self.uc.mem_write(seg["base"], bytes(seg["data"]))
            access = 0x92 if seg["flags"] & 1 else 0x9A
            limit_b = 0xFFFF if len(seg["data"]) >= 0x10000 else max(len(seg["data"]) - 1, 0)
            self.uc.mem_write(seg["selector"], _descriptor(seg["base"], limit_b, access))
        self.uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        self.uc.hook_add(UC_HOOK_BLOCK, self._block)
        code = exe["segments"][exe["entry_seg"] - 1]
        data = exe["segments"][exe["auto"] - 1]
        gdtr_at = 0xF0E0
        self.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, flat & 0xFF, (flat >> 8) & 0xFF,
        ]))
        sp = len(data["data"]) - 2
        blob = bytes([
            0xB8, data["selector"] & 0xFF, (data["selector"] >> 8) & 0xFF, 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, sp & 0xFF, (sp >> 8) & 0xFF,
            0xEA, exe["entry_ip"] & 0xFF, (exe["entry_ip"] >> 8) & 0xFF,
            code["selector"] & 0xFF, (code["selector"] >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF020, blob)
        psp = bytearray(0x100)
        psp[0:2] = b"\xcd\x20"
        tail = b"\r"
        psp[0x80] = len(tail)
        psp[0x81:0x81 + len(tail)] = tail
        self.uc.mem_map(0x100000, 0x1000)
        self.uc.mem_write(0x100000, bytes(psp))
        self.psp = self._map_selector(0x100000, 0xFF, 0x92)
        self.uc.mem_map(0x101000, 0x1000)
        self.uc.mem_write(0x101000, b"\x00\x00")
        self.env = self._map_selector(0x101000, 0xFF, 0x92)
        self.uc.mem_map(0x102000, 0x1000)
        self.task = self._task_selector(data)
        self.dgroup = data["selector"]
        self.layer.dgroup = self.dgroup
        self.layer.task = self.task
        self.layer.heap_brk = exe["heap_at"]
        self.layer.heap_end = exe["heap_end"]
        # The task list is still the string SAMYB_PMTB. A garbage count
        # makes the lookup walk onto the stack and match DS.
        self.uc.mem_write(data["base"] + 0x1B02, b"\x00\x00")
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        began = time.monotonic()
        try:
            self.uc.emu_start(0xF000, 0, timeout=TIMEOUT_US, count=limit)
        except UcError as exc:
            if not self.stop:
                self.stop = str(exc)
        else:
            if not self.stop:
                self.stop = self._ended(limit, time.monotonic() - began)
        return self

    def _block(self, uc, address, size, user):
        cs = uc.reg_read(UC_X86_REG_CS)
        seg = self.selectors.get(cs)
        self.recent.append((cs, address - seg["base"] if seg else address))

    def _ended(self, limit, elapsed):
        """emu_start came back on its own: a hlt, or one of the two caps."""
        cs = self.uc.reg_read(UC_X86_REG_CS)
        ip = self.uc.reg_read(UC_X86_REG_IP)
        if ip and self._code(cs, ip - 1, 1) == b"\xf4":
            return f"hlt at {cs:#x}:{ip - 1:#x}"
        if elapsed * 1_000_000 >= TIMEOUT_US * 0.95:
            cap = f"time cap {TIMEOUT_US // 1_000_000} s"
        else:
            cap = f"instruction cap {limit}"
        cap += f" reached at {cs:#x}:{ip:#x}"
        if not self.layer.trace:
            return cap + ", no Windows call taken"
        module, ordinal, label, _args = self.layer.trace[-1]
        return cap + f", {len(self.layer.trace)} Windows calls taken, last {module}.{ordinal} {label}".rstrip()

    def _word(self, sel, offset):
        seg = self.selectors.get(sel)
        if seg is None:
            return 0
        try:
            raw = self.uc.mem_read(seg["base"] + (offset & 0xFFFF), 2)
        except UcError:
            return 0
        return struct.unpack("<H", raw)[0]

    def _out(self, uc, port, size, value, user):
        if port != 0xE4:
            return
        cs = uc.reg_read(UC_X86_REG_CS)
        ordinal = uc.reg_read(UC_X86_REG_DX)
        module = self.gates.get((cs, ordinal))
        if module is None:
            self.stop = f"out {cs:#x} dx={ordinal:#x}"
            uc.emu_stop()
            return
        if module == "KERNEL" and ordinal == 102:
            args = [uc.reg_read(UC_X86_REG_AX)]
        else:
            sp = uc.reg_read(UC_X86_REG_SP)
            ss = uc.reg_read(UC_X86_REG_SS)
            args = [self._word(ss, sp + 4 + n * 2) for n in range(8)]
        path = None
        if module == "KERNEL" and ordinal == 74:
            path = self._asciiz(args[4], args[3])
        elif module == "KERNEL" and ordinal == 85:
            path = self._asciiz(args[2], args[1])
        try:
            ax = self.layer.call(module, ordinal, args, at=self._site(uc), path=path)
        except (Gap, Refused) as exc:
            self.stop = str(exc)
            uc.emu_stop()
            return
        if module == "KERNEL" and ordinal == 49 and len(args) >= 4:
            off, sel, count = args[1], args[2], args[3]
            raw = self.layer.module_name + b"\x00"
            count = max(count, 1)
            raw = raw[:count]
            seg = self.selectors.get(sel)
            if seg is not None and count:
                uc.mem_write(seg["base"] + (off & 0xFFFF), raw)
                ax = len(raw.rstrip(b"\x00"))
        if module == "KERNEL" and ordinal == 15:
            # pascal16 GlobalAlloc(word long): flags is pushed first, so the
            # dword size is on top, low word nearest SP.
            lo = args[0] if args else 0
            hi = args[1] if len(args) > 1 else 0
            asked = lo | (hi << 16)
            size = asked or 0x1000
            if size > 0x10000:
                # One selector, one 16-bit segment. A larger block needs
                # __AHINCR tiling, which this layer does not do.
                self.layer.capped.append((ax, asked))
            size = min(size, 0x10000)
            size = max((size + 0xFFF) & ~0xFFF, 0x1000)
            base = self.linear
            self.linear += size
            uc.mem_map(base, size)
            self.glock[ax] = self._map_selector(base, size - 1, 0x92)
            self.blocks[base] = {"handle": ax, "selector": self.glock[ax], "size": size, "written": bytearray(size)}
            uc.hook_add(UC_HOOK_MEM_WRITE, self._block_write, base, base, base + size - 1)
            uc.hook_add(UC_HOOK_MEM_READ, self._block_read, base, base, base + size - 1)
            self.layer.gsizes[ax] = size
            # GlobalSize takes the selector GlobalLock returned as well as the handle.
            self.layer.gsizes[self.glock[ax]] = size
        if module == "KERNEL" and ordinal == 18:
            uc.reg_write(UC_X86_REG_DX, self.glock.get(args[0] if args else 0, 0))
            ax = 0
        if module == "KERNEL" and ordinal == 91:
            uc.reg_write(UC_X86_REG_ES, self.psp)
            uc.reg_write(UC_X86_REG_BX, 0x80)
            uc.reg_write(UC_X86_REG_CX, 0x1000)
            uc.reg_write(UC_X86_REG_DX, 1)
            uc.reg_write(UC_X86_REG_SI, 0)
            uc.reg_write(UC_X86_REG_DI, self.dgroup)
            ax = 1
        if module == "KERNEL" and ordinal == 131:
            uc.reg_write(UC_X86_REG_DX, self.env)
            ax = 0
        if module == "KERNEL" and ordinal == 82 and self.layer.last_read:
            seg = self.selectors.get(args[2])
            if seg is not None:
                uc.mem_write(seg["base"] + args[1], self.layer.last_read)
        uc.reg_write(UC_X86_REG_AX, ax & 0xFFFF)
        if (module, ordinal) in (("KERNEL", 20), ("KERNEL", 84), ("USER", 291)):
            # DWORD answers in DX:AX: GlobalSize, _llseek, SetWindowsHookEx.
            uc.reg_write(UC_X86_REG_DX, (ax >> 16) & 0xFFFF)
        elif not (module == "KERNEL" and ordinal in (18, 91, 131)):
            uc.reg_write(UC_X86_REG_DX, 0)
        if self.layer.exit is not None:
            self.stop = f"dos exit {self.layer.exit:#x}"
            uc.emu_stop()

    def _asciiz(self, sel, offset, limit=260):
        seg = self.selectors.get(sel)
        if seg is None:
            return ""
        try:
            raw = bytes(self.uc.mem_read(seg["base"] + offset, limit))
        except UcError:
            return ""
        return raw.split(b"\x00", 1)[0].decode("latin1")

    def _site(self, uc):
        """The far call that reached the gate. SS:SP is still the return address."""
        sp = uc.reg_read(UC_X86_REG_SP)
        ss = uc.reg_read(UC_X86_REG_SS)
        ip, cs = self._word(ss, sp), self._word(ss, sp + 2)
        seg = self.selectors.get(cs)
        if seg is not None and ip >= 5:
            try:
                if uc.mem_read(seg["base"] + ip - 5, 1)[0] == 0x9A:
                    return cs, ip - 5, "call"
            except UcError:
                pass
        return cs, ip, "return"

    def _block_write(self, uc, access, address, size, value, base):
        block = self.blocks[base]
        at = address - base
        block["written"][at:at + size] = b"\x01" * size

    def _block_read(self, uc, access, address, size, value, base):
        """A string scan over GlobalAlloc memory nothing wrote is the stop.

        The layer hands back zeros. A lods/scas/cmps that reads them is
        looking for a record the runtime never made, and walking on only
        reaches the segment limit.
        """
        block = self.blocks[base]
        at = address - base
        if any(block["written"][at:at + size]):
            return
        cs = uc.reg_read(UC_X86_REG_CS)
        ip = uc.reg_read(UC_X86_REG_IP)
        op, after = self._string_op(cs, ip)
        if op is None:
            return
        want = self._compared(cs, after)
        self.stop = (f"scan {op} at {cs:#x}:{ip:#x} read {block['selector']:#x}:{at:#x}, "
                     f"GlobalAlloc block {block['handle']:#x} that nothing wrote")
        if want is not None:
            self.stop += f", looking for {want:#06x}"
        uc.emu_stop()

    def _code(self, cs, ip, n):
        seg = self.selectors.get(cs)
        if seg is None:
            return b""
        try:
            return bytes(self.uc.mem_read(seg["base"] + ip, n))
        except UcError:
            return b""

    def _string_op(self, cs, ip):
        raw = self._code(cs, ip, 6)
        names = {0xAC: "lodsb", 0xAD: "lodsw", 0xAE: "scasb", 0xAF: "scasw", 0xA6: "cmpsb", 0xA7: "cmpsw"}
        prefix = ""
        for i, byte in enumerate(raw):
            if byte in (0xF2, 0xF3):
                prefix = "repne " if byte == 0xF2 else "repe "
                continue
            if byte in (0x26, 0x2E, 0x36, 0x3E, 0x64, 0x65, 0x66, 0x67):
                continue
            if byte in names:
                return prefix + names[byte], ip + i + 1
            return None, ip
        return None, ip

    def _compared(self, cs, ip):
        raw = self._code(cs, ip, 4)
        if raw[:1] == b"\x3d" and len(raw) >= 3:
            return struct.unpack_from("<H", raw, 1)[0]
        if raw[:2] == b"\x83\xf8" and len(raw) >= 3:
            return raw[2] - 0x100 & 0xFFFF if raw[2] & 0x80 else raw[2]
        return None

    def _unmapped(self, uc, access, address, size, value, user):
        self.stop = f"unmapped {address:#x}"
        return False

    def _task_selector(self, data):
        """GetCurrentTask's answer. Not DGROUP, and not a word that already
        sits in the static string table at 0x1B00. Startup matched both
        once and copied from a far pointer whose segment was `uct.`."""
        table = bytes(data["data"][0x1B00:0x1C00])
        taken = {data["selector"]} | {_u16(table, i) for i in range(len(table) - 1)}
        while True:
            sel = self._map_selector(0x102000, 0x1FF, 0x92)
            if sel not in taken:
                return sel

    def _map_selector(self, base, limit, access):
        sel = self._selector()
        self.uc.mem_write(sel, _descriptor(base, limit, access))
        return sel
