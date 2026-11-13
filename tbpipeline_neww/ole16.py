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


# ------------------------------------------------------------------ COMPOBJ, compobj.dll16/compobj.c

CHARS_IN_GUID = 39
CLSCTX_INPROC_SERVER = 0x1
REGDB_E_CLASSNOTREG = 0x80040154
E_NOTIMPL = 0x80004001


def guid_string(raw):
    """compobj.c:663 StringFromGUID216's format, "{%08lX-%04X-%04X-%02X%02X-%02X...}"."""
    d1, d2, d3 = _struct.unpack("<IHH", raw[:8])
    return "{%08X-%04X-%04X-%s-%s}" % (d1, d2, d3, raw[8:10].hex().upper(), raw[10:16].hex().upper())


@api("COMPOBJ", "StringFromGUID2")
def string_from_guid2(wine, arg, guid, out, cmax):
    """compobj.c:661 StringFromGUID216: 0 for no GUID or under CHARS_IN_GUID (:664), else the
    string with its NUL and CHARS_IN_GUID."""
    from . import gdi16
    if not guid or (cmax - 0x10000 if cmax & 0x8000 else cmax) < CHARS_IN_GUID:
        return 0
    gdi16.write(wine, out, guid_string(gdi16.read(wine, guid, 16)).encode() + b"\0")
    return CHARS_IN_GUID


@api("COMPOBJ", "CoGetClassObject")
def co_get_class_object(wine, arg, rclsid, context, server_info, riid, ppv):
    """compobj.c:684 CoGetClassObject16. *ppv is NULL (:692). For CLSCTX_INPROC_SERVER the class's
    16-bit server is HKCR\\CLSID\\{clsid}\\InprocServer (:712); not there is REGDB_E_CLASSNOTREG
    (:716). Without that context it is E_NOTIMPL (:753)."""
    from . import gdi16
    from .shell16 import HKEY_CLASSES_ROOT, _reg
    gdi16.write(wine, ppv, b"\0\0\0\0")
    if not context & CLSCTX_INPROC_SERVER:
        return E_NOTIMPL & 0xFFFF, E_NOTIMPL >> 16
    clsid = guid_string(gdi16.read(wine, rclsid, 16))
    reg = _reg(wine)
    key = reg.walk(reg.key(HKEY_CLASSES_ROOT), f"CLSID\\{clsid}\\InprocServer")
    wine.trace[-1] += f" {clsid}"
    if key is None:
        return REGDB_E_CLASSNOTREG & 0xFFFF, REGDB_E_CLASSNOTREG >> 16
    return 0, 0, (f"COMPOBJ.7 CoGetClassObject {clsid}: the class is registered "
                  f"({(key.default or b'').decode('cp1252', 'replace')}), and neww does not load "
                  "its server and call DllGetClassObject yet")


# ------------------------------------------------------------------ IMalloc16, compobj.c:107-262

OLE_E_ENUM_NOMORE = 0x80040002
REGDB_E_KEYMISSING = 0x80040152
IID_IMALLOC = _struct.pack("<IHH", 2, 0, 0) + bytes.fromhex("c000000000000046")


def _mallocs(wine):
    """compobj_malloc (:107) and each block an IMalloc16 handed out, with the size asked for,
    which HeapSize answers."""
    return wine.__dict__.setdefault("compobj16", {"malloc": 0, "blocks": {}})


def _new_malloc(wine):
    """IMalloc16_Constructor (:243): an object whose vtable points at COMPOBJ.500-508, one reference."""
    from .wine import COMPOBJ
    tables = wine.__dict__.setdefault("com16_vtables", {})
    if "IMalloc16" not in tables:
        handle, _dx, stop = wine._global_alloc(0, 4 * 9)
        if stop:
            return 0, stop
        words = b"".join(_struct.pack("<HH", off, sel) for sel, off in
                         (wine.gate_address("COMPOBJ", o) for o in sorted(COMPOBJ)))
        wine.write(handle, 0, words)
        tables["IMalloc16"] = handle << 16
    handle, _dx, stop = wine._global_alloc(0, 4)
    if stop:
        return 0, stop
    wine.write(handle, 0, _struct.pack("<I", tables["IMalloc16"]))
    _com(wine)[handle << 16] = {"kind": "IMalloc16", "ref": 1}
    return handle << 16, None


def _malloc_alloc(wine, size):
    """IMalloc16_fnAlloc (:169): MapLS(HeapAlloc(size)), a block of its own at offset 0."""
    if size == 0:
        size_asked, size = 0, 1
    else:
        size_asked = size
    handle, _dx, stop = wine._global_alloc(0, size)
    if stop or not handle:
        return 0, stop
    ptr = handle << 16
    _mallocs(wine)["blocks"][ptr] = size_asked
    return ptr, None


def _malloc_free(wine, ptr):
    from .kernel32 import call16
    if _mallocs(wine)["blocks"].pop(ptr, None) is None:
        return f"a block at {ptr >> 16:#x}:{ptr & 0xFFFF:#x} the allocator did not hand out"
    out = call16(wine, "KERNEL", 17, ptr >> 16)
    return out if isinstance(out, str) else None


def _malloc_add_ref(wine, ptr, label):
    obj = _com(wine).get(ptr)
    if obj is None or obj.get("kind") != "IMalloc16":
        return f"{label}: the allocator is not one neww made, so its AddRef is a guest call neww does not make"
    obj["ref"] += 1
    return None


@api("COMPOBJ", "CoGetMalloc")
def co_get_malloc(wine, arg, context, pmalloc):
    """CoGetMalloc16 (:282): the task allocator, made the first time, else AddRef'd. S_OK."""
    from . import gdi16
    state = _mallocs(wine)
    if not state["malloc"]:
        ptr, stop = _new_malloc(wine)
        if stop:
            return 0, 0, f"COMPOBJ.4 CoGetMalloc: {stop}"
        state["malloc"] = ptr
    else:
        stop = _malloc_add_ref(wine, state["malloc"], "COMPOBJ.4 CoGetMalloc")
        if stop:
            return 0, 0, stop
    gdi16.write(wine, pmalloc, _struct.pack("<I", state["malloc"]))
    return S_OK


@api("COMPOBJ", "CoCreateStandardMalloc")
def co_create_standard_malloc(wine, arg, context, pmalloc):
    """CoCreateStandardMalloc16 (:294): a new allocator. S_OK."""
    from . import gdi16
    ptr, stop = _new_malloc(wine)
    if stop:
        return 0, 0, f"COMPOBJ.71 CoCreateStandardMalloc: {stop}"
    gdi16.write(wine, pmalloc, _struct.pack("<I", ptr))
    return S_OK


@api("COMPOBJ", "CoInitialize")
def co_initialize(wine, arg, malloc):
    """CoInitialize16 (:319): no allocator makes a standard one; else the caller's is AddRef'd
    and kept. S_OK."""
    state = _mallocs(wine)
    if not malloc:
        ptr, stop = _new_malloc(wine)
        if stop:
            return 0, 0, f"COMPOBJ.2 CoInitialize: {stop}"
        state["malloc"] = ptr
        return S_OK
    stop = _malloc_add_ref(wine, malloc, "COMPOBJ.2 CoInitialize")
    if stop:
        return 0, 0, stop
    state["malloc"] = malloc
    return S_OK


@api("COMPOBJ", "CoUninitialize")
def co_uninitialize(wine, arg):
    """CoUninitialize16 (:334): CoFreeAllLibraries (neww loads no class servers), then
    compobj_malloc is released and cleared. Void: AX and DX are left."""
    state = _mallocs(wine)
    obj = _com(wine).get(state["malloc"])
    if not state["malloc"]:
        return 0, 0, "COMPOBJ.3 CoUninitialize with no allocator: call_IMalloc_Release (:81) would map a NULL interface"
    if (obj is None or obj.get("kind") != "IMalloc16"):
        return 0, 0, "COMPOBJ.3 CoUninitialize: the allocator is the guest's, so its Release is a guest call neww does not make"
    obj["ref"] -= 1
    if obj["ref"] <= 0:
        del _com(wine)[state["malloc"]]
    state["malloc"] = 0
    return arg.regs("ax"), arg.regs("dx")


def _co_mem_alloc(wine, size, label):
    """CoMemAlloc (:305): call_IMalloc_Alloc on compobj_malloc."""
    state = _mallocs(wine)
    if _com(wine).get(state["malloc"], {}).get("kind") != "IMalloc16":
        if not state["malloc"]:
            # OleInitialize16 goes to ole32 (ole2.c:71) and never sets compobj_malloc; only
            # CoGetMalloc16 and CoInitialize16 do (:284, :322).
            return 0, f"{label}: compobj_malloc is NULL (no CoInitialize or CoGetMalloc yet), so CoMemAlloc's call_IMalloc_Alloc (:92) maps a NULL interface: Wine faults here"
        return 0, f"{label}: compobj_malloc is the guest's, so its Alloc is a guest call neww does not make"
    return _malloc_alloc(wine, size)


@api("COMPOBJ", "StringFromCLSID")
def string_from_clsid(wine, arg, clsid, out):
    """StringFromCLSID16 (:441): 40 bytes from CoMemAlloc, the GUID's string in them. S_OK."""
    from . import gdi16
    ptr, stop = _co_mem_alloc(wine, 40, "COMPOBJ.19 StringFromCLSID")
    if stop:
        return 0, 0, stop
    gdi16.write(wine, ptr, guid_string(gdi16.read(wine, clsid, 16)).encode() + b"\0")
    gdi16.write(wine, out, _struct.pack("<I", ptr))
    return S_OK


@api("COMPOBJ", "ProgIDFromCLSID")
def prog_id_from_clsid(wine, arg, clsid, out):
    """ProgIDFromCLSID16 (:454) -> combase.c:1272 ProgIDFromCLSID. neww has no activation
    context, so it is open_key_for_clsid(clsid, "ProgID") (combase.c:306): no CLSID key is
    REGDB_E_CLASSNOTREG, no ProgID key REGDB_E_KEYMISSING. A ProgID found is copied into a
    CoMemAlloc block."""
    from . import gdi16
    from .shell16 import HKEY_CLASSES_ROOT, _reg
    reg = _reg(wine)
    key = reg.walk(reg.key(HKEY_CLASSES_ROOT), "CLSID\\" + guid_string(gdi16.read(wine, clsid, 16)))
    if key is None:
        return REGDB_E_CLASSNOTREG & 0xFFFF, REGDB_E_CLASSNOTREG >> 16
    sub = key.subkeys.get("progid")
    if sub is None:
        return REGDB_E_KEYMISSING & 0xFFFF, REGDB_E_KEYMISSING >> 16
    value = (sub[1].default or b"").split(b"\0")[0] + b"\0"
    ptr, stop = _co_mem_alloc(wine, len(value), "COMPOBJ.62 ProgIDFromCLSID")
    if stop:
        return 0, 0, stop
    gdi16.write(wine, ptr, value)
    gdi16.write(wine, out, _struct.pack("<I", ptr))
    return S_OK


@_handles("COMPOBJ", 500)
def malloc_query_interface(wine, arg):
    """IMalloc16_fnQueryInterface (:126): IUnknown and IMalloc are the object, with no AddRef;
    anything else OLE_E_ENUM_NOMORE and *obj left."""
    this, riid, obj = _this(arg), arg(2) | arg(3) << 16, arg(4) | arg(5) << 16
    if wine.read(riid >> 16, riid & 0xFFFF, 16) in (IID_IUNKNOWN, IID_IMALLOC):
        _put_ptr(wine, obj, this)
        return 0, 0, None
    return OLE_E_ENUM_NOMORE & 0xFFFF, OLE_E_ENUM_NOMORE >> 16, None


@_handles("COMPOBJ", 501)
def malloc_add_ref(wine, arg):
    """IMalloc16_fnAddRef (:142): the new count."""
    obj = _com(wine)[_this(arg)]
    obj["ref"] += 1
    return obj["ref"] & 0xFFFF, obj["ref"] >> 16, None


@_handles("COMPOBJ", 502)
def malloc_release(wine, arg):
    """IMalloc16_fnRelease (:153): the count left; at 0 the object goes."""
    this = _this(arg)
    obj = _com(wine)[this]
    obj["ref"] -= 1
    if obj["ref"] <= 0:
        del _com(wine)[this]
        if _mallocs(wine)["malloc"] == this:
            _mallocs(wine)["malloc"] = 0
        return 0, 0, None
    return obj["ref"] & 0xFFFF, obj["ref"] >> 16, None


@_handles("COMPOBJ", 503)
def malloc_alloc(wine, arg):
    """IMalloc16_fnAlloc (:169)."""
    ptr, stop = _malloc_alloc(wine, arg(2) | arg(3) << 16)
    if stop:
        return 0, 0, f"COMPOBJ.503 IMalloc16_Alloc: {stop}"
    return ptr & 0xFFFF, ptr >> 16, None


@_handles("COMPOBJ", 504)
def malloc_realloc(wine, arg):
    """IMalloc16_fnRealloc (:191): no block is Alloc; size 0 is Free and NULL; else a new
    block with the old contents, the old one let go."""
    pv, cb = arg(2) | arg(3) << 16, arg(4) | arg(5) << 16
    if not pv:
        return _realloc_new(wine, 0, cb)
    if not cb:
        stop = _malloc_free(wine, pv)
        return 0, 0, (f"COMPOBJ.504 IMalloc16_Realloc: {stop}" if stop else None)
    return _realloc_new(wine, pv, cb)


def _realloc_new(wine, pv, cb):
    old = _mallocs(wine)["blocks"].get(pv) if pv else 0
    if pv and old is None:
        return 0, 0, f"COMPOBJ.504 IMalloc16_Realloc: a block at {pv >> 16:#x}:{pv & 0xFFFF:#x} the allocator did not hand out"
    ptr, stop = _malloc_alloc(wine, cb)
    if stop:
        return 0, 0, f"COMPOBJ.504 IMalloc16_Realloc: {stop}"
    if pv:
        keep = min(old, cb)
        wine.write(ptr >> 16, 0, wine.read(pv >> 16, pv & 0xFFFF, keep))
        stop = _malloc_free(wine, pv)
        if stop:
            return 0, 0, f"COMPOBJ.504 IMalloc16_Realloc: {stop}"
    return ptr & 0xFFFF, ptr >> 16, None


@_handles("COMPOBJ", 505)
def malloc_free(wine, arg):
    """IMalloc16_fnFree (:179). Void: AX and DX are left."""
    stop = _malloc_free(wine, arg(2) | arg(3) << 16)
    if stop:
        return 0, 0, f"COMPOBJ.505 IMalloc16_Free: {stop}"
    return arg.regs("ax"), arg.regs("dx"), None


@_handles("COMPOBJ", 506)
def malloc_get_size(wine, arg):
    """IMalloc16_fnGetSize (:212): HeapSize, the size asked for."""
    size = _mallocs(wine)["blocks"].get(arg(2) | arg(3) << 16)
    if size is None:
        return 0, 0, "COMPOBJ.506 IMalloc16_GetSize of a block the allocator did not hand out"
    return size & 0xFFFF, size >> 16, None


@_handles("COMPOBJ", 507)
def malloc_did_alloc(wine, arg):
    """IMalloc16_fnDidAlloc (:223): -1."""
    return 0xFFFF, 0, None


@_handles("COMPOBJ", 508)
def malloc_heap_minimize(wine, arg):
    """IMalloc16_fnHeapMinimize (:233): NULL."""
    return 0, 0, None
