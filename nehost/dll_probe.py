#!/usr/bin/env python3
"""Call ordinal 1 of each unpacked 16-bit ToolBook DLL.

This is the path taken when TB80RTM does not open the book. Each DLL is
loaded the way TBKBITMAP was: its first export, real mode, stop at the
first far call. 32-bit images are skipped.
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
                flags, _int3f, seg, entry = struct.unpack_from("<BBHH", buf, off)
                off += 6
                if ordinal == 1:
                    return seg, entry, "movable"
            elif kind != 0:
                flags, entry = struct.unpack_from("<BH", buf, off)
                off += 3
                if ordinal == 1:
                    return kind, entry, "fixed"
            ordinal += 1
        if ordinal > 1:
            break
    return None


def segment(buf, ne, index):
    segtab = struct.unpack_from("<H", buf, ne + 0x22)[0]
    shift = struct.unpack_from("<H", buf, ne + 0x32)[0] or 9
    sec, ln, fl, alloc = struct.unpack_from("<HHHH", buf, ne + segtab + (index - 1) * 8)
    return bytearray(buf[(sec << shift):(sec << shift) + ln])


def probe(path):
    buf = path.read_bytes()
    ne = ne_at(buf)
    if ne is None:
        return f"{path.name}: not NE"
    found = first_ordinal(buf, ne)
    if not found:
        return f"{path.name}: no ordinal 1"
    seg, entry, kind = found
    if seg == 0 or seg > struct.unpack_from("<H", buf, ne + 0x1C)[0]:
        return f"{path.name}: ordinal 1 seg {seg} out of range"
    autodata = struct.unpack_from("<H", buf, ne + 0x0E)[0]
    code = segment(buf, ne, seg)
    data = segment(buf, ne, autodata) if autodata else bytearray(0x100)
    data += b"\x00" * (0x8000 - len(data))

    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0, 0x80000)
    uc.mem_write(0x10000, bytes(code[:0x10000]))
    uc.mem_write(0x20000, bytes(data[:0x8000]))
    stack = 0x4000
    frame = struct.pack("<HHHH", 0, 0x30, 0, 0)
    uc.mem_write(0x30000 + stack - len(frame), frame)
    uc.reg_write(UC_X86_REG_CS, 0x1000)
    uc.reg_write(UC_X86_REG_DS, 0x2000)
    uc.reg_write(UC_X86_REG_ES, 0x2000)
    uc.reg_write(UC_X86_REG_SS, 0x3000)
    uc.reg_write(UC_X86_REG_SP, stack - len(frame))

    stop = {}

    def on_code(uc, address, size, user):
        if not (0x10000 <= address < 0x10000 + len(code)):
            return
        ip = address - 0x10000
        if ip + 5 <= len(code) and code[ip] == 0x9A:
            sp = uc.reg_read(UC_X86_REG_SP)
            frame = bytes(uc.mem_read(0x30000 + sp, 8))
            stop["at"] = (ip, bytes(code[ip:ip + 5]), frame)
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code)
    try:
        uc.emu_start(0x10000 + entry, 0, count=500)
    except Exception as exc:
        stop["fault"] = str(exc)
    cs = uc.reg_read(UC_X86_REG_CS)
    ip = uc.reg_read(UC_X86_REG_IP)
    if "at" in stop:
        at, raw, frame = stop["at"]
        words = " ".join(f"{w:04x}" for w in struct.unpack("<4H", frame))
        return f"{path.name}: ord1 {kind} seg {seg}:{entry:#x} far call {at:#x} {raw.hex()} stack {words}"
    return f"{path.name}: ord1 {kind} seg {seg}:{entry:#x} ran {cs:#x}:{ip:#x} {stop.get('fault', 'no far call')}"


def main():
    lines = ["ordinal 1 probe, stop at first far call"]
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
