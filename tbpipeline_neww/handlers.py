"""Handlers written for loaded spec rows, by (module, ordinal).

A module of handlers registers each function with @handles. The row, and so
the pop size, is still the spec's (spec_rows.py). A handler only replaces the
default answer. It is called as fn(wine, arg) and returns (ax, dx, stop).
"""

HANDLERS = {}


def handles(module, *ordinals):
    def wrap(fn):
        for ordinal in ordinals:
            if (module, ordinal) in HANDLERS:
                raise ValueError(f"{module}.{ordinal} has two handlers")
            HANDLERS[(module, ordinal)] = fn
        return fn
    return wrap


def segptr(lo, hi):
    """A far pointer from its two argument words."""
    return lo | (hi << 16)


def signed(word):
    return word - 0x10000 if word & 0x8000 else word


# ---------------------------------------------------------------- by name, with typed arguments

import re as _re
import types as _types

_ENTRY = _re.compile(r"(\d+)\s+pascal\s+(?:-\S+\s+)*(\w+)\s*\((.*?)\)")


def _spec_index(module):
    from .spec_rows import SPEC_ROWS
    out = {}
    for line, _void, _value in SPEC_ROWS.get(module, []):
        m = _ENTRY.match(line)
        if m:
            out.setdefault(m.group(2), (int(m.group(1)), m.group(3).split()))
    return out


_INDEX = {}


def spec_types(module, name):
    """(ordinal, [spec type]) of the first pascal entry with that name in the module's spec."""
    if module not in _INDEX:
        _INDEX[module] = _spec_index(module)
    return _INDEX[module][name]


def unpack(arg, types):
    """The Pascal arguments in spec order. The caller pushed the first one first, so the last
    one is arg(0). word is unsigned, s_word signed, every 4-byte type is one 32-bit number
    (a SEGPTR for a pointer)."""
    sizes = [2 if t in ("word", "s_word") else 4 for t in types]
    idx = sum(s // 2 for s in sizes)
    out = []
    for t, s in zip(types, sizes):
        idx -= s // 2
        if s == 2:
            v = arg(idx)
            out.append(signed(v) if t == "s_word" else v)
        else:
            out.append(arg(idx) | (arg(idx + 1) << 16))
    return out


def answer_of(value):
    """A handler's return as (ax, dx, stop), or a GuestCalls: an int is DX:AX, a generator is
    driven as guest calls (guest.drive)."""
    from .guest import GuestCalls, drive
    if isinstance(value, _types.GeneratorType):
        return drive(value)
    if isinstance(value, GuestCalls):
        return value
    if isinstance(value, int):
        value &= 0xFFFFFFFF
        return value & 0xFFFF, value >> 16, None
    if value is None:
        return 0, 0, None
    if len(value) == 2:
        return value[0] & 0xFFFF, value[1] & 0xFFFF, None
    return value


def api(module, *names):
    """Register fn(wine, arg, *arguments) for the named spec entries. The arguments are
    unpacked by the spec's types. SS is kept in wine.ss for calls into the guest."""
    def wrap(fn):
        for name in names:
            ordinal, types = spec_types(module, name)

            def handler(wine, arg, _types=types, _fn=fn):
                from .guest import GuestCalls
                wine.ss = arg.regs("ss")
                out = answer_of(_fn(wine, arg, *unpack(arg, _types)))
                if isinstance(out, GuestCalls):
                    # The machine runs the calls from the gate's return (Machine._start_guest).
                    wine.registers = {"guest": out}
                    return 0, 0, None
                return out
            handler.__name__ = fn.__name__
            handler.__doc__ = fn.__doc__
            if (module, ordinal) in HANDLERS:
                raise ValueError(f"{module}.{ordinal} has two handlers")
            HANDLERS[(module, ordinal)] = handler
        return fn
    return wrap
