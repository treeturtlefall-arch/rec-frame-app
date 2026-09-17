"""テスト共通ヘルパー・定数。"""
from __future__ import annotations

from PIL import Image

RED = (255, 0, 0, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)

VERIFIED_SIZES = [(640, 360), (512, 512), (1024, 1024), (1920, 1080), (2048, 3072), (300, 500)]


def count_color(img: Image.Image, color: tuple[int, int, int, int]) -> int:
    """画像中の特定色ピクセル数を返す。"""
    data = img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()
    return sum(1 for p in data if tuple(p) == color)
