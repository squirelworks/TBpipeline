"""GDI, from Wine dlls/gdi.exe16, gdi32 and win32u at WINE_COMMIT, for the loaded spec rows.

Objects live in one table, wine.gdi. Stock objects have Wine's own handles:
init_stock_objects creates them first, in the order of the stock object macros,
so GetStockObject(n) is the handle FIRST_GDI_HANDLE (32) + n, and a 16-bit
handle is its low word. Other objects, DCs among them, are numbered by neww
from 0x1004 by 4, as GetDC already numbers its DCs.

Pixels go to a 1024x768, 32-bit screen (Wine's default display mode, see
GetDeviceCaps) kept as a Pillow image, and to Pillow images for bitmaps. A
raster operation is evaluated bit by bit from its ternary code, as Wine's
dib driver does. Text is drawn with a host TrueType font through Pillow,
because Wine too draws with FreeType from font files, and the files Wine
would pick (its own Tahoma, the host's fonts) are not here. TEXT_STANDIN
names the files used; the metrics come from them, not from Wine.
"""

import struct
from pathlib import Path

from .handlers import api, signed

FIRST_GDI_HANDLE = 32
STOCK_LAST = 19
DEFAULT_BITMAP = STOCK_LAST + 1
SCREEN = (1024, 768)

OBJ_PEN, OBJ_BRUSH, OBJ_DC, OBJ_METADC, OBJ_PAL, OBJ_FONT, OBJ_BITMAP, OBJ_REGION, OBJ_MEMDC = 1, 2, 3, 4, 5, 6, 7, 8, 10

BS_SOLID, BS_NULL, BS_HATCHED, BS_PATTERN = 0, 1, 2, 3
PS_SOLID, PS_NULL = 0, 5
TRANSPARENT, OPAQUE = 1, 2
MM_TEXT = 1

# win32u sysparams.c default system colors, COLOR_SCROLLBAR (0) to COLOR_MENUBAR (30).
SYS_COLORS = [
    (212, 208, 200), (58, 110, 165), (10, 36, 106), (128, 128, 128), (212, 208, 200), (255, 255, 255),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (255, 255, 255), (212, 208, 200), (212, 208, 200), (128, 128, 128),
    (10, 36, 106), (255, 255, 255), (212, 208, 200), (128, 128, 128), (128, 128, 128), (0, 0, 0),
    (212, 208, 200), (255, 255, 255), (64, 64, 64), (212, 208, 200), (0, 0, 0), (255, 255, 225),
    (181, 181, 181), (0, 0, 200), (166, 202, 240), (192, 192, 192), (10, 36, 106), (212, 208, 200),
]

# gdi32 objects.c default_system_palette_low and _high: the default palette's 20 entries.
DEFAULT_PALETTE = [
    (0x00, 0x00, 0x00), (0x80, 0x00, 0x00), (0x00, 0x80, 0x00), (0x80, 0x80, 0x00), (0x00, 0x00, 0x80),
    (0x80, 0x00, 0x80), (0x00, 0x80, 0x80), (0xc0, 0xc0, 0xc0), (0xc0, 0xdc, 0xc0), (0xa6, 0xca, 0xf0),
    (0xff, 0xfb, 0xf0), (0xa0, 0xa0, 0xa4), (0x80, 0x80, 0x80), (0xff, 0x00, 0x00), (0x00, 0xff, 0x00),
    (0xff, 0xff, 0x00), (0x00, 0x00, 0xff), (0xff, 0x00, 0xff), (0x00, 0xff, 0xff), (0xff, 0xff, 0xff),
]

FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/freefont")
TEXT_STANDIN = {
    ("swiss", False): "DejaVuSans.ttf", ("swiss", True): "DejaVuSans-Bold.ttf",
    ("roman", False): "DejaVuSerif.ttf", ("roman", True): "DejaVuSerif-Bold.ttf",
    ("modern", False): "DejaVuSansMono.ttf", ("modern", True): "DejaVuSansMono-Bold.ttf",
}


def rgb(colorref, palette=None):
    """A COLORREF as (r, g, b). PALETTEINDEX (0x01) reads the palette, PALETTERGB (0x02) is the
    RGB it names: on a 32-bit display Wine's dib driver matches nothing to a palette."""
    kind = colorref >> 24
    if kind == 0x01:
        entries = palette or DEFAULT_PALETTE
        index = colorref & 0xFFFF
        return entries[index] if index < len(entries) else entries[0]
    return colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF


class GdiObject:
    def __init__(self, kind, **fields):
        self.kind = kind
        self.stock = False
        self.__dict__.update(fields)


class DC(GdiObject):
    def __init__(self, handle, **fields):
        super().__init__(OBJ_DC, handle=handle, hwnd=0, memory=False, origin=(0, 0), clip=None,
                         pen=FIRST_GDI_HANDLE + 7, brush=FIRST_GDI_HANDLE + 0, font=FIRST_GDI_HANDLE + 13,
                         bitmap=FIRST_GDI_HANDLE + DEFAULT_BITMAP, palette=FIRST_GDI_HANDLE + 15,
                         text_color=0, bk_color=0xFFFFFF, bk_mode=OPAQUE, rop2=13, map_mode=MM_TEXT,
                         wnd_org=(0, 0), vp_org=(0, 0), wnd_ext=(1, 1), vp_ext=(1, 1), text_align=0,
                         pos=(0, 0), brush_org=(0, 0), stretch_mode=1, poly_fill=1, saved=[], user_clip=None,
                         char_extra=0, mapper_flags=0, layout=0)
        self.__dict__.update(fields)

    def state(self):
        keys = ("pen", "brush", "font", "bitmap", "palette", "text_color", "bk_color", "bk_mode", "rop2",
                "map_mode", "wnd_org", "vp_org", "wnd_ext", "vp_ext", "text_align", "pos", "brush_org",
                "stretch_mode", "poly_fill", "user_clip", "char_extra")
        return {k: getattr(self, k) for k in keys}


class Gdi:
    """wine.gdi: the object table and the screen."""

    def __init__(self):
        from PIL import Image
        self.objects = {}
        self.next = 0x1004
        self.screen = Image.new("RGB", SCREEN, SYS_COLORS[1])
        self.fonts = {}
        self._stock()

    def _stock(self):
        """init_stock_objects, in its order. Slot 9 is unused at 96 dpi."""
        brushes = [(255, 255, 255), (192, 192, 192), (128, 128, 128), (64, 64, 64), (0, 0, 0)]
        table = [GdiObject(OBJ_BRUSH, style=BS_SOLID, color=c[0] | c[1] << 8 | c[2] << 16, hatch=0) for c in brushes]
        table.append(GdiObject(OBJ_BRUSH, style=BS_NULL, color=0, hatch=0))
        table += [GdiObject(OBJ_PEN, style=PS_SOLID, width=0, color=0xFFFFFF), GdiObject(OBJ_PEN, style=PS_SOLID, width=0, color=0),
                  GdiObject(OBJ_PEN, style=PS_NULL, width=0, color=0), None]
        fixed, var, swiss, modern = 0x01, 0x02, 0x20, 0x30
        table += [
            GdiObject(OBJ_FONT, log=_logfont(12, 0, 400, 255, fixed | modern, "")),
            GdiObject(OBJ_FONT, log=_logfont(12, 0, 400, 0, fixed | modern, "Courier")),
            GdiObject(OBJ_FONT, log=_logfont(12, 0, 400, 0, var | swiss, "MS Sans Serif")),
            GdiObject(OBJ_FONT, log=_logfont(16, 7, 700, 0, var | swiss, "System")),
            GdiObject(OBJ_FONT, log=_logfont(16, 0, 700, 0, var | swiss, "System")),
            GdiObject(OBJ_PAL, entries=list(DEFAULT_PALETTE)),
            GdiObject(OBJ_FONT, log=_logfont(16, 0, 400, 0, fixed | modern, "Courier")),
            GdiObject(OBJ_FONT, log=_logfont(-11, 0, 400, 0, var | swiss, "MS Shell Dlg")),
            GdiObject(OBJ_BRUSH, style=BS_SOLID, color=0xFFFFFF, hatch=0),
            GdiObject(OBJ_PEN, style=PS_SOLID, width=0, color=0),
        ]
        table.append(self.new_bitmap(1, 1, 1))
        for i, obj in enumerate(table):
            if obj is not None:
                obj.stock = True
                self.objects[FIRST_GDI_HANDLE + i] = obj

    def new_bitmap(self, width, height, bpp):
        from PIL import Image
        return GdiObject(OBJ_BITMAP, width=width, height=height, bpp=bpp, planes=1,
                   image=Image.new("RGB", (max(width, 1), max(height, 1)), (0, 0, 0)), dc=0)

    def add(self, obj):
        handle = self.next
        while handle in self.objects:
            handle += 4
        self.next = handle + 4
        self.objects[handle] = obj
        return handle

    def get(self, handle, kind=None):
        obj = self.objects.get(handle)
        if obj is None or (kind is not None and obj.kind not in (kind if isinstance(kind, tuple) else (kind,))):
            return None
        return obj

    # -------------------------------------------------------------- fonts

    def font_for(self, log):
        """A Pillow font for a LOGFONT: (font, height in pixels, ascent, descent)."""
        from PIL import ImageFont
        height = log["height"] or 16
        family = log["pitch_family"] & 0xF0
        face = log["face"].lower()
        if is_fixed_pitch(log):
            kind = "modern"
        elif family == 0x10 or "times" in face or "roman" in face or "serif" in face and "sans" not in face:
            kind = "roman"
        else:
            kind = "swiss"
        bold = log["weight"] >= 600
        key = (kind, bold, height)
        if key in self.fonts:
            return self.fonts[key]
        name = TEXT_STANDIN[(kind, bold)]
        path = next((str(Path(d) / name) for d in FONT_DIRS if (Path(d) / name).exists()), None)

        def load(size):
            # No DejaVu (a Windows host): Pillow's own scalable face stands in.
            # BASIC layout: one glyph per character, the same on every host. Raqm, where Pillow has
            # it, refuses to lay out a lone control character, which GetCharWidth(0, 255) asks for.
            if path:
                return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)
            return ImageFont.load_default(size)
        if height < 0:
            size = -height
            probe = load(size)
            a, d = probe.getmetrics()
            font = probe
        else:
            probe = load(100)
            a0, d0 = probe.getmetrics()
            size = max(1, round(height * 100 / (a0 + d0)))
            font = load(size)
            a, d = font.getmetrics()
        self.fonts[key] = (font, a + d, a, d, size)
        return self.fonts[key]


def is_fixed_pitch(log):
    """A LOGFONT the stand-in draws with the monospace face."""
    face = log["face"].lower()
    return ((log["pitch_family"] & 0x03) == 1 or log["pitch_family"] & 0xF0 == 0x30 or "courier" in face
            or "fixed" in face)


def _logfont(height, width, weight, charset, pitch_family, face, italic=0, underline=0, strike=0, escapement=0,
             orientation=0, out=0, clip=0, quality=0):
    return {"height": height, "width": width, "escapement": escapement, "orientation": orientation,
            "weight": weight, "italic": italic, "underline": underline, "strike": strike, "charset": charset,
            "out": out, "clip": clip, "quality": quality, "pitch_family": pitch_family, "face": face}


def gdi(wine):
    if getattr(wine, "gdi", None) is None:
        wine.gdi = Gdi()
    return wine.gdi


def cstr(wine, ptr, limit=0x10000):
    from .kernel16 import cstr as _cstr
    return _cstr(wine, ptr >> 16, ptr & 0xFFFF, limit)


def read(wine, ptr, n):
    return wine.read(ptr >> 16, ptr & 0xFFFF, n)


def write(wine, ptr, data):
    wine.write(ptr >> 16, ptr & 0xFFFF, data)


# ------------------------------------------------------------------ DCs

def new_dc(wine, **fields):
    g = gdi(wine)
    handle = g.next
    while handle in g.objects:
        handle += 4
    g.next = handle + 4
    g.objects[handle] = DC(handle, **fields)
    return handle


def surface(wine, dc):
    """The image a DC draws on, and the offset of its device origin in it."""
    g = gdi(wine)
    if dc.memory:
        return g.objects[dc.bitmap].image, (0, 0)
    return g.screen, dc.origin


def clip_box(wine, dc):
    """The device clip rectangle in the surface's pixels: (l, t, r, b)."""
    img, (ox, oy) = surface(wine, dc)
    box = (0, 0, img.width, img.height)
    if dc.clip is not None:
        box = _intersect(box, dc.clip)
    if dc.user_clip is not None:
        l, t, r, b = dc.user_clip
        box = _intersect(box, (l + ox, t + oy, r + ox, b + oy))
    return box


def _intersect(a, b):
    l, t, r, b2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (l, t, max(l, r), max(t, b2))


def lp_to_dp(dc, x, y):
    """Wine's mapping for MM_TEXT and the other modes: (x - wnd_org) * vp_ext / wnd_ext + vp_org."""
    (wx, wy), (vx, vy) = dc.wnd_org, dc.vp_org
    (wex, wey), (vex, vey) = dc.wnd_ext, dc.vp_ext
    if dc.map_mode == MM_TEXT:
        return x - wx + vx, y - wy + vy
    return (x - wx) * vex // (wex or 1) + vx, (y - wy) * vey // (wey or 1) + vy


def device_rect(dc, l, t, r, b):
    x0, y0 = lp_to_dp(dc, l, t)
    x1, y1 = lp_to_dp(dc, r, b)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


# ------------------------------------------------------------------ raster operations

def _np():
    import numpy
    return numpy


def mono_pixel(dc, color, fixup):
    """dibdrv get_pixel_color on a 1-bit surface, as 0 or 255. color is (r, g, b).

    Without the fixup it is the nearest color table entry, black first on a tie
    (rgb_to_pixel_colortable). With it, black is 0 and white 1, and any other color is the
    background color's pixel if it is the background color, the other pixel if not."""
    r, g, b = color
    if not fixup:
        black = r * r + g * g + b * b
        white = (255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2
        return 255 if white < black else 0
    if color == (0, 0, 0):
        return 0
    if color == (255, 255, 255):
        return 255
    bk = rgb(dc.bk_color)
    pixel = mono_pixel(dc, bk, False)
    return pixel if color == bk else 255 - pixel


def blit(wine, dc, rect, rop, src=None, src_xy=(0, 0), pattern=None, pattern_fixup=True):
    """Apply a ternary raster operation to rect (device coordinates) of dc.

    src is (image, mono) or None, pattern an (r, g, b) or None. Each output bit is bit
    (P<<2 | S<<1 | D) of the operation's index, as the dib driver's rop tables are.
    """
    np = _np()
    img, (ox, oy) = surface(wine, dc)
    l, t, r, b = rect
    box = _intersect((l + ox, t + oy, r + ox, b + oy), clip_box(wine, dc))
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    index = (rop >> 16) & 0xFF
    dst = np.asarray(img.crop(box), dtype=np.uint8)
    w, h = box[2] - box[0], box[3] - box[1]
    D = dst
    S = np.zeros_like(dst)
    P = np.zeros_like(dst)
    if src is not None:
        simg, mono = src
        sx = src_xy[0] + (box[0] - ox - l)
        sy = src_xy[1] + (box[1] - oy - t)
        crop = simg.crop((sx, sy, sx + w, sy + h))
        S = np.asarray(crop, dtype=np.uint8)
        if mono and not dc_is_mono(wine, dc):
            # A 1-bit source on a color destination: 0 is the text color, 1 the background.
            bit = S[..., 0] > 127
            fg = np.array(rgb(dc.text_color), dtype=np.uint8)
            bg = np.array(rgb(dc.bk_color), dtype=np.uint8)
            S = np.where(bit[..., None], bg, fg).astype(np.uint8)
        elif not mono and dc_is_mono(wine, dc):
            bg = np.array(rgb(dc.bk_color), dtype=np.uint8)
            match = np.all(S == bg, axis=-1)
            S = np.where(match[..., None], 255, 0).astype(np.uint8)
    if pattern is not None:
        if dc_is_mono(wine, dc) and pattern_fixup:
            # dibdrv get_pixel_color with mono_fixup: a brush color becomes 0 or 1 first.
            v = mono_pixel(dc, pattern, True)
            pattern = (v, v, v)
        P = np.broadcast_to(np.array(pattern, dtype=np.uint8), dst.shape).copy()
    out = np.zeros_like(dst)
    for bit in range(8):
        if index >> bit & 1:
            p = P if bit & 4 else ~P
            s = S if bit & 2 else ~S
            d = D if bit & 1 else ~D
            out |= p & s & d
    if dc_is_mono(wine, dc):
        # Every input is 0 or 255 in all three channels by now, so one channel is the bit.
        out = np.repeat(np.where(out[..., :1] > 127, 255, 0).astype(np.uint8), 3, axis=-1)
    from PIL import Image
    img.paste(Image.fromarray(out, "RGB"), box[:2])


def dc_is_mono(wine, dc):
    if not dc.memory:
        return False
    return gdi(wine).objects[dc.bitmap].bpp == 1


def brush_color(wine, dc, handle):
    """The solid color of a brush, or None for a null brush. A brush handle of COLOR_x + 1 is
    that system color, as user32's fill_rect takes it."""
    if 0 < handle <= len(SYS_COLORS):
        return SYS_COLORS[handle - 1]
    brush = gdi(wine).get(handle, OBJ_BRUSH)
    if brush is None or brush.style == BS_NULL:
        return None
    if brush.style == BS_PATTERN:
        return None
    return rgb(brush.color)


def fill(wine, dc, rect, handle):
    """FillRect / PatBlt with a brush: PATCOPY over rect in logical coordinates."""
    color = brush_color(wine, dc, handle)
    brush = gdi(wine).get(handle, OBJ_BRUSH)
    if color is None and brush is not None and brush.style == BS_PATTERN:
        pattern_fill(wine, dc, device_rect(dc, *rect), brush, 0xF00021)
        return
    if color is None:
        return
    blit(wine, dc, device_rect(dc, *rect), 0xF00021, pattern=color)


def pattern_fill(wine, dc, drect, brush, rop):
    """A pattern brush: its bitmap tiled from the brush origin."""
    from PIL import Image
    bmp = gdi(wine).get(brush.bitmap, OBJ_BITMAP)
    if bmp is None:
        return
    l, t, r, b = drect
    tile = bmp.image
    canvas = Image.new("RGB", (max(r - l, 1), max(b - t, 1)))
    ox, oy = dc.brush_org
    for y in range(-((t - oy) % tile.height), canvas.height, tile.height):
        for x in range(-((l - ox) % tile.width), canvas.width, tile.width):
            canvas.paste(tile, (x, y))
    _pattern_blit(wine, dc, drect, canvas, bmp.bpp == 1, rop)


def _pattern_blit(wine, dc, drect, canvas, mono, rop):
    # The pattern stands in the S position: swap P and S bits of the rop's index.
    index = (rop >> 16) & 0xFF
    swapped = 0
    for bit in range(8):
        if index >> bit & 1:
            p, s, d = bit >> 2 & 1, bit >> 1 & 1, bit & 1
            swapped |= 1 << (s << 2 | p << 1 | d)
    blit(wine, dc, drect, swapped << 16, src=(canvas, mono))


def current_brush_blit(wine, dc, drect, rop):
    color = brush_color(wine, dc, dc.brush)
    brush = gdi(wine).get(dc.brush, OBJ_BRUSH)
    if brush is not None and brush.style == BS_PATTERN:
        pattern_fill(wine, dc, drect, brush, rop)
        return
    blit(wine, dc, drect, rop, pattern=color if color is not None else (0, 0, 0))


def rop2_rop3(rop2):
    """The ternary raster op that does a binary one (R2_*) with the pattern as the pen: R2 - 1
    is the truth table, bit (P << 1 | D); the source plays no part."""
    table = (rop2 - 1) & 0xF
    index = 0
    for bit in range(8):
        p, d = bit >> 2 & 1, bit & 1
        if table >> (p << 1 | d) & 1:
            index |= 1 << bit
    return index << 16


def rop2_mix(rop2, pen, dest):
    """Binary raster op on arrays of RGB bytes: R2 - 1 is the truth table, bit (P << 1 | D)."""
    np = _np()
    table = (rop2 - 1) & 0xF
    pen = np.broadcast_to(np.asarray(pen, dtype=np.uint8), dest.shape)
    out = np.zeros_like(dest)
    for p in (0, 1):
        for d in (0, 1):
            if table >> (p << 1 | d) & 1:
                out |= (pen if p else ~pen) & (dest if d else ~dest)
    return out


def pen_line(wine, dc, points):
    """A polyline with the DC's pen, mixed by the DC's ROP2. A null pen draws nothing."""
    pen = gdi(wine).get(dc.pen, OBJ_PEN)
    if pen is None or pen.style == PS_NULL:
        return None
    from PIL import Image, ImageDraw
    img, (ox, oy) = surface(wine, dc)
    box = clip_box(wine, dc)
    pts = [(x + ox, y + oy) for x, y in (lp_to_dp(dc, *p) for p in points)]
    layer = img.crop(box)
    mixed = dc.rop2 != 13
    if mixed:
        target, layer = layer, Image.new("L", layer.size, 0)
    draw = ImageDraw.Draw(layer)
    shifted = [(x - box[0], y - box[1]) for x, y in pts]
    color = 255 if mixed else rgb(pen.color)
    width = max(1, pen.width)
    if len(shifted) >= 2:
        # Wine leaves out a line's last pixel.
        for (x0, y0), (x1, y1) in zip(shifted, shifted[1:]):
            dx, dy = x1 - x0, y1 - y0
            n = max(abs(dx), abs(dy))
            if n == 0:
                continue
            end = (x0 + dx * (n - 1) / n, y0 + dy * (n - 1) / n)
            draw.line([(x0, y0), end], fill=color, width=width)
    if mixed:
        np = _np()
        dest = np.asarray(target.convert("RGB")).copy()
        mask = np.asarray(layer) > 0
        dest[mask] = rop2_mix(dc.rop2, rgb(pen.color), dest[mask])
        layer = Image.fromarray(dest, "RGB").convert(target.mode)
    img.paste(layer, box[:2])
    return None


# ------------------------------------------------------------------ handlers: objects

@api("GDI", "GetStockObject")
def get_stock_object(wine, arg, obj):
    """gdi.c GetStockObject16 -> GetStockObject: 0 out of range or 9."""
    gdi(wine)
    if obj > STOCK_LAST + 1 or obj == 9:
        return 0
    return FIRST_GDI_HANDLE + obj


@api("GDI", "DeleteObject")
def delete_object(wine, arg, handle):
    """DeleteObject: TRUE for a stock object (nothing happens), FALSE for no object. A
    selected object is not freed until its DC lets go of it, but the call still succeeds."""
    g = gdi(wine)
    obj = g.objects.get(handle)
    if obj is None:
        return 0
    if obj.stock:
        return 1
    if obj.kind in (OBJ_DC,):
        return 0
    del g.objects[handle]
    return 1


@api("GDI", "IsGDIObject")
def is_gdi_object(wine, arg, handle):
    """IsGDIObject16: the object's type (OBJ_*), or 0."""
    obj = gdi(wine).objects.get(handle)
    if obj is None:
        return 0
    return OBJ_MEMDC if obj.kind == OBJ_DC and obj.memory else obj.kind


@api("GDI", "SelectObject")
def select_object(wine, arg, hdc, handle):
    """SelectObject: the previous object of that type. A region sets the clip and returns its
    complexity (SIMPLEREGION 2, NULLREGION 1). A bitmap goes into a memory DC only."""
    g = gdi(wine)
    dc = g.get(hdc, OBJ_DC)
    obj = g.objects.get(handle)
    if dc is None or obj is None:
        return 0
    if obj.kind == OBJ_PEN:
        old, dc.pen = dc.pen, handle
    elif obj.kind == OBJ_BRUSH:
        old, dc.brush = dc.brush, handle
    elif obj.kind == OBJ_FONT:
        old, dc.font = dc.font, handle
    elif obj.kind == OBJ_BITMAP:
        if not dc.memory:
            return 0
        if obj.dc and obj.dc != hdc and handle != FIRST_GDI_HANDLE + DEFAULT_BITMAP:
            return 0
        old = dc.bitmap
        prev = g.objects.get(old)
        if prev is not None:
            prev.dc = 0
        dc.bitmap = handle
        obj.dc = hdc
        dc.clip = (0, 0, obj.width, obj.height)
    elif obj.kind == OBJ_REGION:
        return _select_clip(dc, obj)
    else:
        return 0
    return old


def _select_clip(dc, region):
    if region.rect is None:
        dc.user_clip = None
        return 2
    dc.user_clip = region.rect
    l, t, r, b = region.rect
    return 1 if r <= l or b <= t else 2


@api("GDI", "GetObject")
def get_object(wine, arg, handle, count, buf):
    """GetObject16: LOGPEN16, LOGBRUSH16, LOGFONT16, BITMAP16, or a palette's entry count."""
    obj = gdi(wine).objects.get(handle)
    if obj is None:
        return 0
    if obj.kind == OBJ_PEN:
        data = struct.pack("<HhhI", obj.style, obj.width, 0, obj.color)
    elif obj.kind == OBJ_BRUSH:
        data = struct.pack("<HIh", obj.style, obj.color, obj.hatch)
    elif obj.kind == OBJ_FONT:
        data = _pack_logfont(obj.log)
    elif obj.kind == OBJ_BITMAP:
        width_bytes = ((obj.width * obj.bpp + 15) // 16) * 2
        data = struct.pack("<hhhhBBI", 0, obj.width, obj.height, width_bytes, obj.planes, obj.bpp, 0)
    elif obj.kind == OBJ_PAL:
        data = struct.pack("<H", len(obj.entries))
    else:
        return 0
    if not buf:
        return len(data)
    n = min(count, len(data))
    if n <= 0:
        return 0
    write(wine, buf, data[:n])
    return n


def _pack_logfont(log):
    face = log["face"].encode("cp1252", "replace")[:31]
    return struct.pack("<hhhhhBBBBBBBB", log["height"], log["width"], log["escapement"], log["orientation"],
                       log["weight"], log["italic"], log["underline"], log["strike"], log["charset"], log["out"],
                       log["clip"], log["quality"], log["pitch_family"]) + face.ljust(32, b"\x00")


def _unpack_logfont(data):
    v = struct.unpack_from("<hhhhhBBBBBBBB", data)
    face = data[18:50].split(b"\x00", 1)[0].decode("cp1252", "replace")
    return _logfont(v[0], v[1], v[4], v[8], v[12], face, v[5], v[6], v[7], v[2], v[3], v[9], v[10], v[11])


@api("GDI", "CreateSolidBrush")
def create_solid_brush(wine, arg, color):
    return gdi(wine).add(GdiObject(OBJ_BRUSH, style=BS_SOLID, color=color, hatch=0))


@api("GDI", "CreateHatchBrush")
def create_hatch_brush(wine, arg, style, color):
    return gdi(wine).add(GdiObject(OBJ_BRUSH, style=BS_HATCHED, color=color, hatch=style))


@api("GDI", "CreatePatternBrush")
def create_pattern_brush(wine, arg, hbitmap):
    """CreatePatternBrush: Wine copies the bitmap's bits into the brush."""
    g = gdi(wine)
    bmp = g.get(hbitmap, OBJ_BITMAP)
    if bmp is None:
        return 0
    copy = g.new_bitmap(bmp.width, bmp.height, bmp.bpp)
    copy.image = bmp.image.copy()
    return g.add(GdiObject(OBJ_BRUSH, style=BS_PATTERN, color=0, hatch=0, bitmap=g.add(copy)))


@api("GDI", "CreateBrushIndirect")
def create_brush_indirect(wine, arg, ptr):
    style, color, hatch = struct.unpack("<HIh", read(wine, ptr, 8))
    if style == BS_PATTERN:
        return create_pattern_brush(wine, arg, hatch & 0xFFFF)
    return gdi(wine).add(GdiObject(OBJ_BRUSH, style=style, color=color, hatch=hatch))


@api("GDI", "CreatePen")
def create_pen(wine, arg, style, width, color):
    return gdi(wine).add(GdiObject(OBJ_PEN, style=style & 0xFFFF, width=abs(width), color=color))


@api("GDI", "CreatePenIndirect")
def create_pen_indirect(wine, arg, ptr):
    style, width, _y, color = struct.unpack("<HhhI", read(wine, ptr, 10))
    return gdi(wine).add(GdiObject(OBJ_PEN, style=style, width=abs(width), color=color))


@api("GDI", "CreateFontIndirect")
def create_font_indirect(wine, arg, ptr):
    """CreateFontIndirect16: NULL is 0. The LOGFONT is kept; a face is realized when drawing."""
    if not ptr:
        return 0
    return gdi(wine).add(GdiObject(OBJ_FONT, log=_unpack_logfont(read(wine, ptr, 50))))


@api("GDI", "CreateFont")
def create_font(wine, arg, height, width, esc, orient, weight, italic, underline, strike, charset, out, clip,
                quality, pitch, face):
    name = cstr(wine, face, 32).decode("cp1252", "replace") if face else ""
    log = _logfont(height, width, weight, charset & 0xFF, pitch & 0xFF, name, italic & 0xFF, underline & 0xFF,
                   strike & 0xFF, esc, orient, out & 0xFF, clip & 0xFF, quality & 0xFF)
    return gdi(wine).add(GdiObject(OBJ_FONT, log=log))


@api("GDI", "CreateBitmap")
def create_bitmap(wine, arg, width, height, planes, bpp, bits):
    """CreateBitmap: a 1-bit bitmap is mono, any other depth is the display's (Wine makes a
    DDB at the requested depth, which neww keeps as 24-bit color)."""
    g = gdi(wine)
    if not width or not height:
        return FIRST_GDI_HANDLE + DEFAULT_BITMAP
    bmp = g.new_bitmap(width, height, 1 if planes * bpp == 1 else planes * bpp)
    if bits:
        _set_bits(wine, bmp, read(wine, bits, ((width * bmp.bpp + 15) // 16) * 2 * height))
    return g.add(bmp)


def _set_bits(wine, bmp, data):
    """DDB bits: rows padded to 16 bits, top row first."""
    from PIL import Image
    stride = ((bmp.width * bmp.bpp + 15) // 16) * 2
    if bmp.bpp == 1:
        img = Image.frombytes("1", (bmp.width, bmp.height), bytes(data[:stride * bmp.height]), "raw", "1", stride)
        bmp.image = img.convert("RGB")
        return None
    if bmp.bpp == 8:
        pal = DEFAULT_PALETTE
        rows = []
        for y in range(bmp.height):
            row = data[y * stride:y * stride + bmp.width]
            rows.append(b"".join(bytes(pal[i] if i < 10 else pal[i - 236] if i >= 246 else (0, 0, 0)) for i in row))
        bmp.image = Image.frombytes("RGB", (bmp.width, bmp.height), b"".join(rows))
        return None
    return f"bitmap bits at {bmp.bpp} bpp"


@api("GDI", "CreateBitmapIndirect")
def create_bitmap_indirect(wine, arg, ptr):
    _type, width, height, width_bytes, planes, bpp, bits = struct.unpack("<hhhhBBI", read(wine, ptr, 14))
    g = gdi(wine)
    bmp = g.new_bitmap(width, height, 1 if planes * bpp == 1 else planes * bpp)
    if bits:
        _set_bits(wine, bmp, read(wine, bits, width_bytes * height))
    return g.add(bmp)


@api("GDI", "CreateCompatibleBitmap")
def create_compatible_bitmap(wine, arg, hdc, width, height):
    """A bitmap of the DC's format: mono for a memory DC holding a mono bitmap, else color."""
    g = gdi(wine)
    dc = g.get(hdc, OBJ_DC)
    if dc is None:
        return 0
    if not width or not height:
        return FIRST_GDI_HANDLE + DEFAULT_BITMAP
    handle = g.add(g.new_bitmap(width, height, 1 if dc_is_mono(wine, dc) else 32))
    wine.trace[-1] += f" {width}x{height} -> {handle:#x}"
    return handle


@api("GDI", "CreateCompatibleDC")
def create_compatible_dc(wine, arg, hdc):
    """A memory DC with the 1x1 mono default bitmap selected."""
    g = gdi(wine)
    handle = new_dc(wine, memory=True)
    g.objects[handle].clip = (0, 0, 1, 1)
    return handle


@api("GDI", "DeleteDC")
def delete_dc(wine, arg, hdc):
    g = gdi(wine)
    dc = g.get(hdc, OBJ_DC)
    if dc is None:
        return 0
    bmp = g.objects.get(dc.bitmap)
    if bmp is not None and bmp.kind == OBJ_BITMAP:
        bmp.dc = 0
    del g.objects[hdc]
    if hdc in wine.dcs:
        del wine.dcs[hdc]
    return 1


@api("GDI", "CreateDC", "CreateIC")
def create_dc(wine, arg, driver, device, output, init):
    """CreateDC16 for "DISPLAY" is a screen DC. A printer driver stops."""
    name = cstr(wine, driver, 64).decode("latin1").upper() if driver else ""
    if name not in ("DISPLAY", "DISPLAY.DRV"):
        return 0, 0, f"GDI CreateDC({name!r}): Wine loads that printer driver, and neww has none"
    return new_dc(wine)


# ------------------------------------------------------------------ handlers: attributes

def _dc(wine, hdc):
    return gdi(wine).get(hdc, OBJ_DC)


def _swap(attr, ret_long=True):
    def fn(wine, arg, hdc, value):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0x80000000 if attr in ("text_color", "bk_color") else 0
        old = getattr(dc, attr)
        setattr(dc, attr, value)
        return old
    return fn


for _name, _attr in (("SetTextColor", "text_color"), ("SetBkColor", "bk_color"), ("SetBkMode", "bk_mode"),
                     ("SetROP2", "rop2"), ("SetTextAlign", "text_align"), ("SetStretchBltMode", "stretch_mode"),
                     ("SetPolyFillMode", "poly_fill"), ("SetMapperFlags", "mapper_flags")):
    api("GDI", _name)(_swap(_attr))


def _getter(attr):
    def fn(wine, arg, hdc):
        dc = _dc(wine, hdc)
        return getattr(dc, attr) if dc is not None else 0
    return fn


for _name, _attr in (("GetTextColor", "text_color"), ("GetBkColor", "bk_color"), ("GetBkMode", "bk_mode"),
                     ("GetMapMode", "map_mode")):
    api("GDI", _name)(_getter(_attr))


@api("GDI", "SetTextCharacterExtra")
def set_text_character_extra(wine, arg, hdc, extra):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0x8000
    old, dc.char_extra = dc.char_extra, extra
    return old


@api("GDI", "SetTextJustification")
def set_text_justification(wine, arg, hdc, extra, count):
    return 1 if _dc(wine, hdc) is not None else 0


@api("GDI", "SetMapMode")
def set_map_mode(wine, arg, hdc, mode):
    dc = _dc(wine, hdc)
    if dc is None or not 1 <= mode <= 8:
        return 0
    old, dc.map_mode = dc.map_mode, mode
    if mode == MM_TEXT:
        dc.wnd_ext = dc.vp_ext = (1, 1)
    elif mode not in (7, 8):
        return 0, 0, f"GDI SetMapMode({mode}): the metric modes need the display's size in mm, set by mode"
    return old


def _org(attr, offset=False):
    def fn(wine, arg, hdc, x, y):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0
        old = getattr(dc, attr)
        if attr.endswith("ext") and dc.map_mode in (MM_TEXT,):
            return old[0] & 0xFFFF | (old[1] & 0xFFFF) << 16
        new = (old[0] + x, old[1] + y) if offset else (x, y)
        setattr(dc, attr, new)
        return old[0] & 0xFFFF | (old[1] & 0xFFFF) << 16
    return fn


api("GDI", "SetWindowOrg")(_org("wnd_org"))
api("GDI", "SetViewportOrg")(_org("vp_org"))
api("GDI", "SetWindowExt")(_org("wnd_ext"))
api("GDI", "SetViewportExt")(_org("vp_ext"))


def _get_pair(attr):
    def fn(wine, arg, hdc):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0
        v = getattr(dc, attr)
        return v[0] & 0xFFFF | (v[1] & 0xFFFF) << 16
    return fn


api("GDI", "GetWindowOrg")(_get_pair("wnd_org"))
api("GDI", "GetViewportOrg")(_get_pair("vp_org"))
api("GDI", "GetWindowExt")(_get_pair("wnd_ext"))
api("GDI", "GetViewportExt")(_get_pair("vp_ext"))
api("GDI", "GetCurrentPosition")(_get_pair("pos"))


@api("GDI", "GetDCOrg")
def get_dc_org(wine, arg, hdc):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    x, y = (0, 0) if dc.memory else dc.origin
    return x & 0xFFFF | (y & 0xFFFF) << 16


@api("GDI", "SetBrushOrg")
def set_brush_org(wine, arg, hdc, x, y):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    old, dc.brush_org = dc.brush_org, (x, y)
    return old[0] & 0xFFFF | (old[1] & 0xFFFF) << 16


@api("GDI", "UnrealizeObject")
def unrealize_object(wine, arg, handle):
    return 1 if gdi(wine).objects.get(handle) is not None else 0


@api("GDI", "SaveDC")
def save_dc(wine, arg, hdc):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    dc.saved.append(dc.state())
    return len(dc.saved)


@api("GDI", "RestoreDC")
def restore_dc(wine, arg, hdc, level):
    """RestoreDC: a negative level counts back from the top, a positive one is that save."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    if level < 0:
        level = len(dc.saved) + level + 1
    if level <= 0 or level > len(dc.saved):
        return 0
    state = dc.saved[level - 1]
    del dc.saved[level - 1:]
    dc.__dict__.update(state)
    return 1


@api("GDI", "GetNearestColor")
def get_nearest_color(wine, arg, hdc, color):
    """On a 32-bit display every RGB is itself. A palette index is its entry."""
    if _dc(wine, hdc) is None:
        return 0xFFFFFFFF
    r, g, b = rgb(color)
    return r | g << 8 | b << 16


# ------------------------------------------------------------------ regions and clipping

@api("GDI", "CreateRectRgn")
def create_rect_rgn(wine, arg, l, t, r, b):
    """A rectangle region, normalized; neww keeps rectangle regions only."""
    return gdi(wine).add(GdiObject(OBJ_REGION, rect=(min(l, r), min(t, b), max(l, r), max(t, b))))


@api("GDI", "CreateRectRgnIndirect")
def create_rect_rgn_indirect(wine, arg, ptr):
    l, t, r, b = struct.unpack("<hhhh", read(wine, ptr, 8))
    return gdi(wine).add(GdiObject(OBJ_REGION, rect=(min(l, r), min(t, b), max(l, r), max(t, b))))


@api("GDI", "SetRectRgn")
def set_rect_rgn(wine, arg, hrgn, l, t, r, b):
    rgn = gdi(wine).get(hrgn, OBJ_REGION)
    if rgn is not None:
        rgn.rect = (min(l, r), min(t, b), max(l, r), max(t, b))
    return arg.regs("ax"), 0


@api("GDI", "GetRgnBox")
def get_rgn_box(wine, arg, hrgn, ptr):
    rgn = gdi(wine).get(hrgn, OBJ_REGION)
    if rgn is None:
        return 0
    l, t, r, b = rgn.rect
    write(wine, ptr, struct.pack("<hhhh", l, t, r, b))
    return 1 if r <= l or b <= t else 2


@api("GDI", "CombineRgn")
def combine_rgn(wine, arg, dest, src1, src2, mode):
    """CombineRgn for results that stay one rectangle. Others stop, naming the mode."""
    g = gdi(wine)
    d, a = g.get(dest, OBJ_REGION), g.get(src1, OBJ_REGION)
    if d is None or a is None:
        return 0
    if mode == 5:  # RGN_COPY
        d.rect = a.rect
    else:
        b = g.get(src2, OBJ_REGION)
        if b is None:
            return 0
        if mode == 1:  # RGN_AND
            d.rect = _intersect(a.rect, b.rect)
        elif mode == 2 and _contains(a.rect, b.rect):
            d.rect = a.rect
        elif mode == 2 and _contains(b.rect, a.rect):
            d.rect = b.rect
        elif _empty(b.rect) and mode in (2, 3, 4):
            d.rect = a.rect
        elif _empty(a.rect) and mode in (2, 3):
            # REGION_UnionRegion / REGION_XorRegion with an empty first region: the second.
            d.rect = b.rect
        elif _empty(a.rect) and mode == 4:
            d.rect = (0, 0, 0, 0)
        else:
            return 0, 0, f"GDI CombineRgn mode {mode} of {a.rect} and {b.rect}: the result is not one rectangle, and neww keeps rectangles only"
    return 1 if _empty(d.rect) else 2


def _empty(r):
    return r[2] <= r[0] or r[3] <= r[1]


def _contains(a, b):
    return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]


@api("GDI", "SelectClipRgn")
def select_clip_rgn(wine, arg, hdc, hrgn):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    if not hrgn:
        dc.user_clip = None
        return 2
    rgn = gdi(wine).get(hrgn, OBJ_REGION)
    if rgn is None:
        return 0
    return _select_clip(dc, rgn)


@api("GDI", "IntersectClipRect")
def intersect_clip_rect(wine, arg, hdc, l, t, r, b):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    rect = device_rect(dc, l, t, r, b)
    dc.user_clip = _intersect(dc.user_clip, rect) if dc.user_clip is not None else rect
    return 1 if _empty(dc.user_clip) else 2


@api("GDI", "ExcludeClipRect")
def exclude_clip_rect(wine, arg, hdc, l, t, r, b):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    rect = device_rect(dc, l, t, r, b)
    base = dc.user_clip
    if base is None:
        img, (ox, oy) = surface(wine, dc)
        cl = clip_box(wine, dc)
        base = (cl[0] - ox, cl[1] - oy, cl[2] - ox, cl[3] - oy)
    if _empty(_intersect(base, rect)):
        dc.user_clip = base
        return 2
    if _contains(rect, base):
        dc.user_clip = (base[0], base[1], base[0], base[1])
        return 1
    return 0, 0, f"GDI ExcludeClipRect {rect} from {base}: the clip is no longer one rectangle, and neww keeps rectangles only"


@api("GDI", "GetClipBox")
def get_clip_box(wine, arg, hdc, ptr):
    """GetClipBox: the clip in logical coordinates (MM_TEXT: device minus the origins)."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    img, (ox, oy) = surface(wine, dc)
    l, t, r, b = clip_box(wine, dc)
    l, t, r, b = l - ox, t - oy, r - ox, b - oy
    (wx, wy), (vx, vy) = dc.wnd_org, dc.vp_org
    write(wine, ptr, struct.pack("<hhhh", l - vx + wx, t - vy + wy, r - vx + wx, b - vy + wy))
    return 1 if r <= l or b <= t else 2


@api("GDI", "PtVisible")
def pt_visible(wine, arg, hdc, x, y):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    img, (ox, oy) = surface(wine, dc)
    dx, dy = lp_to_dp(dc, x, y)
    l, t, r, b = clip_box(wine, dc)
    return 1 if l <= dx + ox < r and t <= dy + oy < b else 0


@api("GDI", "RectVisible")
def rect_visible(wine, arg, hdc, ptr):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    l, t, r, b = struct.unpack("<hhhh", read(wine, ptr, 8))
    img, (ox, oy) = surface(wine, dc)
    dl, dt, dr, db = device_rect(dc, l, t, r, b)
    return 0 if _empty(_intersect((dl + ox, dt + oy, dr + ox, db + oy), clip_box(wine, dc))) else 1


# ------------------------------------------------------------------ drawing

@api("GDI", "PatBlt")
def pat_blt(wine, arg, hdc, x, y, w, h, rop):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    current_brush_blit(wine, dc, device_rect(dc, x, y, x + w, y + h), rop)
    return 1


@api("GDI", "BitBlt")
def bit_blt(wine, arg, hdst, x, y, w, h, hsrc, sx, sy, rop):
    g = gdi(wine)
    dc = _dc(wine, hdst)
    if dc is None:
        return 0
    uses_src = ((rop >> 2) ^ rop) & 0x330000
    uses_pat = ((rop >> 4) ^ rop) & 0x0F0000
    src = None
    if uses_src:
        sdc = _dc(wine, hsrc)
        if sdc is None:
            return 0
        simg, (sox, soy) = surface(wine, sdc)
        sxd, syd = lp_to_dp(sdc, sx, sy)
        src = (simg, dc_is_mono(wine, sdc))
        src_xy = (sxd + sox, syd + soy)
    else:
        src_xy = (0, 0)
    color = brush_color(wine, dc, dc.brush) if uses_pat else None
    blit(wine, dc, device_rect(dc, x, y, x + w, y + h), rop, src=src, src_xy=src_xy,
         pattern=(color if color is not None else (0, 0, 0)) if uses_pat else None)
    return 1


@api("GDI", "StretchBlt")
def stretch_blt(wine, arg, hdst, x, y, w, h, hsrc, sx, sy, sw, sh, rop):
    """StretchBlt: the source scaled to the destination size (nearest pixel), then BitBlt's rop."""
    from PIL import Image
    if (w, h) == (sw, sh):
        return bit_blt(wine, arg, hdst, x, y, w, h, hsrc, sx, sy, rop)
    dc, sdc = _dc(wine, hdst), _dc(wine, hsrc)
    if dc is None or sdc is None or not w or not h or not sw or not sh:
        return 0
    simg, (sox, soy) = surface(wine, sdc)
    sxd, syd = lp_to_dp(sdc, sx, sy)
    crop = simg.crop((sxd + sox, syd + soy, sxd + sox + abs(sw), syd + soy + abs(sh)))
    if sw < 0:
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if sh < 0:
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
    if (w < 0) != (sw < 0) and w < 0:
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if (h < 0) != (sh < 0) and h < 0:
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
    scaled = crop.resize((abs(w), abs(h)), Image.NEAREST)
    color = brush_color(wine, dc, dc.brush)
    blit(wine, dc, device_rect(dc, x, y, x + w, y + h), rop, src=(scaled, dc_is_mono(wine, sdc)),
         src_xy=(0, 0), pattern=color or (0, 0, 0))
    return 1


@api("GDI", "Rectangle")
def rectangle(wine, arg, hdc, l, t, r, b):
    """Rectangle: the interior with the brush, the outline with the pen, right and bottom
    edges excluded."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    l, r = min(l, r), max(l, r)
    t, b = min(t, b), max(t, b)
    pen = gdi(wine).get(dc.pen, OBJ_PEN)
    inset = 0 if pen is None or pen.style == PS_NULL else max(1, pen.width)
    color = brush_color(wine, dc, dc.brush)
    if color is not None:
        dl, dt, dr, db = device_rect(dc, l + inset, t + inset, r - inset, b - inset)
        if inset == 0:
            dl, dt, dr, db = device_rect(dc, l, t, r - 1, b - 1)
        blit(wine, dc, (dl, dt, dr, db), rop2_rop3(dc.rop2), pattern=color)
    if inset:
        why = pen_line(wine, dc, [(l, t), (r - 1, t), (r - 1, b - 1), (l, b - 1), (l, t - 1)])
        if why:
            return 0, 0, f"GDI Rectangle: {why}"
    return 1


@api("GDI", "MoveTo")
def move_to(wine, arg, hdc, x, y):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    old, dc.pos = dc.pos, (x, y)
    return old[0] & 0xFFFF | (old[1] & 0xFFFF) << 16


@api("GDI", "MoveToEx")
def move_to_ex(wine, arg, hdc, x, y, ptr):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    if ptr:
        write(wine, ptr, struct.pack("<hh", *dc.pos))
    dc.pos = (x, y)
    return 1


@api("GDI", "LineTo")
def line_to(wine, arg, hdc, x, y):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    why = pen_line(wine, dc, [dc.pos, (x, y)])
    dc.pos = (x, y)
    if why:
        return 0, 0, f"GDI LineTo: {why}"
    return 1


@api("GDI", "SetPixel")
def set_pixel(wine, arg, hdc, x, y, color):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0xFFFFFFFF
    dx, dy = lp_to_dp(dc, x, y)
    # dibdrv_SetPixel: the pixel without the 1bpp massaging, and the color it stands for back.
    r, g, b = rgb(color)
    if dc_is_mono(wine, dc):
        v = mono_pixel(dc, (r, g, b), False)
        r = g = b = v
    blit(wine, dc, (dx, dy, dx + 1, dy + 1), 0xF00021, pattern=(r, g, b), pattern_fixup=False)
    return r | g << 8 | b << 16


@api("GDI", "GetPixel")
def get_pixel(wine, arg, hdc, x, y):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0xFFFFFFFF
    img, (ox, oy) = surface(wine, dc)
    dx, dy = lp_to_dp(dc, x, y)
    l, t, r, b = clip_box(wine, dc)
    if not (l <= dx + ox < r and t <= dy + oy < b):
        return 0xFFFFFFFF
    p = img.getpixel((dx + ox, dy + oy))
    return p[0] | p[1] << 8 | p[2] << 16


# ------------------------------------------------------------------ text

def realize(wine, dc):
    g = gdi(wine)
    font = g.get(dc.font, OBJ_FONT) or g.objects[FIRST_GDI_HANDLE + 13]
    return g.font_for(font.log), font.log


def tm_pitch(log):
    """tmPitchAndFamily. TMPF_FIXED_PITCH (1) means the font is VARIABLE pitch; Windows named the bit
    backwards. TMPF_VECTOR (2) and TMPF_TRUETYPE (4) are set, as for a TrueType face. TB80BAS reads
    bit 0: clear, it gives every character the width of the break character instead of asking
    GetCharWidth, so proportional text was laid out as if it were monospace."""
    return (log["pitch_family"] & 0xF0) | 0x06 | (0 if is_fixed_pitch(log) else 0x01)


def text_metrics(wine, dc):
    (pil, height, ascent, descent, size), log = realize(wine, dc)
    widths = [pil.getlength(chr(c)) for c in range(32, 127)]
    ave = round(pil.getlength("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ") / 52)
    internal = height - size if log["height"] >= 0 else height - size
    return {
        "height": height, "ascent": ascent, "descent": descent, "internal": max(0, internal), "external": 0,
        "ave": ave, "max": round(max(widths)), "weight": log["weight"], "italic": log["italic"],
        "underline": log["underline"], "strike": log["strike"], "first": 32, "last": 255, "default": 31,
        "break": 32, "pitch": tm_pitch(log),
        "charset": log["charset"], "overhang": 0, "aspect": 96,
    }


@api("GDI", "GetTextMetrics")
def get_text_metrics(wine, arg, hdc, ptr):
    """TEXTMETRIC16 from the stand-in font (see TEXT_STANDIN)."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    m = text_metrics(wine, dc)
    data = struct.pack("<hhhhhhhhBBBBBBBBBhhh", m["height"], m["ascent"], m["descent"], m["internal"], m["external"],
                       m["ave"], m["max"], m["weight"], m["italic"], m["underline"], m["strike"], m["first"],
                       m["last"], m["default"], m["break"], m["pitch"], m["charset"], m["overhang"], m["aspect"],
                       m["aspect"])
    write(wine, ptr, data)
    return 1


def char_width(pil, ch):
    """One character's advance in whole pixels, as GetCharWidth gives it. The extent of a string is
    the sum of these, so a caller that adds up GetCharWidth lands where TextOut stops."""
    return round(pil.getlength(ch))


def text_width(wine, dc, text):
    (pil, *_rest), _log = realize(wine, dc)
    return sum(char_width(pil, ch) for ch in text) + dc.char_extra * len(text)


@api("GDI", "GetTextExtent")
def get_text_extent(wine, arg, hdc, ptr, count):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    text = read(wine, ptr, max(count, 0)).decode("cp1252", "replace")
    (_pil, height, *_r), _log = realize(wine, dc)
    return text_width(wine, dc, text) & 0xFFFF | height << 16


@api("GDI", "GetTextExtentPoint")
def get_text_extent_point(wine, arg, hdc, ptr, count, size):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    text = read(wine, ptr, max(count, 0)).decode("cp1252", "replace")
    (_pil, height, *_r), _log = realize(wine, dc)
    write(wine, size, struct.pack("<hh", text_width(wine, dc, text), height))
    return 1


@api("GDI", "GetCharWidth")
def get_char_width(wine, arg, hdc, first, last, ptr):
    dc = _dc(wine, hdc)
    if dc is None or last < first:
        return 0
    (pil, *_r), _log = realize(wine, dc)
    out = b"".join(struct.pack("<h", char_width(pil, bytes([c]).decode("cp1252", "replace")))
                   for c in range(first, last + 1))
    write(wine, ptr, out)
    return 1


@api("GDI", "GetTextFace")
def get_text_face(wine, arg, hdc, count, ptr):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    _f, log = realize(wine, dc)
    face = log["face"].encode("cp1252", "replace")
    if not ptr:
        return len(face) + 1
    n = min(count - 1, len(face))
    if n < 0:
        return 0
    write(wine, ptr, face[:n] + b"\x00")
    return n


def draw_text(wine, dc, x, y, text, opaque_rect=None, clip_rect=None):
    """TextOut and ExtTextOut: TA_TOP/TA_BASELINE/TA_BOTTOM and TA_LEFT/RIGHT/CENTER, TA_UPDATECP,
    an opaque background in OPAQUE mode."""
    from PIL import Image, ImageDraw
    (pil, height, ascent, descent, size), log = realize(wine, dc)
    width = text_width(wine, dc, text)
    align = dc.text_align
    if align & 1:  # TA_UPDATECP
        x, y = dc.pos
    h_align = align & 6
    v_align = align & 24
    if h_align == 2:  # TA_RIGHT
        x -= width
    elif h_align == 6:  # TA_CENTER
        x -= width // 2
    if v_align == 24:  # TA_BASELINE
        y -= ascent
    elif v_align == 8:  # TA_BOTTOM
        y -= height
    if align & 1:
        dc.pos = (x + width if h_align == 0 else dc.pos[0], dc.pos[1])
    dl, dt = lp_to_dp(dc, x, y)
    img, (ox, oy) = surface(wine, dc)
    box = clip_box(wine, dc)
    if clip_rect is not None:
        cl = device_rect(dc, *clip_rect)
        box = _intersect(box, (cl[0] + ox, cl[1] + oy, cl[2] + ox, cl[3] + oy))
    if opaque_rect is not None:
        blit(wine, dc, device_rect(dc, *opaque_rect), 0xF00021, pattern=rgb(dc.bk_color))
    if dc.bk_mode == OPAQUE:
        bl, bt, br, bb = dl + ox, dt + oy, dl + ox + width, dt + oy + height
        area = _intersect((bl, bt, br, bb), box)
        if not _empty(area):
            ImageDraw.Draw(img).rectangle([area[0], area[1], area[2] - 1, area[3] - 1], fill=rgb(dc.bk_color))
    layer = Image.new("L", (max(width, 1) + size, height + 2), 0)
    draw = ImageDraw.Draw(layer)
    cx = 0
    for ch in text:
        draw.text((cx, 0), ch, font=pil, fill=255)
        cx += char_width(pil, ch) + dc.char_extra
    if log["underline"]:
        draw.line([(0, ascent + 1), (width, ascent + 1)], fill=255)
    if log["strike"]:
        draw.line([(0, ascent * 2 // 3), (width, ascent * 2 // 3)], fill=255)
    color = Image.new("RGB", layer.size, rgb(dc.text_color))
    mask = layer.point(lambda v: 255 if v >= 128 else 0)
    gx, gy = dl + ox, dt + oy
    sub = (max(box[0] - gx, 0), max(box[1] - gy, 0), min(box[2] - gx, layer.width), min(box[3] - gy, layer.height))
    if sub[2] > sub[0] and sub[3] > sub[1]:
        img.paste(color.crop(sub), (gx + sub[0], gy + sub[1]), mask.crop(sub))
    return width


@api("GDI", "TextOut")
def text_out(wine, arg, hdc, x, y, ptr, count):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    text = read(wine, ptr, max(count, 0)).decode("cp1252", "replace")
    draw_text(wine, dc, x, y, text)
    wine.trace[-1] += f" {text!r}"
    return 1


@api("GDI", "ExtTextOut")
def ext_text_out(wine, arg, hdc, x, y, flags, rect_ptr, ptr, count, dx_ptr):
    """ExtTextOut16: ETO_OPAQUE (2) fills the rectangle, ETO_CLIPPED (4) clips to it. Character
    spacing from lpDx stops: neww lays out with the font's own widths."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    rect = struct.unpack("<hhhh", read(wine, rect_ptr, 8)) if rect_ptr else None
    text = read(wine, ptr, max(count, 0)).decode("cp1252", "replace") if ptr else ""
    if dx_ptr and text:
        dxs = struct.unpack(f"<{len(text)}h", read(wine, dx_ptr, 2 * len(text)))
        (pil, *_r), _l = realize(wine, dc)
        own = [char_width(pil, c) for c in text]
        if list(dxs) != own:
            return 0, 0, f"GDI ExtTextOut {text!r} with lpDx {list(dxs)}: neww lays text out with the font's widths {own}"
    draw_text(wine, dc, x, y, text, opaque_rect=rect if flags & 2 and rect else None,
              clip_rect=rect if flags & 4 and rect else None)
    wine.trace[-1] += f" {text!r}"
    return 1


# ------------------------------------------------------------------ palettes

@api("GDI", "CreatePalette")
def create_palette(wine, arg, ptr):
    version, count = struct.unpack("<HH", read(wine, ptr, 4))
    raw = read(wine, ptr + 4, 4 * count)
    entries = [tuple(raw[4 * i:4 * i + 3]) for i in range(count)]
    return gdi(wine).add(GdiObject(OBJ_PAL, entries=entries))


@api("GDI", "GetPaletteEntries")
def get_palette_entries(wine, arg, hpal, start, count, ptr):
    pal = gdi(wine).get(hpal, OBJ_PAL)
    if pal is None:
        return 0
    if not ptr:
        return len(pal.entries)
    chunk = pal.entries[start:start + count]
    write(wine, ptr, b"".join(bytes(e) + b"\x00" for e in chunk))
    return len(chunk)


@api("GDI", "GetSystemPaletteEntries")
def get_system_palette_entries(wine, arg, hdc, start, count, ptr):
    """On a display that is not palettized (RC_PALETTE clear) Wine returns 0."""
    return 0


@api("GDI", "GetNearestPaletteIndex")
def get_nearest_palette_index(wine, arg, hpal, color):
    pal = gdi(wine).get(hpal, OBJ_PAL)
    if pal is None or not pal.entries:
        return 0
    r, g, b = rgb(color)
    return min(range(len(pal.entries)), key=lambda i: (pal.entries[i][0] - r) ** 2 + (pal.entries[i][1] - g) ** 2 + (pal.entries[i][2] - b) ** 2)


# ------------------------------------------------------------------ bitmaps from bits

def dib_image(wine, info_ptr, bits_ptr, usage, palette=None):
    """A packed BITMAPINFO and its bits as (image, width, height, bpp). Bottom-up unless the
    height is negative. 1, 4, 8, 24 and 32 bpp, BI_RGB only."""
    from PIL import Image
    size = struct.unpack("<I", read(wine, info_ptr, 4))[0]
    if size == 12:
        w, h, planes, bpp = struct.unpack("<HHHH", read(wine, info_ptr + 4, 8))
        comp, used, entry = 0, 0, 3
    else:
        w, h, planes, bpp, comp, _sz, _xp, _yp, used, _imp = struct.unpack("<iiHHIIiiII", read(wine, info_ptr + 4, 36))
        entry = 4
    if comp != 0:
        return None, f"DIB compression {comp}"
    colors = used or (1 << bpp if bpp <= 8 else 0)
    table = []
    if colors:
        raw = read(wine, info_ptr + size, entry * colors)
        if usage == 1:
            idx = struct.unpack(f"<{colors}H", read(wine, info_ptr + size, 2 * colors))
            pal = palette or DEFAULT_PALETTE
            table = [pal[i] if i < len(pal) else (0, 0, 0) for i in idx]
        else:
            table = [(raw[entry * i + 2], raw[entry * i + 1], raw[entry * i]) for i in range(colors)]
    top_down = h < 0
    h = abs(h)
    stride = ((w * bpp + 31) // 32) * 4
    data = _read_huge(wine, bits_ptr, stride * h)
    if bpp in (1, 4, 8):
        img = Image.frombytes("P", (w, h), data, "raw", {1: "P;1", 4: "P;4", 8: "P"}[bpp], stride, 1 if top_down else -1)
        flat = []
        for c in table + [(0, 0, 0)] * (256 - len(table)):
            flat += list(c)
        img.putpalette(flat)
        img = img.convert("RGB")
    elif bpp == 24:
        img = Image.frombytes("RGB", (w, h), data, "raw", "BGR", stride, 1 if top_down else -1)
    elif bpp == 32:
        img = Image.frombytes("RGB", (w, h), data, "raw", "BGRX", stride, 1 if top_down else -1)
    else:
        return None, f"DIB at {bpp} bpp"
    mono = bpp == 1 and table[:2] == [(0, 0, 0), (255, 255, 255)]
    return (img, w, h, 1 if mono else 32), None


def _read_huge(wine, ptr, n):
    """Bits may run past 64K: a huge pointer's next selectors follow, as MapSL makes it flat."""
    sel, off = ptr >> 16, ptr & 0xFFFF
    base = wine.linear(sel) if wine.linear else None
    if base is None or getattr(wine, "read_linear", None) is None:
        return read(wine, ptr, n)
    return wine.read_linear(base + off, n)


@api("GDI", "CreateDIBitmap")
def create_di_bitmap(wine, arg, hdc, header, init, bits, info, usage):
    """CreateDIBitmap16: a DDB of the DC's format (color), from the header's size. CBM_INIT (4)
    sets the bits from info and bits."""
    g = gdi(wine)
    size = struct.unpack("<I", read(wine, header, 4))[0]
    if size == 12:
        w, h = struct.unpack("<HH", read(wine, header + 4, 4))
    else:
        w, h = struct.unpack("<ii", read(wine, header + 4, 8))
    bmp = g.new_bitmap(w, abs(h), 32)
    if init & 4 and bits and info:
        got, why = dib_image(wine, info, bits, usage)
        if why:
            return 0, 0, f"GDI CreateDIBitmap: {why}"
        bmp.image.paste(got[0], (0, 0))
    return g.add(bmp)


@api("GDI", "SetDIBitsToDevice")
def set_di_bits_to_device(wine, arg, hdc, x, y, cx, cy, sx, sy, start, lines, bits, info, usage):
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    got, why = dib_image(wine, info, bits, usage)
    if why:
        return 0, 0, f"GDI SetDIBitsToDevice: {why}"
    img, w, h, _bpp = got
    if start != 0 or lines < h:
        return 0, 0, f"GDI SetDIBitsToDevice bands (start {start}, {lines} of {h} lines): neww draws whole DIBs only"
    blit(wine, dc, device_rect(dc, x, y, x + cx, y + cy), 0xCC0020, src=(img, False), src_xy=(sx, h - sy - cy))
    return lines


@api("GDI", "SetDIBits")
def set_di_bits(wine, arg, hdc, hbitmap, start, lines, bits, info, usage):
    bmp = gdi(wine).get(hbitmap, OBJ_BITMAP)
    if bmp is None:
        return 0
    got, why = dib_image(wine, info, bits, usage)
    if why:
        return 0, 0, f"GDI SetDIBits: {why}"
    img, w, h, _bpp = got
    if start != 0 or lines < h:
        return 0, 0, f"GDI SetDIBits bands (start {start}, {lines} of {h}): neww sets whole DIBs only"
    bmp.image.paste(img, (0, bmp.height - h))
    return lines


@api("GDI", "GetBitmapBits")
def get_bitmap_bits(wine, arg, hbitmap, count, ptr):
    bmp = gdi(wine).get(hbitmap, OBJ_BITMAP)
    if bmp is None:
        return 0
    if bmp.bpp != 1:
        return 0, 0, f"GDI GetBitmapBits of a {bmp.bpp}-bit bitmap: neww keeps color bitmaps as RGB"
    stride = ((bmp.width + 15) // 16) * 2
    data = bmp.image.convert("1").tobytes("raw", "1", stride)
    n = min(count, len(data))
    write(wine, ptr, data[:n])
    return n


@api("GDI", "SetBitmapBits")
def set_bitmap_bits(wine, arg, hbitmap, count, ptr):
    bmp = gdi(wine).get(hbitmap, OBJ_BITMAP)
    if bmp is None:
        return 0
    why = _set_bits(wine, bmp, read(wine, ptr, count))
    if why:
        return 0, 0, f"GDI SetBitmapBits: {why}"
    return count


@api("GDI", "StretchDIBits")
def stretch_di_bits(wine, arg, hdc, x, y, w, h, sx, sy, sw, sh, bits, info, usage, rop):
    """StretchDIBits16 as Wine's nulldrv_StretchDIBits: source rows count from the DIB's bottom
    unless it is top-down (and, for a SRCCOPY that is not a plain copy from the origin, then too),
    the source is scaled to the destination (nearest pixel) and drawn with the rop. The answer is
    the DIB's height for SRCCOPY, its biHeight otherwise, and 0 when the source rectangle misses
    the DIB."""
    from PIL import Image
    dc = _dc(wine, hdc)
    if dc is None or not bits:
        return 0
    got, why = dib_image(wine, info, bits, usage)
    if why:
        return 0, 0, f"GDI StretchDIBits: {why}"
    img, dw, height, _bpp = got
    size = struct.unpack("<I", read(wine, info, 4))[0]
    bi_height = struct.unpack("<h" if size == 12 else "<i", read(wine, info + 8, 2 if size == 12 else 4))[0]
    top_down = bi_height < 0
    plain = sx == 0 and sy == 0 and sw == w and sh == h
    if not top_down or (rop == 0xCC0020 and not plain):
        sy = height - sy - sh
    l, r = sorted((sx, sx + sw))
    t, b = sorted((sy, sy + sh))
    if _empty(_intersect((l, t, r, b), (0, 0, dw, height))):
        return 0
    if not w or not h or not sw or not sh:
        return 0
    crop = img.crop((l, t, r, b))
    if (sw < 0) != (w < 0):
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if (sh < 0) != (h < 0):
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
    if crop.size != (abs(w), abs(h)):
        crop = crop.resize((abs(w), abs(h)), Image.NEAREST)
    color = brush_color(wine, dc, dc.brush)
    blit(wine, dc, device_rect(dc, x, y, x + w, y + h), rop, src=(crop, False), src_xy=(0, 0),
         pattern=color or (0, 0, 0))
    return height if rop == 0xCC0020 else bi_height


@api("GDI", "MulDiv")
def mul_div(wine, arg, a, b, d):
    """gdi.c MulDiv16: rounded half away from zero (C division truncates toward zero), and
    -32768 for a zero divisor or a result outside -32767..32767."""
    if not d:
        return 0x8000
    if d < 0:
        a, d = -a, -d
    p = a * b
    if (a < 0 and b < 0) or (a >= 0 and b >= 0):
        ret = _cdiv(p + d // 2, d)
    else:
        ret = _cdiv(p - d // 2, d)
    if ret > 32767 or ret < -32767:
        return 0x8000
    return ret & 0xFFFF


def _cdiv(n, d):
    """C integer division: truncates toward zero."""
    q = abs(n) // abs(d)
    return q if (n < 0) == (d < 0) else -q


# ------------------------------------------------------------------ batch 6: mapping, regions, palette

def _map_points(wine, hdc, ptr, count, inverse, name):
    """LPtoDP16 / DPtoLP16: count POINT16s in place. MM_TEXT only: the other modes go through
    Wine's floating transform (GDI_ROUND), which neww does not keep."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    if dc.map_mode != MM_TEXT:
        return 0, 0, f"GDI {name} in map mode {dc.map_mode}: neww maps MM_TEXT only here"
    if count <= 0:
        return 1
    (wx, wy), (vx, vy) = dc.wnd_org, dc.vp_org
    dx, dy = (wx - vx, wy - vy) if inverse else (vx - wx, vy - wy)
    pts = list(struct.unpack(f"<{2 * count}h", read(wine, ptr, 4 * count)))
    out = []
    for i in range(0, len(pts), 2):
        out += [(pts[i] + dx) & 0xFFFF, (pts[i + 1] + dy) & 0xFFFF]
    write(wine, ptr, struct.pack(f"<{2 * count}H", *out))
    return 1


@api("GDI", "LPtoDP")
def lp_to_dp16(wine, arg, hdc, ptr, count):
    """gdi.c LPtoDP16 -> LPtoDP: (x - window origin) + viewport origin in MM_TEXT."""
    return _map_points(wine, hdc, ptr, count, False, "LPtoDP")


@api("GDI", "DPtoLP")
def dp_to_lp16(wine, arg, hdc, ptr, count):
    """gdi.c DPtoLP16 -> DPtoLP: the inverse, (x - viewport origin) + window origin."""
    return _map_points(wine, hdc, ptr, count, True, "DPtoLP")


@api("GDI", "FillRgn")
def fill_rgn(wine, arg, hdc, hrgn, hbrush):
    """nulldrv_FillRgn: select the brush, dibdrv_PaintRgn (each rectangle in logical units,
    to the device, filled with the brush, clipped), select the old brush back."""
    g = gdi(wine)
    dc = _dc(wine, hdc)
    rgn = g.get(hrgn, OBJ_REGION)
    if dc is None or rgn is None or g.get(hbrush, OBJ_BRUSH) is None:
        return 0
    if not _empty(rgn.rect):
        fill(wine, dc, rgn.rect, hbrush)
    return 1


@api("GDI", "RectInRegionOld", "RectInRegion")
def rect_in_region(wine, arg, hrgn, ptr):
    """region.c NtGdiRectInRegion: the rectangle, ordered, overlaps one of the region's."""
    rgn = gdi(wine).get(hrgn, OBJ_REGION)
    if rgn is None:
        return 0
    l, t, r, b = struct.unpack("<hhhh", read(wine, ptr, 8))
    l, r = sorted((l, r))
    t, b = sorted((t, b))
    rl, rt, rr, rb = rgn.rect
    if _empty(rgn.rect):
        return 0
    return 1 if rr > l and rl < r and rb > t and rt < b else 0
