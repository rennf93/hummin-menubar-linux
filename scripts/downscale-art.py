#!/usr/bin/env python3
"""Dev-time helper: box-filter downscale the macOS repo's extracted template
art (Sources/HumminMenubar/Resources/menubar-template.png) to the tray-sized
RGBA PNG this repo embeds at icon/art-64.png.

Usage: scripts/downscale-art.py <menubar-template.png> [icon/art-64.png]
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hummin_menubar.icon import decode_png  # noqa: E402

TARGET_WIDTH = 64


def resize_alpha_weighted(rgba, w, h, tw, th):
    """Box-filter downscale; RGB channels are alpha-weighted so transparent
    (black) pixels don't darken edges."""
    out = bytearray(tw * th * 4)
    for ty in range(th):
        y0, y1 = round(ty * h / th), max(round((ty + 1) * h / th), round(ty * h / th) + 1)
        for tx in range(tw):
            x0, x1 = round(tx * w / tw), max(round((tx + 1) * w / tw), round(tx * w / tw) + 1)
            r = g = b = a = n = 0
            for y in range(y0, min(y1, h)):
                for x in range(x0, min(x1, w)):
                    i = (y * w + x) * 4
                    alpha = rgba[i + 3]
                    r += rgba[i] * alpha
                    g += rgba[i + 1] * alpha
                    b += rgba[i + 2] * alpha
                    a += alpha
                    n += 1
            o = (ty * tw + tx) * 4
            out[o + 3] = a // n
            if a:
                out[o] = r // a
                out[o + 1] = g // a
                out[o + 2] = b // a
    return bytes(out)


def encode_png(w, h, rgba):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload +
                struct.pack(">I", zlib.crc32(kind + payload)))
    stride = w * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "icon/art-64.png"
    with open(src, "rb") as f:
        w, h, rgba = decode_png(f.read())
    tw = TARGET_WIDTH
    th = max(1, round(h * tw / w))
    print(f"{w}x{h} -> {tw}x{th}")
    small = resize_alpha_weighted(rgba, w, h, tw, th)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as f:
        f.write(encode_png(tw, th, small))
    print(f"wrote {dst} ({os.path.getsize(dst)} bytes)")


if __name__ == "__main__":
    main()
