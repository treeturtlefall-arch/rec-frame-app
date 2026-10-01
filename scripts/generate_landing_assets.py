"""Generate public landing images with the application's real overlay renderer.

Run from the repository root with .venv/Scripts/python scripts/generate_landing_assets.py.
The two local test_picture_* source files are never copied or modified.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rec_config import OverlayConfig  # noqa: E402
from rec_overlay import composite_with_config, load_base_image  # noqa: E402

OUT = ROOT / "docs" / "assets" / "landing"
STAMP = "2026/09/18 PM 08:30"
CONFIG = OverlayConfig(color="white", thickness="large", show_cross=True,
                       show_timecode=True, timecode_text=STAMP)


def clean(image: Image.Image) -> Image.Image:
    # A fresh image has no inherited EXIF, GPS, comments, or ICC metadata.
    result = Image.new("RGB", image.size)
    result.paste(image.convert("RGB"))
    return result


def save(image: Image.Image, name: str) -> None:
    result = clean(image)
    if name.endswith(".jpg"):
        result.save(OUT / name, quality=95, optimize=True, subsampling=0)
    else:
        result.save(OUT / name, optimize=True)


def source(path: str, size: tuple[int, int]) -> Image.Image:
    with load_base_image(ROOT / path) as opened:
        image = clean(opened)
    image.thumbnail(size, Image.Resampling.LANCZOS)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dog = source("test_picture_1.jpg", (960, 1280))
    art = source("test_picture_2.png", (1024, 1024))
    save(dog, "dog_before.jpg")
    save(art, "art_before.jpg")
    for effect in ("off", "oled", "2000s"):
        result = composite_with_config(dog, replace(CONFIG, effect=effect))
        save(result, f"dog_{effect}.jpg")
        # Identical source rectangle, magnified 3x without smoothing.
        detail = result.crop((dog.width - 280, 16, dog.width - 16, 148))
        save(detail.resize((792, 396), Image.Resampling.NEAREST), f"rec_{effect}.png")
    art_config = replace(CONFIG, effect="2000s", thickness="medium")
    save(composite_with_config(art, art_config), "art_2000s.jpg")
    save(composite_with_config(art, replace(CONFIG, effect="oled")), "art_oled.jpg")
    dog_result = composite_with_config(dog, replace(CONFIG, effect="oled"))
    timecode = dog_result.crop((dog.width - 530, dog.height - 125,
                               dog.width - 16, dog.height - 16))
    save(timecode.resize((1028, 218), Image.Resampling.NEAREST), "timestamp.png")

    styles = [("black", "small", "Arial(標準)"),
              ("white", "medium", "Arial Narrow Bold(細長)"),
              ("white", "large", "Consolas(等幅)")]
    for index, (color, thickness, font) in enumerate(styles, 1):
        result = composite_with_config(dog, replace(CONFIG, color=color,
                                                    thickness=thickness, font_key=font))
        save(result.crop((0, 0, dog.width, 195)), f"style_{index}.png")

    # Numbered callouts leave the overlay visible; labels live in the HTML legend.
    diagram = dog_result.copy()
    draw = ImageDraw.Draw(diagram)
    try:
        font = ImageFont.truetype("arialbd.ttf", 26)
    except OSError:
        font = ImageFont.load_default(size=26)
    points = [(175, 190, 35, 30), (175, 105, 85, 65),
              (740, 185, 820, 76), (575, 575, 480, 640),
              (650, 1120, 770, 1205)]
    for number, (x, y, target_x, target_y) in enumerate(points, 1):
        draw.line((x, y, target_x, target_y), fill="#7fd0c8", width=3)
        draw.ellipse((x - 23, y - 23, x + 23, y + 23), fill="#0b0d0f",
                     outline="#7fd0c8", width=3)
        draw.text((x, y), str(number), font=font, fill="white", anchor="mm")
    save(diagram, "elements.jpg")
    with Image.open(ROOT / "docs" / "assets" / "ui_simple.png") as ui:
        save(ui.crop((720, 0, 910, 54)).resize((570, 162), Image.Resampling.LANCZOS),
             "language.png")
    print(f"Generated {len(list(OUT.iterdir()))} public images in docs/assets/landing")


if __name__ == "__main__":
    main()
