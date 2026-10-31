"""NE resources, as Wine krnl386.exe16/resource.c finds and loads them.

An HRSRC is the offset of the NE_NAMEINFO from the start of the module's NE
header, Wine's `(char *)pNameInfo - (char *)pModule`, because NE_MODULE keeps
the header's tables at the header's own offsets.
"""

import struct
from pathlib import Path

NE_SEGFLAGS_MOVEABLE = 0x0010
RT_NAMETABLE = 15


class Stop(Exception):
    pass


class Resources:
    """The resource table of one NE file."""

    def __init__(self, path):
        data = Path(path).read_bytes()
        ne = struct.unpack_from("<I", data, 0x3C)[0]
        self.data = data
        self.ne = ne
        self.rsrctab = struct.unpack_from("<H", data, ne + 0x24)[0]
        restab = struct.unpack_from("<H", data, ne + 0x26)[0]
        self.types = []  # (type_id, [(hrsrc, offset, length, flags, id)])
        self.shift = 0
        # handle of a loaded resource -> hrsrc; hrsrc -> [handle, usage]
        self.loaded = {}
        if not self.rsrctab or self.rsrctab == restab:
            return
        at = ne + self.rsrctab
        self.shift = struct.unpack_from("<H", data, at)[0]
        p = at + 2
        while p + 2 <= len(data):
            type_id = struct.unpack_from("<H", data, p)[0]
            if type_id == 0:
                break
            count = struct.unpack_from("<H", data, p + 2)[0]
            names = []
            q = p + 8
            for _ in range(count):
                off, length, flags, rid = struct.unpack_from("<HHHH", data, q)
                names.append((q - ne, off, length, flags, rid))
                q += 12
            self.types.append((type_id, names))
            p = q

    def _string(self, offset):
        at = self.ne + self.rsrctab + offset
        n = self.data[at]
        return self.data[at + 1:at + 1 + n].decode("latin1")

    def _matches(self, rid, want):
        if isinstance(want, int):
            return rid == (want | 0x8000)
        return not rid & 0x8000 and self._string(rid).lower() == want.lower()

    def find(self, name, type_):
        """Wine FindResource16 over this table. name and type_ are an int id or a string."""
        if not self.types:
            return 0
        if (isinstance(name, str) or isinstance(type_, str)) and any(t == (RT_NAMETABLE | 0x8000) for t, _ in self.types):
            # NE_FindNameTableId maps names through an RT_NAMETABLE resource.
            raise Stop("the module has an RT_NAMETABLE, and neww does not read NE_FindNameTableId's table")
        for type_id, names in self.types:
            if not self._matches(type_id, type_):
                continue
            for hrsrc, _off, _length, _flags, rid in names:
                if self._matches(rid, name):
                    return hrsrc
        return 0

    def entry(self, hrsrc):
        """The NE_NAMEINFO at hrsrc as (offset, length, flags), or None, as LoadResource16 checks it."""
        for _type_id, names in self.types:
            for row in names:
                if row[0] == hrsrc:
                    return row[1:4]
        return None

    def bytes_of(self, hrsrc):
        off, length, _flags = self.entry(hrsrc)
        start = off << self.shift
        return self.data[start:start + (length << self.shift)]

    def size(self, hrsrc):
        """SizeofResource16: the NAMEINFO length shifted by the table's alignment."""
        row = self.entry(hrsrc)
        return (row[1] << self.shift) if row else 0


def res_name(arg_off, arg_sel, string):
    """A LPCSTR argument as Wine's get_res_name reads it: an int id, or a name, '#nnn' an id."""
    if arg_sel == 0:
        return arg_off
    text = string(arg_sel, arg_off)
    if text.startswith("#"):
        digits = ""
        for ch in text[1:]:
            if not ch.isdigit():
                break
            digits += ch
        return int(digits or "0")
    return text
