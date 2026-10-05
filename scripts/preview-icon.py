#!/usr/bin/env python3
"""Dev-time helper, the counterpart of the macOS repo's preview-main.swift:
renders the tray icon variants (art light/dark + the geometric fallback) to
docs/ so the bird can be eyeballed without launching the app."""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hummin_menubar import icon  # noqa: E402


def encode_png(w, h, rgba):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload +
                struct.pack(">I", zlib.crc32(kind + payload)))
    stride = w * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def flatten(w, h, argb, bg=(120, 120, 120)):
    """Composite the ARGB pixmap over a panel-grey background."""
    out = bytearray(w * h * 4)
    for i in range(0, len(argb), 4):
        a = argb[i + 3] / 255.0
        for c in range(3):
            out[i + c] = round(argb[2 - c] * a + bg[c] * (1 - a))
        out[i + 3] = 255
    return bytes(out)


def main():
    os.makedirs("docs", exist_ok=True)
    # The art PNG is black-on-transparent; recolor like the app does.
    art_w, art_h, art_rgba = 0, 0, None
    path = os.path.join("icon", "art-64.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            art_w, art_h, art_rgba = icon.decode_png(f.read())
    panels = {"dark": (56, 56, 56), "light": (235, 235, 235)}
    for theme, bg in panels.items():
        if art_rgba is not None:
            rgb = icon._LIGHT if theme == "dark" else icon._DARK
            argb = bytearray(len(art_rgba))
            for i in range(0, len(art_rgba), 4):
                argb[i] = rgb[2]
                argb[i + 1] = rgb[1]
                argb[i + 2] = rgb[0]
                argb[i + 3] = art_rgba[i + 3]
        else:
            _, _, argb = icon.render(theme)  # fallback bird
        name = f"docs/bird-{theme}.png"
        with open(name, "wb") as f:
            f.write(encode_png(art_w, art_h, flatten(art_w, art_h, bytes(argb), bg)))
        print("wrote", name)


if __name__ == "__main__":
    main()
