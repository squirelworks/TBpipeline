"""USER resources and menus, from Wine dlls/user.exe16/user.c and win32u menu.c at WINE_COMMIT.

LoadString, LoadBitmap, LoadIcon, LoadCursor, LoadAccelerators and LoadMenu
read the module's NE resource table through the same FindResource16 that
KERNEL.60 uses. A 16-bit icon or cursor handle is a moveable global block
holding a CURSORICONINFO and its bits, as get_icon_16 makes it. The system
cursors and icons (hInstance 0) come from user32's resources, which neww does
not have: they are blocks of that layout with the standard size and blank
bits, so the handles are real and the pictures are not.
"""

import struct

from .handlers import api, signed
from . import gdi16
from .user_wnd import wm, string_at

RT_CURSOR, RT_BITMAP, RT_ICON, RT_MENU, RT_DIALOG, RT_STRING = 1, 2, 3, 4, 5, 6
RT_ACCELERATOR, RT_GROUP_CURSOR, RT_GROUP_ICON = 9, 12, 14

MF_GRAYED, MF_DISABLED, MF_BITMAP, MF_CHECKED, MF_POPUP = 0x1, 0x2, 0x4, 0x8, 0x10
MF_MENUBARBREAK, MF_MENUBREAK, MF_END, MF_OWNERDRAW, MF_SEPARATOR = 0x20, 0x40, 0x80, 0x100, 0x800
MF_BYPOSITION = 0x400


def resource_bytes(wine, inst, name, type_):
    """FindResource16 + LoadResource16 as bytes: (data, hrsrc) or (None, 0)."""
    from .resource import Stop as ResourceStop
    table = wine.resources(inst)
    if table is None:
        return None, 0
    try:
        hrsrc = table.find(name, type_)
    except ResourceStop as why:
        raise
    if not hrsrc:
        return None, 0
    return bytes(table.bytes_of(hrsrc)), hrsrc


def res_arg(wine, ptr):
    """A resource name argument: an id when the selector is 0, '#nnn' an id, else the name."""
    from .resource import res_name
    return res_name(ptr & 0xFFFF, ptr >> 16, lambda sel, off: gdi16.cstr(wine, sel << 16 | off).decode("latin1"))


# ------------------------------------------------------------------ strings

@api("USER", "LoadString")
def load_string(wine, arg, inst, ident, buf, buflen):
    """user.c LoadString16: block (id >> 4) + 1, the (id & 15)-th Pascal string in it."""
    data, _h = resource_bytes(wine, inst, (ident >> 4) + 1, RT_STRING)
    if data is None:
        return 0
    p = 0
    for _ in range(ident & 0xF):
        if p >= len(data):
            return 0
        p += data[p] + 1
    if p >= len(data):
        return 0
    n = data[p]
    if not buf:
        return n
    ret = min(buflen - 1, n)
    if ret > 0:
        text = data[p + 1:p + 1 + ret]
        gdi16.write(wine, buf, text + b"\x00")
        wine.trace[-1] += f" {ident} {text.decode('cp1252', 'replace')!r}"
    elif buflen > 1:
        gdi16.write(wine, buf, b"\x00")
        ret = 0
    return ret


# ------------------------------------------------------------------ bitmaps

def dib_from_bytes(data):
    """A packed DIB (BITMAPINFOHEADER or BITMAPCOREHEADER, colors, bits) as (image, w, h, mono)."""
    from PIL import Image
    size = struct.unpack_from("<I", data)[0]
    if size == 12:
        w, h, _planes, bpp = struct.unpack_from("<HHHH", data, 4)
        comp, used, entry = 0, 0, 3
    else:
        w, h, _planes, bpp, comp, _sz, _x, _y, used, _imp = struct.unpack_from("<iiHHIIiiII", data, 4)
        entry = 4
    if comp != 0:
        return None, f"compression {comp}"
    colors = used or (1 << bpp if bpp <= 8 else 0)
    table = [(data[size + entry * i + 2], data[size + entry * i + 1], data[size + entry * i]) for i in range(colors)]
    bits = data[size + entry * colors:]
    top_down = h < 0
    h = abs(h)
    stride = ((w * bpp + 31) // 32) * 4
    raw = bits[:stride * h].ljust(stride * h, b"\x00")
    if bpp in (1, 4, 8):
        img = Image.frombytes("P", (w, h), raw, "raw", {1: "P;1", 4: "P;4", 8: "P"}[bpp], stride, 1 if top_down else -1)
        flat = []
        for c in table + [(0, 0, 0)] * (256 - len(table)):
            flat += list(c)
        img.putpalette(flat)
        img = img.convert("RGB")
    elif bpp == 24:
        img = Image.frombytes("RGB", (w, h), raw, "raw", "BGR", stride, 1 if top_down else -1)
    elif bpp == 32:
        img = Image.frombytes("RGB", (w, h), raw, "raw", "BGRX", stride, 1 if top_down else -1)
    elif bpp == 16:
        img = Image.frombytes("RGB", (w, h), raw, "raw", "BGR;15", stride, 1 if top_down else -1)
    else:
        return None, f"{bpp} bpp"
    mono = bpp == 1 and table[:2] == [(0, 0, 0), (255, 255, 255)]
    return (img, w, h, mono), None


@api("USER", "LoadBitmap")
def load_bitmap(wine, arg, inst, name_ptr):
    """user.c LoadImage16 IMAGE_BITMAP: the RT_BITMAP resource through LoadImageW from a file,
    which makes a screen-compatible bitmap (mono for a black-and-white 1-bit DIB)."""
    name = res_arg(wine, name_ptr)
    if not inst:
        return 0, 0, f"USER.175 LoadBitmap(0, {name!r}): a user32 OBM_ bitmap, and neww has no user32 resources"
    data, _h = resource_bytes(wine, wine._exe_ptr(inst) or inst, name, RT_BITMAP)
    if data is None:
        wine.trace[-1] += f" {name!r} not found"
        return 0
    got, why = dib_from_bytes(data)
    if why:
        return 0, 0, f"USER.175 LoadBitmap({name!r}): {why}"
    img, w, h, mono = got
    g = gdi16.gdi(wine)
    bmp = g.new_bitmap(w, h, 1 if mono else 32)
    bmp.image = img
    handle = g.add(bmp)
    wine.trace[-1] += f" {name!r} {w}x{h} -> {handle:#x}"
    return handle


# ------------------------------------------------------------------ icons and cursors

# SM_CXICON, SM_CYICON, SM_CXCURSOR, SM_CYCURSOR at 96 dpi.
ICON_SIZE = 32


def _icon_block(wine, width, height, hotspot=(0, 0), bpp=1, and_bits=None, xor_bits=None, image=None):
    """GlobalAlloc16(GMEM_MOVEABLE) with CURSORICONINFO and the bits, as get_icon_16 does."""
    wbytes = ((width + 15) // 16) * 2
    and_size = wbytes * height
    xbytes = ((width * bpp + 15) // 16) * 2
    xor_size = xbytes * height
    header = struct.pack("<hhHHHBB", hotspot[0], hotspot[1], width, height, xbytes, 1, bpp)
    body = (and_bits or b"\xff" * and_size)[:and_size].ljust(and_size, b"\xff") + \
        (xor_bits or bytes(xor_size))[:xor_size].ljust(xor_size, b"\x00")
    handle, _dx, why = wine._global_alloc(0x0002, len(header) + len(body))
    if why:
        return 0, why
    sel = wine.selector_of(handle)
    wine.write(sel, 0, header + body)
    icons = getattr(wine, "icons", None)
    if icons is None:
        icons = wine.icons = {}
    icons[handle] = {"width": width, "height": height, "image": image, "hotspot": hotspot}
    return handle, None


SYSTEM_CURSORS = {32512: "IDC_ARROW", 32513: "IDC_IBEAM", 32514: "IDC_WAIT", 32515: "IDC_CROSS",
                  32516: "IDC_UPARROW", 32640: "IDC_SIZE", 32641: "IDC_ICON", 32642: "IDC_SIZENWSE",
                  32643: "IDC_SIZENESW", 32644: "IDC_SIZEWE", 32645: "IDC_SIZENS", 32646: "IDC_SIZEALL",
                  32648: "IDC_NO", 32649: "IDC_HAND", 32650: "IDC_APPSTARTING", 32651: "IDC_HELP"}
SYSTEM_ICONS = {32512: "IDI_APPLICATION", 32513: "IDI_HAND", 32514: "IDI_QUESTION", 32515: "IDI_EXCLAMATION",
                32516: "IDI_ASTERISK", 32517: "IDI_WINLOGO"}


def _shared(wine, key):
    shared = getattr(wine, "shared_icons", None)
    if shared is None:
        shared = wine.shared_icons = {}
    return shared, shared.get(key)


def _load_cursor_icon(wine, inst, name_ptr, is_icon):
    name = res_arg(wine, name_ptr)
    if not inst:
        table = SYSTEM_ICONS if is_icon else SYSTEM_CURSORS
        if name not in table:
            return 0, None
        shared, found = _shared(wine, ("system", is_icon, name))
        if found:
            return found, None
        handle, why = _icon_block(wine, ICON_SIZE, ICON_SIZE, (0, 0) if is_icon else (0, 0))
        if why:
            return 0, why
        shared[("system", is_icon, name)] = handle
        wine.trace[-1] += f" {table[name]} -> {handle:#x}"
        return handle, None
    module = wine._exe_ptr(inst) or inst
    group, ghrsrc = resource_bytes(wine, module, name, RT_GROUP_ICON if is_icon else RT_GROUP_CURSOR)
    if group is None:
        wine.trace[-1] += f" {name!r} not found"
        return 0, None
    _res, _type, count = struct.unpack_from("<HHH", group)
    # LookupIconIdFromDirectory: the entry closest to 32x32 at the display's depth. neww takes
    # the one with the largest color depth among those 32 wide, else the first.
    best, best_key = None, None
    for i in range(count):
        if is_icon:
            w, h, colors, _r, planes, bpp, size, rid = struct.unpack_from("<BBBBHHIH", group, 6 + 14 * i)
            w, h = w or 256, h or 256
        else:
            w, h2, planes, bpp, size, rid = struct.unpack_from("<HHHHIH", group, 6 + 14 * i)
            h = h2 // 2
        key = (abs(w - ICON_SIZE) + abs(h - ICON_SIZE), -(planes * bpp))
        if best_key is None or key < best_key:
            best, best_key = (w, h, rid), key
    if best is None:
        return 0, None
    shared, found = _shared(wine, (module, is_icon, best[2]))
    if found:
        return found, None
    bits, _h = resource_bytes(wine, module, best[2], RT_ICON if is_icon else RT_CURSOR)
    if bits is None:
        return 0, None
    hotspot = (0, 0)
    if not is_icon:
        hotspot = struct.unpack_from("<hh", bits)
        bits = bits[4:]
    got, why = dib_from_bytes(bits)
    image = None
    if not why:
        img, w, h2, _mono = got
        image = img.crop((0, 0, w, h2 // 2)) if h2 > w else img
    handle, why = _icon_block(wine, best[0], best[1], hotspot, image=image)
    if why:
        return 0, why
    shared[(module, is_icon, best[2])] = handle
    wine.trace[-1] += f" {name!r} -> {handle:#x}"
    return handle, None


@api("USER", "LoadIcon")
def load_icon(wine, arg, inst, name_ptr):
    handle, why = _load_cursor_icon(wine, inst, name_ptr, True)
    return (0, 0, f"USER.174 LoadIcon: {why}") if why else handle


@api("USER", "LoadCursor")
def load_cursor(wine, arg, inst, name_ptr):
    handle, why = _load_cursor_icon(wine, inst, name_ptr, False)
    return (0, 0, f"USER.173 LoadCursor: {why}") if why else handle


@api("USER", "DrawIcon")
def draw_icon(wine, arg, hdc, x, y, hicon):
    """DrawIcon: the icon's picture where neww has one, from its resource."""
    dc = gdi16.gdi(wine).get(hdc, gdi16.OBJ_DC)
    info = getattr(wine, "icons", {}).get(hicon)
    if dc is None or info is None:
        return 0
    if info["image"] is not None:
        gdi16.blit(wine, dc, gdi16.device_rect(dc, x, y, x + info["width"], y + info["height"]), 0xCC0020,
                   src=(info["image"], False))
    return 1


# ------------------------------------------------------------------ accelerators

@api("USER", "LoadAccelerators")
def load_accelerators(wine, arg, inst, name_ptr):
    """user.c LoadAccelerators16: the RT_ACCELERATOR resource's 5-byte entries in a global block."""
    name = res_arg(wine, name_ptr)
    data, _h = resource_bytes(wine, wine._exe_ptr(inst) or inst, name, RT_ACCELERATOR)
    if data is None:
        return 0
    handle, _dx, why = wine._global_alloc(0x0002, max(len(data), 1))
    if why:
        return 0, 0, f"USER.177 LoadAccelerators: {why}"
    wine.write(wine.selector_of(handle), 0, data)
    return handle


@api("USER", "TranslateAccelerator")
def translate_accelerator(wine, arg, hwnd, haccel, ptr):
    """Only WM_KEYDOWN, WM_CHAR, WM_SYSKEYDOWN and WM_SYSCHAR are looked up, and neww has no input."""
    msg = struct.unpack("<H", gdi16.read(wine, ptr + 2, 2))[0]
    if msg in (0x100, 0x102, 0x104, 0x106):
        return 0, 0, "TranslateAccelerator of a key message: neww has no input, so this cannot happen"
    return 0


# ------------------------------------------------------------------ menus

class Menu:
    def __init__(self, popup):
        self.items = []
        self.popup = popup


def _menus(wine):
    m = wm(wine)
    if not hasattr(m, "menus"):
        m.menus = {}
    return m.menus


def new_menu(wine, popup):
    m = wm(wine)
    handle = m._handle()
    _menus(wine)[handle] = Menu(popup)
    return handle


def menu_items(wine, hmenu):
    menu = _menus(wine).get(hmenu)
    return menu.items if menu is not None else None


def parse_menu(wine, data, pos, popup):
    """A 16-bit MENUITEMTEMPLATE level: flags, an id unless MF_POPUP, the text. MF_END ends it."""
    handle = new_menu(wine, popup)
    menu = _menus(wine)[handle]
    while pos < len(data):
        flags = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        ident = 0
        if not flags & MF_POPUP:
            ident = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        end = data.index(b"\x00", pos)
        text = data[pos:end].decode("cp1252", "replace")
        pos = end + 1
        item = {"flags": flags & ~MF_END, "id": ident, "text": text, "sub": 0}
        if flags & MF_POPUP:
            item["sub"], pos = parse_menu(wine, data, pos, True)
            item["id"] = item["sub"]
        if not text and not flags & MF_POPUP and not ident:
            item["flags"] |= MF_SEPARATOR
        menu.items.append(item)
        if flags & MF_END:
            break
    return handle, pos


def load_menu(wine, module, name_ptr):
    """LoadMenu16. Returns (hmenu, stop)."""
    name = res_arg(wine, name_ptr) if isinstance(name_ptr, int) else name_ptr
    data, _h = resource_bytes(wine, module, name, RT_MENU)
    if data is None:
        return 0, None
    version, header = struct.unpack_from("<HH", data)
    if version != 0:
        return 0, f"LoadMenu({name!r}) version {version}: a MENUEX template, which 16-bit Wine does not load either"
    handle, _pos = parse_menu(wine, data, 4 + header, False)
    return handle, None


@api("USER", "LoadMenu")
def load_menu16(wine, arg, inst, name_ptr):
    handle, why = load_menu(wine, wine._exe_ptr(inst) or inst, name_ptr)
    return (0, 0, f"USER.150 {why}") if why else handle


@api("USER", "LoadMenuIndirect")
def load_menu_indirect(wine, arg, ptr):
    """LoadMenuIndirect16: a MENUITEMTEMPLATEHEADER (version 0 for a 3.x program, else 0 is the
    answer), its offset skipped, then parse_menu_resource. The template is read from the
    pointer to the end of its block."""
    sel, off = ptr >> 16, ptr & 0xFFFF
    size = wine.size(sel) if wine.size is not None else None
    end = min(size if size else 0x10000, 0x10000)
    if not ptr or off + 4 > end:
        return 0, 0, f"USER.220 LoadMenuIndirect: template {sel:#x}:{off:#x} is not in a block neww knows"
    data = wine.read(sel, off, end - off)
    version, header = struct.unpack_from("<HH", data)
    if version != 0:
        return 0, 0
    try:
        handle, _pos = parse_menu(wine, data, 4 + header, False)
    except (ValueError, struct.error):
        return 0, 0, "USER.220 LoadMenuIndirect: the template runs past the end of its block"
    return handle, 0


@api("USER", "CreateMenu")
def create_menu(wine, arg):
    return new_menu(wine, False)


@api("USER", "CreatePopupMenu")
def create_popup_menu(wine, arg):
    return new_menu(wine, True)


@api("USER", "DestroyMenu")
def destroy_menu(wine, arg, hmenu):
    menus = _menus(wine)
    menu = menus.pop(hmenu, None)
    if menu is None:
        return 0
    for item in menu.items:
        if item["sub"]:
            destroy_menu(wine, arg, item["sub"])
    return 1


def _find(wine, hmenu, item, flags):
    """MENU_FindItem: by position, or by command id through the popups."""
    menu = _menus(wine).get(hmenu)
    if menu is None:
        return None, None
    if flags & MF_BYPOSITION:
        return (menu, item) if 0 <= item < len(menu.items) else (None, None)
    for i, it in enumerate(menu.items):
        if it["sub"]:
            found = _find(wine, it["sub"], item, flags)
            if found[0] is not None:
                return found
            if it["id"] == item:
                return menu, i
        elif it["id"] == item:
            return menu, i
    return None, None


@api("USER", "GetSubMenu")
def get_sub_menu(wine, arg, hmenu, pos):
    menu = _menus(wine).get(hmenu)
    if menu is None or not 0 <= signed(pos) < len(menu.items):
        return 0
    return menu.items[signed(pos)]["sub"]


@api("USER", "GetMenuItemCount")
def get_menu_item_count(wine, arg, hmenu):
    menu = _menus(wine).get(hmenu)
    return len(menu.items) if menu is not None else 0xFFFF


@api("USER", "GetMenuItemID")
def get_menu_item_id(wine, arg, hmenu, pos):
    menu = _menus(wine).get(hmenu)
    if menu is None or not 0 <= pos < len(menu.items):
        return 0xFFFF
    item = menu.items[pos]
    return 0xFFFF if item["sub"] else item["id"]


@api("USER", "GetMenuState")
def get_menu_state(wine, arg, hmenu, item, flags):
    menu, i = _find(wine, hmenu, item, flags)
    if menu is None:
        return 0xFFFF
    it = menu.items[i]
    if it["sub"]:
        sub = _menus(wine).get(it["sub"])
        return ((len(sub.items) if sub else 0) << 8) | (it["flags"] & 0xFF) | MF_POPUP
    return it["flags"]


def _set_flag(wine, hmenu, item, flags, mask, value):
    menu, i = _find(wine, hmenu, item, flags)
    if menu is None:
        return 0xFFFF
    it = menu.items[i]
    old = it["flags"] & mask
    it["flags"] = (it["flags"] & ~mask) | (value & mask)
    return old


@api("USER", "EnableMenuItem")
def enable_menu_item(wine, arg, hmenu, item, flags):
    return _set_flag(wine, hmenu, item, flags, MF_GRAYED | MF_DISABLED, flags)


@api("USER", "CheckMenuItem")
def check_menu_item(wine, arg, hmenu, item, flags):
    return _set_flag(wine, hmenu, item, flags, MF_CHECKED, flags)


def _item(wine, flags, ident, data):
    text = ""
    if not flags & (MF_BITMAP | MF_OWNERDRAW | MF_SEPARATOR) and data >> 16:
        text = string_at(wine, data) or ""
    sub = ident if flags & MF_POPUP else 0
    return {"flags": flags & ~(MF_BYPOSITION | MF_POPUP) | (0 if not flags & MF_POPUP else 0), "id": ident,
            "text": text, "sub": sub, "data": data}


@api("USER", "AppendMenu")
def append_menu(wine, arg, hmenu, flags, ident, data):
    menu = _menus(wine).get(hmenu)
    if menu is None:
        return 0
    menu.items.append(_item(wine, flags, ident, data))
    return 1


@api("USER", "InsertMenu")
def insert_menu(wine, arg, hmenu, pos, flags, ident, data):
    menu = _menus(wine).get(hmenu)
    if menu is None:
        return 0
    if flags & MF_BYPOSITION:
        at = pos if pos != 0xFFFF and pos <= len(menu.items) else len(menu.items)
        menu.items.insert(at, _item(wine, flags, ident, data))
        return 1
    target, i = _find(wine, hmenu, pos, flags)
    if target is None:
        if pos == 0xFFFF:
            menu.items.append(_item(wine, flags, ident, data))
            return 1
        return 0
    target.items.insert(i, _item(wine, flags, ident, data))
    return 1


@api("USER", "ModifyMenu")
def modify_menu(wine, arg, hmenu, pos, flags, ident, data):
    target, i = _find(wine, hmenu, pos, flags)
    if target is None:
        return 0
    target.items[i] = _item(wine, flags, ident, data)
    return 1


@api("USER", "RemoveMenu")
def remove_menu(wine, arg, hmenu, pos, flags):
    target, i = _find(wine, hmenu, pos, flags)
    if target is None:
        return 0
    del target.items[i]
    return 1


@api("USER", "DeleteMenu")
def delete_menu(wine, arg, hmenu, pos, flags):
    target, i = _find(wine, hmenu, pos, flags)
    if target is None:
        return 0
    item = target.items.pop(i)
    if item["sub"]:
        destroy_menu(wine, arg, item["sub"])
    return 1


@api("USER", "GetMenuString")
def get_menu_string(wine, arg, hmenu, item, ptr, count, flags):
    target, i = _find(wine, hmenu, item, flags)
    if target is None:
        return 0
    text = (target.items[i]["text"] or "").encode("cp1252", "replace")
    if not ptr or count <= 0:
        return len(text)
    text = text[:count - 1]
    gdi16.write(wine, ptr, text + b"\x00")
    return len(text)


@api("USER", "GetMenu")
def get_menu(wine, arg, hwnd):
    w = wm(wine).get(hwnd)
    return w.menu if w is not None else 0


@api("USER", "SetMenu")
def set_menu(wine, arg, hwnd, hmenu):
    """SetMenu: the frame changes, which Wine applies with SWP_FRAMECHANGED."""
    from .user_wnd import set_window_pos, SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED
    w = wm(wine).get(hwnd)
    if w is None or w.style & 0x40000000:
        return 0
    w.menu = hmenu
    yield from set_window_pos(wine, hwnd, 0, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    return 1


@api("USER", "DrawMenuBar")
def draw_menu_bar(wine, arg, hwnd):
    from .user_wnd import draw_frame
    w = wm(wine).get(hwnd)
    if w is not None:
        draw_frame(wine, w)
    return arg.regs("ax"), 0


@api("USER", "GetSystemMenu")
def get_system_menu(wine, arg, hwnd, revert):
    """The window's system menu: Wine copies user32's SYSMENU resource. neww makes an empty
    popup, so items the task appends are kept."""
    w = wm(wine).get(hwnd)
    if w is None:
        return 0
    if not w.sysmenu:
        w.sysmenu = new_menu(wine, True)
    return w.sysmenu


@api("USER", "CopyIcon", "CopyCursor")
def copy_icon(wine, arg, inst, hicon):
    """user.c CopyIcon16: CreateCursorIconIndirect16 of the same CURSORICONINFO and bits."""
    sel = wine.selector_of(hicon) if hicon else None
    size = wine.size(sel) if sel is not None else None
    if not size:
        return 0
    data = wine.read(sel, 0, size)
    handle, _dx, why = wine._global_alloc(0x0002, size)
    if why:
        return 0, 0, f"USER CopyIcon: {why}"
    wine.write(wine.selector_of(handle), 0, data)
    icons = getattr(wine, "icons", None)
    if icons is not None and hicon in icons:
        icons[handle] = dict(icons[hicon])
    return handle


@api("USER", "GetDialogBaseUnits")
def get_dialog_base_units(wine, arg):
    """sysparams.c get_dialog_base_units: get_char_dimensions of the screen DC's font (the
    stock SYSTEM_FONT), (width of a-zA-Z / 26 + 1) / 2 and the text height, at 96 dpi.
    The font is neww's stand-in (gdi16.TEXT_STANDIN), so the numbers are its metrics."""
    from .user_wnd import get_dc, release_dc
    m = wm(wine)
    if not getattr(m, "base_units", None):
        hdc = get_dc(wine, 0)
        dc = gdi16.gdi(wine).objects[hdc]
        (pil, height, *_r), _log = gdi16.realize(wine, dc)
        cx = round(pil.getlength("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        m.base_units = ((cx // 26 + 1) // 2, height)
        release_dc(wine, 0, hdc)
    cx, cy = m.base_units
    return cx | cy << 16


@api("USER", "IsMenu")
def is_menu(wine, arg, hmenu):
    """user32 IsMenu: TRUE when GetMenuInfo finds the menu."""
    return 1 if hmenu in _menus(wine) else 0
