"""Generate a test card for the SwitchBot Art Frame (E Ink Spectra 6).

Each band is there to answer one question about what the app does to an
image before sending it to the frame:

- Spectra 6 swatches: are pure palette colours passed through untouched?
- Near-miss swatches: how are off-palette colours mapped or dithered?
- Gradients: is there dithering, and of what kind (ordered, error diffusion)?
- Line pairs / checkerboards / small text: is the image scaled or sharpened?
- Corner markers and 1 px border: is anything cropped, rotated or flipped?

Usage:  uv run --with pillow tools/make_test_image.py [WIDTH HEIGHT]
Default 1200x1600 (portrait) is an assumption for the 13.3" panel; the capture
will show the real resolution.
"""

import colorsys
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (1200, 1600)
OUT = Path(__file__).with_name(f"art_frame_test_card_{W}x{H}.png")

SPECTRA6 = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
}
NEAR_MISS = {
    "orange": (255, 128, 0),
    "pink": (255, 160, 200),
    "grey 50%": (128, 128, 128),
    "cyan": (0, 255, 255),
    "purple": (128, 0, 160),
    "brown": (120, 70, 20),
    "sky": (120, 180, 230),
    "peach": (230, 180, 150),
}


def font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
m = 40  # margin
y = m


def label(text: str, size: int = 26) -> None:
    global y
    d.text((m, y), text, fill="black", font=font(size))
    y += size + 10


def swatch_row(colours: dict[str, tuple[int, int, int]], height: int) -> None:
    global y
    n = len(colours)
    w = (W - 2 * m) / n
    for i, (name, rgb) in enumerate(colours.items()):
        x0, x1 = m + i * w, m + (i + 1) * w
        d.rectangle([x0, y, x1 - 1, y + height], fill=rgb)
        if rgb == (255, 255, 255):  # otherwise invisible on the white page
            d.rectangle([x0, y, x1 - 1, y + height], outline=(0, 0, 0))
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        d.text((x0 + 8, y + height - 34), name, font=font(22),
               fill="white" if lum < 140 else "black")
    y += height + 24


def gradient(fn, height: int) -> None:
    global y
    span = W - 2 * m
    for x in range(span):
        d.line([(m + x, y), (m + x, y + height)], fill=fn(x / (span - 1)))
    y += height + 18


# --- title -------------------------------------------------------------------
d.text((m, y), f"Art Frame test card  {W}x{H}", fill="black", font=font(44))
y += 64

label("Spectra 6 palette (should pass through unchanged)")
swatch_row(SPECTRA6, 130)

label("Off-palette colours (mapped or dithered?)")
swatch_row(NEAR_MISS, 130)

label("Gradients: grey, hue, red, blue")
gradient(lambda t: (round(255 * t),) * 3, 70)
gradient(lambda t: tuple(round(255 * c) for c in colorsys.hsv_to_rgb(t, 1, 1)), 70)
gradient(lambda t: (255, round(255 * (1 - t)), round(255 * (1 - t))), 50)
gradient(lambda t: (round(255 * (1 - t)), round(255 * (1 - t)), 255), 50)

# --- resolution ----------------------------------------------------------------
label("Line pairs: 1, 2, 3, 4 px   |   checkerboards: 1, 2, 4 px")
block_h, block_w = 150, 130
x = m
for period in (1, 2, 3, 4):
    for i in range(0, block_w, period * 2):
        d.rectangle([x + i, y, x + i + period - 1, y + block_h // 2 - 4], fill="black")
    for j in range(0, block_h // 2, period * 2):
        d.rectangle([x, y + block_h // 2 + j, x + block_w - 1,
                     y + block_h // 2 + j + period - 1], fill="black")
    x += block_w + 20
for cell in (1, 2, 4):
    for i in range(0, block_w, cell):
        for j in range(0, block_h, cell):
            if (i // cell + j // cell) % 2:
                d.rectangle([x + i, y + j, x + i + cell - 1, y + j + cell - 1],
                            fill="black")
    x += block_w + 20
y += block_h + 24

label("Text sizes: 32 / 24 / 18 / 14 / 10 px")
for size in (32, 24, 18, 14, 10):
    d.text((m, y), f"{size}px  The quick brown fox jumps over the lazy dog 0123456789",
           fill="black", font=font(size))
    y += size + 8
y += 10

# Thin coloured lines on white and black: fine colour detail.
label("1 px colour lines on white and black")
for bg, x0 in (("white", m), ("black", W // 2 + 10)):
    d.rectangle([x0, y, x0 + W // 2 - m - 10, y + 90], fill=bg)
    for k, rgb in enumerate(list(SPECTRA6.values())[2:] + [NEAR_MISS["orange"]]):
        yy = y + 12 + k * 16
        d.line([(x0 + 10, yy), (x0 + W // 2 - m - 20, yy)], fill=rgb, width=1)
y += 110

# --- geometry markers (drawn last so nothing covers them) ----------------------
d.rectangle([0, 0, W - 1, H - 1], outline="black", width=1)
corner = 24
for cx, cy, colour in (
    (0, 0, "red"), (W - corner, 0, "green"),
    (0, H - corner, "blue"), (W - corner, H - corner, "yellow"),
):
    d.rectangle([cx, cy, cx + corner - 1, cy + corner - 1], fill=colour)
d.text((m, H - m - 30), "Bottom edge. Corners: TL red, TR green, BL blue, BR yellow",
       fill="black", font=font(22))
d.polygon([(W - m - 60, H - m - 10), (W - m, H - m - 10), (W - m - 30, H - m - 60)],
          fill="black")  # arrow pointing up: shows rotation / flip

assert y < H - 2 * m, f"layout overflowed ({y} > {H})"
img.save(OUT, optimize=True)
print(OUT, img.size)
