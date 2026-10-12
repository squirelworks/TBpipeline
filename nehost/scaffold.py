#!/usr/bin/env python3
"""Scaffolding for r3. Walk every ordinal, not just startup.

Ordinal 1 is the loader. The work is a later ordinal. This binds each
FFFF import to a return stub, calls the ordinal, and records what it
did: returned, called a Windows ordinal, stopped on an unbound far
call, or faulted at the entry.
"""

import os
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES,
    UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

UNPACKED = Path(os.environ.get("TBK_UNPACKED") or (Path(__file__).resolve().parent.parent / "bin"))
WORK = (
    "TB80BAS.DLL", "TB80BMP.DLL", "TB80CMP.DLL", "TB80UTL.DLL",
    "TB80MM.DLL", "TBWIN.DLL", "TB80OLE.DLL", "TB80RCR.DLL",
)


def ne_at(buf):
    if len(buf) < 0x40 or buf[:2] != b"MZ":
        return None
    off = struct.unpack_from("<H", buf, 0x3C)[0]
    if off + 2 > len(buf) or buf[off:off + 2] != b"NE":
        return None
    return off


def modules(buf, ne):
    cmod = struct.unpack_from("<H", buf, ne + 0x1E)[0]
    modtab = struct.unpack_from("<H", buf, ne + 0x28)[0]
    imptab = struct.unpack_from("<H", buf, ne + 0x2A)[0]
    out = []
    for i in range(cmod):
        nameoff = struct.unpack_from("<H", buf, ne + modtab + i * 2)[0]
        n = buf[ne + imptab + nameoff]
        out.append(buf[ne + imptab + nameoff + 1:ne + imptab + nameoff + 1 + n].decode("ascii", "replace"))
    return out


def ordinals(buf, ne):
    enttab = struct.unpack_from("<H", buf, ne + 0x04)[0]
    cbenttab = struct.unpack_from("<H", buf, ne + 0x06)[0]
    off = ne + enttab
    end = off + cbenttab
    ordinal = 1
    found = {}
    while off < end:
        count = buf[off]
        if count == 0:
            break
        kind = buf[off + 1]
        off += 2
        for _ in range(count):
            if kind == 0xFF:
                _flags, _int3f, seg, entry = struct.unpack_from("<BBHH", buf, off)
                off += 6
                found[ordinal] = (seg, entry)
            elif kind != 0:
                _flags, entry = struct.unpack_from("<BH", buf, off)
                off += 3
                found[ordinal] = (kind, entry)
            ordinal += 1
    return found


def segment(buf, ne, index):
    segtab = struct.unpack_from("<H", buf, ne + 0x22)[0]
    shift = struct.unpack_from("<H", buf, ne + 0x32)[0] or 9
    nseg = struct.unpack_from("<H", buf, ne + 0x1C)[0]
    if index < 1 or index > nseg:
        return bytearray()
    sec, ln, fl, alloc = struct.unpack_from("<HHHH", buf, ne + segtab + (index - 1) * 8)
    return bytearray(buf[(sec << shift):(sec << shift) + ln])


def imports(buf, ne, seg):
    names = modules(buf, ne)
    segtab = struct.unpack_from("<H", buf, ne + 0x22)[0]
    shift = struct.unpack_from("<H", buf, ne + 0x32)[0] or 9
    nseg = struct.unpack_from("<H", buf, ne + 0x1C)[0]
    if seg < 1 or seg > nseg:
        return {}
    sec, ln, fl, alloc = struct.unpack_from("<HHHH", buf, ne + segtab + (seg - 1) * 8)
    if not fl & 0x0100:
        return {}
    base = sec << shift
    count = struct.unpack_from("<H", buf, base + ln)[0]
    found = {}
    for n in range(count):
        typ, flags, src, mod, ordinal = struct.unpack_from("<BBHHH", buf, base + ln + 2 + n * 8)
        if typ == 3 and flags & 1 and 1 <= mod <= len(names):
            found[src - 1] = (names[mod - 1], ordinal)
    return found


def call(buf, ne, seg, entry):
    nseg = struct.unpack_from("<H", buf, ne + 0x1C)[0]
    if seg < 1 or seg > nseg:
        return "bad-seg", []
    autodata = struct.unpack_from("<H", buf, ne + 0x0E)[0]
    code = bytearray(segment(buf, ne, seg))
    if not code:
        return "empty", []
    data = segment(buf, ne, autodata) if autodata else bytearray(0x100)
    data += b"\x00" * (0x8000 - len(data))
    bound = imports(buf, ne, seg)
    stubs = {}
    for at, (mod, ordinal) in bound.items():
        if at < 0 or at + 5 > len(code) or code[at] != 0x9A:
            continue
        slot = len(stubs)
        stubs[slot] = f"{mod}.{ordinal}"
        struct.pack_into("<HH", code, at + 1, slot * 4, 0x4000)

    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0, 0x80000)
    uc.mem_write(0x10000, bytes(code[:0x10000]))
    uc.mem_write(0x20000, bytes(data[:0x8000]))
    stub = bytearray(max(0x100, len(stubs) * 4 + 4))
    for slot in range(len(stubs)):
        stub[slot * 4:slot * 4 + 4] = b"\xb8" + struct.pack("<H", slot) + b"\xcb"
    uc.mem_write(0x40000, bytes(stub))
    stack = 0x4000
    uc.mem_write(0x30000 + stack - 8, struct.pack("<HHHH", 0, 0x30, 0, 0))
    uc.reg_write(UC_X86_REG_CS, 0x1000)
    uc.reg_write(UC_X86_REG_DS, 0x2000)
    uc.reg_write(UC_X86_REG_ES, 0x2000)
    uc.reg_write(UC_X86_REG_SS, 0x3000)
    uc.reg_write(UC_X86_REG_SP, stack - 8)

    hits = []
    stop = {}

    def on_code(uc, address, size, user):
        if 0x40000 <= address < 0x40000 + len(stub):
            slot = (address - 0x40000) // 4
            if slot in stubs and (not hits or hits[-1] != stubs[slot]):
                hits.append(stubs[slot])
            return
        if not (0x10000 <= address < 0x10000 + len(code)):
            return
        ip = address - 0x10000
        if ip + 5 <= len(code) and code[ip] == 0x9A:
            sel = struct.unpack_from("<H", code, ip + 3)[0]
            if sel != 0x4000:
                stop["at"] = ip
                uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code)
    try:
        uc.emu_start(0x10000 + (entry & 0xFFFF), 0, count=1000)
    except Exception as exc:
        stop["fault"] = type(exc).__name__
    if "fault" in stop and not hits:
        return "fault", hits
    if "at" in stop:
        return f"unbound@{stop['at']:#x}", hits
    return "returned", hits


def walk(path):
    buf = path.read_bytes()
    ne = ne_at(buf)
    if ne is None:
        return [f"{path.name}: not NE"]
    table = ordinals(buf, ne)
    lines = [f"{path.name}: {len(table)} ordinals"]
    counts = {"returned": 0, "fault": 0, "unbound": 0, "called": 0}
    for ordinal in sorted(table):
        seg, entry = table[ordinal]
        try:
            status, hits = call(buf, ne, seg, entry)
        except Exception as exc:
            status, hits = "fault", []
        if hits:
            counts["called"] += 1
        elif status == "returned":
            counts["returned"] += 1
        elif status == "fault":
            counts["fault"] += 1
        else:
            counts["unbound"] += 1
        if ordinal <= 3 or hits or status.startswith("unbound"):
            called = ", ".join(hits[:4]) if hits else ""
            lines.append(f"  ord {ordinal} seg {seg}:{entry:#x} {status} {called}".rstrip())
    lines.append(
        f"  {counts['called']} called, {counts['returned']} returned, "
        f"{counts['unbound']} unbound, {counts['fault']} faulted"
    )
    return lines


def main():
    lines = ["r3 scaffold: later ordinals, FFFF bound"]
    for name in WORK:
        path = UNPACKED / name
        if not path.is_file():
            lines.append(f"{name}: missing")
            continue
        lines.extend(walk(path))
    text = "\n".join(lines)
    print(text)
    out = Path(__file__).resolve().parent / "scaffold.txt"
    out.write_text(text + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
