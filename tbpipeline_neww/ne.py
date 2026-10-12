"""NE image: segments, entry table, and the fixups that link modules."""

import struct
from dataclasses import dataclass, field


@dataclass
class Entry:
    segment: int
    offset: int
    movable: bool = False


@dataclass
class Fixup:
    segment: int
    atype: int
    flags: int
    disp: int
    target1: int
    target2: int


@dataclass
class Segment:
    index: int
    flags: int
    data: bytearray
    selector: int = 0
    base: int = 0


@dataclass
class Image:
    path: str
    name: str
    entry_seg: int
    entry_ip: int
    auto: int
    heap: int
    stack: int
    modules: list
    entries: dict
    names: dict
    segments: list
    fixups: list = field(default_factory=list)
    synthetic: bool = False


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def parse(path):
    data = open(path, "rb").read()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError(f"not an NE file: {path}")
    ne = struct.unpack_from("<I", data, 0x3C)[0]
    if data[ne:ne + 2] != b"NE":
        raise ValueError(f"not an NE file: {path}")
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
        blob = bytearray(alloc if alloc < 0x10000 else 0x10000)
        if not flags & 0x0008:
            start = sector << shift
            chunk = data[start:start + raw_size]
            blob[:len(chunk)] = chunk[:len(blob)]
        segments.append(Segment(i + 1, flags, blob))
        if flags & 0x0100 and raw_size and (sector << shift) + raw_size + 2 <= len(data):
            base = sector << shift
            count = _u16(data, base + raw_size)
            pos = base + raw_size + 2
            for _ in range(count):
                if pos + 8 > len(data):
                    break
                atype, fl, disp, t1, t2 = struct.unpack_from("<BBHHH", data, pos)
                pos += 8
                fixups.append(Fixup(i + 1, atype, fl, disp, t1, t2))
    restab = ne + _u16(data, ne + 0x26)
    n = data[restab]
    name = data[restab + 1:restab + 1 + n].decode("ascii", "replace").upper()
    cmod = _u16(data, ne + 0x1E)
    modtab = _u16(data, ne + 0x28)
    imptab = _u16(data, ne + 0x2A)
    modules = []
    for i in range(cmod):
        off = _u16(data, ne + modtab + 2 * i)
        at = ne + imptab + off
        ln = data[at]
        modules.append(data[at + 1:at + 1 + ln].decode("ascii", "replace").upper())
    return Image(
        path=str(path),
        name=name or path.rsplit("/", 1)[-1].split(".", 1)[0].upper(),
        entry_seg=(csip >> 16) & 0xFFFF,
        entry_ip=csip & 0xFFFF,
        auto=_u16(data, ne + 0x0E),
        heap=_u16(data, ne + 0x10),
        stack=_u16(data, ne + 0x12),
        modules=modules,
        entries=_entries(data, ne),
        names=_names(data, ne),
        segments=segments,
        fixups=fixups,
    )


def _names(data, ne):
    out = {}

    def walk(off):
        while off < len(data):
            n = data[off]
            if n == 0:
                break
            text = data[off + 1:off + 1 + n].decode("latin1", "replace")
            ordinal = _u16(data, off + 1 + n)
            if ordinal:
                out.setdefault(ordinal, text)
            off += 1 + n + 2

    walk(ne + _u16(data, ne + 0x26))
    nrest = struct.unpack_from("<I", data, ne + 0x2C)[0]
    if 0 < nrest < len(data):
        walk(nrest)
    return out


def _entries(data, ne):
    off = ne + _u16(data, ne + 4)
    end = off + _u16(data, ne + 6)
    ordinal = 1
    out = {}
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
                _flags = data[off]
                seg_i = data[off + 3]
                ip = _u16(data, off + 4)
                off += 6
                out[ordinal] = Entry(seg_i, ip, True)
            else:
                ip = _u16(data, off + 1)
                off += 3
                out[ordinal] = Entry(seg, ip, False)
            ordinal += 1
    return out


def import_name(image_path, offset):
    data = open(image_path, "rb").read()
    ne = struct.unpack_from("<I", data, 0x3C)[0]
    imptab = _u16(data, ne + 0x2A)
    at = ne + imptab + offset
    if at >= len(data):
        return ""
    n = data[at]
    return data[at + 1:at + 1 + n].decode("latin1", "replace")
