"""Generate assets/signalcompanion.ico — the app/installer icon.

Matches the tray look: a dark rounded disc with three brand dots (R/G/B).
Pure Pillow; run to regenerate:

    python assets/_generate_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

DOTS = [(228, 64, 64), (74, 200, 120), (70, 130, 220)]   # red / green / blue


def _render(size):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = s * 0.04
    d.ellipse([m, m, s - m, s - m], fill=(34, 34, 38, 255),
              outline=(20, 20, 20, 255), width=max(1, int(s * 0.03)))
    # vertical stack of three dots
    n = len(DOTS)
    dot = s * 0.20
    gap = (s * 0.62) / n
    y = s * 0.20
    cx = s / 2
    for color in DOTS:
        d.ellipse([cx - dot / 2, y, cx + dot / 2, y + dot], fill=color + (255,))
        y += gap
    return img


def main():
    out = Path(__file__).resolve().parent / "signalcompanion.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = _render(256)
    base.save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
