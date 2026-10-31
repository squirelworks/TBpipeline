"""State behind the KERNEL handlers: profiles, files written in memory, blocks.

Wine's answers here read the host. neww's host is the --b directory, read by
base name, and what the guest wrote during the run, kept in memory. Nothing is
written to disk.
"""

import struct
from pathlib import Path

HFILE_ERROR = 0xFFFF


def _ini(text):
    """Sections in file order: [(name, [(key, value)])]. Wine's PROFILE_Load, without its
    Unicode detection: lines are latin-1, keys and values stripped, a line with no '=' is a key
    with no value."""
    sections = [("", [])]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("["):
            end = line.find("]")
            sections.append((line[1:end if end > 0 else len(line)].strip(), []))
            continue
        key, eq, value = line.partition("=")
        sections[-1][1].append((key.strip(), value.strip() if eq else None))
    return sections


class KernelState:
    """Mixed into Wine. The machine sets read, write, linear, resize, is_code."""

    def _kstate(self):
        if not hasattr(self, "written"):
            # Base name, upper case -> bytearray: files the guest created this run.
            self.written = {}
            # Base name, upper case -> parsed INI after the guest wrote it.
            self.profiles = {}
            self.error_mode = 0

    # ------------------------------------------------------------ profiles

    def _profile(self, filename):
        self._kstate()
        name = filename.decode("latin1").replace("/", "\\").rsplit("\\", 1)[-1].upper()
        if name in self.profiles:
            return name, self.profiles[name]
        data = self.written.get(name)
        if data is None:
            host = self.resolve(name)
            data = Path(host).read_bytes() if host is not None and not str(host).lower().endswith((".tbk", ".sbk")) else b""
        self.profiles[name] = _ini(bytes(data).decode("latin1"))
        return name, self.profiles[name]

    @staticmethod
    def _find(sections, name):
        for sname, keys in sections:
            if sname.lower() == name.lower():
                return keys
        return None

    def profile_string(self, section, entry, default, buf, length, filename, put=None):
        """GetPrivateProfileString16 -> PROFILE_GetString. Returns (ax, dx, stop). buf is
        (selector, offset); put(data), when given, writes the buffer instead (a Win32 caller,
        whose buf is (pointer, 0))."""
        sel, off = buf
        if put is None:
            put = lambda data: self.write(sel, off, data)
        if section is None:
            if sel and length:
                put(b"\x00")
            return 0, 0, None
        _name, sections = self._profile(filename)
        keys = self._find(sections, section.decode("latin1"))
        if entry is None and keys:
            # The 16-bit wrapper: the key names, each with a NUL, then a NUL.
            out = b""
            for key, value in keys:
                if value is None:
                    continue
                out += key.encode("latin1") + b"\x00"
            if not length:
                return 0, 0, None
            if len(out) + 1 <= length:
                put(out + b"\x00")
                return len(out), 0, None
            if length > 2:
                put(out[:length - 2] + b"\x00\x00")
                return length - 2, 0, None
            return 0, 0, None
        value = None
        if keys is not None and entry is not None:
            for key, val in keys:
                if key.lower() == entry.decode("latin1").lower() and val is not None:
                    value = val
                    break
        if value is not None:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            text = value.encode("latin1")
        else:
            text = (default or b"").rstrip(b" \t")
        if not sel or not length:
            return 0, 0, None
        text = text[:length - 1]
        put(text + b"\x00")
        return len(text), 0, None

    def profile_int(self, section, entry, default, filename, mask=0xFFFF):
        """GetPrivateProfileIntA: the value as a number (RtlUnicodeStringToInteger), else the
        default. mask is the answer's width: a word for the 16-bit call, 32 bits for Win32."""
        _name, sections = self._profile(filename)
        keys = self._find(sections, section.decode("latin1")) if section is not None else None
        value = None
        if keys is not None and entry is not None:
            for key, val in keys:
                if key.lower() == entry.decode("latin1").lower() and val is not None:
                    value = val
                    break
        if not value:
            return default & mask, 0, None
        text = value.strip()
        sign = 1
        if text[:1] in "+-":
            sign = -1 if text[0] == "-" else 1
            text = text[1:]
        base = 10
        if text[:2].lower() == "0x":
            base, text = 16, text[2:]
        elif text[:2].lower() == "0o":
            base, text = 8, text[2:]
        elif text[:2].lower() == "0b":
            base, text = 2, text[2:]
        digits = ""
        for ch in text:
            if ch.lower() in "0123456789abcdef"[:base]:
                digits += ch
            else:
                break
        number = sign * int(digits, base) if digits else 0
        return number & mask, 0, None

    def write_profile(self, section, entry, string, filename):
        """WritePrivateProfileStringA, into neww's copy of the file for the run. TRUE."""
        name, sections = self._profile(filename)
        if section is None:
            return 1, 0, None
        sname = section.decode("latin1")
        keys = self._find(sections, sname)
        if entry is None:
            if keys is not None:
                sections[:] = [s for s in sections if s[1] is not keys]
            return 1, 0, None
        if keys is None:
            if string is None:
                return 1, 0, None
            keys = []
            sections.append((sname, keys))
        key = entry.decode("latin1")
        for i, (k, _v) in enumerate(keys):
            if k.lower() == key.lower():
                if string is None:
                    del keys[i]
                else:
                    keys[i] = (k, string.decode("latin1"))
                return 1, 0, None
        if string is not None:
            keys.append((key, string.decode("latin1")))
        return 1, 0, None

    # ------------------------------------------------------------ files

    def file_exists(self, path):
        self._kstate()
        name = path.replace("/", "\\").rsplit("\\", 1)[-1].upper()
        return name in self.written or self.resolve(path) is not None

    def create_file(self, path, keep_open=True):
        """_lcreat: an empty file of that base name, in memory. Returns the handle."""
        self._kstate()
        name = path.replace("/", "\\").rsplit("\\", 1)[-1].upper()
        data = bytearray()
        self.written[name] = data
        self.profiles.pop(name, None)
        if not keep_open:
            return 0
        handle = self.next_file
        self.next_file += 1
        self.files[handle] = [path, None, data, 0]
        return handle

    def write_file(self, handle, sel, off, count):
        """_hwrite16: write at the position, count 0 truncates there. Returns (ax, dx, stop)."""
        entry = self.files.get(handle)
        if entry is None:
            return HFILE_ERROR, 0, None
        if not isinstance(entry[2], bytearray):
            return 0, 0, f"_lwrite on handle {handle} ({entry[0]!r}): neww opened it from --b to read, and does not write the host"
        data = entry[2]
        pos = entry[3]
        if count == 0:
            del data[pos:]
            return 0, 0, None
        chunk = self.read(sel, off, count)
        if len(data) < pos:
            data.extend(b"\x00" * (pos - len(data)))
        data[pos:pos + len(chunk)] = chunk
        entry[3] = pos + len(chunk)
        name = entry[0].replace("/", "\\").rsplit("\\", 1)[-1].upper()
        self.profiles.pop(name, None)
        return len(chunk) & 0xFFFF, len(chunk) >> 16, None

    def write_huge(self, sel, off, data):
        """Write across a huge block's tiles, as Wine's flat MapSL pointer does."""
        base = self.linear(sel)
        if base is None:
            return
        self.write_linear(base + off, data)

    # ------------------------------------------------------------ blocks

    def handle_of(self, sel):
        """The arena's handle for a selector: the moveable handle if the block was allocated so."""
        for handle, (block_sel, _size, _flags) in self.heap.items():
            if block_sel == sel:
                return handle
        return sel
