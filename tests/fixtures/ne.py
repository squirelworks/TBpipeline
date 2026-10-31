"""A tiny original NE image, built in code, for probes that read relocs.

Segments are (code bytes, relocs, is_data). A reloc is
(atype, flags, offset, t1, t2), the 8-byte NE record. Imported module
names go in the module reference table. Nothing here comes from a
ToolBook binary.
"""

import struct

SHIFT = 4


def build(segments, modules=()):
    ne = 0x40
    header = 0x40
    segtab = header
    modref = segtab + 8 * len(segments)
    imptab = modref + 2 * len(modules)
    imports = b"\x00"
    refs = []
    for name in modules:
        refs.append(len(imports))
        imports += bytes([len(name)]) + name.encode("ascii")
    body_at = ne + imptab + len(imports)
    body_at = (body_at + (1 << SHIFT) - 1) & ~((1 << SHIFT) - 1)
    blob = bytearray(body_at)
    blob[0:2] = b"MZ"
    struct.pack_into("<H", blob, 0x3C, ne)
    blob[ne:ne + 2] = b"NE"
    struct.pack_into("<H", blob, ne + 0x1C, len(segments))
    struct.pack_into("<H", blob, ne + 0x1E, len(modules))
    struct.pack_into("<H", blob, ne + 0x22, segtab)
    struct.pack_into("<H", blob, ne + 0x28, modref)
    struct.pack_into("<H", blob, ne + 0x2A, imptab)
    struct.pack_into("<H", blob, ne + 0x32, SHIFT)
    for i, ref in enumerate(refs):
        struct.pack_into("<H", blob, ne + modref + 2 * i, ref)
    blob[ne + imptab:ne + imptab + len(imports)] = imports
    for i, (code, relocs, is_data) in enumerate(segments):
        while len(blob) % (1 << SHIFT):
            blob.append(0)
        sector = len(blob) >> SHIFT
        flags = (1 if is_data else 0) | (0x0100 if relocs else 0)
        struct.pack_into("<HHHH", blob, ne + segtab + 8 * i, sector, len(code), flags, len(code))
        blob += code
        if relocs:
            blob += struct.pack("<H", len(relocs))
            for rec in relocs:
                blob += struct.pack("<BBHHH", *rec)
    return bytes(blob)
