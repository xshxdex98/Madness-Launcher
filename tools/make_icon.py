"""Build the application icon from the Madness Crew artwork.

Run this after changing assets/madness_crew.png, then rebuild the executable:

    python tools/make_icon.py
    python -m PyInstaller madness_launcher.spec --noconfirm

The source art sits in the middle of a square canvas with empty bands above and
below, so pasting it straight into an icon would leave the mark floating small
in the tile. It is cropped to its content and re-centred on a square first,
which is what makes it fill the taskbar button.

Pillow is a build-time tool only. The launcher itself never imports it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "madness_crew.png"
TARGET = ROOT / "assets" / "madness_crew.ico"

# Windows picks from these: 16 in the titlebar, 32 in the taskbar, 48 in
# Explorer's medium view, 256 for extra-large icons and the Alt-Tab switcher.
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Fraction of the tile the artwork spans. A little air stops it touching the
# edges, which is what makes an icon look pasted-in rather than designed.
FILL = 0.94


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    image = Image.open(source).convert("RGBA")

    box = image.getbbox()
    if box is None:
        raise SystemExit(f"{source} is fully transparent — nothing to draw.")
    art = image.crop(box)

    # Square canvas sized to the longer edge, so the aspect ratio is kept.
    side = max(art.size)
    canvas_side = round(side / FILL)
    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    canvas.paste(
        art,
        ((canvas_side - art.width) // 2, (canvas_side - art.height) // 2),
        art,
    )

    # Resize per size explicitly rather than leaving it to the ICO writer, so
    # every frame goes through the same high-quality filter.
    frames = [
        canvas.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES])
    return target


if __name__ == "__main__":
    out = build()
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    print("sizes:", ", ".join(f"{s}x{s}" for s in SIZES))
    sys.exit(0)
