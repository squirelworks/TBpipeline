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
