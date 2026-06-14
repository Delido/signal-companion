"""Generate the SignalRGB library thumbnail for the CS2 effect.

SignalRGB shows a per-effect preview from a .png with the same base name as the
.html. We build it from the Counter-Strike 2 cover art (assets/cs2_source.jpg)
with the SignalCompanion icon badged into the corner, sized 320x200 to match the
effect canvas, and write it into the effect package so it ships + installs
alongside the html.

Pure Pillow; run to regenerate:

    python assets/_generate_effect_preview.py
"""
from pathlib import Path

from PIL import Image

W, H = 320, 200
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def cover_resize(img, w, h):
    """Scale to cover w x h, then center-crop."""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
    iw, ih = img.size
    left, top = (iw - w) // 2, (ih - h) // 2
    return img.crop((left, top, left + w, top + h))


def main():
    base = Image.open(HERE / "cs2_source.jpg").convert("RGB")
    canvas = cover_resize(base, W, H)

    icon_path = HERE / "signalcompanion.ico"
    if icon_path.is_file():
        icon = Image.open(icon_path).convert("RGBA")
        sz = 54
        icon = icon.resize((sz, sz), Image.LANCZOS)
        # subtle dark rounded backing so the icon reads on any background
        pad = 6
        backing = Image.new("RGBA", (sz + pad * 2, sz + pad * 2), (0, 0, 0, 120))
        bx, by = W - backing.width - 6, H - backing.height - 6
        canvas = canvas.convert("RGBA")
        canvas.alpha_composite(backing, (bx, by))
        canvas.alpha_composite(icon, (bx + pad, by + pad))
        canvas = canvas.convert("RGB")

    out = ROOT / "signal_companion" / "plugins" / "cs2_gsi" / "effect" / "cs2_reactive.png"
    canvas.save(out, format="PNG")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
