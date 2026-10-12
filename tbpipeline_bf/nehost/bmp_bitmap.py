#!/usr/bin/env python3
"""Call TB80BMP ordinal 3, TBKBITMAP, and stop at the first external call.

TBKBITMAP is segment 3 offset 0x3E0. It pushes its two arguments and
calls 0x1FA2. That function's first far call is the contract we do not
have pinned. This host loads the unpacked segment, calls the ordinal
with two dummy far pointers, and logs the stack at the first call it
cannot follow.
"""

import os
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DS,
    UC_X86_REG_ES, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

HERE = Path(__file__).resolve().parent
DLL = Path(os.environ.get("TBK_UNPACKED") or HERE.parent / "bin") / "TB80BMP.DLL"

ENTRY = 0x3E0
SEG = 3
DGROUP = 27


def desc(base, limit, access):
    raw = bytearray(8)
    raw[0] = limit & 0xFF
    raw[1] = (limit >> 8) & 0xFF
    raw[2] = base & 0xFF
    raw[3] = (base >> 8) & 0xFF
    raw[4] = (base >> 16) & 0xFF
    raw[5] = access
    raw[6] = 0x40 | ((limit >> 16) & 0x0F)
    raw[7] = (base >> 24) & 0xFF
    return bytes(raw)


def segment(buf, index):
    ne = struct.unpack_from("<H", buf, 0x3C)[0]
    segtab = struct.unpack_from("<H", buf, ne + 0x22)[0]
    shift = struct.unpack_from("<H", buf, ne + 0x32)[0] or 9
    sec, ln, fl, alloc = struct.unpack_from("<HHHH", buf, ne + segtab + (index - 1) * 8)
    return bytearray(buf[(sec << shift):(sec << shift) + ln]), max(alloc, ln)


def main():
    blob = DLL.read_bytes()
    code, _ = segment(blob, SEG)
    data, dalloc = segment(blob, DGROUP)
    data += b"\x00" * (0x4000 - len(data))

    # dummy graphic object and stream, the two arguments
    obj = 0x3000
    stream = 0x3200
    data[obj:obj + 0x40] = b"\x00" * 0x40
    data[stream:stream + 0x20] = b"BM" + b"\x00" * 0x1E

    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0, 0x80000)
    uc.mem_write(0x10000, bytes(code))
    uc.mem_write(0x20000, bytes(data))

    # real mode. CS 0x1000 is linear 0x10000, DS 0x2000 is 0x20000.
    stack = 0x4000
    frame = struct.pack("<HHHH", 0, 0x30, obj, stream)
    uc.mem_write(0x30000 + stack - len(frame), frame)
    uc.reg_write(UC_X86_REG_CS, 0x1000)
    uc.reg_write(UC_X86_REG_DS, 0x2000)
    uc.reg_write(UC_X86_REG_ES, 0x2000)
    uc.reg_write(UC_X86_REG_SS, 0x3000)
    uc.reg_write(UC_X86_REG_SP, stack - len(frame))
    uc.reg_write(UC_X86_REG_IP, ENTRY)

    log = []
    stop = {"at": None}

    def on_code(uc, address, size, user):
        ip = address - 0x10000
        if ip == 0x1FCD:
            sp = uc.reg_read(UC_X86_REG_SP)
            frame = bytes(uc.mem_read(0x30000 + sp, 16))
            stop["at"] = (ip, sp, frame)
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code)
    try:
        uc.emu_start(0x10000 + ENTRY, 0, count=2000)
    except Exception as exc:
        log.append(("fault", str(exc)))

    lines = [
        f"TB80BMP TBKBITMAP seg {SEG}:{ENTRY:#x}",
        f"dll {DLL}",
    ]
    if stop["at"]:
        ip, sp, frame = stop["at"]
        words = struct.unpack("<8H", frame)
        lines.append(f"stopped at far call {ip:#x}")
        lines.append(f"  bytes {code[ip:ip+5].hex()}  lcall, selector not bound")
        lines.append(f"  stack sp {sp:#x} {' '.join(f'{w:04x}' for w in words)}")
        lines.append("  pushed before the call: SS:local, DS:0x23aa, 0x02a6, 0x1fd0, DS:0x23aa")
    else:
        lines.append("did not reach the far call")
    for item in log:
        lines.append(f"  {item}")
    text = "\n".join(lines)
    print(text)
    out = HERE / "bmp_bitmap.txt"
    out.write_text(text + "\n", encoding="utf-8")
    print("wrote", out)
    return 0 if stop["at"] else 1


if __name__ == "__main__":
    sys.exit(main())
