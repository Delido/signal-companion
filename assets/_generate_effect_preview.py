"""Generate the SignalRGB library thumbnail for the CS2 effect.

SignalRGB shows a per-effect preview image: a .png with the SAME base name as
the .html, sitting next to it in the Effects folder. Without it the library
shows a broken-image placeholder. We render a representative 320x200 preview
(the effect's HP gradient green -> red, with a low-HP red glow) and write it to
the effect package so it's bundled and installed alongside the html.

Pure Pillow; run to regenerate:

    python assets/_generate_effect_preview.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 320, 200


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main():
    img = Image.new("RGB", (W, H), (0, 0, 0))
    px = img.load()

    full = (30, 200, 60)     # high HP  (green)
    mid = (220, 170, 30)     # mid HP   (amber)
    low = (220, 30, 30)      # low HP   (red)

    for x in range(W):
        t = x / (W - 1)
        col = _lerp(full, mid, t * 2) if t < 0.5 else _lerp(mid, low, (t - 0.5) * 2)
        for y in range(H):
            # subtle vertical shading for depth
            shade = 0.78 + 0.22 * (1 - abs(y - H / 2) / (H / 2))
            px[x, y] = tuple(int(c * shade) for c in col)

    # Low-HP red glow on the right edge (the effect's pulse), softened.
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W - 120, H // 2 - 70, W + 40, H // 2 + 70], fill=(255, 40, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(28))
    img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.35)

    out = (Path(__file__).resolve().parents[1]
           / "signal_companion" / "plugins" / "cs2_gsi" / "effect" / "cs2_reactive.png")
    img.save(out, format="PNG")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
