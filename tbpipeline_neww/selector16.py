"""KERNEL's selector functions, from Wine dlls/krnl386.exe16/selector.c at WINE_COMMIT.

The machine's descriptors are the LDT here (machine.SelectorHooks). A program uses these to
reach memory it has a 32-bit address for: AllocSelector, then SetSelectorBase and
SetSelectorLimit, as ToolBook does to hand a script a 16:16 pointer to Win32 memory.
"""

from .handlers import api


def _hooks(wine):
    return getattr(wine, "selectors", None)


@api("KERNEL", "AllocSelector")
def alloc_selector(wine, arg, sel):
    """AllocSelector16: a new selector; with sel, a copy of its descriptor (one selector for
    each 64K of its limit, get_sel_count). Wine leaves a new entry as alloc_entries made it;
    neww makes it an empty read/write data segment, as Windows did, for SetSelectorBase and
    SetSelectorLimit to fill."""
    hooks = _hooks(wine)
    if hooks is None:
        return 0, 0, "KERNEL.175 AllocSelector: no machine"
    if not sel:
        new = hooks.new()
        wine.trace[-1] += f" -> {new:#x}"
        return new, 0
    info = hooks.info(sel)
    if info is None:
        return 0, 0
    base, limit, access = info
    count = (limit >> 16) + 1
    first = None
    for i in range(count):
        new = hooks.new()
        first = new if first is None else first
        part = min(limit - 0x10000 * i, 0xFFFF) if count > 1 else limit
        hooks.set(new, base + 0x10000 * i, part, access)
    wine.trace[-1] += f" {sel:#x} -> {first:#x}"
    return first, 0


@api("KERNEL", "FreeSelector")
def free_selector(wine, arg, sel):
    """FreeSelector16: 0, or sel when it is not a selector in use."""
    hooks = _hooks(wine)
    if hooks is None or hooks.info(sel) is None:
        return sel, 0
    hooks.free(sel)
    return 0, 0


@api("KERNEL", "GetSelectorBase")
def get_selector_base(wine, arg, sel):
    """GetSelectorBase: the descriptor's base, 0 for none."""
    info = _hooks(wine).info(sel) if _hooks(wine) else None
    base = info[0] if info else 0
    return base & 0xFFFF, base >> 16


@api("KERNEL", "SetSelectorBase")
def set_selector_base(wine, arg, sel, base):
    """SetSelectorBase: the base set, the limit and access kept. Answers sel."""
    hooks = _hooks(wine)
    info = hooks.info(sel) if hooks else None
    if info is None:
        return 0, 0
    hooks.set(sel, base, info[1], info[2])
    wine.trace[-1] += f" {sel:#x} = {base:#x}"
    return sel, 0


@api("KERNEL", "GetSelectorLimit")
def get_selector_limit(wine, arg, sel):
    """GetSelectorLimit16: the limit in bytes, 0 for none."""
    info = _hooks(wine).info(sel) if _hooks(wine) else None
    limit = info[1] if info else 0
    return limit & 0xFFFF, limit >> 16


@api("KERNEL", "SetSelectorLimit")
def set_selector_limit(wine, arg, sel, limit):
    """SetSelectorLimit16: the limit set (page granular above 1MB), base and access kept.
    Answers sel."""
    hooks = _hooks(wine)
    info = hooks.info(sel) if hooks else None
    if info is None:
        return 0, 0
    hooks.set(sel, info[0], limit, info[2])
    wine.trace[-1] += f" {sel:#x} limit {limit:#x}"
    return sel, 0


@api("KERNEL", "PrestoChangoSelector")
def presto_chango_selector(wine, arg, src, dst):
    """PrestoChangoSelector16: dst gets src's descriptor with code and data swapped (the
    access byte's executable bit). Answers dst."""
    hooks = _hooks(wine)
    info = hooks.info(src) if hooks else None
    if info is None or hooks.info(dst) is None:
        return dst, 0
    base, limit, access = info
    hooks.set(dst, base, limit, access ^ 0x08)
    wine.trace[-1] += f" {src:#x} -> {dst:#x}"
    return dst, 0


# ---------------------------------------------------------------- DPMI

def int31(wine, reg):
    """int31.c DOSVM_Int31Handler, the DPMI functions a run reaches, on the same descriptors
    as the KERNEL selector functions. CF clear on success; a selector that is not in use is
    error 8022h (invalid selector) with CF set. Returns (registers to set, stop)."""
    ax = reg("ax")
    bx = reg("bx")
    wine.trace.append(f"INT31 AX={ax:#06x} BX={bx:#x}")
    hooks = _hooks(wine)
    bad = {"ax": 0x8022, "eflags_cf": 1}
    if ax == 0x0006:
        # Get segment base address: CX:DX.
        info = hooks.info(bx)
        if info is None:
            return bad, None
        wine.trace[-1] += f" base {info[0]:#x}"
        return {"cx": info[0] >> 16, "dx": info[0] & 0xFFFF, "eflags_cf": 0}, None
    if ax == 0x0007:
        # Set segment base address from CX:DX.
        info = hooks.info(bx)
        if info is None:
            return bad, None
        base = reg("cx") << 16 | reg("dx")
        hooks.set(bx, base, info[1], info[2])
        wine.trace[-1] += f" base = {base:#x}"
        return {"eflags_cf": 0}, None
    if ax == 0x0008:
        # Set segment limit from CX:DX.
        info = hooks.info(bx)
        if info is None:
            return bad, None
        limit = reg("cx") << 16 | reg("dx")
        hooks.set(bx, info[0], limit, info[2])
        wine.trace[-1] += f" limit = {limit:#x}"
        return {"eflags_cf": 0}, None
    return {}, f"INT 31h AX={ax:#06x}: this DOSVM_Int31Handler function is not in neww yet"
