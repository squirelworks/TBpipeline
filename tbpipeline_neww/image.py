"""One address space. Fixups point at a real segment or at a Windows gate."""

import struct
from pathlib import Path

from .ne import Image, Segment, import_name, parse
from .wine import GDI, KERNEL, SYSTEM, USER, WIN87EM, Wine


class Selectors(dict):
    """Segments by selector, found by descriptor index as the CPU finds them.

    The table bit and RPL do not change which block a selector names, so a moveable
    handle (the selector with the table bit set) finds its block too.
    """

    def __getitem__(self, sel):
        return super().__getitem__(sel & ~7)

    def get(self, sel, default=None):
        return super().get(sel & ~7, default)

    def __contains__(self, sel):
        return super().__contains__(sel & ~7)


class Sandbox:
    def __init__(self, root):
        self.root = Path(root)
        self.wine = Wine(root)
        self.images = {}
        self.selectors = Selectors()
        self.gates = {}
        # (module, ordinal) -> offset of the ES and DS words a register contract's stub loads.
        self.slots = {}
        self.next_index = 1
        self.linear = 0x200000
        self.linked = 0
        self.equates = 0
        self.gaps = []
        # A call that could not be linked lands on a trap. A trap is not a gate:
        # Wine never answers it, and the run stops with the gap's text.
        self.trap = None
        self.traps = []
        self.exe = None

    def load(self):
        files = sorted(self.root.glob("*.EXE")) + sorted(self.root.glob("*.DLL"))
        files += sorted(self.root.glob("*.exe")) + sorted(self.root.glob("*.dll"))
        seen = set()
        for path in files:
            key = path.name.upper()
            if key in seen:
                continue
            seen.add(key)
            try:
                image = parse(path)
            except ValueError:
                continue
            self.images[image.name] = image
            if image.name == "TB80RTM":
                self.exe = image
        if self.exe is None:
            exes = [img for img in self.images.values() if img.path.upper().endswith(".EXE")]
            self.exe = exes[0] if exes else None
        self._gates()
        self._place()
        self.trap = Segment(0, 0, bytearray(0x10000))
        self._place_segment(self.trap)
        self._link()
        return self

    def _selector(self):
        sel = self.next_index * 8
        self.next_index += 1
        return sel

    def _place_segment(self, seg):
        sel = self._selector()
        size = max(len(seg.data), 16)
        seg.selector = sel
        seg.base = self.linear
        self.linear += (size + 0xFFF) & ~0xFFF
        self.selectors[sel] = seg
        return sel

    def _gates(self):
        wanted = {name: set() for name in SYSTEM}
        for image in self.images.values():
            for fix in image.fixups:
                if not fix.flags & 1 or fix.flags & 2:
                    continue
                if (fix.flags & 3) == 3 or not 1 <= fix.target1 <= len(image.modules):
                    continue
                module = image.modules[fix.target1 - 1]
                if module in wanted and self.wine.equate(module, fix.target2) is None:
                    wanted[module].add(fix.target2)
        for module, ordinals in wanted.items():
            tables = {"KERNEL": KERNEL, "USER": USER, "GDI": GDI, "WIN87EM": WIN87EM}
            for ordinal in tables.get(module, {}):
                ordinals.add(ordinal)
            if not ordinals:
                continue
            hi = max(ordinals)
            blob = bytearray((hi + 1) * 8)
            for ordinal in ordinals:
                spec = self.wine.usable(module, ordinal)
                pop = spec.pop if spec else 0
                stub = bytearray(8)
                stub[0:5] = bytes([0xBA, ordinal & 0xFF, (ordinal >> 8) & 0xFF, 0xE6, 0xE4])
                if spec and spec.ret == "register":
                    # A register contract reads and sets registers, DX among them, so its stub
                    # does not load DX: OUT 0E7h, and the gate finds the ordinal from IP / 8.
                    # It may set ES and DS. Unicorn's register write does not load a
                    # protected-mode descriptor, so the guest loads them: the stub jumps to a
                    # tail that does mov es, cs:[slot] ; mov ds, cs:[slot + 2] ; retf pop.
                    tail = len(blob)
                    slot = tail + 13
                    blob += bytes([0x2E, 0x8E, 0x06, slot & 0xFF, slot >> 8,
                                   0x2E, 0x8E, 0x1E, (slot + 2) & 0xFF, (slot + 2) >> 8,
                                   0xCA, pop & 0xFF, (pop >> 8) & 0xFF, 0, 0, 0, 0])
                    rel = (tail - (ordinal * 8 + 5)) & 0xFFFF
                    stub[0:5] = bytes([0xE6, 0xE7, 0xE9, rel & 0xFF, rel >> 8])
                    self.slots[(module, ordinal)] = slot
                elif spec:
                    stub[5:8] = bytes([0xCA, pop & 0xFF, (pop >> 8) & 0xFF])
                blob[ordinal * 8:(ordinal + 1) * 8] = stub
            seg = Segment(1, 0, blob)
            image = Image(
                path="", name=module, entry_seg=1, entry_ip=0, auto=0, heap=0, stack=0,
                modules=[], entries={}, names={}, segments=[seg], synthetic=True,
            )
            self.images[module] = image

    def _place(self):
        auto = self.exe.auto if self.exe else 0
        heap = self.exe.heap if self.exe else 0
        stack = self.exe.stack if self.exe else 0
        for image in self.images.values():
            for seg in image.segments:
                if image is not self.exe and not image.synthetic and seg.index == image.auto and image.heap:
                    # A DLL's DGROUP gets its NE heap too (NE_CreateSegment), rounded as GLOBAL_Alloc rounds.
                    size = (len(seg.data) + image.heap + 0x1F) & ~0x1F
                    if size <= 0x10000:
                        seg.data.extend(b"\x00" * (size - len(seg.data)))
                if image is self.exe and seg.index == auto:
                    # Wine ne_segment.c NE_CreateSegment: minsize + stack + heap, and
                    # global.c GLOBAL_Alloc rounds a block up to 32 bytes.
                    size = (len(seg.data) + heap + stack + 0x1F) & ~0x1F
                    if size <= 0x10000:
                        seg.data.extend(b"\x00" * (size - len(seg.data)))
                self._place_segment(seg)
            if image.synthetic and image.segments:
                sel = image.segments[0].selector
                for ordinal in range(len(image.segments[0].data) // 8):
                    stub = image.segments[0].data[ordinal * 8:ordinal * 8 + 4]
                    if (stub[0] == 0xBA and stub[3] == 0xE6) or stub[:2] == b"\xE6\xE7":
                        self.gates[(sel, ordinal)] = image.name

    def _link(self):
        for image in list(self.images.values()):
            if image.synthetic:
                continue
            for fix in image.fixups:
                self._one(image, fix)

    def _one(self, image, fix):
        if fix.segment < 1 or fix.segment > len(image.segments):
            return
        seg = image.segments[fix.segment - 1]
        if (fix.flags & 3) == 3:
            return
        kind, *rest = self._target(image, fix)
        # Additive (flag 4): one location, and the word there is an addend, not the next link.
        additive = bool(fix.flags & 4)
        sites = [fix.disp] if additive else self._chain(seg, fix.disp)
        for disp in sites:
            addend = struct.unpack_from("<H", seg.data, disp)[0] if additive and disp + 2 <= len(seg.data) else 0
            if kind == "equate":
                self._write(seg, disp, fix.atype, rest[0] + addend, 0)
                self.equates += 1
            elif kind == "code":
                target, index, offset = rest
                if not 1 <= index <= len(target.segments):
                    self._gap(seg, disp, fix.atype, f"{image.name} -> {target.name} segment {index}")
                    continue
                sel = target.segments[index - 1].selector
                self._write(seg, disp, fix.atype, offset + addend, sel)
                self.linked += 1
            elif kind == "gate":
                module, ordinal = rest
                gate = self.images.get(module)
                if gate is None or not gate.segments:
                    self._gap(seg, disp, fix.atype, f"{module}.{ordinal}")
                    continue
                sel = gate.segments[0].selector
                self._write(seg, disp, fix.atype, ordinal * 8 + addend, sel)
                self.linked += 1
            else:
                module, ordinal = rest
                self._gap(seg, disp, fix.atype, f"{image.name} -> {module}.{ordinal}")

    def _gap(self, seg, disp, atype, text):
        if text not in self.traps:
            self.traps.append(text)
            self.gaps.append(text)
        slot = self.traps.index(text)
        if (slot + 1) * 8 > len(self.trap.data):
            return
        # mov dx, slot ; out 0E5h, al ; hlt
        self.trap.data[slot * 8:slot * 8 + 6] = bytes([0xBA, slot & 0xFF, slot >> 8, 0xE6, 0xE5, 0xF4])
        self._write(seg, disp, atype, slot * 8, self.trap.selector)

    def _target(self, image, fix):
        if not fix.flags & 3:
            offset = 0 if fix.atype == 2 else fix.target2
            return ("code", image, fix.target1, offset)
        if fix.flags & 2:
            module = image.modules[fix.target1 - 1] if 1 <= fix.target1 <= len(image.modules) else "?"
            name = import_name(image.path, fix.target2).upper()
            other = self.images.get(module)
            if other and not other.synthetic:
                for ordinal, text in other.names.items():
                    if text.upper() == name:
                        ent = other.entries.get(ordinal)
                        if ent:
                            return ("code", other, ent.segment, ent.offset)
            return ("gap", module, name or fix.target2)
        if not 1 <= fix.target1 <= len(image.modules):
            return ("gap", "?", fix.target2)
        module = image.modules[fix.target1 - 1]
        equated = self.wine.equate(module, fix.target2)
        if equated:
            return ("equate", equated[1])
        other = self.images.get(module)
        if other and not other.synthetic:
            ent = other.entries.get(fix.target2)
            if ent:
                return ("code", other, ent.segment, ent.offset)
            return ("gap", module, fix.target2)
        if other and other.synthetic:
            return ("gate", module, fix.target2)
        return ("gap", module, fix.target2)

    def _chain(self, seg, disp):
        seen = set()
        while disp not in (0, 0xFFFF) and disp not in seen and disp + 2 <= len(seg.data):
            seen.add(disp)
            nxt = struct.unpack_from("<H", seg.data, disp)[0]
            yield disp
            disp = nxt

    def _write(self, seg, disp, atype, offset, selector):
        if atype == 3 and disp + 4 <= len(seg.data):
            struct.pack_into("<HH", seg.data, disp, offset & 0xFFFF, selector & 0xFFFF)
        elif disp + 2 <= len(seg.data):
            value = selector if atype == 2 else offset
            struct.pack_into("<H", seg.data, disp, value & 0xFFFF)
