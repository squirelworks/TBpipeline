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

from .handlers import api as _handlers_api, signed

# Every GDI handler by its spec name, so metafile playback calls the same code a program would.
BY_NAME = {}


def api(module, *names):
    """handlers.api, also keeping each GDI handler in BY_NAME."""
    register = _handlers_api(module, *names)

    def wrap(fn):
        if module == "GDI":
            for name in names:
                BY_NAME[name] = fn
        return register(fn)
    return wrap

FIRST_GDI_HANDLE = 32
STOCK_LAST = 19
DEFAULT_BITMAP = STOCK_LAST + 1
SCREEN = (1024, 768)

OBJ_PEN, OBJ_BRUSH, OBJ_DC, OBJ_METADC, OBJ_PAL, OBJ_FONT, OBJ_BITMAP, OBJ_REGION, OBJ_MEMDC = 1, 2, 3, 4, 5, 6, 7, 8, 10

BS_SOLID, BS_NULL, BS_HATCHED, BS_PATTERN = 0, 1, 2, 3
PS_SOLID, PS_NULL = 0, 5
TRANSPARENT, OPAQUE = 1, 2
MM_TEXT, MM_LOMETRIC, MM_HIMETRIC, MM_LOENGLISH, MM_HIENGLISH, MM_TWIPS, MM_ISOTROPIC, MM_ANISOTROPIC = range(1, 9)

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

FONT_DIRS = ("/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2",
             "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/freefont")
# Liberation first: its widths match Arial, Times New Roman and Courier New, the faces ToolBook
# books name, so text ToolBook measures to fit a field or a button fits. DejaVu is wider.
TEXT_STANDIN = {
    ("swiss", False): ("LiberationSans-Regular.ttf", "DejaVuSans.ttf"),
    ("swiss", True): ("LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"),
    ("roman", False): ("LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"),
    ("roman", True): ("LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"),
    ("modern", False): ("LiberationMono-Regular.ttf", "DejaVuSansMono.ttf"),
    ("modern", True): ("LiberationMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"),
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
        path = next((str(Path(d) / name) for name in TEXT_STANDIN[(kind, bold)] for d in FONT_DIRS
                     if (Path(d) / name).exists()), None)

        def load(size):
            # None of them (a Windows host): Pillow's own scalable face stands in.
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


def gdi_round(value):
    """Wine 2528aff2 dlls/win32u/ntgdi_private.h:108 GDI_ROUND: floor(val + 0.5)."""
    import math
    return int(math.floor(value + 0.5))


def xform(dc):
    """The window-to-viewport transform as (scale x, scale y, dx, dy): Wine 2528aff2
    dlls/win32u/dc.c:417 construct_window_to_viewport. neww has no world transform, so
    DC_UpdateXforms (dc.c:455) leaves this as xformWorld2Vport."""
    (wx, wy), (vx, vy) = dc.wnd_org, dc.vp_org
    (wex, wey), (vex, vey) = dc.wnd_ext, dc.vp_ext
    sx, sy = vex / wex, vey / wey
    return sx, sy, vx - sx * wx, vy - sy * wy


def scaled(dc):
    """True when a logical unit is not one device pixel (a scaling or mirroring map mode)."""
    sx, sy, _dx, _dy = xform(dc)
    return sx != 1 or sy != 1


def _identity(dc):
    return dc.wnd_ext == dc.vp_ext


def lp_to_dp(dc, x, y):
    """Wine 2528aff2 dlls/win32u/mapping.c:265 lp_to_dp: each point through xformWorld2Vport,
    GDI_ROUND. With equal extents (MM_TEXT) that is x - window org + viewport org."""
    (wx, wy), (vx, vy) = dc.wnd_org, dc.vp_org
    if _identity(dc):
        return x - wx + vx, y - wy + vy
    sx, sy, dx, dy = xform(dc)
    return gdi_round(x * sx + dx), gdi_round(y * sy + dy)


def dp_to_lp(dc, x, y):
    """Wine 2528aff2 dlls/win32u/mapping.c:185 dp_to_lp: the inverse transform (DC_InvertXform),
    GDI_ROUND."""
    (wx, wy), (vx, vy) = dc.wnd_org, dc.vp_org
    if _identity(dc):
        return x - vx + wx, y - vy + wy
    sx, sy, dx, dy = xform(dc)
    # DC_InvertXform (Wine 2528aff2 dlls/win32u/dc.c:395) for a matrix with no shear.
    ix, iy = 1 / sx, 1 / sy
    return gdi_round(x * ix - dx * ix), gdi_round(y * iy - dy * iy)


def pen_device_width(dc, width):
    """Wine 2528aff2 dlls/win32u/dibdrv/objects.c:1762 get_pen_device_width: 0 is 1, else the
    length of (width, 0) mapped to the device, floored, at least 1."""
    import math
    if not width:
        return 1
    x0, y0 = lp_to_dp(dc, 0, 0)
    x1, y1 = lp_to_dp(dc, width, 0)
    return max(int(math.floor(math.hypot(x1 - x0, y1 - y0))), 1)


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


def pen_line(wine, dc, points, device=False):
    """A polyline with the DC's pen, mixed by the DC's ROP2. A null pen draws nothing. With
    device, the points are already device coordinates."""
    pen = gdi(wine).get(dc.pen, OBJ_PEN)
    if pen is None or pen.style == PS_NULL:
        return None
    from PIL import Image, ImageDraw
    img, (ox, oy) = surface(wine, dc)
    box = clip_box(wine, dc)
    pts = [(x + ox, y + oy) for x, y in (p if device else lp_to_dp(dc, *p) for p in points)]
    layer = img.crop(box)
    mixed = dc.rop2 != 13
    if mixed:
        target, layer = layer, Image.new("L", layer.size, 0)
    draw = ImageDraw.Draw(layer)
    shifted = [(x - box[0], y - box[1]) for x, y in pts]
    color = 255 if mixed else rgb(pen.color)
    width = pen_device_width(dc, pen.width)
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


# ------------------------------------------------------------------ handlers: metafiles

@api("GDI", "SetMetaFileBits")
def set_metafile_bits(wine, arg, hmem):
    """Wine 2528aff2: dlls/gdi.exe16/metafile.c:295 SetMetaFileBits16 returns hMem (:299).

    The 16-bit metafile handle is the global block that holds the metafile bytes, so
    the bytes stay where the caller put them and nothing is copied."""
    return hmem


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


def _virtual(dc):
    """get_dc_virtual_size and get_dc_virtual_res (Wine 2528aff2 dlls/win32u/mapping.c:60, :72):
    with no SetVirtualResolution they are GetDeviceCaps HORZSIZE/VERTSIZE (mm) and
    HORZRES/VERTRES (pixels), the screen's caps for every DC neww makes (wine.SCREEN_CAPS)."""
    from .wine import SCREEN_CAPS
    return (SCREEN_CAPS[4], SCREEN_CAPS[6]), (SCREEN_CAPS[8], SCREEN_CAPS[10])


def _muldiv(a, b, c):
    """Wine 2528aff2 dlls/win32u/mapping.c:37 muldiv: rounded half away from zero, -1 for c 0
    or a result outside 32 bits."""
    if not c:
        return -1
    if c < 0:
        a, c = -a, -c
    p = a * b
    ret = _cdiv(p + c // 2, c) if (a < 0) == (b < 0) else _cdiv(p - c // 2, c)
    return -1 if ret > 2147483647 or ret < -2147483647 else ret


def _fix_isotropic(dc):
    """Wine 2528aff2 dlls/win32u/mapping.c:89 MAPPING_FixIsotropic: shrink the larger viewport
    extent so a logical unit is as long across as down."""
    (size_x, size_y), (res_x, res_y) = _virtual(dc)
    (wex, wey), (vex, vey) = dc.wnd_ext, dc.vp_ext
    xdim = abs(vex * size_x / (res_x * wex))
    ydim = abs(vey * size_y / (res_y * wey))
    if xdim > ydim:
        cx = gdi_round(vex * ydim / xdim) or (1 if vex >= 0 else -1)
        dc.vp_ext = (cx, vey)
    else:
        cy = gdi_round(vey * xdim / ydim) or (1 if vey >= 0 else -1)
        dc.vp_ext = (vex, cy)


def _compute_xform(dc):
    """Wine 2528aff2 dlls/win32u/mapping.c:285 NtGdiComputeXformCoefficients: the isotropic fix,
    then DC_UpdateXforms (neww computes the transform from the extents when it maps)."""
    if dc.map_mode == MM_ISOTROPIC:
        _fix_isotropic(dc)
    return True


@api("GDI", "SetMapMode")
def set_map_mode(wine, arg, hdc, mode):
    """SetMapMode16 (Wine 2528aff2 dlls/gdi.exe16/gdi.c:463) -> SetMapMode (dlls/gdi32/dc.c:1021)
    -> set_map_mode (dlls/win32u/mapping.c:113): the old mode, or 0. Choosing the mode a DC
    already has is TRUE without change for MM_ISOTROPIC and MM_ANISOTROPIC; the other modes set
    both extents from the display's size and resolution."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    old = dc.map_mode
    if mode == old and mode in (MM_ISOTROPIC, MM_ANISOTROPIC):
        return old
    (size_x, size_y), (res_x, res_y) = _virtual(dc)
    if mode == MM_TEXT:
        dc.wnd_ext = dc.vp_ext = (1, 1)
    elif mode in (MM_LOMETRIC, MM_ISOTROPIC):
        dc.wnd_ext, dc.vp_ext = (size_x * 10, size_y * 10), (res_x, -res_y)
    elif mode == MM_HIMETRIC:
        dc.wnd_ext, dc.vp_ext = (size_x * 100, size_y * 100), (res_x, -res_y)
    elif mode == MM_LOENGLISH:
        dc.wnd_ext, dc.vp_ext = (_muldiv(1000, size_x, 254), _muldiv(1000, size_y, 254)), (res_x, -res_y)
    elif mode == MM_HIENGLISH:
        dc.wnd_ext, dc.vp_ext = (_muldiv(10000, size_x, 254), _muldiv(10000, size_y, 254)), (res_x, -res_y)
    elif mode == MM_TWIPS:
        dc.wnd_ext, dc.vp_ext = (_muldiv(14400, size_x, 254), _muldiv(14400, size_y, 254)), (res_x, -res_y)
    elif mode != MM_ANISOTROPIC:
        return 0
    dc.map_mode = mode
    return old


def _pack(pair):
    return pair[0] & 0xFFFF | (pair[1] & 0xFFFF) << 16


def _put_pair(wine, ptr, pair):
    """A POINT16 or SIZE16 out parameter, as the 16-bit wrappers copy the 32-bit one down."""
    if ptr:
        write(wine, ptr, struct.pack("<hh", signed(pair[0] & 0xFFFF), signed(pair[1] & 0xFFFF)))


def _set_org(dc, attr, x, y, offset):
    """SetWindowOrgEx / SetViewportOrgEx / OffsetWindowOrgEx / OffsetViewportOrgEx
    (Wine 2528aff2 dlls/gdi32/dc.c:1205, :1280, :1222, :1297): the old origin out, the new one
    set (or added), then NtGdiComputeXformCoefficients. Always TRUE for a DC."""
    old = getattr(dc, attr)
    setattr(dc, attr, (old[0] + x, old[1] + y) if offset else (x, y))
    return _compute_xform(dc), old


def _set_ext(dc, attr, x, y):
    """SetWindowExtEx / SetViewportExtEx (Wine 2528aff2 dlls/gdi32/dc.c:1175, :1250): the old
    extent out; outside MM_ISOTROPIC and MM_ANISOTROPIC nothing changes and the answer is TRUE;
    a zero x or y is FALSE; else the extent is set and NtGdiComputeXformCoefficients runs."""
    old = getattr(dc, attr)
    if dc.map_mode not in (MM_ISOTROPIC, MM_ANISOTROPIC):
        return True, old
    if not x or not y:
        return False, old
    setattr(dc, attr, (x, y))
    return _compute_xform(dc), old


def _scale_ext(dc, attr, x_num, x_denom, y_num, y_denom):
    """NtGdiScaleViewportExtEx / NtGdiScaleWindowExtEx (Wine 2528aff2 dlls/win32u/mapping.c:300,
    :333): the old extent out; in MM_ISOTROPIC and MM_ANISOTROPIC each extent times num / denom
    (C division), 0 made 1, then the isotropic fix. A zero num or denom there is FALSE."""
    old = getattr(dc, attr)
    if dc.map_mode in (MM_ISOTROPIC, MM_ANISOTROPIC):
        if not x_num or not x_denom or not y_num or not y_denom:
            return False, old
        cx = _cdiv(old[0] * x_num, x_denom) or 1
        cy = _cdiv(old[1] * y_num, y_denom) or 1
        setattr(dc, attr, (cx, cy))
        _compute_xform(dc)
    return True, old


def _old_style(change):
    """The Win 3.0 forms (GDI.11 to GDI.18, Wine 2528aff2 dlls/gdi.exe16/gdi.c:535 to :614):
    the Ex call, then MAKELONG of the old point or size, or 0 when it failed."""
    def fn(wine, arg, hdc, *args):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0
        ok, old = change(dc, *args)
        return _pack(old) if ok else 0
    return fn


def _ex_style(change):
    """The Ex forms (GDI.476 to GDI.485, Wine 2528aff2 dlls/gdi.exe16/gdi.c:3155 to :3291):
    BOOL16, the old point or size copied to the out pointer when there is one."""
    def fn(wine, arg, hdc, *args):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0
        *rest, ptr = args
        ok, old = change(dc, *rest)
        _put_pair(wine, ptr, old)
        return 1 if ok else 0
    return fn


_CHANGES = {
    "WindowOrg": lambda dc, x, y: _set_org(dc, "wnd_org", x, y, False),
    "ViewportOrg": lambda dc, x, y: _set_org(dc, "vp_org", x, y, False),
    "OffsetWindowOrg": lambda dc, x, y: _set_org(dc, "wnd_org", x, y, True),
    "OffsetViewportOrg": lambda dc, x, y: _set_org(dc, "vp_org", x, y, True),
    "WindowExt": lambda dc, x, y: _set_ext(dc, "wnd_ext", x, y),
    "ViewportExt": lambda dc, x, y: _set_ext(dc, "vp_ext", x, y),
    "ScaleWindowExt": lambda dc, a, b, c, d: _scale_ext(dc, "wnd_ext", a, b, c, d),
    "ScaleViewportExt": lambda dc, a, b, c, d: _scale_ext(dc, "vp_ext", a, b, c, d),
}

for _key, _change in _CHANGES.items():
    _name = _key if _key.startswith(("Offset", "Scale")) else "Set" + _key
    api("GDI", _name)(_old_style(_change))
    api("GDI", _name + "Ex")(_ex_style(_change))


def _get_pair(attr):
    def fn(wine, arg, hdc):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0
        return _pack(getattr(dc, attr))
    return fn


api("GDI", "GetWindowOrg")(_get_pair("wnd_org"))
api("GDI", "GetViewportOrg")(_get_pair("vp_org"))
api("GDI", "GetWindowExt")(_get_pair("wnd_ext"))
api("GDI", "GetViewportExt")(_get_pair("vp_ext"))
api("GDI", "GetCurrentPosition")(_get_pair("pos"))


def _get_pair_ex(attr):
    """GetViewportExtEx16, GetViewportOrgEx16, GetWindowExtEx16, GetWindowOrgEx16 (Wine 2528aff2
    dlls/gdi.exe16/gdi.c:3103, :3116, :3129, :3142): FALSE for no DC, else the pair written."""
    def fn(wine, arg, hdc, ptr):
        dc = _dc(wine, hdc)
        if dc is None:
            return 0
        _put_pair(wine, ptr, getattr(dc, attr))
        return 1
    return fn


api("GDI", "GetViewportExtEx")(_get_pair_ex("vp_ext"))
api("GDI", "GetViewportOrgEx")(_get_pair_ex("vp_org"))
api("GDI", "GetWindowExtEx")(_get_pair_ex("wnd_ext"))
api("GDI", "GetWindowOrgEx")(_get_pair_ex("wnd_org"))


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
    """GetClipBox: the clip in logical coordinates."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    img, (ox, oy) = surface(wine, dc)
    l, t, r, b = clip_box(wine, dc)
    l, t, r, b = l - ox, t - oy, r - ox, b - oy
    # NtGdiGetAppClipBox (Wine 2528aff2 dlls/win32u/clipping.c:366): dp_to_lp of both corners.
    ll, lt = dp_to_lp(dc, l, t)
    lr, lb = dp_to_lp(dc, r, b)
    write(wine, ptr, struct.pack("<hhhh", ll, lt, lr, lb))
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
        if scaled(dc) or scaled(sdc):
            # BitBlt is NtGdiStretchBlt with the source the destination's logical size
            # (Wine 2528aff2 dlls/win32u/bitblt.c); through a scaling transform the device
            # sizes differ, so it stretches.
            return _stretch(wine, dc, sdc, x, y, w, h, sx, sy, w, h, rop)
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
    """StretchBlt: the source scaled to the destination size (nearest pixel), then BitBlt's rop.
    Both rectangles are mapped to device pixels first, as Wine's get_vis_rectangles does."""
    dc, sdc = _dc(wine, hdst), _dc(wine, hsrc)
    if (w, h) == (sw, sh) and not (dc is not None and scaled(dc)) and not (sdc is not None and scaled(sdc)):
        return bit_blt(wine, arg, hdst, x, y, w, h, hsrc, sx, sy, rop)
    if dc is None or sdc is None or not w or not h or not sw or not sh:
        return 0
    return _stretch(wine, dc, sdc, x, y, w, h, sx, sy, sw, sh, rop)


def _stretch(wine, dc, sdc, x, y, w, h, sx, sy, sw, sh, rop):
    from PIL import Image
    simg, (sox, soy) = surface(wine, sdc)
    sxd, syd = lp_to_dp(sdc, sx, sy)
    sxe, sye = lp_to_dp(sdc, sx + sw, sy + sh)
    sw, sh = sxe - sxd, sye - syd
    x0, y0 = lp_to_dp(dc, x, y)
    x1, y1 = lp_to_dp(dc, x + w, y + h)
    w, h = x1 - x0, y1 - y0
    if not w or not h or not sw or not sh:
        return 1
    crop = simg.crop((sxd + sox, syd + soy, sxd + sox + abs(sw), syd + soy + abs(sh)))
    if sw < 0:
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if sh < 0:
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
    if (w < 0) != (sw < 0) and w < 0:
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if (h < 0) != (sh < 0) and h < 0:
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
    scaled_img = crop.resize((abs(w), abs(h)), Image.NEAREST)
    color = brush_color(wine, dc, dc.brush)
    blit(wine, dc, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), rop,
         src=(scaled_img, dc_is_mono(wine, sdc)), src_xy=(0, 0), pattern=color or (0, 0, 0))
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
    if scaled(dc):
        return _device_rectangle(wine, dc, pen, device_rect(dc, l, t, r, b))
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


def _device_rectangle(wine, dc, pen, rect):
    """Rectangle in a scaling map mode: dibdrv_Rectangle (Wine 2528aff2
    dlls/win32u/dibdrv/graphics.c) works on the device rectangle, lp_to_dp'd and ordered, with
    the pen's device width; the same edges as in MM_TEXT, in device pixels."""
    l, t, r, b = rect
    inset = 0 if pen is None or pen.style == PS_NULL else pen_device_width(dc, pen.width)
    color = brush_color(wine, dc, dc.brush)
    if color is not None:
        fill = (l + inset, t + inset, r - inset, b - inset) if inset else (l, t, r - 1, b - 1)
        blit(wine, dc, fill, rop2_rop3(dc.rop2), pattern=color)
    if inset:
        why = pen_line(wine, dc, [(l, t), (r - 1, t), (r - 1, b - 1), (l, b - 1), (l, t - 1)], device=True)
        if why:
            return 0, 0, f"GDI Rectangle: {why}"
    return 1


# ------------------------------------------------------------------ shapes

def paint_shape(wine, dc, paint):
    """Ellipse, Polygon, Arc and the rest: paint(draw, to, what, width) draws "fill" (the
    interior, with the brush) and then "line" (the outline, with the pen) on 1-bit masks in
    device pixels. Each mask is mixed into the surface by the DC's ROP2. A null brush or pen
    leaves its part out."""
    from PIL import Image, ImageDraw
    np = _np()
    img, (ox, oy) = surface(wine, dc)
    box = clip_box(wine, dc)
    if _empty(box):
        return
    pen = gdi(wine).get(dc.pen, OBJ_PEN)
    pen_rgb = None if pen is None or pen.style == PS_NULL else rgb(pen.color)
    width = 1 if pen is None else pen_device_width(dc, pen.width)

    def to(x, y):
        dx, dy = lp_to_dp(dc, x, y)
        return (dx + ox - box[0], dy + oy - box[1])

    size = (box[2] - box[0], box[3] - box[1])
    dest = np.asarray(img.crop(box).convert("RGB")).copy()
    for what, color in (("fill", brush_color(wine, dc, dc.brush)), ("line", pen_rgb)):
        if color is None:
            continue
        mask = Image.new("1", size, 0)
        paint(ImageDraw.Draw(mask), to, what, width)
        sel = np.asarray(mask, dtype=bool)
        if sel.any():
            dest[sel] = rop2_mix(dc.rop2, color, dest[sel])
    img.paste(Image.fromarray(dest, "RGB").convert(img.mode), box[:2])


def _box(to, l, t, r, b):
    (x0, y0), (x1, y1) = to(min(l, r), min(t, b)), to(max(l, r), max(t, b))
    return [x0, y0, x1 - 1, y1 - 1]


def _angle(l, t, r, b, x, y):
    """The angle PIL draws from (clockwise degrees from 3 o'clock) of the ray to (x, y)."""
    import math
    return math.degrees(math.atan2(y - (t + b) / 2, x - (l + r) / 2))


def _points(wine, ptr, count):
    raw = read(wine, ptr, 4 * max(count, 0))
    return [struct.unpack_from("<hh", raw, 4 * i) for i in range(count)]


@api("GDI", "Ellipse")
def ellipse(wine, arg, hdc, l, t, r, b):
    """Ellipse: inside the box, right and bottom edges excluded.

    Wine 2528aff2: dlls/gdi.exe16/gdi.c:682 Ellipse16 returns Ellipse(); dlls/win32u/painting.c:376
    NtGdiEllipse answers FALSE for no DC, else dibdrv_Ellipse (dlls/win32u/dibdrv/graphics.c:995),
    which is dibdrv_RoundRect (:997) and answers TRUE."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0

    def paint(draw, to, what, width):
        xy = _box(to, l, t, r, b)
        if xy[2] < xy[0] or xy[3] < xy[1]:
            return
        if what == "fill":
            draw.ellipse(xy, fill=1)
        else:
            draw.ellipse(xy, outline=1, width=width)
    paint_shape(wine, dc, paint)
    return 1


@api("GDI", "RoundRect")
def round_rect(wine, arg, hdc, l, t, r, b, ew, eh):
    """Wine 2528aff2: dlls/gdi.exe16/gdi.c:722 RoundRect16; dlls/win32u/painting.c:413 FALSE for no
    DC; dlls/win32u/dibdrv/graphics.c:1447 dibdrv_RoundRect TRUE (also for an empty box, :1458)."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0

    def paint(draw, to, what, width):
        xy = _box(to, l, t, r, b)
        if xy[2] < xy[0] or xy[3] < xy[1]:
            return
        radius = max(0, min(abs(ew), abs(eh)) // 2)
        if what == "fill":
            draw.rounded_rectangle(xy, radius, fill=1)
        else:
            draw.rounded_rectangle(xy, radius, outline=1, width=width)
    paint_shape(wine, dc, paint)
    return 1


def _arc_shape(wine, hdc, l, t, r, b, xs, ys, xe, ye, kind):
    """Arc, Pie and Chord go counterclockwise from the start ray to the end ray. PIL goes
    clockwise, so it draws from the end ray to the start ray.

    Wine 2528aff2: dlls/gdi.exe16/gdi.c:672 Arc16, :702 Pie16, :2427 Chord16; each goes to
    NtGdiArcInternal, dlls/win32u/painting.c:313 FALSE for no DC; dlls/win32u/dibdrv/graphics.c:314
    draw_arc answers TRUE (also for an empty box, :325)."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    start, end = _angle(l, t, r, b, xe, ye), _angle(l, t, r, b, xs, ys)
    if end <= start:
        end += 360

    def paint(draw, to, what, width):
        xy = _box(to, l, t, r, b)
        if xy[2] < xy[0] or xy[3] < xy[1]:
            return
        if kind == "arc":
            if what == "line":
                draw.arc(xy, start, end, fill=1, width=width)
        elif what == "fill":
            getattr(draw, kind)(xy, start, end, fill=1)
        else:
            getattr(draw, kind)(xy, start, end, outline=1, width=width)
    paint_shape(wine, dc, paint)
    return 1


@api("GDI", "Arc")
def arc(wine, arg, hdc, l, t, r, b, xs, ys, xe, ye):
    return _arc_shape(wine, hdc, l, t, r, b, xs, ys, xe, ye, "arc")


@api("GDI", "Pie")
def pie(wine, arg, hdc, l, t, r, b, xs, ys, xe, ye):
    return _arc_shape(wine, hdc, l, t, r, b, xs, ys, xe, ye, "pieslice")


@api("GDI", "Chord")
def chord(wine, arg, hdc, l, t, r, b, xs, ys, xe, ye):
    return _arc_shape(wine, hdc, l, t, r, b, xs, ys, xe, ye, "chord")


@api("GDI", "Polygon")
def polygon(wine, arg, hdc, ptr, count):
    """Polygon: closed, filled with the brush, outlined with the pen. Fewer than two points
    draw nothing and answer FALSE.

    Wine 2528aff2: dlls/gdi.exe16/gdi.c:811 Polygon16 returns Polygon(); dlls/win32u/painting.c:573
    FALSE for no DC; dlls/win32u/dibdrv/graphics.c:1260 FALSE for fewer than 2 points, else TRUE."""
    dc = _dc(wine, hdc)
    if dc is None or count < 2:
        return 0
    pts = _points(wine, ptr, count)

    def paint(draw, to, what, width):
        xy = [to(*p) for p in pts]
        if what == "fill":
            draw.polygon(xy, fill=1)
        else:
            draw.line(xy + xy[:1], fill=1, width=width)
    paint_shape(wine, dc, paint)
    return 1


@api("GDI", "Polyline")
def polyline(wine, arg, hdc, ptr, count):
    """Polyline: the pen only, as LineTo from each point to the next.

    Wine 2528aff2: dlls/gdi.exe16/gdi.c:832 Polyline16; dlls/win32u/painting.c:573 FALSE for no DC;
    dlls/win32u/dibdrv/graphics.c:1331 FALSE for fewer than 2 points, else TRUE."""
    dc = _dc(wine, hdc)
    if dc is None or count < 2:
        return 0
    why = pen_line(wine, dc, _points(wine, ptr, count))
    if why:
        return 0, 0, f"GDI Polyline: {why}"
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


def scaled_text(dc, name, text):
    """A stop for text drawn through a scaling transform. Wine scales the font's height to the
    device when it is selected (Wine 2528aff2 dlls/win32u/font.c INTERNAL_YWSTODS) and lays the
    text out in device units; neww's text layout is in MM_TEXT units only."""
    if scaled(dc) and text:
        return 0, 0, f"GDI {name} {text!r} in map mode {dc.map_mode} with a scaling transform: neww lays text out in MM_TEXT units only"
    return None


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
    stop = scaled_text(dc, "TextOut", text)
    if stop:
        return stop
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
    stop = scaled_text(dc, "ExtTextOut", text)
    if stop:
        return stop
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
    # The destination in device pixels (nulldrv_StretchDIBits maps both corners with lp_to_dp).
    x0, y0 = lp_to_dp(dc, x, y)
    x1, y1 = lp_to_dp(dc, x + w, y + h)
    dw, dh = x1 - x0, y1 - y0
    if not dw or not dh:
        return height if rop == 0xCC0020 else bi_height
    if (sw < 0) != (dw < 0):
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    if (sh < 0) != (dh < 0):
        crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
    if crop.size != (abs(dw), abs(dh)):
        crop = crop.resize((abs(dw), abs(dh)), Image.NEAREST)
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
    """LPtoDP16 / DPtoLP16 (Wine 2528aff2 dlls/gdi.exe16/gdi.c:3693, :3662): count POINT16s in
    place through NtGdiTransformPoints (dlls/win32u/mapping.c:208), each coordinate GDI_ROUNDed
    and cut to 16 bits as the wrapper copies it back."""
    dc = _dc(wine, hdc)
    if dc is None:
        return 0
    if count <= 0:
        return 1
    fn = dp_to_lp if inverse else lp_to_dp
    pts = list(struct.unpack(f"<{2 * count}h", read(wine, ptr, 4 * count)))
    out = []
    for i in range(0, len(pts), 2):
        x, y = fn(dc, pts[i], pts[i + 1])
        out += [x & 0xFFFF, y & 0xFFFF]
    write(wine, ptr, struct.pack(f"<{2 * count}H", *out))
    return 1


@api("GDI", "LPtoDP")
def lp_to_dp16(wine, arg, hdc, ptr, count):
    """gdi.c LPtoDP16 -> LPtoDP: logical to device through the DC's transform."""
    return _map_points(wine, hdc, ptr, count, False, "LPtoDP")


@api("GDI", "DPtoLP")
def dp_to_lp16(wine, arg, hdc, ptr, count):
    """gdi.c DPtoLP16 -> DPtoLP: the inverse transform."""
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


# ------------------------------------------------------------------ metafile playback

META_EOF = 0x0000
GMEM_MOVEABLE_ZEROINIT = 0x0042
DIB_RGB_COLORS = 0

# The records Wine 2528aff2 dlls/gdi32/metafile.c:1000-1012 lists with META_UNIMP: a FIXME, then
# TRUE, nothing drawn.
META_UNIMP = {0x062F: "META_DRAWTEXT", 0x0436: "META_ANIMATEPALETTE", 0x0037: "META_SETPALENTRIES",
              0x0139: "META_RESIZEPALETTE", 0x014C: "META_RESETDC", 0x014D: "META_STARTDOC",
              0x004F: "META_STARTPAGE", 0x0050: "META_ENDPAGE", 0x0052: "META_ABORTDOC",
              0x005E: "META_ENDDOC", 0x00F8: "META_CREATEBRUSH", 0x02FD: "META_CREATEBITMAPINDIRECT",
              0x06FE: "META_CREATEBITMAP"}


def huge_ptr(sel, offset):
    """A SEGPTR to byte offset of a block that starts at sel:0. Past 64K the selector steps by
    __AHINCR (8), as EnumMetaFile16 builds seg + (HIWORD(offset) << __AHSHIFT)
    (Wine 2528aff2 dlls/gdi.exe16/metafile.c:225)."""
    return ((sel + (offset >> 16) * 8) & 0xFFFF) << 16 | (offset & 0xFFFF)


def ptr_add(ptr, n):
    """ptr + n bytes, carrying into the next tile of a huge block."""
    return huge_ptr(ptr >> 16, (ptr & 0xFFFF) + n)


def _kernel(wine, ordinal, *words):
    """A KERNEL handler called from GDI code, as Wine's gdi.exe16 calls GlobalAlloc16 and friends."""
    from .kernel32 import call16
    return call16(wine, "KERNEL", ordinal, *words)


def metafile_header(wine, hmf):
    """MF_GetMetaHeader16 (Wine 2528aff2 dlls/gdi.exe16/metafile.c:46) is GlobalLock16(hmf): the
    block's selector and its METAHEADER (type, header words, version, size in words, objects,
    max record, params), or None when hmf is no block."""
    sel = wine.selector_of(hmf) if hmf else None
    if sel is None:
        return None
    mh = struct.unpack("<HHHIHIH", read(wine, sel << 16, 18))
    return sel, mh


def bitmap_info_size(wine, info_ptr, usage):
    """Wine 2528aff2 dlls/gdi32/metafile.c:113 bitmap_info_size: header, BI_BITFIELDS masks and the
    color table (RGBQUAD or RGBTRIPLE for DIB_RGB_COLORS, WORD indices otherwise)."""
    size = struct.unpack("<I", read(wine, info_ptr, 4))[0]
    if size == 12:
        bpp = struct.unpack("<H", read(wine, info_ptr + 10, 2))[0]
        colors = 1 << bpp if bpp <= 8 else 0
        return 12 + colors * (3 if usage == DIB_RGB_COLORS else 2)
    bpp, comp = struct.unpack("<HI", read(wine, info_ptr + 14, 6))
    used = struct.unpack("<I", read(wine, info_ptr + 32, 4))[0]
    colors = min(used, 256) if used else (0 if bpp > 8 else 1 << bpp)
    masks = 3 if comp == 3 else 0
    return max(size, 40 + 4 * masks) + colors * (4 if usage == DIB_RGB_COLORS else 2)


class GuestHandleTable:
    """A HANDLETABLE16 in guest memory: one WORD per metafile object."""

    def __init__(self, wine, ptr, count):
        self.wine, self.ptr, self.count = wine, ptr, count

    def get(self, i):
        if not 0 <= i < self.count:
            return 0
        return struct.unpack("<H", read(self.wine, ptr_add(self.ptr, 2 * i), 2))[0]

    def set(self, i, handle):
        if 0 <= i < self.count:
            write(self.wine, ptr_add(self.ptr, 2 * i), struct.pack("<H", handle & 0xFFFF))

    def handles(self):
        return [self.get(i) for i in range(self.count)]


class HostHandleTable(GuestHandleTable):
    """PlayMetaFile's own table (Wine 2528aff2 dlls/gdi32/metafile.c:398 HeapAlloc), not in the guest."""

    def __init__(self, count):
        self.slots = [0] * count
        self.count = count

    def get(self, i):
        return self.slots[i] if 0 <= i < self.count else 0

    def set(self, i, handle):
        if 0 <= i < self.count:
            self.slots[i] = handle & 0xFFFF


def _add_handle(table, handle):
    """MF_AddHandle (Wine 2528aff2 dlls/gdi32/metafile.c:79): the first empty slot, or none."""
    for i in range(table.count):
        if table.get(i) == 0:
            table.set(i, handle)
            return i
    return -1


def _gdi_call(wine, arg, name, record, *args):
    """One GDI call made by a record, through neww's own handler. (value, stop)."""
    from .handlers import answer_of
    fn = BY_NAME.get(name)
    if fn is None:
        return 0, f"GDI PlayMetaFileRecord: {record} calls {name}, which neww does not answer"
    ax, dx, stop = answer_of(fn(wine, arg, *args))
    return ax | dx << 16, stop


def play_record(wine, arg, hdc, table, mr):
    """Wine 2528aff2 dlls/gdi32/metafile.c:528 PlayMetaFileRecord for the record at SEGPTR mr:
    each record is the GDI call it names, with its parameters in reverse order (rdParm[0] is the
    last argument). Returns None, or a stop string. A record Wine has no case for answers FALSE
    (:1014); one Wine lists as unimplemented is skipped (:1000)."""
    size, function = struct.unpack("<IH", read(wine, mr, 6))
    nparm = max(size - 3, 0)
    raw = _read_huge(wine, ptr_add(mr, 6), 2 * nparm) if nparm else b""
    u = list(struct.unpack(f"<{nparm}H", raw))
    p = [signed(w) for w in u]
    parm = ptr_add(mr, 6)
    at = lambda words: ptr_add(parm, 2 * words)
    dword = lambda lo: u[lo] | u[lo + 1] << 16
    name = f"record {function:#06x}"

    def call(fn, *args):
        _value, stop = _gdi_call(wine, arg, fn, name, *args)
        return stop

    def create(fn, *args):
        value, stop = _gdi_call(wine, arg, fn, name, *args)
        if not stop:
            _add_handle(table, value & 0xFFFF)
        return stop

    def need(n):
        if nparm < n:
            return f"GDI PlayMetaFileRecord: {name} has {nparm} parameter words, fewer than {n}"
        return None

    simple = {
        0x0201: ("SetBkColor", 2, lambda: (dword(0),)),
        0x0102: ("SetBkMode", 1, lambda: (u[0],)),
        0x0103: ("SetMapMode", 1, lambda: (u[0],)),
        0x0104: ("SetROP2", 1, lambda: (u[0],)),
        0x0105: ("SetRelAbs", 1, lambda: (u[0],)),
        0x0106: ("SetPolyFillMode", 1, lambda: (u[0],)),
        0x0107: ("SetStretchBltMode", 1, lambda: (u[0],)),
        0x0209: ("SetTextColor", 2, lambda: (dword(0),)),
        0x020B: ("SetWindowOrgEx", 2, lambda: (p[1], p[0], 0)),
        0x020C: ("SetWindowExtEx", 2, lambda: (p[1], p[0], 0)),
        0x020D: ("SetViewportOrgEx", 2, lambda: (p[1], p[0], 0)),
        0x020E: ("SetViewportExtEx", 2, lambda: (p[1], p[0], 0)),
        0x020F: ("OffsetWindowOrgEx", 2, lambda: (p[1], p[0], 0)),
        0x0410: ("ScaleWindowExtEx", 4, lambda: (p[3], p[2], p[1], p[0], 0)),
        0x0211: ("OffsetViewportOrgEx", 2, lambda: (p[1], p[0], 0)),
        0x0412: ("ScaleViewportExtEx", 4, lambda: (p[3], p[2], p[1], p[0], 0)),
        0x0213: ("LineTo", 2, lambda: (p[1], p[0])),
        0x0214: ("MoveToEx", 2, lambda: (p[1], p[0], 0)),
        0x0415: ("ExcludeClipRect", 4, lambda: (p[3], p[2], p[1], p[0])),
        0x0416: ("IntersectClipRect", 4, lambda: (p[3], p[2], p[1], p[0])),
        0x0817: ("Arc", 8, lambda: tuple(p[7::-1])),
        0x0418: ("Ellipse", 4, lambda: (p[3], p[2], p[1], p[0])),
        0x0419: ("FloodFill", 4, lambda: (p[3], p[2], dword(0))),
        0x081A: ("Pie", 8, lambda: tuple(p[7::-1])),
        0x041B: ("Rectangle", 4, lambda: (p[3], p[2], p[1], p[0])),
        0x061C: ("RoundRect", 6, lambda: tuple(p[5::-1])),
        0x061D: ("PatBlt", 6, lambda: (p[5], p[4], p[3], p[2], dword(0))),
        0x001E: ("SaveDC", 0, lambda: ()),
        0x041F: ("SetPixel", 4, lambda: (p[3], p[2], dword(0))),
        0x0220: ("OffsetClipRgn", 2, lambda: (p[1], p[0])),
        0x0324: ("Polygon", 1, lambda: (at(1), u[0])),
        0x0325: ("Polyline", 1, lambda: (at(1), u[0])),
        0x0127: ("RestoreDC", 1, lambda: (p[0],)),
        0x0830: ("Chord", 8, lambda: tuple(p[7::-1])),
        0x012E: ("SetTextAlign", 1, lambda: (u[0],)),
        0x0231: ("SetMapperFlags", 2, lambda: (dword(0),)),
        0x0108: ("SetTextCharacterExtra", 1, lambda: (p[0],)),
        0x020A: ("SetTextJustification", 2, lambda: (p[1], p[0])),
        0x0548: ("ExtFloodFill", 5, lambda: (p[4], p[3], u[1] | u[2] << 16, u[0])),
    }
    if function == META_EOF:
        return None
    if function in simple:
        fn, n, args = simple[function]
        return need(n) or call(fn, hdc, *args())
    if function in META_UNIMP:
        wine.trace.append(f"  PlayMetaFileRecord: {META_UNIMP[function]} not implemented (Wine FIXME)")
        return None
    if function == 0x01F0:  # META_DELETEOBJECT
        stop = need(1) or call("DeleteObject", table.get(u[0]))
        table.set(u[0], 0)
        return stop
    if function == 0x012D:  # META_SELECTOBJECT
        return need(1) or call("SelectObject", hdc, table.get(u[0]))
    if function == 0x0521:  # META_TEXTOUT
        if need(1):
            return need(1)
        s1 = p[0]
        k = (s1 + 1) >> 1
        return need(k + 3) or call("TextOut", hdc, p[k + 2], p[k + 1], at(1), s1)
    if function == 0x02FA:  # META_CREATEPENINDIRECT: rdParm is a LOGPEN16
        return need(5) or create("CreatePenIndirect", parm)
    if function == 0x02FB:  # META_CREATEFONTINDIRECT: rdParm is a LOGFONT16
        return need(9) or create("CreateFontIndirect", parm)
    if function == 0x02FC:  # META_CREATEBRUSHINDIRECT: rdParm is a LOGBRUSH16
        return need(4) or create("CreateBrushIndirect", parm)
    if function == 0x00F7:  # META_CREATEPALETTE: rdParm is a LOGPALETTE
        return need(2) or create("CreatePalette", parm)
    if function == 0x0F43:  # META_STRETCHDIB
        if need(11 + 20):
            return need(11 + 20)
        info = at(11)
        bits = ptr_add(info, bitmap_info_size(wine, info, u[2]))
        return call("StretchDIBits", hdc, p[10], p[9], p[8], p[7], p[6], p[5], p[4], p[3],
                    bits, info, u[2], dword(0))
    if function == 0x0B41:  # META_DIBSTRETCHBLT
        if need(10 + 20):
            return need(10 + 20)
        info = at(10)
        bits = ptr_add(info, bitmap_info_size(wine, info, DIB_RGB_COLORS))
        return call("StretchDIBits", hdc, p[9], p[8], p[7], p[6], p[5], p[4], p[3], p[2],
                    bits, info, DIB_RGB_COLORS, dword(0))
    if function == 0x0940:  # META_DIBBITBLT, with a DIB or as a PatBlt
        if size > 12:
            if need(8 + 20):
                return need(8 + 20)
            info = at(8)
            bits = ptr_add(info, bitmap_info_size(wine, info, u[0]))
            return call("StretchDIBits", hdc, p[7], p[6], p[5], p[4], p[3], p[2], p[5], p[4],
                        bits, info, DIB_RGB_COLORS, dword(0))
        return need(9) or call("PatBlt", hdc, p[8], p[7], p[6], p[5], dword(0))
    if function == 0x0D33:  # META_SETDIBTODEV
        if need(9 + 20):
            return need(9 + 20)
        info = at(9)
        bits = ptr_add(info, bitmap_info_size(wine, info, u[0]))
        return call("SetDIBitsToDevice", hdc, p[8], p[7], p[6], p[5], p[4], p[3], u[2], u[1],
                    bits, info, u[0])
    if function == 0x012C:  # META_SELECTCLIPREGION
        return need(1) or call("SelectClipRgn", hdc, table.get(u[0]) if u[0] else 0)
    if function == 0x0228:  # META_FILLREGION
        return need(2) or call("FillRgn", hdc, table.get(u[1]), table.get(u[0]))
    if function == 0x0234:  # META_SELECTPALETTE
        return need(2) or call("SelectPalette", hdc, table.get(u[1]), u[0])
    if function == 0x0035:  # META_REALIZEPALETTE
        return call("RealizePalette", hdc)
    names = {0x0538: "META_POLYPOLYGON", 0x01F9: "META_CREATEPATTERNBRUSH", 0x0626: "META_ESCAPE",
             0x0A32: "META_EXTTEXTOUT", 0x0B23: "META_STRETCHBLT", 0x0922: "META_BITBLT",
             0x06FF: "META_CREATEREGION", 0x0429: "META_FRAMEREGION", 0x012A: "META_INVERTREGION",
             0x012B: "META_PAINTREGION", 0x0142: "META_DIBCREATEPATTERNBRUSH"}
    if function in names:
        return f"GDI PlayMetaFileRecord: {names[function]} ({function:#06x}) is not played by neww yet"
    return f"GDI PlayMetaFileRecord: record {function:#06x} is not one Wine plays (it answers FALSE)"


@api("GDI", "PlayMetaFileRecord")
def play_metafile_record16(wine, arg, hdc, ht, mr, handles):
    """Wine 2528aff2 dlls/gdi.exe16/gdi.c:2072 PlayMetaFileRecord16: void. The 16-bit handle
    table is copied to a 32-bit one, the record played, and the handles copied back; neww plays
    straight on the guest's table."""
    stop = play_record(wine, arg, hdc, GuestHandleTable(wine, ht, handles), mr)
    if stop:
        return 0, 0, stop
    return 0


@api("GDI", "GetMetaFileBits")
def get_metafile_bits16(wine, arg, hmf):
    """Wine 2528aff2 dlls/gdi.exe16/metafile.c:275 GetMetaFileBits16: the handle is the memory."""
    return hmf


@api("GDI", "DeleteMetaFile")
def delete_metafile16(wine, arg, hmf):
    """Wine 2528aff2 dlls/gdi.exe16/metafile.c:115 DeleteMetaFile16: !GlobalFree16(hmf)."""
    out = _kernel(wine, 17, hmf)
    if isinstance(out, str):
        return 0, 0, out
    return 0 if out[0] else 1


@api("GDI", "IsValidMetaFile")
def is_valid_metafile16(wine, arg, hmf):
    """Wine 2528aff2 dlls/gdi.exe16/metafile.c:153 IsValidMetaFile16: type 1 or 2, a header of 9
    words, version 0x300."""
    got = metafile_header(wine, hmf)
    if got is None:
        return 0
    mt_type, header, version = got[1][:3]
    return 1 if mt_type in (1, 2) and header == 9 and version == 0x300 else 0


@api("GDI", "PlayMetaFile")
def play_metafile16(wine, arg, hdc, hmf):
    """PlayMetaFile16 (Wine 2528aff2 dlls/gdi.exe16/metafile.c:172) -> PlayMetaFile
    (dlls/gdi32/metafile.c:361): keep the pen, brush, palette and clip; play each record up to
    META_EOF or one under 3 words; put them back; delete what the metafile left in its table."""
    got = metafile_header(wine, hmf)
    dc = _dc(wine, hdc)
    if got is None:
        return 0
    sel, (_t, header, _v, size, objects, _m, _p) = got
    if dc is None:
        # Not a DC: every call the records make fails, and PlayMetaFile still answers TRUE.
        return 0, 0, f"GDI PlayMetaFile({hdc:#x}): not a DC neww made"
    pen, brush, palette, clip = dc.pen, dc.brush, dc.palette, dc.user_clip
    table = HostHandleTable(objects)
    offset = header * 2
    while offset < size * 2:
        mr = huge_ptr(sel, offset)
        rd_size, function = struct.unpack("<IH", read(wine, mr, 6))
        if rd_size < 3:
            break
        offset += rd_size * 2
        if function == META_EOF:
            break
        stop = play_record(wine, arg, hdc, table, mr)
        if stop:
            return 0, 0, stop
    for name, handle in (("SelectObject", pen), ("SelectObject", brush)):
        _gdi_call(wine, arg, name, "PlayMetaFile", hdc, handle)
    dc.palette = palette
    dc.user_clip = clip
    for handle in table.slots:
        if handle:
            _gdi_call(wine, arg, "DeleteObject", "PlayMetaFile", handle)
    return 1


@api("GDI", "EnumMetaFile")
def enum_metafile16(wine, arg, hdc, hmf, proc, data):
    """Wine 2528aff2 dlls/gdi.exe16/metafile.c:185 EnumMetaFile16. The pen, brush and font are
    kept; a zeroed moveable HANDLETABLE16 of mtNoObjects words is allocated and locked; the
    callback is called Pascal (hdc, table, record, objects, data) for every record, META_EOF
    included, while offset < mtSize * 2, and a 0 in AX ends the walk with FALSE. Then the pen,
    brush and font go back, every handle left in the table is deleted and the table freed."""
    from .guest import Call
    got = metafile_header(wine, hmf)
    if got is None:
        return 0
    sel, (_t, header, _v, size, objects, _m, _p) = got
    dc = _dc(wine, hdc)
    pen, brush, font = (dc.pen, dc.brush, dc.font) if dc is not None else (0, 0, 0)
    if objects:
        out = _kernel(wine, 15, GMEM_MOVEABLE_ZEROINIT, 0, (2 * objects) & 0xFFFF)
        if isinstance(out, str):
            return 0, 0, out
        hht = out[0]
        out = _kernel(wine, 18, hht)
        if isinstance(out, str):
            return 0, 0, out
        spht = out[1] << 16 | out[0]
    else:
        # With no objects the table is 0 bytes: GLOBAL_Alloc makes a discarded block
        # (Wine 2528aff2 dlls/krnl386.exe16/global.c:205) and K32WOWGlobalLock16 of a block with
        # no base is selector 0 (global.c:466), so the callback gets a NULL table.
        hht, spht = 0, 0
    table = GuestHandleTable(wine, spht, objects)
    result = 1
    offset = header * 2
    while offset < size * 2:
        mr = huge_ptr(sel, offset)
        rd_size = struct.unpack("<I", read(wine, mr, 4))[0]
        ax, _dx = yield Call(proc >> 16, proc & 0xFFFF, regs={"ds": wine.ss, "es": wine.ss},
                             words=[hdc, spht >> 16, spht & 0xFFFF, mr >> 16, mr & 0xFFFF,
                                    objects, (data >> 16) & 0xFFFF, data & 0xFFFF])
        if not ax & 0xFFFF:
            result = 0
            break
        if rd_size == 0:
            # Wine would add 0 and call the callback for this record for ever.
            return 0, 0, f"GDI EnumMetaFile({hmf:#x}): a record of size 0 at offset {offset}"
        offset += rd_size * 2
    if dc is not None:
        for handle in (brush, pen, font):
            _gdi_call(wine, arg, "SelectObject", "EnumMetaFile", hdc, handle)
    for handle in table.handles():
        if handle:
            _gdi_call(wine, arg, "DeleteObject", "EnumMetaFile", handle)
    if hht:
        out = _kernel(wine, 17, hht)
        if isinstance(out, str):
            return 0, 0, out
    return result
