"""Tiny original NE images for the newl tests. No ToolBook bytes.

    build(path, name, segments=[Seg(code, relocs=[...])], modules=[...],
          imports=[...], entries=[(seg, offset)], exe=True)

A reloc is (atype, flags, offset, t1, t2), the NE record as written.
"""

import struct
from dataclasses import dataclass, field

FAR = 3
SELECTOR = 2
OFFSET = 5
INTERNAL = 0
BY_ORDINAL = 1
BY_NAME = 2


@dataclass
class Seg:
    data: bytes
    relocs: list = field(default_factory=list)
    flags: int = 0  # 0x0001 is data
    alloc: int = 0


def name_offsets(modules, imports):
    """Where build() will put each import name, for a BY_NAME reloc's t2."""
    at = 1 + sum(1 + len(m) for m in modules)
    out = {}
    for text in imports:
        out[text] = at
        at += 1 + len(text)
    return out


def build(path, name, segments, modules=(), imports=(), entries=(), exe=True,
          entry=(1, 0), auto=0, heap=0, stack=0, names=(), ne_flags=None):
    """Write an NE image. imports are the names a BY_NAME reloc points at.
    names are (text, ordinal) for the resident name table after the module name.
    Returns {import name: offset in the imported names table}."""
    nseg = len(segments)
    ne = 0x40
    head = 0x40
    segtab = head
    restab = segtab + nseg * 8
    res = bytearray()
    for text, ordinal in ((name, 0),) + tuple(names):
        raw = text.encode("ascii")
        res += bytes([len(raw)]) + raw + struct.pack("<H", ordinal)
    res += b"\x00"
    modref = restab + len(res)
    imp = bytearray(b"\x00")
    mod_offsets = []
    for mod in modules:
        mod_offsets.append(len(imp))
        raw = mod.encode("ascii")
        imp += bytes([len(raw)]) + raw
    name_offsets = {}
    for text in imports:
        name_offsets[text] = len(imp)
        raw = text.encode("ascii")
        imp += bytes([len(raw)]) + raw
    imptab = modref + 2 * len(modules)
    enttab = imptab + len(imp)
    ent = bytearray()
    for seg, offset in entries:
        ent += bytes([1, seg, 1]) + struct.pack("<H", offset)
    ent += b"\x00"
    end = ne + enttab + len(ent)

    shift = 4
    body = bytearray()
    at = (end + 15) & ~15
    rows = []
    for seg in segments:
        sector = at >> shift
        blob = bytes(seg.data)
        chunk = bytearray(blob)
        flags = seg.flags
        if seg.relocs:
            flags |= 0x0100
            chunk += struct.pack("<H", len(seg.relocs))
            for atype, fl, off, t1, t2 in seg.relocs:
                chunk += struct.pack("<BBHHH", atype, fl, off, t1, t2)
        chunk += b"\x00" * ((-len(chunk)) % 16)
        rows.append(struct.pack("<HHHH", sector, len(blob), flags, seg.alloc or len(blob)))
        body += chunk
        at += len(chunk)

    hdr = bytearray(0x40)
    hdr[0:2] = b"NE"
    struct.pack_into("<HH", hdr, 0x04, enttab, len(ent))
    struct.pack_into("<H", hdr, 0x0C, ne_flags if ne_flags is not None else (0x0002 if exe else 0x8000))
    struct.pack_into("<HHH", hdr, 0x0E, auto, heap, stack)
    struct.pack_into("<I", hdr, 0x14, (entry[0] << 16) | entry[1])
    struct.pack_into("<HHH", hdr, 0x1C, nseg, len(modules), 0)
    struct.pack_into("<HHHHH", hdr, 0x22, segtab, restab, restab, modref, imptab)
    struct.pack_into("<I", hdr, 0x2C, 0)
    struct.pack_into("<H", hdr, 0x32, shift)

    mz = bytearray(0x40)
    mz[0:2] = b"MZ"
    struct.pack_into("<I", mz, 0x3C, ne)
    out = mz + hdr + b"".join(rows) + res + struct.pack(f"<{len(modules)}H", *mod_offsets) + imp + ent
    out += b"\x00" * (((end + 15) & ~15) - len(out))
    out += body
    with open(path, "wb") as fh:
        fh.write(out)
    return name_offsets
