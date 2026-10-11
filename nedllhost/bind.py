#!/usr/bin/env python3
"""Bind TB80RTM import relocs to unpacked ToolBook NE DLLs.

Windows modules (KERNEL, USER, GDI, SHELL, KEYBOARD, COMMDLG, WIN87EM)
are not in this set. A reloc that names one of them stays a stub. A reloc
that names TB80BAS, TB80RCR, TB80LNL, TB80OLE, TB80UTL or TB80W16 is
resolved to that DLL's entry-table segment and offset.
"""

import os
import struct
import sys

DLLS = {
    "TB80BAS": "TB80BAS.DLL",
    "TB80RCR": "TB80RCR.DLL",
    "TB80LNL": "TB80LNL.DLL",
    "TB80OLE": "TB80OLE.DLL",
    "TB80UTL": "TB80UTL.DLL",
    "TB80W16": "TB80W16.DLL",
}


def u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def modules(data, ne):
    imptab = u16(data, ne + 0x2A)
    modtab = u16(data, ne + 0x28)
    nmod = u16(data, ne + 0x1E)
    names = []
    for i in range(nmod):
        at = ne + imptab + u16(data, ne + modtab + i * 2)
        n = data[at]
        names.append(data[at + 1:at + 1 + n].decode("latin1", "replace").upper())
    return names


def exports(data):
    ne = u16(data, 0x3C)
    entoff, entlen = struct.unpack_from("<HH", data, ne + 4)
    blob = data[ne + entoff:ne + entoff + entlen]
    out = {}
    ordinal = 1
    i = 0
    while i < len(blob):
        count = blob[i]
        i += 1
        if count == 0:
            break
        segment = blob[i]
        i += 1
        if segment == 0:
            ordinal += count
            continue
        for _ in range(count):
            flags = blob[i]
            i += 1
            if segment == 0xFF:
                i += 2
                seg = blob[i]
                i += 1
                offset = u16(blob, i)
                i += 2
            else:
                seg = segment
                offset = u16(blob, i)
                i += 2
            if flags & 1:
                out[ordinal] = (seg, offset)
            ordinal += 1
    return out


def segment_bytes(data, segnum):
    ne = u16(data, 0x3C)
    segoff = u16(data, ne + 0x22)
    shift = u16(data, ne + 0x32)
    off, size, flags, alloc = struct.unpack_from("<HHHH", data, ne + segoff + (segnum - 1) * 8)
    base = off << shift
    return data[base:base + size], flags


def rtm_imports(data):
    ne = u16(data, 0x3C)
    names = modules(data, ne)
    segoff = u16(data, ne + 0x22)
    shift = u16(data, ne + 0x32)
    nseg = u16(data, ne + 0x1C)
    found = []
    for i in range(nseg):
        off, size, flags, alloc = struct.unpack_from("<HHHH", data, ne + segoff + i * 8)
        if not flags & 0x0100:
            continue
        base = off << shift
        count = u16(data, base + size)
        for n in range(count):
            atype, fl, disp, t1, t2 = struct.unpack_from("<BBHHH", data, base + size + 2 + n * 8)
            if not fl & 1 or t1 < 1 or t1 > len(names):
                continue
            found.append((names[t1 - 1], t2, i + 1, disp))
    return found


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "/workspace/artifacts/unpacked"
    rtm = open(os.path.join(root, "TB80RTM.EXE"), "rb").read()
    tables = {}
    for mod, filename in DLLS.items():
        path = os.path.join(root, filename)
        blob = open(path, "rb").read()
        tables[mod] = (exports(blob), blob)
        print(f"{mod}: {len(tables[mod][0])} exported ordinals")
    hits = {}
    missing = {}
    for mod, ordinal, seg, disp in rtm_imports(rtm):
        key = (mod, ordinal)
        if mod not in tables:
            missing[key] = missing.get(key, 0) + 1
            continue
        table, blob = tables[mod]
        if ordinal not in table:
            missing[key] = missing.get(key, 0) + 1
            continue
        hits[key] = table[ordinal]
    print(f"resolved {len(hits)} distinct ToolBook imports, {len(missing)} unresolved")
    for (mod, ordinal), (seg, offset) in sorted(hits.items()):
        raw, flags = segment_bytes(tables[mod][1], seg)
        entry = raw[offset:offset + 6].hex() if offset + 6 <= len(raw) else "past-segment"
        print(f"  {mod}.{ordinal} -> seg {seg}:{offset:#x} {entry}")
    windows = sorted(k for k in missing if k[0] not in tables)
    print("windows stubs:", ", ".join(f"{m}.{n}" for m, n in windows[:12]))
    out = os.path.join(os.path.dirname(__file__), "BIND.txt")
    open(out, "w").write(
        f"resolved {len(hits)}\nunresolved {len(missing)}\n"
        + "\n".join(f"{m}.{n} seg {s}:{o:#x}" for (m, n), (s, o) in sorted(hits.items()))
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
