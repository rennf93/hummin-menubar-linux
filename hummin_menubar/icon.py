"""Tray icon: the same hummingbird as the macOS template art, recolored for
the panel at runtime (Linux has no template-image mechanism, so the app picks
a light bird on dark themes and vice versa; see __main__.py).

Falls back to the construction-geometry bird (circles, arcs and wedges, no
freehand curves) if icon/art-64.png is missing — same spirit as the macOS
vector fallback.
"""
import os
import struct
import zlib

_LIGHT = (240, 240, 240)   # for dark panels (COSMIC default)
_DARK = (32, 32, 32)       # for light panels

# Geometric fallback bird, design space 100x75, y-up: head upper left, body
# behind, beak wedge far left, wing crescent up-right, tail wedges lower right.
_CIRCLES = [(36.0, 47.0, 9.5), (53.0, 36.0, 13.5)]
_WEDGES = [((27, 46), (4, 40.5), (27, 42.5)),
           ((58, 27), (86, 7), (63, 21.5)),
           ((62, 23), (89, 14.5), (66, 18))]
_WING = ((50.0, 34.0, 30.0), (47.0, 31.0, 24.0), 32.0, 78.0)  # outer, inner, a0, a1


def render(variant):
    """Returns (width, height, ARGB byte string) for the SNI IconPixmap.

    Per the SNI spec the data is ARGB32 in network byte order, i.e. per pixel:
    A, R, G, B (COSMIC's applet rotates that to RGBA for rendering)."""
    w, h, rgba = _load_art()
    if rgba is None:
        w, h, rgba = _fallback_bird(64)
    rgb = _LIGHT if variant == "light" else _DARK
    argb = bytearray(len(rgba))
    for i in range(0, len(rgba), 4):
        alpha = rgba[i + 3]
        # zero the color under fully transparent pixels so scaled rendering
        # doesn't pick up fringes
        color = rgb[0] if alpha else 0
        argb[i] = alpha          # A
        argb[i + 1] = color      # R
        argb[i + 2] = color      # G
        argb[i + 3] = color      # B
    return w, h, bytes(argb)


def _load_art():
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "icon", "art-64.png")
    try:
        with open(path, "rb") as f:
            w, h, rgba = decode_png(f.read())
        return w, h, rgba
    except (OSError, ValueError):
        return None


# ---- minimal PNG decode (8-bit RGBA, non-interlaced) ----------------------------

def decode_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, header = 8, b"", None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk[:13])
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    if header is None:
        raise ValueError("missing IHDR")
    w, h, depth, color, _comp, _filt, interlace = header
    if depth != 8 or color != 6 or interlace != 0:
        raise ValueError(f"unsupported PNG: depth={depth} color={color}")
    raw = zlib.decompress(idat)
    stride = w * 4
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    src = 0
    for y in range(h):
        filt = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride
        if filt == 1:
            for x in range(4, stride):
                line[x] = (line[x] + line[x - 4]) & 0xFF
        elif filt == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif filt == 3:
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif filt == 4:
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                b = prev[x]
                c = prev[x - 4] if x >= 4 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        elif filt != 0:
            raise ValueError(f"bad filter {filt}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, bytes(out)


# ---- geometric fallback ---------------------------------------------------------

def _in_wedge(a, b, c, x, y):
    d1 = (x - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (y - b[1])
    d2 = (x - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (y - c[1])
    d3 = (x - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (y - a[1])
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _in_wing(x, y):
    (ox, oy, orr), (ix, iy, ir), a0, a1 = _WING
    import math
    if (x - ox) ** 2 + (y - oy) ** 2 > orr ** 2:
        return False
    if (x - ix) ** 2 + (y - iy) ** 2 < ir ** 2:
        return False
    ang = math.degrees(math.atan2(y - oy, x - ox))
    return a0 <= ang <= a1


def _hit(x, y):
    if _in_wing(x, y):
        return True
    for cx, cy, r in _CIRCLES:
        if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
            return True
    return any(_in_wedge(a, b, c, x, y) for a, b, c in _WEDGES)


def _fallback_bird(px_width, ss=3):
    """Rasterize the design space (100x75, y-up) at 3x supersampling."""
    w, h = px_width, round(px_width * 75 / 100)
    rgba = bytearray(w * h * 4)
    scale = 100.0 / w
    for py in range(h):
        for px in range(w):
            count = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) * scale
                    y = 75.0 - (py + (sy + 0.5) / ss) * scale
                    if _hit(x, y):
                        count += 1
            alpha = round(count * 255 / (ss * ss))
            i = (py * w + px) * 4
            rgba[i:i + 4] = bytes((0, 0, 0, alpha))
    return w, h, bytes(rgba)
