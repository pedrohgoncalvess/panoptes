"""Generate extension PNG icons from the eye mark; Pillow is only needed here."""

import math
from pathlib import Path

from PIL import Image, ImageDraw

directory = Path(__file__).parent
scale = 4
image = Image.new("RGBA", (128 * scale, 128 * scale))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((16, 16, 496, 496), radius=112, fill="#244bc5")
points = []
for sign, indexes in [(1, range(101)), (-1, range(100, -1, -1))]:
    for index in indexes:
        t = index / 100
        points.append(((22 + 84 * t) * scale, (64 + sign * 92 * t * (1 - t)) * scale))
draw.polygon(points, fill="white")
for x, y, radius, color in [(64, 64, 19, "#244bc5"), (64, 64, 10, "#50ddcc"), (60, 59, 4, "white")]:
    draw.ellipse(((x-radius)*scale, (y-radius)*scale, (x+radius)*scale, (y+radius)*scale), fill=color)
for size in (16, 32, 48, 128):
    image.resize((size, size), Image.Resampling.LANCZOS).save(directory / f"icon{size}.png")
