"""SHELL's registry calls, from Wine dlls/shell.dll16 at WINE_COMMIT.

Wine forwards them to advapi32 over its registry. neww's registry starts
empty and lives in memory for the run: a key the guest did not create is not
there, which is what an empty Wine prefix answers.
"""

import struct

from .handlers import handles, segptr
from .kernel16 import cstr

ERROR_SUCCESS = 0
ERROR_FILE_NOT_FOUND = 2
ERROR_INVALID_HANDLE = 6
ERROR_MORE_DATA = 234
ERROR_NO_MORE_ITEMS = 259
HKEY_CLASSES_ROOT = 0x80000000
# Wine shell.dll16 fix_win16_hkey: 0 is HKEY_CLASSES_ROOT, and the Win16 1 too.
PREDEFINED = {0x80000000, 0x80000001, 0x80000002, 0x80000003, 0x80000004, 0x80000005, 0x80000006}


class Key:
    def __init__(self):
        self.subkeys = {}  # lower name -> (name, Key)
        self.default = None  # bytes, the value RegQueryValue reads


class Registry:
    def __init__(self):
        self.roots = {hkey: Key() for hkey in PREDEFINED}
        self.open = {}
        self.next = 0x100

    def key(self, hkey):
        if hkey in (0, 1):
            hkey = HKEY_CLASSES_ROOT
        return self.roots.get(hkey) or self.open.get(hkey)

    def walk(self, key, path, create=False):
        for part in [p for p in path.split("\\") if p]:
            found = key.subkeys.get(part.lower())
            if found is None:
                if not create:
                    return None
                found = (part, Key())
                key.subkeys[part.lower()] = found
            key = found[1]
        return key

    def handle(self, key):
        h = self.next
        self.next += 4
        self.open[h] = key
        return h


def _reg(wine):
    if not hasattr(wine, "registry"):
        wine.registry = Registry()
    return wine.registry


def _subkey(wine, lo, hi):
    return cstr(wine, hi, lo, 512).decode("cp1252", "replace") if (hi or lo) else ""


def _open(wine, arg, create):
    """RegOpenKey16 / RegCreateKey16(HKEY, LPCSTR, PHKEY)."""
    reg = _reg(wine)
    hkey = segptr(arg(4), arg(5))
    out = (arg(1), arg(0))
    key = reg.key(hkey)
    if key is None:
        return ERROR_INVALID_HANDLE, 0, None
    sub = _subkey(wine, arg(2), arg(3))
    found = reg.walk(key, sub, create)
    if found is None:
        return ERROR_FILE_NOT_FOUND, 0, None
    handle = reg.handle(found)
    if out[0]:
        wine.write(out[0], out[1], struct.pack("<I", handle))
    return ERROR_SUCCESS, 0, None


@handles("SHELL", 1)
def reg_open_key(wine, arg):
    return _open(wine, arg, False)


@handles("SHELL", 2)
def reg_create_key(wine, arg):
    return _open(wine, arg, True)


@handles("SHELL", 3)
def reg_close_key(wine, arg):
    reg = _reg(wine)
    hkey = segptr(arg(0), arg(1))
    if hkey in PREDEFINED:
        return ERROR_SUCCESS, 0, None
    return (ERROR_SUCCESS if reg.open.pop(hkey, None) is not None else ERROR_INVALID_HANDLE), 0, None


@handles("SHELL", 4)
def reg_delete_key(wine, arg):
    reg = _reg(wine)
    key = reg.key(segptr(arg(2), arg(3)))
    sub = _subkey(wine, arg(0), arg(1))
    if key is None:
        return ERROR_INVALID_HANDLE, 0, None
    parts = [p for p in sub.split("\\") if p]
    parent = reg.walk(key, "\\".join(parts[:-1])) if parts else None
    if parent is None or parts[-1].lower() not in parent.subkeys:
        return ERROR_FILE_NOT_FOUND, 0, None
    del parent.subkeys[parts[-1].lower()]
    return ERROR_SUCCESS, 0, None


@handles("SHELL", 5)
def reg_set_value(wine, arg):
    """RegSetValue16(HKEY, subkey, type, data, count): the subkey's default value, made if needed."""
    reg = _reg(wine)
    key = reg.key(segptr(arg(8), arg(9)))
    if key is None:
        return ERROR_INVALID_HANDLE, 0, None
    target = reg.walk(key, _subkey(wine, arg(6), arg(7)), True)
    target.default = cstr(wine, arg(3), arg(2))
    return ERROR_SUCCESS, 0, None


@handles("SHELL", 6)
def reg_query_value(wine, arg):
    """RegQueryValue16(HKEY, subkey, data, LPDWORD count): the default value of the subkey."""
    reg = _reg(wine)
    key = reg.key(segptr(arg(6), arg(7)))
    if key is None:
        return ERROR_INVALID_HANDLE, 0, None
    target = reg.walk(key, _subkey(wine, arg(4), arg(5)))
    if target is None:
        return ERROR_FILE_NOT_FOUND, 0, None
    value = (target.default or b"") + b"\x00"
    count_ptr = (arg(1), arg(0))
    have = struct.unpack("<I", wine.read(count_ptr[0], count_ptr[1], 4).ljust(4, b"\0"))[0] if count_ptr[0] else 0
    if count_ptr[0]:
        wine.write(count_ptr[0], count_ptr[1], struct.pack("<I", len(value)))
    if arg(3) or arg(2):
        if have < len(value):
            return ERROR_MORE_DATA, 0, None
        wine.write(arg(3), arg(2), value)
    return ERROR_SUCCESS, 0, None


@handles("SHELL", 7)
def reg_enum_key(wine, arg):
    """RegEnumKey16(HKEY, index, buffer, size)."""
    reg = _reg(wine)
    key = reg.key(segptr(arg(6), arg(7)))
    if key is None:
        return ERROR_INVALID_HANDLE, 0, None
    index = segptr(arg(4), arg(5))
    names = [name for name, _k in key.subkeys.values()]
    if index >= len(names):
        return ERROR_NO_MORE_ITEMS, 0, None
    raw = names[index].encode("cp1252", "replace")
    size = segptr(arg(0), arg(1))
    if size <= len(raw):
        return ERROR_MORE_DATA, 0, None
    wine.write(arg(3), arg(2), raw + b"\x00")
    return ERROR_SUCCESS, 0, None
