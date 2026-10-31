"""Tiny original NE files for the neww tests. No ToolBook bytes.

build() writes one NE image. Segments are (flags, code bytes, fixups).
A fixup is (atype, flags, disp, target1, target2), the same row ne.py
reads. A far call written by call_far() leaves 0xFFFF in the offset
word, which ends the fixup chain.
"""

import struct
from pathlib import Path

SHIFT = 4


def call_far():
    """9A ofs seg, with the chain end in the offset word."""
    return bytes([0x9A, 0xFF, 0xFF, 0x00, 0x00])


def mov_ax(value):
    return bytes([0xB8, value & 0xFF, (value >> 8) & 0xFF])


def name_offset(modules, imports, want):
    """Offset of an imported function name in the table build() writes."""
    off = 1 + sum(1 + len(m) for m in modules)
    for item in imports:
        if item == want:
            return off
        off += 1 + len(item)
    raise KeyError(want)


def build(name, segments, modules=(), entries=(), entry=(1, 0), auto=0, heap=0, stack=0, exe=True, imports=()):
    """entries: (ordinal, segment, offset, export name) rows, fixed bundles.

    imports are function names for by-name fixups; see name_offset().
    """
    ne = 0x40
    header = bytearray(0x40)
    # Tables follow the header in this order.
    segtab = bytearray()
    restab = bytearray()
    restab += bytes([len(name)]) + name.encode("ascii") + b"\x00\x00"
    for ordinal, _seg, _off, export in entries:
        if export:
            restab += bytes([len(export)]) + export.encode("ascii") + struct.pack("<H", ordinal)
    restab += b"\x00"
    imptab = bytearray(b"\x00")
    modtab = bytearray()
    for module in modules:
        modtab += struct.pack("<H", len(imptab))
        imptab += bytes([len(module)]) + module.encode("ascii")
    for item in imports:
        imptab += bytes([len(item)]) + item.encode("ascii")
    enttab = bytearray()
    last = 0
    for ordinal, seg, off, _export in sorted(entries):
        if ordinal > last + 1:
            enttab += bytes([ordinal - last - 1, 0])
        enttab += bytes([1, seg, 0x01]) + struct.pack("<H", off)
        last = ordinal
    enttab += b"\x00"
    off = 0x40
    tables = {}
    for key, blob in (("seg", segtab), ("res", b""), ("rest", restab), ("mod", modtab), ("imp", imptab), ("ent", enttab)):
        tables[key] = off
        if key == "seg":
            off += 8 * len(segments)
        else:
            off += len(blob)
    body = bytearray()
    start = ne + off
    pad = (-start) % (1 << SHIFT)
    body += b"\x00" * pad
    cursor = start + pad
    rows = []
    for flags, code, fixups in segments:
        code = bytes(code)
        sector = cursor >> SHIFT
        if fixups:
            flags |= 0x0100
        chunk = bytearray(code)
        if fixups:
            chunk += struct.pack("<H", len(fixups))
            for fix in fixups:
                chunk += struct.pack("<BBHHH", *fix)
        chunk += b"\x00" * ((-len(chunk)) % (1 << SHIFT))
        rows.append(struct.pack("<HHHH", sector, len(code), flags, len(code)))
        body += chunk
        cursor += len(chunk)
    segtab[:] = b"".join(rows)
    header[0:2] = b"NE"
    struct.pack_into("<HH", header, 0x04, tables["ent"], len(enttab))
    struct.pack_into("<H", header, 0x0C, 0x0302 if exe else 0x8002)
    struct.pack_into("<HHH", header, 0x0E, auto, heap, stack)
    struct.pack_into("<I", header, 0x14, (entry[0] << 16) | entry[1])
    struct.pack_into("<HH", header, 0x1C, len(segments), len(modules))
    struct.pack_into("<HHHHHH", header, 0x22, tables["seg"], tables["res"], tables["rest"],
                     tables["mod"], tables["imp"], 0)
    struct.pack_into("<I", header, 0x2C, 0)
    struct.pack_into("<H", header, 0x32, SHIFT)
    mz = bytearray(0x40)
    mz[0:2] = b"MZ"
    struct.pack_into("<I", mz, 0x3C, ne)
    blob = bytes(mz) + bytes(header) + bytes(segtab) + bytes(restab) + bytes(modtab) + bytes(imptab) + bytes(enttab)
    assert len(blob) == start, (len(blob), start)
    return blob + bytes(body)


def write(directory, filename, blob):
    path = Path(directory) / filename
    path.write_bytes(blob)
    return path


def exit_program(directory, before=b"", modules=("KERNEL",), dos3call=102, data=256):
    """TB80RTM.EXE: code runs `before`, then AX=4C00 and KERNEL.DOS3Call.

    `before` may hold far calls; their fixups are passed back by the
    caller through exit_program_with().
    """
    return exit_program_with(directory, before, [], modules=modules, dos3call=dos3call, data=data)


def exit_program_with(directory, before, fixups, modules=("KERNEL",), dos3call=102, data=256, imports=()):
    """data is a size in bytes, or the bytes of DGROUP."""
    code = bytearray(before)
    code += mov_ax(0x4C00)
    at = len(code)
    code += call_far()
    code += bytes([0xF4])
    fixups = list(fixups) + [(3, 1, at + 1, modules.index("KERNEL") + 1, dos3call)]
    data = bytes(data) if isinstance(data, (bytes, bytearray)) else b"\x00" * data
    blob = build(
        "TB80RTM",
        [(0x0000, bytes(code), fixups), (0x0001, data, [])],
        modules=modules, entry=(1, 0), auto=2, imports=imports,
    )
    return write(directory, "TB80RTM.EXE", blob)
