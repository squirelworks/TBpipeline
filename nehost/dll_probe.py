#!/usr/bin/env python3
"""Call ordinal 1 of each unpacked 16-bit DLL, with FFFF imports bound.

A FFFF far call is a type-3 reloc: module index and ordinal. Each one is
patched to a stub that returns. The log says which ordinals ran, and
where the next unbound call is.
"""

import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES,
    UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

UNPACKED = Path("/workspace/artifacts/unpacked")


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


def first_ordinal(buf, ne):
    enttab = struct.unpack_from("<H", buf, ne + 0x04)[0]
    cbenttab = struct.unpack_from("<H", buf, ne + 0x06)[0]
    off = ne + enttab
    end = off + cbenttab
    ordinal = 1
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
                if ordinal == 1:
                    return seg, entry
            elif kind != 0:
                _flags, entry = struct.unpack_from("<BH", buf, off)
                off += 3
                if ordinal == 1:
                    return kind, entry
            ordinal += 1
        if ordinal > 1:
            break
    return None


def segment(buf, ne, index):
    segtab = struct.unpack_from("<H", buf, ne + 0x22)[0]
    shift = struct.unpack_from("<H", buf, ne + 0x32)[0] or 9
    sec, ln, fl, alloc = struct.unpack_from("<HHHH", buf, ne + segtab + (index - 1) * 8)
    return bytearray(buf[(sec << shift):(sec << shift) + ln])


def imports(buf, ne, seg):
    names = modules(buf, ne)
    segtab = struct.unpack_from("<H", buf, ne + 0x22)[0]
    shift = struct.unpack_from("<H", buf, ne + 0x32)[0] or 9
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


def probe(path):
    buf = path.read_bytes()
    ne = ne_at(buf)
    if ne is None:
        return f"{path.name}: not NE"
    found = first_ordinal(buf, ne)
    if not found:
        return f"{path.name}: no ordinal 1"
    seg, entry = found
    if seg == 0 or seg > struct.unpack_from("<H", buf, ne + 0x1C)[0]:
        return f"{path.name}: ordinal 1 seg {seg} out of range"
    autodata = struct.unpack_from("<H", buf, ne + 0x0E)[0]
    code = bytearray(segment(buf, ne, seg))
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
    stub = bytearray(0x800)
    for slot in range(len(stubs)):
        stub[slot * 4:slot * 4 + 4] = b"\xb8" + struct.pack("<H", slot) + b"\xcb"
    uc.mem_write(0x40000, bytes(stub))

    stack = 0x4000
    frame = struct.pack("<HHHH", 0, 0x30, 0, 0)
    uc.mem_write(0x30000 + stack - len(frame), frame)
    uc.reg_write(UC_X86_REG_CS, 0x1000)
    uc.reg_write(UC_X86_REG_DS, 0x2000)
    uc.reg_write(UC_X86_REG_ES, 0x2000)
    uc.reg_write(UC_X86_REG_SS, 0x3000)
    uc.reg_write(UC_X86_REG_SP, stack - len(frame))

    hits = []
    stop = {}

    def on_code(uc, address, size, user):
        if 0x40000 <= address < 0x40800:
            slot = (address - 0x40000) // 4
            if slot in stubs and (not hits or hits[-1] != stubs[slot]):
                hits.append(stubs[slot])
            return
        if not (0x10000 <= address < 0x10000 + len(code)):
            return
        ip = address - 0x10000
        if ip + 5 <= len(code) and code[ip] == 0x9A:
            sel = struct.unpack_from("<H", code, ip + 3)[0]
            if sel == 0x4000:
                return
            stop["at"] = (ip, bytes(code[ip:ip + 5]))
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code)
    try:
        uc.emu_start(0x10000 + entry, 0, count=2000)
    except Exception as exc:
        stop["fault"] = str(exc)
    cs = uc.reg_read(UC_X86_REG_CS)
    ip = uc.reg_read(UC_X86_REG_IP)
    called = ", ".join(hits[:8]) or "none"
    if "at" in stop:
        at, raw = stop["at"]
        return f"{path.name}: ord1 seg {seg}:{entry:#x} called [{called}] unbound {at:#x} {raw.hex()}"
    return f"{path.name}: ord1 seg {seg}:{entry:#x} called [{called}] {cs:#x}:{ip:#x} {stop.get('fault', 'returned')}"


def main():
    lines = ["ordinal 1 probe, FFFF imports bound to return stubs"]
    for path in sorted(UNPACKED.glob("TB*.DLL")) + sorted(UNPACKED.glob("TB*.EXE")):
        try:
            lines.append("  " + probe(path))
        except Exception as exc:
            lines.append(f"  {path.name}: {exc}")
    text = "\n".join(lines)
    print(text)
    out = Path(__file__).resolve().parent / "dll_probe.txt"
    out.write_text(text + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
