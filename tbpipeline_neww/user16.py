"""USER text and atoms, from Wine dlls/user.exe16 at WINE_COMMIT, for the loaded spec rows.

Window management, painting and messages are not here yet. Those rows still
answer by default.
"""

import struct

from .handlers import handles, segptr, signed
from .kernel16 import cstr

# Wine atom.c: MAXINTATOM. String atoms are 0xC000 and up, integer atoms below.
MAXINTATOM = 0xC000


def _ansi(text):
    return text.decode("cp1252", "replace")


def _bytes(text):
    return text.encode("cp1252", "replace")


# ---------------------------------------------------------------- keyboard.drv16 keyboard.c

def _code_page(wine, src, dst, from_cp, to_cp):
    text = cstr(wine, src >> 16, src & 0xFFFF)
    out = text.decode(from_cp, "replace").encode(to_cp, "replace")
    wine.write(dst >> 16, dst & 0xFFFF, out + b"\x00")


@handles("KEYBOARD", 5)
def ansi_to_oem(wine, arg):
    """keyboard.c AnsiToOem16(s, d): CharToOemA, then -1. The ANSI code page is 1252 and the
    OEM one 437, Wine's defaults for an English locale. A character 437 lacks becomes '?',
    where Windows' best-fit table may pick a look-alike."""
    _code_page(wine, segptr(arg(2), arg(3)), segptr(arg(0), arg(1)), "cp1252", "cp437")
    return 0xFFFF, 0, None


@handles("KEYBOARD", 6)
def oem_to_ansi(wine, arg):
    """keyboard.c OemToAnsi16(s, d): OemToCharA, then -1. Code page 437 to 1252."""
    _code_page(wine, segptr(arg(2), arg(3)), segptr(arg(0), arg(1)), "cp437", "cp1252")
    return 0xFFFF, 0, None


# ---------------------------------------------------------------- strings, user.c

@handles("USER", 430)
def lstrcmp(wine, arg):
    """user.c lstrcmp16: strcmp, as -1, 0 or 1."""
    a, b = cstr(wine, arg(3), arg(2)), cstr(wine, arg(1), arg(0))
    return ((a > b) - (a < b)) & 0xFFFF, 0, None


@handles("USER", 471)
def lstrcmpi(wine, arg):
    """user.c lstrcmpi16 -> lstrcmpiA: CompareStringA with NORM_IGNORECASE, minus 2.

    neww compares the strings lower-cased in code page 1252, character by character. Equal and
    not equal are Wine's answer. The order of punctuation, which CompareString weighs
    linguistically, can differ.
    """
    a, b = _ansi(cstr(wine, arg(3), arg(2))).lower(), _ansi(cstr(wine, arg(1), arg(0))).lower()
    return ((a > b) - (a < b)) & 0xFFFF, 0, None


def _case_ptr(wine, arg, upper):
    """AnsiUpper16 / AnsiLower16: a character when the high word is 0, else the string in place."""
    ptr = segptr(arg(0), arg(1))
    if not ptr >> 16:
        ch = bytes([ptr & 0xFF])
        out = _bytes(_ansi(ch).upper() if upper else _ansi(ch).lower())[:1] or ch
        return out[0], 0, None
    text = cstr(wine, arg(1), arg(0))
    conv = _bytes(_ansi(text).upper() if upper else _ansi(text).lower())
    if len(conv) == len(text):
        wine.write(arg(1), arg(0), conv)
    return arg(0), arg(1), None


@handles("USER", 431)
def ansi_upper(wine, arg):
    return _case_ptr(wine, arg, True)


@handles("USER", 432)
def ansi_lower(wine, arg):
    return _case_ptr(wine, arg, False)


def _case_buff(wine, arg, upper):
    """AnsiUpperBuff16 / AnsiLowerBuff16(ptr, len): len 0 means 65536. Returns len."""
    length = arg(0) or 0x10000
    data = wine.read(arg(2), arg(1), length)
    conv = bytes(_bytes(_ansi(bytes([c])).upper() if upper else _ansi(bytes([c])).lower())[:1] or bytes([c]) for c in data)
    wine.write(arg(2), arg(1), conv)
    return arg(0), 0, None


@handles("USER", 437)
def ansi_upper_buff(wine, arg):
    return _case_buff(wine, arg, True)


@handles("USER", 438)
def ansi_lower_buff(wine, arg):
    return _case_buff(wine, arg, False)


def _char(arg):
    return _ansi(bytes([arg(0) & 0xFF]))


@handles("USER", 433)
def is_char_alpha(wine, arg):
    return (1 if _char(arg).isalpha() else 0), 0, None


@handles("USER", 434)
def is_char_alpha_numeric(wine, arg):
    return (1 if _char(arg).isalnum() else 0), 0, None


@handles("USER", 435)
def is_char_upper(wine, arg):
    return (1 if _char(arg).isupper() else 0), 0, None


@handles("USER", 436)
def is_char_lower(wine, arg):
    return (1 if _char(arg).islower() else 0), 0, None


@handles("USER", 472)
def ansi_next(wine, arg):
    """user.c AnsiNext16: current + 1, unless it points at the NUL (CharNextA, no DBCS in 1252)."""
    ptr = segptr(arg(0), arg(1))
    at = wine.read(ptr >> 16, ptr & 0xFFFF, 1)
    if at and at != b"\x00":
        ptr += 1
    return ptr & 0xFFFF, ptr >> 16, None


@handles("USER", 473)
def ansi_prev(wine, arg):
    """user.c AnsiPrev16(start, current): current - 1, not before start (CharPrevA)."""
    cur = segptr(arg(0), arg(1))
    start = segptr(arg(2), arg(3))
    if (cur & 0xFFFF) > (start & 0xFFFF):
        cur -= 1
    return cur & 0xFFFF, cur >> 16, None


# ---------------------------------------------------------------- wsprintf, user.c

def _format(spec, pull, read_str):
    """wvsprintf16, line for line. pull(size) takes the next 2 or 4 argument bytes."""
    out = bytearray()
    i = 0
    while i < len(spec):
        if spec[i] != 0x25:
            out.append(spec[i])
            i += 1
            continue
        i += 1
        if i < len(spec) and spec[i] == 0x25:
            out.append(0x25)
            i += 1
            continue
        flags = width = precision = 0
        if i < len(spec) and spec[i] == ord("-"):
            flags |= 1
            i += 1
        if i < len(spec) and spec[i] == ord("#"):
            flags |= 2
            i += 1
        if i < len(spec) and spec[i] == ord("0"):
            flags |= 4
            i += 1
        while i < len(spec) and 0x30 <= spec[i] <= 0x39:
            width = width * 10 + spec[i] - 0x30
            i += 1
        if i < len(spec) and spec[i] == ord("."):
            i += 1
            while i < len(spec) and 0x30 <= spec[i] <= 0x39:
                precision = precision * 10 + spec[i] - 0x30
                i += 1
        if i < len(spec) and spec[i] == ord("l"):
            flags |= 8
            i += 1
        elif i < len(spec) and spec[i] == ord("h"):
            flags |= 0x10
            i += 1
        c = chr(spec[i]) if i < len(spec) else "\0"
        if c in "cC":
            kind = "char"
        elif c in "sS":
            kind = "string"
        elif c in "di":
            kind = "signed"
        elif c == "u":
            kind = "unsigned"
        elif c in "pXx":
            if c == "p":
                width, flags = 8, flags | 4
            if c in "pX":
                flags |= 0x20
            kind = "hexa"
        else:
            # Unknown: Wine steps back so the character prints as itself.
            kind = None
            i -= 1
        i += 1
        if kind is None:
            continue
        number = b""
        if kind == "char":
            char_view = pull(2) & 0xFF
            length = precision = 1
        elif kind == "string":
            view = read_str(pull(4))
            length = 0
            while (not precision or length < precision) and length < len(view):
                length += 1
            precision = length
            view = view[:length]
        else:
            value = pull(4) if flags & 8 else pull(2)
            if kind == "signed":
                value = (value - (1 << 32) if value & 0x80000000 else value) if flags & 8 else signed(value)
                number = str(value).encode()
            elif kind == "unsigned":
                number = str(value).encode()
            else:
                number = (f"{value:X}" if flags & 0x20 else f"{value:x}").encode()
            length = len(number)
        if precision < length:
            precision = length
        if flags & 1:
            flags &= ~4
        if flags & 4 and width > precision:
            precision = width
        if flags & 2:
            length += 2
        sign = 0
        if not flags & 1:
            out += b" " * max(width - precision, 0)
        if kind == "char":
            if char_view:
                out.append(char_view)
            elif width > 1:
                out.append(0x20)
        elif kind == "string":
            out += view
        else:
            if kind == "hexa" and flags & 2:
                out += b"0X" if flags & 0x20 else b"0x"
                length -= 2
            if kind in ("hexa", "signed") and number[:1] == b"-":
                out.append(0x2D)
                sign = 1
            out += b"0" * max(precision - length, 0)
            if length > sign:
                out += number[sign:length]
        if flags & 1:
            out += b" " * max(width - precision, 0)
    return bytes(out)


def _sprintf(wine, buf, spec_ptr, args_sel, args_off):
    pos = [args_off]

    def pull(size):
        raw = wine.read(args_sel, pos[0], size)
        pos[0] += size
        raw = raw.ljust(size, b"\x00")
        return struct.unpack("<H" if size == 2 else "<I", raw)[0]

    def read_str(ptr):
        sel, off = ptr >> 16, ptr & 0xFFFF
        size = wine.size(sel) if sel else None
        if size is None or off >= size:
            # IsBadReadPtr16 is TRUE: "".
            return b""
        return cstr(wine, sel, off)

    text = _format(cstr(wine, spec_ptr >> 16, spec_ptr & 0xFFFF), pull, read_str)
    wine.write(buf >> 16, buf & 0xFFFF, text + b"\x00")
    return len(text) & 0xFFFF, 0, None


@handles("USER", 421)
def wvsprintf(wine, arg):
    """user.c wvsprintf16(buffer, spec, VA_LIST16 args)."""
    return _sprintf(wine, segptr(arg(4), arg(5)), segptr(arg(2), arg(3)), arg(1), arg(0))


@handles("USER", 420)
def wsprintf(wine, arg):
    """user.c wsprintf16, varargs: buffer and spec, then the arguments, on the caller's stack."""
    ss, sp = arg.regs("ss"), arg.regs("sp")
    return _sprintf(wine, segptr(arg(0), arg(1)), segptr(arg(2), arg(3)), ss, sp + 12)


# ---------------------------------------------------------------- atoms

def _atom_name(wine, lo, hi):
    """An atom argument: an int (MAKEINTATOM or '#nnn') or a name."""
    if not hi:
        return lo
    name = cstr(wine, hi, lo, 256)
    if name.startswith(b"#") and name[1:].isdigit():
        return int(name[1:])
    return _ansi(name)


@handles("USER", 268)
def global_add_atom(wine, arg):
    """GlobalAddAtom16 -> GlobalAddAtomA: an integer atom is itself (0 if out of range), a string
    atom gets a reference in the global table that RegisterWindowMessage and
    RegisterClipboardFormat share."""
    name = _atom_name(wine, arg(0), arg(1))
    if isinstance(name, int):
        return (name if 0 < name < MAXINTATOM else 0), 0, None
    return wine.add_atom(name), 0, None


@handles("USER", 270)
def global_find_atom(wine, arg):
    name = _atom_name(wine, arg(0), arg(1))
    if isinstance(name, int):
        return (name if 0 < name < MAXINTATOM else 0), 0, None
    return wine.messages.get(name.lower(), 0), 0, None


@handles("USER", 269)
def global_delete_atom(wine, arg):
    """GlobalDeleteAtom: 0 on success. The reference count goes down. neww keeps the name until
    its count is 0, then frees it."""
    return wine.delete_atom(arg(0)), 0, None


@handles("USER", 271)
def global_get_atom_name(wine, arg):
    """GlobalGetAtomNameA(atom, buffer, size): an integer atom is '#nnn'. Returns the length copied."""
    atom, size = arg(3), signed(arg(0))
    if 0 < atom < MAXINTATOM:
        text = f"#{atom}".encode()
    else:
        text = next((_bytes(n) for n, a in wine.atom_names.items() if a == atom), None)
        if text is None:
            return 0, 0, None
    if size <= 0:
        return 0, 0, None
    text = text[:size - 1]
    wine.write(arg(2), arg(1), text + b"\x00")
    return len(text), 0, None


@handles("USER", 145)
def register_clipboard_format(wine, arg):
    """RegisterClipboardFormat16 -> RegisterClipboardFormatA: a string atom in the global table."""
    name = cstr(wine, arg(1), arg(0), 256)
    if not name:
        return 0, 0, None
    return wine.add_atom(_ansi(name)), 0, None


@handles("USER", 146)
def get_clipboard_format_name(wine, arg):
    """GetClipboardFormatName16(format, buffer, size): the atom's name. 0 for a predefined format."""
    fmt, size = arg(3), signed(arg(0))
    text = next((_bytes(n) for n, a in wine.atom_names.items() if a == fmt), None)
    if text is None or size <= 0:
        return 0, 0, None
    text = text[:size - 1]
    wine.write(arg(2), arg(1), text + b"\x00")
    return len(text), 0, None
