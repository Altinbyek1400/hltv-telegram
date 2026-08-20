"""Тоглолтын карт зураг үүсгэх (Pillow)."""

from __future__ import annotations

import io
import os

import requests
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 560
BG = (12, 16, 24)
PANEL = (20, 26, 38)
WHITE = (245, 247, 250)
MUTED = (140, 152, 172)
DIM = (94, 105, 125)

ACCENTS = {
    "announce": (59, 130, 246),   # цэнхэр
    "live": (239, 68, 68),        # улаан
    "result": (34, 197, 94),      # ногоон
}

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "C:/Windows/Fonts",
]
CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size)
    if key in CACHE:
        return CACHE[key]
    names = (
        ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"]
        if bold
        else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"]
    )
    for directory in FONT_DIRS:
        for name in names:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                CACHE[key] = ImageFont.truetype(path, size)
                return CACHE[key]
    CACHE[key] = ImageFont.load_default()
    return CACHE[key]


def centered(draw: ImageDraw.ImageDraw, xy, text, fnt, fill):
    if not text:
        return
    x, y = xy
    box = draw.textbbox((0, 0), text, font=fnt)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2), text, font=fnt, fill=fill)


def fit(text: str, fnt, draw: ImageDraw.ImageDraw, max_width: int) -> str:
    if draw.textlength(text, font=fnt) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=fnt) > max_width:
        text = text[:-1]
    return text + "…"


def logo(url: str | None, size: int) -> Image.Image | None:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200 or not r.content:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    img.thumbnail((size, size), Image.LANCZOS)
    return img


def render(
    kind: str,
    team_a: dict,
    team_b: dict,
    center: str,
    sub: str,
    tournament: str,
    stage: str,
    footer: str,
) -> bytes:
    """kind: announce | live | result"""
    accent = ACCENTS.get(kind, ACCENTS["announce"])
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 10], fill=accent)
    d.rounded_rectangle([40, 150, W - 40, 460], radius=28, fill=PANEL)

    centered(d, (W / 2, 70), fit(tournament, font(True, 36), d, W - 160), font(True, 36), WHITE)
    if stage:
        centered(d, (W / 2, 118), fit(stage, font(False, 27), d, W - 200), font(False, 27), MUTED)

    for team, cx in ((team_a, 250), (team_b, 830)):
        mark = logo(team.get("logo"), 170)
        if mark:
            img.paste(mark, (int(cx - mark.width / 2), int(275 - mark.height / 2)), mark)
        else:
            d.ellipse([cx - 70, 205, cx + 70, 345], outline=DIM, width=3)
            initials = "".join(w[0] for w in team["name"].split()[:2]).upper()
            centered(d, (cx, 275), initials, font(True, 54), DIM)
        centered(d, (cx, 400), fit(team["name"], font(True, 38), d, 400), font(True, 38), WHITE)

    centered(d, (W / 2, 262), center, font(True, 78), WHITE)
    if sub:
        centered(d, (W / 2, 340), sub, font(False, 30), MUTED)

    centered(d, (W / 2, 508), footer, font(True, 30), accent)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
