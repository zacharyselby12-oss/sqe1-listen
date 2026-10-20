#!/usr/bin/env python3
"""Make the cover pictures for the feed by area of law (run by hand; the PNGs are kept in covers/).

  python tools/covers.py      # writes covers/<area>.png, 1400 x 1400, same style as cover.png
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
NAVY, AMBER, WHITE = (20, 52, 104), (244, 165, 36), (255, 255, 255)
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size):
    return ImageFont.truetype(BOLD, size)


def wrap(draw, text, size, width):
    """Split text into lines that fit the width, shrinking the font if a single word is too wide."""
    while size > 40:
        f = font(size)
        words, lines, cur = text.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=f) <= width:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if all(draw.textlength(l, font=f) <= width for l in lines) and len(lines) <= 3:
            return f, lines
        size -= 8
    return font(size), [text]


def cover(name, out):
    im = Image.new("RGB", (1400, 1400), NAVY)
    d = ImageDraw.Draw(im)
    top = font(110)
    t = "SQE1 LISTEN"
    d.text(((1400 - d.textlength(t, font=top)) / 2, 120), t, font=top, fill=AMBER)
    f, lines = wrap(d, name, 190, 1200)
    lh = f.size * 1.15
    y = 560 - lh * len(lines) / 2
    for l in lines:
        d.text(((1400 - d.textlength(l, font=f)) / 2, y), l, font=f, fill=WHITE)
        y += lh
    d.rounded_rectangle((120, 960, 1280, 1240), radius=60, fill=AMBER)   # the same sound-wave bar as cover.png
    heights = [60, 140, 220, 120, 260, 180, 100, 240, 160, 80, 200, 140, 60]
    x = 190
    for h in heights:
        d.rounded_rectangle((x, 1100 - h / 2, x + 44, 1100 + h / 2), radius=22, fill=NAVY)
        x += 78
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)


if __name__ == "__main__":
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for code, name in cfg["areaNames"].items():
        cover(name, ROOT / "covers" / ("%s.png" % code))
        print("covers/%s.png" % code)
