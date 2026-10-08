# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
"""Draw assets/icon.ico (and icon.png) for Keno BOT.  Run: python tools/make_icon.py"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = 256
COLS, ROWS = 8, 5
HOT = {(0, 1), (1, 4), (2, 2), (3, 0), (3, 6), (4, 3), (1, 1), (2, 5), (4, 6), (0, 6)}


def build(scale: int = 4) -> Image.Image:
    side = SIZE * scale
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(side * 0.18)
    draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=(14, 21, 33, 255))
    draw.rounded_rectangle(
        (int(side * 0.02), int(side * 0.02), side - int(side * 0.02), side - int(side * 0.02)),
        radius=int(radius * 0.86),
        outline=(51, 65, 85, 255),
        width=max(1, int(side * 0.012)),
    )
    margin = side * 0.14
    cell = (side - 2 * margin) / max(COLS, ROWS)
    dot = cell * 0.30
    for row in range(ROWS):
        for col in range(COLS):
            cx = margin + cell * (col + 0.5) + (cell * (COLS - ROWS) / 2 if COLS > ROWS else 0)
            cy = margin + cell * (row + 0.5)
            fill = (242, 193, 78, 255) if (row, col) in HOT else (71, 85, 105, 255)
            draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=fill)
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    icon = build()
    icon.save(assets / "icon.png")
    icon.save(
        assets / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {(assets / 'icon.ico').relative_to(ROOT)} and icon.png")


if __name__ == "__main__":
    main()
