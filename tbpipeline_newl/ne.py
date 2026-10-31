"""Read the imports an NE file actually asks for."""

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Import:
    module: str
    ordinal: int
    name: str
    address: str  # "far", "offset", "selector"


def load(path):
    data = open(path, "rb").read()
    if data[:2] != b"MZ":
        raise ValueError(f"not an NE file: {path}")
    ne = struct.unpack_from("<I", data, 0x3C)[0]
    if data[ne:ne + 2] != b"NE":
        raise ValueError(f"not an NE file: {path}")
    return data, ne


def module_name(data, ne):
    restab = ne + struct.unpack_from("<H", data, ne + 0x26)[0]
    n = data[restab]
    return data[restab + 1:restab + 1 + n].decode("ascii", "replace")


def imported_modules(data, ne):
    cmod = struct.unpack_from("<H", data, ne + 0x1E)[0]
    modtab = struct.unpack_from("<H", data, ne + 0x28)[0]
    imptab = struct.unpack_from("<H", data, ne + 0x2A)[0]
    names = []
    for i in range(cmod):
        off = struct.unpack_from("<H", data, ne + modtab + 2 * i)[0]
        at = ne + imptab + off
        n = data[at]
        names.append(data[at + 1:at + 1 + n].decode("ascii", "replace"))
    return names


def _import_name(data, ne, offset):
    imptab = struct.unpack_from("<H", data, ne + 0x2A)[0]
    at = ne + imptab + offset
    if at >= len(data):
        return ""
    n = data[at]
    return data[at + 1:at + 1 + n].decode("latin1", "replace")


def imports(path):
    """Unique Windows-style imports. Address kind comes from the reloc byte."""
    data, ne = load(path)
    mods = imported_modules(data, ne)
    shift = struct.unpack_from("<H", data, ne + 0x32)[0]
    nseg = struct.unpack_from("<H", data, ne + 0x1C)[0]
    segtab = ne + struct.unpack_from("<H", data, ne + 0x22)[0]
    kind = {0: "offset", 2: "selector", 3: "far", 5: "offset32"}
    found = {}
    for i in range(nseg):
        sector, size, flags, _alloc = struct.unpack_from("<HHHH", data, segtab + i * 8)
        if not flags & 0x0100 or size == 0:
            continue
        base = sector << shift
        count = struct.unpack_from("<H", data, base + size)[0]
        pos = base + size + 2
        for _ in range(count):
            if pos + 8 > len(data):
                break
            atype, fl, _disp, t1, t2 = struct.unpack_from("<BBHHH", data, pos)
            pos += 8
            if (fl & 3) == 3 or not (fl & 3):
                continue
            if not 1 <= t1 <= len(mods):
                continue
            if fl & 2:
                ordinal, name = 0, _import_name(data, ne, t2)
            else:
                ordinal, name = t2, ""
            key = (mods[t1 - 1].upper(), ordinal, name.upper())
            found[key] = Import(mods[t1 - 1], ordinal, name, kind.get(atype, f"type{atype}"))
    return sorted(found.values(), key=lambda item: (item.module.upper(), item.ordinal, item.name.upper()))


def exported_names(path):
    """{ordinal: name} from the resident and nonresident name tables."""
    data, ne = load(path)
    names = {}

    def walk(at, first):
        while 0 <= at < len(data):
            n = data[at]
            if n == 0:
                break
            text = data[at + 1:at + 1 + n].decode("latin1", "replace")
            ordinal = struct.unpack_from("<H", data, at + 1 + n)[0]
            if not first and ordinal:
                names.setdefault(ordinal, text)
            first = False
            at += 1 + n + 2

    walk(ne + struct.unpack_from("<H", data, ne + 0x26)[0], True)
    nonres = struct.unpack_from("<I", data, ne + 0x2C)[0]
    if 0 < nonres < len(data):
        walk(nonres, True)
    return names
