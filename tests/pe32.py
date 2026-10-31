"""Tiny original PE32 DLLs for the bf host's 32-bit tests. No ToolBook bytes.

build() lays one .text section at RVA 0x1000 holding the code, the export
directory and the import directory. Code is a list of (export name, bytes);
the first entry is the DLL entry point. A call to an import is
call_import(n): `call dword [IAT + 4n]`, with the IAT address filled in.
"""

import struct
from pathlib import Path

BASE = 0x10000000
TEXT = 0x1000
EXPORTS = 0x1800
IMPORTS = 0x1A00


def call_import(n):
    return ("import", n)


def build(code, imports=(), dll="TESTW32.DLL"):
    """code: [(name or None, [bytes or call_import(n), ...])]. imports: [(dll, name)]."""
    text = bytearray(0x1000)
    iat = IMPORTS + 0x100
    at = 0
    funcs = []
    for name, parts in code:
        funcs.append((name, TEXT + at))
        for part in parts:
            if isinstance(part, tuple):
                blob = bytes([0xFF, 0x15]) + struct.pack("<I", BASE + iat + 4 * part[1])
            else:
                blob = bytes(part)
            text[at:at + len(blob)] = blob
            at += len(blob)
        at = (at + 15) & ~15

    def put(rva, blob):
        text[rva - TEXT:rva - TEXT + len(blob)] = blob

    named = [(n, rva) for n, rva in funcs if n]
    strings = EXPORTS + 0x100
    name_rvas = []
    put(strings, dll.encode() + b"\x00")
    cursor = strings + len(dll) + 1
    for n, _ in named:
        name_rvas.append(cursor)
        put(cursor, n.encode() + b"\x00")
        cursor += len(n) + 1
    table = EXPORTS + 0x28
    put(EXPORTS, struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, strings, 1, len(named), len(named),
                             table, table + 4 * len(named), table + 8 * len(named)))
    for i, (n, rva) in enumerate(named):
        put(table + 4 * i, struct.pack("<I", rva))
        put(table + 4 * len(named) + 4 * i, struct.pack("<I", name_rvas[i]))
        put(table + 8 * len(named) + 2 * i, struct.pack("<H", i))

    if imports:
        # One descriptor per DLL would be the usual layout; one table per
        # import row keeps this builder short and is still valid.
        descs = IMPORTS
        hints = IMPORTS + 0x180
        rows = list(imports)
        for i, (lib, name) in enumerate(rows):
            put(hints, struct.pack("<H", 0) + name.encode() + b"\x00")
            lib_at = hints + 3 + len(name)
            put(lib_at, lib.encode() + b"\x00")
            ilt = IMPORTS + 0x140 + 8 * i
            put(ilt, struct.pack("<II", hints, 0))
            put(iat + 4 * i, struct.pack("<I", hints))
            put(descs + 20 * i, struct.pack("<IIIII", ilt, 0, 0, lib_at, iat + 4 * i))
            hints = lib_at + len(lib) + 1
        # The loader walks each descriptor's thunks to a zero entry.
        for i in range(len(rows)):
            put(IMPORTS + 0x140 + 8 * i + 4, bytes(4))

    headers = bytearray(0x400)
    headers[0:2] = b"MZ"
    struct.pack_into("<I", headers, 0x3C, 0x40)
    headers[0x40:0x44] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", headers, 0x44, 0x14C, 1, 0, 0, 0, 0xE0, 0x210E)
    opt = 0x58
    struct.pack_into("<HBBIIIIII", headers, opt, 0x10B, 6, 0, 0x1000, 0, 0, funcs[0][1], TEXT, TEXT)
    struct.pack_into("<III", headers, opt + 28, BASE, 0x1000, 0x200)
    struct.pack_into("<HHHHHHI", headers, opt + 40, 4, 0, 0, 0, 4, 0, 0)
    struct.pack_into("<IIIHH", headers, opt + 56, 0x3000, 0x400, 0, 2, 0)
    struct.pack_into("<IIIIII", headers, opt + 72, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    struct.pack_into("<II", headers, opt + 96, EXPORTS, 0x200)
    if imports:
        struct.pack_into("<II", headers, opt + 104, IMPORTS, 20 * (len(imports) + 1))
    sec = opt + 0xE0
    headers[sec:sec + 8] = b".text\x00\x00\x00"
    struct.pack_into("<IIIIIIHHI", headers, sec + 8, 0x1000, TEXT, 0x1000, 0x400, 0, 0, 0, 0, 0xE0000020)
    return bytes(headers) + bytes(text)


def write(directory, filename, blob):
    path = Path(directory) / filename
    path.write_bytes(blob)
    return path
