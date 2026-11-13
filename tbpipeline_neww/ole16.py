"""OLE2's calls, from Wine dlls/ole2.dll16 at WINE_COMMIT.

ole2.c forwards them to ole32. A 16-bit task is a thread there, so per-thread state
(COM_CurrentInfo) is kept per task here.
"""

from .handlers import api

S_OK, S_FALSE = 0, 1


@api("OLE2", "OleInitialize")
def ole_initialize(wine, arg, reserved):
    """ole2.c:71-74 OleInitialize16 -> ole32/ole2.c:162-183 OleInitialize. CoInitializeEx
    (COINIT_APARTMENTTHREADED) succeeds, then S_OK while the thread's ole_inits is 0 and
    S_FALSE once it is not. ole32/ole2.c:193 counts the call."""
    counts = wine.__dict__.setdefault("ole_inits", {})
    inits = counts.get(wine.htask, 0)
    counts[wine.htask] = inits + 1
    return (S_FALSE if inits else S_OK), 0


@api("OLE2", "OleUninitialize")
def ole_uninitialize(wine, arg):
    """ole2.c:79 OleUninitialize16 -> ole32/ole2.c:218 OleUninitialize: nothing while the
    thread's ole_inits is 0 (:224), else one fewer (:232). The libraries it frees at the
    bottom (clipboard, drag and drop) are ones neww never made. Void: AX and DX are left."""
    counts = wine.__dict__.setdefault("ole_inits", {})
    if counts.get(wine.htask, 0):
        counts[wine.htask] -= 1
    return arg.regs("ax"), arg.regs("dx")


E_FAIL = 0x80004005


@api("OLE2", "OleFlushClipboard")
def ole_flush_clipboard(wine, arg):
    """ole2.c:270 OleFlushClipboard16 -> ole32/clipboard.c:2277 OleFlushClipboard: E_FAIL while
    the thread's ole_inits is 0 (:2288); else, with no source data object (:2296), S_OK.
    neww has no OleSetClipboard, which is what sets one (it stops by name), so there is never
    one here. The spec's -ret16 keeps the low word."""
    if not wine.__dict__.get("ole_inits", {}).get(wine.htask, 0):
        return E_FAIL & 0xFFFF
    return S_OK


# ---------------------------------------------------------------- CreateDispTypeInfo, CreateStdDispatch
#
# Wine's 16-bit CreateDispTypeInfo16 (dlls/ole2disp.dll16/ole2disp.c:477) is E_NOTIMPL and
# CreateStdDispatch16 (:489) returns 0 without setting its out pointer. On Windows both work, and
# ToolBook's TB80OLE relies on them: INITIALIZEOLEREMOTE keeps the dispatch object they make,
# and UNINITIALIZEOLEREMOTE releases it at exit through a pointer that Wine leaves NULL. neww
# acts as Windows does there, as oleaut32 does in 32 bits (dlls/oleaut32/typelib.c:8669
# CreateDispTypeInfo, dlls/oleaut32/dispatch.c:450 CreateStdDispatch): the objects count their
# references and answer QueryInterface. A method neww does not have yet stops by name.

import struct as _struct

from .handlers import handles as _handles

E_NOINTERFACE, E_INVALIDARG = 0x80004002, 0x80070057



def _iid(n):
    """The IIDs of the 0002040n-0000-0000-C000-000000000046 family, as bytes in memory."""
    return _struct.pack("<IHH", 0x00020400 + n, 0, 0) + bytes.fromhex("c000000000000046")


IID_IUNKNOWN = _struct.pack("<IHH", 0, 0, 0) + bytes.fromhex("c000000000000046")
IID_IDISPATCH, IID_ITYPEINFO = _iid(0), _iid(1)


def _com(wine):
    return wine.__dict__.setdefault("com16", {})


def _put_ptr(wine, where, value):
    wine.write(where >> 16, where & 0xFFFF, _struct.pack("<I", value))


def _vtable(wine, kind):
    """The interface's vtable, made once: far pointers to its method rows' gates."""
    from .wine import COM16
    tables = wine.__dict__.setdefault("com16_vtables", {})
    if kind in tables:
        return tables[kind], None
    first, methods = COM16[kind]
    handle, _dx, stop = wine._global_alloc(0, 4 * len(methods))
    if stop:
        return 0, stop
    words = b""
    for i in range(len(methods)):
        sel, off = wine.gate_address("OLE2DISP", first + i)
        words += _struct.pack("<HH", off, sel)
    wine.write(handle, 0, words)
    tables[kind] = handle << 16
    return tables[kind], None


def _new_object(wine, interfaces):
    """A block holding one vtable pointer per interface, 4 bytes apart. Returns its address."""
    handle, _dx, stop = wine._global_alloc(0, 4 * len(interfaces))
    if stop:
        return 0, stop
    for i, kind in enumerate(interfaces):
        vt, stop = _vtable(wine, kind)
        if stop:
            return 0, stop
        wine.write(handle, 4 * i, _struct.pack("<I", vt))
    return handle << 16, None


@api("OLE2DISP", "CreateDispTypeInfo")
def create_disp_type_info(wine, arg, pidata, lcid, pptinfo):
    """CreateDispTypeInfo as oleaut32 typelib.c:8669 makes it: a new ITypeInfo with one
    reference, S_OK. neww keeps the INTERFACEDATA's address for the methods that would read
    it, none of which it has yet."""
    if not pptinfo:
        return E_INVALIDARG
    ptr, stop = _new_object(wine, ["ITypeInfo16"])
    if stop:
        return 0, 0, f"OLE2DISP.31 CreateDispTypeInfo: {stop}"
    _com(wine)[ptr] = {"kind": "ITypeInfo16", "ref": 1, "idata": pidata, "lcid": lcid}
    _put_ptr(wine, pptinfo, ptr)
    wine.trace[-1] += f" -> ITypeInfo {ptr >> 16:#x}:{ptr & 0xFFFF:#x}"
    return S_OK


@api("OLE2DISP", "CreateStdDispatch")
def create_std_dispatch(wine, arg, outer, pv_this, ptinfo, ppunk):
    """CreateStdDispatch as oleaut32 dispatch.c:450 makes it: E_INVALIDARG for no pvThis, type
    info or out pointer; else one object with an IDispatch (+0) and its inner IUnknown (+4),
    one reference, the outer unknown (or the inner one), and an AddRef on the type info
    (:473). *ppunk is the inner IUnknown."""
    if not pv_this or not ptinfo or not ppunk:
        return E_INVALIDARG
    info = _com(wine).get(ptinfo)
    if info is None:
        return 0, 0, "OLE2DISP.32 CreateStdDispatch: the type info is not one neww made, so its AddRef is a guest call neww does not make"
    ptr, stop = _new_object(wine, ["StdDispatch16", "StdDispatchInner16"])
    if stop:
        return 0, 0, f"OLE2DISP.32 CreateStdDispatch: {stop}"
    info["ref"] += 1
    inner = ptr + 4
    _com(wine)[ptr] = {"kind": "StdDispatch16", "ref": 1, "outer": outer or inner, "this": pv_this,
                       "typeinfo": ptinfo, "inner": inner}
    _com(wine)[inner] = {"kind": "StdDispatchInner16", "object": ptr}
    _put_ptr(wine, ppunk, inner)
    wine.trace[-1] += f" -> {inner >> 16:#x}:{inner & 0xFFFF:#x}"
    return S_OK


def _this(arg):
    """A cdecl method's first argument, the interface pointer: on top of the stack."""
    return arg(0) | arg(1) << 16


def _release_typeinfo(wine, ptr):
    info = _com(wine)[ptr]
    info["ref"] -= 1
    if info["ref"] <= 0:
        del _com(wine)[ptr]
        return 0
    return info["ref"]


@_handles("OLE2DISP", 500)
def typeinfo_query_interface(wine, arg):
    """ITypeInfo_fnQueryInterface (dlls/oleaut32/typelib.c:5653): IUnknown and ITypeInfo are
    the object, with a reference; anything else E_NOINTERFACE and *ppv NULL. ITypeInfo2,
    ICreateTypeInfo, ICreateTypeInfo2 and ITypeComp stop: neww's object has none of them."""
    this, riid, ppv = _this(arg), arg(2) | arg(3) << 16, arg(4) | arg(5) << 16
    iid = wine.read(riid >> 16, riid & 0xFFFF, 16)
    if iid in (IID_IUNKNOWN, IID_ITYPEINFO):
        _com(wine)[this]["ref"] += 1
        _put_ptr(wine, ppv, this)
        return 0, 0, None
    if iid[4:] == IID_ITYPEINFO[4:] and _struct.unpack("<I", iid[:4])[0] in (0x00020412, 0x00020405, 0x0002040E, 0x00020403):
        return 0, 0, "OLE2DISP.500 ITypeInfo::QueryInterface for ITypeInfo2, ICreateTypeInfo, ICreateTypeInfo2 or ITypeComp, which neww's type info does not have"
    _put_ptr(wine, ppv, 0)
    return E_NOINTERFACE & 0xFFFF, E_NOINTERFACE >> 16, None


@_handles("OLE2DISP", 501)
def typeinfo_add_ref(wine, arg):
    """ITypeInfo_fnAddRef (typelib.c:5682): the new count."""
    info = _com(wine)[_this(arg)]
    info["ref"] += 1
    return info["ref"], 0, None


@_handles("OLE2DISP", 502)
def typeinfo_release(wine, arg):
    """ITypeInfo_fnRelease: the count left; at 0 the object goes."""
    return _release_typeinfo(wine, _this(arg)), 0, None


@_handles("OLE2DISP", 530)
def inner_query_interface(wine, arg):
    """std_dispatch_inner_QueryInterface (dlls/oleaut32/dispatch.c:389): IUnknown is the inner
    unknown, IDispatch the dispatch interface, each with a reference; else E_NOINTERFACE."""
    this, riid, ppv = _this(arg), arg(2) | arg(3) << 16, arg(4) | arg(5) << 16
    obj = _com(wine)[_com(wine)[this]["object"]]
    iid = wine.read(riid >> 16, riid & 0xFFFF, 16)
    if iid == IID_IUNKNOWN:
        out = this
    elif iid == IID_IDISPATCH:
        out = _com(wine)[this]["object"]
    else:
        _put_ptr(wine, ppv, 0)
        return E_NOINTERFACE & 0xFFFF, E_NOINTERFACE >> 16, None
    if out == this:
        obj["ref"] += 1
    else:
        # IUnknown_AddRef on the IDispatch goes to the outer unknown (dispatch.c:229).
        if obj["outer"] != obj["inner"]:
            return 0, 0, "OLE2DISP.530 StdDispatch inner QueryInterface(IDispatch) AddRefs the outer object, a guest call neww does not make"
        obj["ref"] += 1
    _put_ptr(wine, ppv, out)
    return 0, 0, None


@_handles("OLE2DISP", 531)
def inner_add_ref(wine, arg):
    """std_dispatch_inner_AddRef (dispatch.c:414): the new count."""
    obj = _com(wine)[_com(wine)[_this(arg)]["object"]]
    obj["ref"] += 1
    return obj["ref"], 0, None


@_handles("OLE2DISP", 532)
def inner_release(wine, arg):
    """std_dispatch_inner_Release (dispatch.c:424): the count left; at 0 the type info is
    released (ITypeInfo_Release) and the object goes."""
    this = _this(arg)
    ptr = _com(wine)[this]["object"]
    obj = _com(wine)[ptr]
    obj["ref"] -= 1
    if obj["ref"] > 0:
        return obj["ref"], 0, None
    if obj["typeinfo"] in _com(wine):
        _release_typeinfo(wine, obj["typeinfo"])
    del _com(wine)[ptr]
    del _com(wine)[this]
    return 0, 0, None


def _not_yet(ordinal, label):
    def stop(wine, arg):
        return 0, 0, f"OLE2DISP.{ordinal} {label}: neww's object does not have this method yet"
    stop.__name__ = f"com16_{ordinal}"
    return stop


def _register_rest():
    from .wine import COM16
    names = {"ITypeInfo16": "ITypeInfo", "StdDispatchInner16": "StdDispatch inner IUnknown",
             "StdDispatch16": "StdDispatch IDispatch"}
    done = {500, 501, 502, 530, 531, 532}
    for kind, (first, methods) in COM16.items():
        for i, method in enumerate(methods):
            if first + i in done:
                continue
            reason = f"{names[kind]}::{method.partition('(')[0]}"
            if kind == "StdDispatch16" and i < 3:
                reason += " delegates to the outer object (dispatch.c:223), a guest call"
            _handles("OLE2DISP", first + i)(_not_yet(first + i, reason))


_register_rest()
