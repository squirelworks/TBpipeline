"""A tiny original i386 PE DLL for the neww tests. No ToolBook bytes.

build() lays out one section at RVA 0x1000: code, a data word, the import directory, the
export directory and the base relocations, in that order.

The code has these functions (stdcall):

    DllMain(h, reason, reserved)   stores reason at DATA, answers 1 (or 0 with fail=True)
    Add(a, b)                      a + b
    Ver()                          calls the first import with no arguments
    Pass2(a, b)                    calls the second import with (a, b)
"""

import struct

BASE = 0x10000000
TEXT = 0x1000
DLLMAIN, ADD, VER, PASS2 = 0x1000, 0x1020, 0x1040, 0x1060
DATA = 0x1200
IMPORTS = 0x1300
EXPORTS = 0x1400
RELOCS = 0x1500
SIZE = 0x2000


def build(name="TINY", imports=(("KERNEL32.dll", ("GetVersion", "GetTempPathA")),), base=BASE, fail=False):
    sec = bytearray(0x1000)

    def put(rva, raw):
        sec[rva - TEXT:rva - TEXT + len(raw)] = raw

    relocs = []
    # DllMain: mov eax, [esp+8] ; mov [DATA], eax ; mov eax, ok ; ret 12
    code = bytes([0x8B, 0x44, 0x24, 0x08, 0xA3]) + struct.pack("<I", base + DATA)
    relocs.append(DLLMAIN + 5)
    code += bytes([0xB8]) + struct.pack("<I", 0 if fail else 1) + bytes([0xC2, 0x0C, 0x00])
    put(DLLMAIN, code)
    # Add: mov eax, [esp+4] ; add eax, [esp+8] ; ret 8
    put(ADD, bytes([0x8B, 0x44, 0x24, 0x04, 0x03, 0x44, 0x24, 0x08, 0xC2, 0x08, 0x00]))
    iat = IMPORTS + 0x60
    # Ver: call [iat] ; ret
    put(VER, bytes([0xFF, 0x15]) + struct.pack("<I", base + iat) + bytes([0xC3]))
    relocs.append(VER + 2)
    # Pass2: push [esp+8] ; push [esp+8] ; call [iat+4] ; ret 8
    put(PASS2, bytes([0xFF, 0x74, 0x24, 0x08, 0xFF, 0x74, 0x24, 0x08, 0xFF, 0x15])
        + struct.pack("<I", base + iat + 4) + bytes([0xC2, 0x08, 0x00]))
    relocs.append(PASS2 + 10)

    # Imports: descriptors at IMPORTS, then lookup tables, IATs, names.
    descs = bytearray()
    lookup_at = IMPORTS + 0x40
    names = bytearray()
    names_at = IMPORTS + 0x80
    entries = []
    for dll, funcs in imports:
        entries.append((dll, funcs))
    # One IAT block at IMPORTS + 0x60 and lookups at IMPORTS + 0x40, each DLL's run ending in 0.
    flat = [(dll, f) for dll, funcs in entries for f in funcs]
    lookups = []
    for dll, f in flat:
        lookups.append(names_at + len(names))
        names += b"\x00\x00" + f.encode() + b"\x00"
        if len(names) % 2:
            names += b"\x00"
    dll_names = {}
    for dll, _ in entries:
        dll_names[dll] = names_at + len(names)
        names += dll.encode() + b"\x00"
    i = 0
    for dll, funcs in entries:
        descs += struct.pack("<IIIII", lookup_at + 4 * i, 0, 0, dll_names[dll], iat + 4 * i)
        i += len(funcs) + 1
    descs += bytes(20)
    put(IMPORTS, descs)
    k = 0
    words = []
    for dll, funcs in entries:
        words += lookups[k:k + len(funcs)] + [0]
        k += len(funcs)
    put(lookup_at, b"".join(struct.pack("<I", w) for w in words))
    put(iat, b"".join(struct.pack("<I", w) for w in words))
    put(names_at, bytes(names))

    # Exports: Add, Pass2, Ver by name, ordinals 1..3 from base 1.
    funcs = [ADD, VER, PASS2]
    export_names = [("Add", 0), ("Pass2", 2), ("Ver", 1)]
    at = EXPORTS + 0x28
    func_tab, name_tab, ord_tab, strings = at, at + 12, at + 24, at + 30
    blob = bytearray()
    name_rvas = []
    dll_name_rva = strings
    blob += (name + ".dll").encode() + b"\x00"
    for n, _o in export_names:
        name_rvas.append(strings + len(blob))
        blob += n.encode() + b"\x00"
    put(EXPORTS, struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, dll_name_rva, 1, 3, 3, func_tab, name_tab, ord_tab))
    put(func_tab, b"".join(struct.pack("<I", f) for f in funcs))
    put(name_tab, b"".join(struct.pack("<I", r) for r in name_rvas))
    put(ord_tab, b"".join(struct.pack("<H", o) for _n, o in export_names))
    put(strings, bytes(blob))
    export_size = strings + len(blob) - EXPORTS

    # Relocations: one block for page 0x1000.
    entries_r = [0x3000 | (r - 0x1000) for r in relocs]
    if len(entries_r) % 2:
        entries_r.append(0)
    block = struct.pack("<II", 0x1000, 8 + 2 * len(entries_r)) + b"".join(struct.pack("<H", e) for e in entries_r)
    put(RELOCS, block)

    # Headers.
    head = bytearray(0x200)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x40)
    head[0x40:0x44] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", head, 0x44, 0x014C, 1, 0, 0, 0, 0xE0, 0x2102)
    opt = 0x58
    struct.pack_into("<HBBIIIIII", head, opt, 0x10B, 6, 0, 0x1000, 0, 0, DLLMAIN, TEXT, TEXT)
    struct.pack_into("<III", head, opt + 28, base, 0x1000, 0x200)
    struct.pack_into("<HHHHHHI", head, opt + 40, 4, 0, 0, 0, 4, 0, 0)
    struct.pack_into("<IIIHH", head, opt + 56, SIZE, 0x200, 0, 2, 0)
    struct.pack_into("<IIIIII", head, opt + 72, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    dirs = [(0, 0)] * 16
    dirs[0] = (EXPORTS, export_size)
    dirs[1] = (IMPORTS, 0x28 * len(entries))
    dirs[5] = (RELOCS, len(block))
    for i, (rva, size) in enumerate(dirs):
        struct.pack_into("<II", head, opt + 96 + 8 * i, rva, size)
    sh = opt + 0xE0
    head[sh:sh + 8] = b".text\x00\x00\x00"
    struct.pack_into("<IIIIIIHHI", head, sh + 8, 0x1000, TEXT, 0x1000, 0x200, 0, 0, 0, 0, 0xE0000060)
    return bytes(head) + bytes(sec)
