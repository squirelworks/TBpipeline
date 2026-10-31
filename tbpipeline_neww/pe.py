"""A 32-bit PE file: headers, sections, imports, exports and base relocations.

Read the way Wine's loader (dlls/ntdll/loader.c, virtual.c map_image_into_view) reads
them, for an i386 image. Only what loading and binding need.
"""

import struct

IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_FILE_DLL = 0x2000
IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x10B
IMAGE_ORDINAL_FLAG32 = 0x80000000
IMAGE_REL_BASED_ABSOLUTE = 0
IMAGE_REL_BASED_HIGHLOW = 3

DIR_EXPORT, DIR_IMPORT, DIR_RESOURCE, DIR_BASERELOC, DIR_TLS = 0, 1, 2, 5, 9


class Section:
    def __init__(self, name, rva, vsize, raw_off, raw_size, flags):
        self.name = name
        self.rva = rva
        self.vsize = vsize
        self.raw_off = raw_off
        self.raw_size = raw_size
        self.flags = flags


class PE:
    def __init__(self, data, name=""):
        self.data = bytes(data)
        self.name = name
        if self.data[:2] != b"MZ" or len(self.data) < 0x40:
            raise ValueError("no MZ header")
        off = struct.unpack_from("<I", self.data, 0x3C)[0]
        if self.data[off:off + 4] != b"PE\x00\x00":
            raise ValueError("no PE header")
        machine, nsec, _stamp, _sym, _nsym, opt_size, chars = struct.unpack_from("<HHIIIHH", self.data, off + 4)
        if machine != IMAGE_FILE_MACHINE_I386:
            raise ValueError(f"machine {machine:#x}, not i386")
        opt = off + 24
        if struct.unpack_from("<H", self.data, opt)[0] != IMAGE_NT_OPTIONAL_HDR32_MAGIC:
            raise ValueError("not a PE32 optional header")
        self.characteristics = chars
        self.entry = struct.unpack_from("<I", self.data, opt + 16)[0]
        self.image_base = struct.unpack_from("<I", self.data, opt + 28)[0]
        self.section_alignment, self.file_alignment = struct.unpack_from("<II", self.data, opt + 32)
        self.size_of_image, self.size_of_headers = struct.unpack_from("<II", self.data, opt + 56)
        self.stack_reserve, self.stack_commit, self.heap_reserve, self.heap_commit = struct.unpack_from("<IIII", self.data, opt + 72)
        ndirs = struct.unpack_from("<I", self.data, opt + 92)[0]
        self.dirs = [struct.unpack_from("<II", self.data, opt + 96 + 8 * i) for i in range(min(ndirs, 16))]
        self.dirs += [(0, 0)] * (16 - len(self.dirs))
        self.sections = []
        sec = opt + opt_size
        for i in range(nsec):
            raw = self.data[sec + 40 * i: sec + 40 * i + 40]
            name = raw[:8].rstrip(b"\x00").decode("latin1")
            vsize, rva, raw_size, raw_off = struct.unpack_from("<IIII", raw, 8)
            flags = struct.unpack_from("<I", raw, 36)[0]
            self.sections.append(Section(name, rva, vsize, raw_off, raw_size, flags))

    @property
    def is_dll(self):
        return bool(self.characteristics & IMAGE_FILE_DLL)

    def image(self):
        """The image as mapped: headers, then each section at its RVA, zero filled."""
        out = bytearray(self.size_of_image)
        out[:self.size_of_headers] = self.data[:self.size_of_headers]
        for s in self.sections:
            size = min(s.raw_size, s.vsize or s.raw_size)
            chunk = self.data[s.raw_off:s.raw_off + size]
            out[s.rva:s.rva + len(chunk)] = chunk
        return out


def cstr_at(img, rva):
    end = img.index(b"\x00", rva)
    return img[rva:end].decode("latin1")


def imports(img, pe):
    """[(dll name, [(iat rva, name or ordinal)])] from the mapped image."""
    rva, size = pe.dirs[DIR_IMPORT]
    out = []
    if not rva:
        return out
    while True:
        lookup, _stamp, _fwd, name_rva, iat = struct.unpack_from("<IIIII", img, rva)
        if not name_rva and not iat:
            break
        names = []
        table = lookup or iat
        i = 0
        while True:
            thunk = struct.unpack_from("<I", img, table + 4 * i)[0]
            if not thunk:
                break
            if thunk & IMAGE_ORDINAL_FLAG32:
                what = thunk & 0xFFFF
            else:
                what = cstr_at(img, (thunk & 0x7FFFFFFF) + 2)
            names.append((iat + 4 * i, what))
            i += 1
        out.append((cstr_at(img, name_rva), names))
        rva += 20
    return out


def exports(img, pe):
    """(by name {name: rva}, by ordinal {ordinal: rva}, export dir range). A forwarder's rva
    falls inside the export directory."""
    rva, size = pe.dirs[DIR_EXPORT]
    if not rva:
        return {}, {}, (0, 0)
    base, nfuncs, nnames, funcs, names, ords = struct.unpack_from("<IIIIII", img, rva + 16)
    by_ord = {}
    for i in range(nfuncs):
        f = struct.unpack_from("<I", img, funcs + 4 * i)[0]
        if f:
            by_ord[base + i] = f
    by_name = {}
    for i in range(nnames):
        n = struct.unpack_from("<I", img, names + 4 * i)[0]
        o = struct.unpack_from("<H", img, ords + 2 * i)[0]
        by_name[cstr_at(img, n)] = struct.unpack_from("<I", img, funcs + 4 * o)[0]
    return by_name, by_ord, (rva, rva + size)


def relocate(img, pe, base):
    """Apply the base relocations for a load at base. Returns a stop, or None."""
    delta = (base - pe.image_base) & 0xFFFFFFFF
    if not delta:
        return None
    rva, size = pe.dirs[DIR_BASERELOC]
    if not rva:
        return "the image has no relocations and its base is taken"
    end = rva + size
    while rva < end:
        page, block = struct.unpack_from("<II", img, rva)
        if block < 8:
            break
        for i in range((block - 8) // 2):
            entry = struct.unpack_from("<H", img, rva + 8 + 2 * i)[0]
            kind, off = entry >> 12, entry & 0xFFF
            if kind == IMAGE_REL_BASED_ABSOLUTE:
                continue
            if kind != IMAGE_REL_BASED_HIGHLOW:
                return f"relocation type {kind}, which an i386 image does not use"
            at = page + off
            value = struct.unpack_from("<I", img, at)[0]
            struct.pack_into("<I", img, at, (value + delta) & 0xFFFFFFFF)
        rva += block
    return None
