"""ファインダー風オーバーレイの純粋な画像生成層。GUI非依存。

SPEC.md §3 が正本。全寸法は `s = min(w, h)` 基準の相対値で決める。
PIL の `rectangle` は inclusive 描画のため、右・下隅は `-1` 補正で
四隅の端距離をピクセル一致させる (AGENTS.md 注意点)。
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from rec_config import (
    ALL_BUILTIN_FONTS,
    BUNDLED_FONT_CHOICES,
    CLASSIC_DOT_STYLE,
    COLOR_PRESETS,
    DEFAULT_DOT_STYLE,
    DEFAULT_EFFECT,
    DEFAULT_FONT,
    DEFAULT_RETRO_EFFECT,
    DEFAULT_THICKNESS,
    DOT_ASSET_EXTENSIONS,
    FONT_CHOICES,
    EffectKey,
    OverlayColor,
    OverlayConfig,
    ThicknessKey,
    discover_dot_assets,
    get_bundled_fonts_dir,
    get_dot_assets_dir,
    parse_color_to_rgba,
    resolve_custom_font_path,
)

# ━━━ 四隅L字枠 (SPEC §3.1) ━━━
MARGIN_RATIO = 0.028  # 四隅の端距離 int(s*0.028)
ARM_LEN_RATIO = 0.16  # L字の一辺 int(s*0.16)
# 枠太さは大・中・小の比率で切替。中=従来値。電池線幅は連動しない(枠のみ適用)。
THICKNESS_RATIOS: dict[str, float] = {
    "small": 0.005,
    "medium": 0.008,
    "large": 0.012,
}
THICKNESS_RATIO = THICKNESS_RATIOS["medium"]  # 後方互換エイリアス
MIN_THICKNESS = 2

# ━━━ 電池マーク (SPEC §3.2) ━━━
BAT_W_RATIO = 0.075
BAT_H_RATIO = 0.045
BAT_X_OFFSET_RATIO = 0.02
BAT_Y_OFFSET_RATIO = 0.015
BAT_T_RATIO = 0.005
NUB_W_RATIO = 0.12  # 本体幅に対する比率
NUB_H_RATIO = 0.45  # 本体高に対する比率
BAT_BARS = 4

# ━━━ 赤丸＋REC (SPEC §3.3) ━━━
REC_FONT_RATIO = 0.055
MIN_REC_FONT_SIZE = 10
DOT_R_RATIO = 0.022
REC_GAP_RATIO = 0.012
REC_BLOCK_X_OFFSET_RATIO = 0.02
REC_BLOCK_Y_OFFSET_RATIO = 0.008
REC_DY_RATIO = 0.01  # rec_dy = int(s*0.01) の下げ補正を維持すること
RED = (255, 0, 0, 255)

# ━━━ 中央十字 (SPEC §3.4・§10.2) ━━━
CROSS_HALF_RATIO = 0.035  # 片腕 int(s*0.035)
CROSS_T_RATIO = 0.002  # 線幅 max(1, int(s*0.002)) — 枠より一回り細く

# ━━━ タイムコード (SPEC §3.5) ━━━
TIMECODE_FONT_RATIO = 0.04  # REC(0.055)より一回り小さく
TIMECODE_X_OFFSET_RATIO = 0.02
TIMECODE_Y_GAP_RATIO = 0.008

# ━━━ 半透明座布団ボックス (SPEC §3.7) ━━━
BOX_PAD_X_RATIO = 0.010  # ボックス内左右余白
BOX_PAD_Y_RATIO = 0.008  # ボックス内上下余白
BOX_CLEARANCE_X_RATIO = 0.012  # L字枠縦線からのクリアランス
BOX_CLEARANCE_Y_RATIO = 0.010  # L字枠横線からのクリアランス

# ━━━ UI劣化エフェクト (SPEC §3.6) ━━━
SHIFT_BASE_RATIO = 0.002  # RGBシフト基準量 max(1, int(s*0.002))。弱×1 / 強×2
BLOOM_WEAK_RATIO_WHITE = 0.006  # ブルーム弱・白枠の半径 max(1, int(s*0.006))
BLOOM_WEAK_ALPHA_WHITE = 190  # ブルーム弱・白枠の発光層α
BLOOM_WEAK_RATIO_BLACK = 0.005  # ブルーム弱・黒枠は少し抑える
BLOOM_WEAK_ALPHA_BLACK = 160
BLOOM_STRONG_RATIO = 0.008  # ブルーム強の半径 max(1, int(s*0.008))
BLOOM_STRONG_ALPHA = 220  # ブルーム強の発光層のα
PIXEL_SCALE_WEAK = 0.5  # 低解像度化 (弱)。縮小BILINEAR→拡大NEAREST

# レトロエフェクト強度レベル定義 (0:OFF 〜 6:極限Break)
RETRO_EFFECT_LEVELS: dict[int, dict] = {
    0: {"shift": 0, "bloom": "none", "pixel_scale": 1.0},
    1: {"shift": 1, "bloom": "none", "pixel_scale": 0.8},
    2: {"shift": 1, "bloom": "none", "pixel_scale": 0.5},
    3: {"shift": 2, "bloom": "weak", "pixel_scale": 0.4},
    4: {"shift": 3, "bloom": "weak", "pixel_scale": 0.32},
    5: {"shift": 4, "bloom": "strong", "pixel_scale": 0.25},
    6: {"shift": 6, "bloom": "strong", "pixel_scale": 0.18},
}

EFFECT_PRESETS: dict[str, dict] = {
    "off": {"shift": 0, "bloom": "none", "pixel_scale": 1.0},
    "oled": {"shift": 0, "bloom": "weak", "pixel_scale": 1.0},
    "2000s": {"shift": 1, "bloom": "none", "pixel_scale": PIXEL_SCALE_WEAK},
}

_FONT_SEARCH_PATHS = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/meiryo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def resolve_bundled_font_path(font_key: str) -> Path | None:
    """同梱オープンソースフォントの実ファイルパスを解決する。"""
    local_dir = get_bundled_fonts_dir()
    if not local_dir.is_dir():
        return None
    filename = BUNDLED_FONT_CHOICES.get(font_key)
    if filename:
        p = local_dir / filename
        if p.is_file():
            return p
    # 直接ファイル名指定
    direct = local_dir / font_key
    if direct.is_file():
        return direct
    return None


@lru_cache(maxsize=64)
def _load_font(size: int, font_key: str = DEFAULT_FONT,
               custom_path: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """選択フォントを読み込む。無ければフォールバック。"""
    tried: list[str] = []
    if custom_path:
        tried.append(custom_path)
    elif font_key in BUNDLED_FONT_CHOICES:
        bundled = resolve_bundled_font_path(font_key)
        if bundled is not None:
            tried.append(str(bundled))
    elif font_key in FONT_CHOICES:
        tried.append(f"C:/Windows/Fonts/{FONT_CHOICES[font_key]}")
    else:
        # custom_fontsなしで未知名が来た場合は既定名で解決
        tried.append(f"C:/Windows/Fonts/{FONT_CHOICES.get(DEFAULT_FONT, 'arial.ttf')}")

    # 同梱フォントフォルダも探索対象に追加
    bundled_default = resolve_bundled_font_path("Roboto Condensed Bold(細長)")
    if bundled_default is not None:
        tried.append(str(bundled_default))

    tried += list(_FONT_SEARCH_PATHS)
    for path in tried:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _custom_path_for(font_key: str, custom_fonts: dict[str, str] | None) -> str | None:
    """描画用のカスタム実パス。存在するファイルのみ返す (欠落はNone→fallback)。"""
    p = resolve_custom_font_path(font_key, custom_fonts)
    if p is None:
        return None
    try:
        return str(p) if p.exists() and p.is_file() else None
    except OSError:
        return None


def _mono_color(color: OverlayColor | str, custom_color: str = "") -> tuple[int, int, int, int]:
    """枠・文字・十字などの描画色 (RGBA) を解決する。custom_color を最優先。"""
    if custom_color and isinstance(custom_color, str) and custom_color.strip():
        parsed = parse_color_to_rgba(custom_color.strip())
        if parsed is not None:
            return parsed
    parsed = parse_color_to_rgba(color)
    if parsed is not None:
        return parsed
    return (255, 255, 255, 255) if str(color).lower() == "white" else (0, 0, 0, 255)


def _color_luminance(color_rgba: tuple[int, int, int, int]) -> float:
    """描画色の知覚輝度 (0..255) を計算する (ITU-R BT.601)。"""
    return 0.299 * color_rgba[0] + 0.587 * color_rgba[1] + 0.114 * color_rgba[2]


def _bg_box_color(
    color_rgba: tuple[int, int, int, int],
    opacity: float,
) -> tuple[int, int, int, int] | None:
    """座布団ボックスの背景色を解決する。

    知覚輝度連動: 暗色 (黒など輝度 < 60) は白半透明、明色・蛍光色は黒半透明。
    """
    if opacity <= 0.0:
        return None
    alpha = max(0, min(255, int(round(255 * opacity))))
    lum = _color_luminance(color_rgba)
    rgb = (255, 255, 255) if lum < 60.0 else (0, 0, 0)
    return (*rgb, alpha)


def _tight_ink_metrics(
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    text: str,
) -> tuple[int, int, int, int]:
    """anchor='lt' 描画時の厳密なインク左上オフセット (dx, dy) とインク寸法 (w, h) を返す。"""
    if not text or not text.strip():
        return 0, 0, 0, 0
    try:
        mask, offset = font.getmask2(text, anchor="lt")
        mb = mask.getbbox()
        if mb is not None:
            return offset[0] + mb[0], offset[1] + mb[1], mb[2] - mb[0], mb[3] - mb[1]
    except Exception:
        pass
    bbox = font.getbbox(text, anchor="lt")
    return bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]


def _thickness_to_ratio(thickness: int | float | str = DEFAULT_THICKNESS) -> float:
    """0..100 の数値 (または small/medium/large 文字列) を短辺比率に換算する。"""
    if isinstance(thickness, (int, float)):
        val = max(0.0, min(100.0, float(thickness)))
        if val <= 50.0:
            return 0.0010 + (0.0080 - 0.0010) * (val / 50.0)
        return 0.0080 + (0.0200 - 0.0080) * ((val - 50.0) / 50.0)
    if isinstance(thickness, str):
        key = thickness.lower().strip()
        if key in THICKNESS_RATIOS:
            return THICKNESS_RATIOS[key]
        try:
            return _thickness_to_ratio(float(key))
        except ValueError:
            pass
    return THICKNESS_RATIOS["medium"]


def _frame_thickness(s: int, thickness: ThicknessKey | int | str = DEFAULT_THICKNESS) -> int:
    """四隅L字枠の線太さ。大・中・小の比率または 0..100 スライダーで切替、最低1px。"""
    if isinstance(thickness, (int, float)):
        ratio = _thickness_to_ratio(thickness)
        return max(1, int(round(s * ratio)))
    ratio = THICKNESS_RATIOS.get(str(thickness), THICKNESS_RATIOS["medium"])
    return max(MIN_THICKNESS, int(s * ratio))


@lru_cache(maxsize=32)
def _load_and_resize_dot_asset(asset_path: str, target_size: int) -> Image.Image | None:
    """丸マーク透過素材を読み込み、指定ピクセルサイズ (正方形) にリサイズする。"""
    try:
        p = Path(asset_path)
        if not p.is_file():
            return None
        with Image.open(p) as im:
            rgba = im.convert("RGBA")
            safe_size = max(1, target_size)
            return rgba.resize((safe_size, safe_size), Image.Resampling.LANCZOS)
    except Exception:
        return None


def _resolve_dot_asset_path(dot_style: str) -> str | None:
    """dot_style を素材ファイルパスへ解決する。"""
    assets = discover_dot_assets()
    if dot_style in assets:
        return assets[dot_style]
    p = Path(dot_style)
    if p.is_file() and p.suffix.lower() in DOT_ASSET_EXTENSIONS:
        return str(p)
    return None


def _composite_dot_asset(overlay: Image.Image, asset_img: Image.Image, x: int, y: int) -> None:
    """マーク素材を overlay にアルファ合成する。"""
    if x >= 0 and y >= 0:
        overlay.alpha_composite(asset_img, dest=(x, y))
        return
    sx, sy = max(0, -x), max(0, -y)
    if sx >= asset_img.width or sy >= asset_img.height:
        return
    overlay.alpha_composite(asset_img, dest=(max(0, x), max(0, y)), source=(sx, sy))


def _draw_corner_frames(
    d: ImageDraw.ImageDraw, w: int, h: int, s: int,
    mono: tuple[int, int, int, int],
    margin_x: int, margin_y: int, arm_len: int, thickness: int,
) -> None:
    # 左上 / 右上 / 左下 / 右下 のL字を4本の線分ではなく矩形で描く (角が綺麗)
    corners = [
        (margin_x, margin_y, 1, 1),                          # 左上
        (w - 1 - margin_x, margin_y, -1, 1),                 # 右上
        (margin_x, h - 1 - margin_y, 1, -1),                 # 左下
        (w - 1 - margin_x, h - 1 - margin_y, -1, -1),        # 右下
    ]
    for cx, cy, sx, sy in corners:
        # 横棒
        x0 = min(cx, cx + sx * arm_len)
        x1 = max(cx, cx + sx * arm_len)
        y0 = cy if sy > 0 else cy - thickness
        y1 = cy + thickness if sy > 0 else cy
        d.rectangle([x0, y0, x1, y1], fill=mono)
        # 縦棒
        x0 = cx if sx > 0 else cx - thickness
        x1 = cx + thickness if sx > 0 else cx
        y0 = min(cy, cy + sy * arm_len)
        y1 = max(cy, cy + sy * arm_len)
        d.rectangle([x0, y0, x1, y1], fill=mono)


def _draw_battery(
    d: ImageDraw.ImageDraw, s: int,
    margin_x: int, margin_y: int, thickness: int,
    mono: tuple[int, int, int, int],
    active_bars: int = BAT_BARS,
    bg_box_opacity: float = 0.0,
    bg_box_color: tuple[int, int, int, int] | None = None,
) -> None:
    bat_w = int(s * BAT_W_RATIO)
    bat_h = int(s * BAT_H_RATIO)
    nub_w = int(bat_w * NUB_W_RATIO)
    nub_h = int(bat_h * NUB_H_RATIO)

    if bg_box_opacity > 0.0 and bg_box_color is not None:
        total_w = bat_w + nub_w
        pad_x = max(2, int(round(s * BOX_PAD_X_RATIO)))
        pad_y = max(2, int(round(s * BOX_PAD_Y_RATIO)))
        clearance_x = max(2, int(round(s * BOX_CLEARANCE_X_RATIO)))
        clearance_y = max(2, int(round(s * BOX_CLEARANCE_Y_RATIO)))
        box_w = total_w + pad_x * 2
        box_h = bat_h + pad_y * 2
        box_x0 = (margin_x + thickness) + clearance_x
        box_y0 = (margin_y + thickness) + clearance_y
        box_x1 = box_x0 + box_w
        box_y1 = box_y0 + box_h
        d.rectangle([box_x0, box_y0, box_x1, box_y1], fill=bg_box_color)
        bat_x = box_x0 + pad_x
        bat_y = box_y0 + pad_y
    else:
        bat_x = margin_x + int(s * BAT_X_OFFSET_RATIO)
        bat_y = margin_y + thickness + int(s * BAT_Y_OFFSET_RATIO)

    bat_t = max(MIN_THICKNESS, int(s * BAT_T_RATIO))
    d.rectangle([bat_x, bat_y, bat_x + bat_w, bat_y + bat_h],
                outline=mono, width=bat_t)
    # 電池の突起 (右側)
    nub_x = bat_x + bat_w
    nub_y = bat_y + (bat_h - nub_h) // 2
    d.rectangle([nub_x, nub_y, nub_x + nub_w, nub_y + nub_h],
                fill=mono)
    # 電池残量バー (4本、内幅いっぱいに均等配置)
    pad = bat_t + 1
    avail = bat_w - pad * 2
    if avail <= 0 or (bat_h - pad * 2) < 0:
        return  # 極小画像では残量バー省略
    pitch = avail / BAT_BARS
    bar_w = pitch * 0.5
    bars_to_draw = max(0, min(BAT_BARS, active_bars))
    for i in range(bars_to_draw):
        bx0 = bat_x + pad + i * pitch
        by0 = bat_y + pad
        bx1 = bx0 + bar_w
        by1 = bat_y + bat_h - pad
        d.rectangle([bx0, by0, bx1, by1], fill=mono)


def _draw_rec_indicator(
    overlay: Image.Image,
    d: ImageDraw.ImageDraw, w: int, s: int,
    margin_x: int, margin_y: int, thickness: int,
    mono: tuple[int, int, int, int], font_key: str,
    custom_fonts: dict[str, str] | None = None,
    rec_text: str = "REC",
    show_red_dot: bool = True,
    dot_style: str = DEFAULT_DOT_STYLE,
    bg_box_opacity: float = 0.0,
    bg_box_color: tuple[int, int, int, int] | None = None,
    red_dot_visible: bool = True,
) -> None:
    rec_font_size = max(MIN_REC_FONT_SIZE, int(s * REC_FONT_RATIO))
    font = _load_font(rec_font_size, font_key, _custom_path_for(font_key, custom_fonts))
    label = rec_text if rec_text is not None else "REC"
    dot_r = int(s * DOT_R_RATIO)
    dot_diam = dot_r * 2
    gap = int(s * REC_GAP_RATIO)
    rec_dy = int(s * REC_DY_RATIO)

    # 既存互換モード (座布団OFF・真円classic・REC標準文字列)
    if bg_box_opacity <= 0.0 and dot_style == CLASSIC_DOT_STYLE and label == "REC" and show_red_dot:
        bbox = d.textbbox((0, 0), label, font=font, anchor="lt")
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        block_w = dot_diam + gap + text_w
        block_x = w - margin_x - int(s * REC_BLOCK_X_OFFSET_RATIO) - block_w
        block_y = margin_y + thickness + int(s * REC_BLOCK_Y_OFFSET_RATIO) + rec_dy
        row_h = max(text_h, dot_diam)
        cy = block_y + row_h // 2
        if red_dot_visible:
            d.ellipse([block_x, cy - dot_r, block_x + dot_diam, cy + dot_r], fill=RED)
        d.text((block_x + dot_diam + gap - bbox[0], cy - text_h // 2 - bbox[1]),
               label, font=font, fill=mono, anchor="lt")
        return

    # 詳細カスタマイズ・座布団・アセット描画モード
    has_text = bool(label.strip())
    if has_text:
        ink_dx, ink_dy, text_w, text_h = _tight_ink_metrics(font, label)
    else:
        ink_dx, ink_dy, text_w, text_h = 0, 0, 0, 0

    content_w = (dot_diam if show_red_dot else 0) + (gap if show_red_dot and has_text else 0) + (text_w if has_text else 0)
    content_h = max(dot_diam if show_red_dot else 0, text_h if has_text else 0)

    pad_x = max(2, int(round(s * BOX_PAD_X_RATIO)))
    pad_y = max(2, int(round(s * BOX_PAD_Y_RATIO)))
    clearance_x = max(2, int(round(s * BOX_CLEARANCE_X_RATIO)))
    clearance_y = max(2, int(round(s * BOX_CLEARANCE_Y_RATIO)))

    box_w = content_w + pad_x * 2
    box_h = content_h + pad_y * 2

    if bg_box_opacity > 0.0 and bg_box_color is not None:
        box_x1 = (w - 1 - margin_x - thickness) - clearance_x
        box_x0 = box_x1 - box_w
        box_y0 = (margin_y + thickness) + clearance_y
        box_y1 = box_y0 + box_h
        d.rectangle([box_x0, box_y0, box_x1, box_y1], fill=bg_box_color)
        cy = box_y0 + box_h // 2
        curr_x = box_x0 + pad_x
    else:
        curr_x = w - margin_x - int(s * REC_BLOCK_X_OFFSET_RATIO) - content_w
        block_y = margin_y + thickness + int(s * REC_BLOCK_Y_OFFSET_RATIO) + rec_dy
        cy = block_y + content_h // 2

    if show_red_dot and red_dot_visible:
        dot_y0 = cy - dot_r
        asset_img = None
        if dot_style != CLASSIC_DOT_STYLE:
            target_path = _resolve_dot_asset_path(dot_style)
            if target_path:
                asset_img = _load_and_resize_dot_asset(target_path, dot_diam)
        if asset_img is not None:
            _composite_dot_asset(overlay, asset_img, curr_x, dot_y0)
        else:
            d.ellipse([curr_x, dot_y0, curr_x + dot_diam, dot_y0 + dot_diam], fill=RED)

    if show_red_dot:
        curr_x += dot_diam + gap

    if has_text:
        text_ink_y0 = cy - text_h // 2
        draw_x = curr_x - ink_dx
        draw_y = text_ink_y0 - ink_dy
        d.text((draw_x, draw_y), label, font=font, fill=mono, anchor="lt")


def _draw_center_cross(
    d: ImageDraw.ImageDraw, w: int, h: int, s: int,
    mono: tuple[int, int, int, int],
) -> None:
    """画像センターの十字マーク。枠色に連動、枠太さには連動しない。"""
    half = int(s * CROSS_HALF_RATIO)
    t = max(1, int(s * CROSS_T_RATIO))
    cx, cy = w // 2, h // 2
    d.rectangle([cx - half, cy - t // 2, cx + half, cy + t // 2], fill=mono)
    d.rectangle([cx - t // 2, cy - half, cx + t // 2, cy + half], fill=mono)


def _draw_timecode(
    d: ImageDraw.ImageDraw, w: int, h: int, s: int,
    margin_x: int, margin_y: int, thickness: int,
    mono: tuple[int, int, int, int], font_key: str, text: str,
    custom_fonts: dict[str, str] | None = None,
    bg_box_opacity: float = 0.0,
    bg_box_color: tuple[int, int, int, int] | None = None,
) -> None:
    """右下の日時表示。"""
    if not text or not text.strip():
        return
    font_size = max(MIN_REC_FONT_SIZE, int(s * TIMECODE_FONT_RATIO))
    font = _load_font(font_size, font_key, _custom_path_for(font_key, custom_fonts))

    if bg_box_opacity > 0.0 and bg_box_color is not None:
        tc_dx, tc_dy, tc_w, tc_h = _tight_ink_metrics(font, text)
        pad_x = max(2, int(round(s * BOX_PAD_X_RATIO)))
        pad_y = max(2, int(round(s * BOX_PAD_Y_RATIO)))
        clearance_x = max(2, int(round(s * BOX_CLEARANCE_X_RATIO)))
        clearance_y = max(2, int(round(s * BOX_CLEARANCE_Y_RATIO)))
        tc_box_w = tc_w + pad_x * 2
        tc_box_h = tc_h + pad_y * 2
        tc_box_x1 = (w - 1 - margin_x - thickness) - clearance_x
        tc_box_x0 = tc_box_x1 - tc_box_w
        tc_box_y1 = (h - 1 - margin_y - thickness) - clearance_y
        tc_box_y0 = tc_box_y1 - tc_box_h
        d.rectangle([tc_box_x0, tc_box_y0, tc_box_x1, tc_box_y1], fill=bg_box_color)
        tc_cy = tc_box_y0 + tc_box_h // 2
        tc_ink_x0 = tc_box_x0 + pad_x
        tc_ink_y0 = tc_cy - tc_h // 2
        tc_draw_x = tc_ink_x0 - tc_dx
        tc_draw_y = tc_ink_y0 - tc_dy
        d.text((tc_draw_x, tc_draw_y), text, font=font, fill=mono, anchor="lt")
    else:
        rec_dy = int(s * REC_DY_RATIO)
        x = w - margin_x - int(s * TIMECODE_X_OFFSET_RATIO)
        y = h - 1 - margin_y - thickness - int(s * TIMECODE_Y_GAP_RATIO) - rec_dy
        d.text((x, y), text, font=font, fill=mono, anchor="rb")


# ━━━ 撮影日時モード (SPEC §3.5) ━━━
EXIF_DATETIME_TAGS: tuple[int, ...] = (36867, 36868, 306)


def parse_exif_datetimestr(value: str | bytes | None) -> datetime | None:
    """EXIF日時文字列 `YYYY:MM:DD HH:MM:SS` をパースする。不正はNone。"""
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", "ignore")
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip().rstrip("\x00").strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def format_photo_timecode(dt: datetime) -> str:
    """撮影日時をタイムコード書式 `YYYY/MM/DD AM/PM HH:MM` に整形する。"""
    ampm = "AM" if dt.hour < 12 else "PM"
    h12 = dt.hour % 12 or 12
    return f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d} {ampm} {h12:02d}:{dt.minute:02d}"


def photo_timecode_text(
    img: Image.Image | None = None,
    path: str | Path | None = None,
    fallback: str = "",
) -> str:
    """写真毎の日文字列を `EXIF→ファイルmtime→固定文` の順で解決する。"""
    if img is not None:
        try:
            exif = img.getexif()
            if exif:
                for tag in EXIF_DATETIME_TAGS:
                    dt = parse_exif_datetimestr(exif.get(tag))
                    if dt is not None:
                        return format_photo_timecode(dt)
        except Exception:
            pass
    if path is not None:
        try:
            dt = datetime.fromtimestamp(os.stat(path).st_mtime)
            return format_photo_timecode(dt)
        except (OSError, ValueError, OverflowError):
            pass
    return fallback


def resolve_timecode_text(
    config: OverlayConfig,
    img: Image.Image | None = None,
    path: str | Path | None = None,
) -> str:
    """描画に使う日時文。撮影日時モードONなら写真毎に解決、OFFなら固定文。"""
    if config.timecode_from_exif:
        return photo_timecode_text(img, path, config.timecode_text)
    return config.timecode_text


def resolve_photo_config(
    config: OverlayConfig,
    img: Image.Image | None = None,
    path: str | Path | None = None,
) -> OverlayConfig:
    """写真毎の日時を反映した描画用設定。元の設定は変更しない。"""
    text = resolve_timecode_text(config, img, path)
    if text == config.timecode_text:
        return config
    return replace(config, timecode_text=text)


def _shift_channel(ch: Image.Image, dx: int) -> Image.Image:
    """1ch画像を水平シフトする。はみ出しは0クリア (wrapさせない)。"""
    if dx == 0:
        return ch
    return ch.transform(ch.size, Image.AFFINE, (1, 0, dx, 0, 1, 0),
                        fillcolor=0)


def _apply_rgb_shift(overlay: Image.Image, level: int, s: int) -> Image.Image:
    """色収差: Rを左へ・Bを右へずらす。GとAは固定。"""
    if level <= 0:
        return overlay
    d = max(1, int(s * SHIFT_BASE_RATIO)) * level
    r, g, b, a = overlay.split()
    return Image.merge("RGBA", (_shift_channel(r, d), g,
                                _shift_channel(b, -d), a))


def _apply_bloom(overlay: Image.Image, strength: str, s: int,
                 color: OverlayColor | str = "white") -> Image.Image:
    """発光: ぼかし複製を背後に敷き、元のUIを上に重ねる。"""
    if strength == "none":
        return overlay
    if strength == "strong":
        ratio, alpha = BLOOM_STRONG_RATIO, BLOOM_STRONG_ALPHA
    else:
        # 暗色判定: black または 輝度 < 60
        parsed = parse_color_to_rgba(color) if isinstance(color, str) else color
        is_dark = (parsed is not None and _color_luminance(parsed) < 60.0) if parsed else (str(color).lower() == "black")
        if is_dark:
            ratio, alpha = BLOOM_WEAK_RATIO_BLACK, BLOOM_WEAK_ALPHA_BLACK
        else:
            ratio, alpha = BLOOM_WEAK_RATIO_WHITE, BLOOM_WEAK_ALPHA_WHITE
    radius = max(1, int(s * ratio))
    glow = overlay.filter(ImageFilter.GaussianBlur(radius))
    r, g, b, a = glow.split()
    a = a.point(lambda v: v * alpha // 255)
    glow = Image.merge("RGBA", (r, g, b, a))
    return Image.alpha_composite(glow, overlay)


def _apply_pixelation(overlay: Image.Image, scale: float) -> Image.Image:
    """低解像度化: 縮小 (BILINEARで細線消失を抑える) →等倍復元 (NEAREST)。"""
    if scale >= 1.0:
        return overlay
    w, h = overlay.size
    small = overlay.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                           Image.Resampling.BILINEAR)
    return small.resize((w, h), Image.Resampling.NEAREST)


def apply_ui_effects(overlay: Image.Image, preset: int | EffectKey | str = DEFAULT_EFFECT,
                     s: int | None = None, color: OverlayColor | str = "white") -> Image.Image:
    """描画済みUIレイヤーにエフェクトを適用して返す。"""
    p: dict | None = None
    if isinstance(preset, int):
        p = RETRO_EFFECT_LEVELS.get(max(0, min(6, preset)), RETRO_EFFECT_LEVELS[0])
    elif isinstance(preset, str):
        try:
            val = int(round(float(preset.strip())))
            p = RETRO_EFFECT_LEVELS.get(max(0, min(6, val)), RETRO_EFFECT_LEVELS[0])
        except ValueError:
            cleaned = preset.strip().lower()
            if cleaned not in EFFECT_PRESETS:
                raise ValueError(f"unknown effect preset: {preset!r}")
            p = EFFECT_PRESETS[cleaned]
    else:
        p = RETRO_EFFECT_LEVELS[0]

    if p is None or (p["shift"] <= 0 and p["bloom"] == "none" and p["pixel_scale"] >= 1.0):
        return overlay

    if s is None:
        s = min(overlay.size)
    overlay = _apply_rgb_shift(overlay, p["shift"], s)
    overlay = _apply_bloom(overlay, p["bloom"], s, color)
    overlay = _apply_pixelation(overlay, p["pixel_scale"])
    return overlay


def create_rec_overlay(w: int, h: int, color: OverlayColor | str = "black",
                       font_key: str = DEFAULT_FONT,
                       thickness: ThicknessKey | int | str = DEFAULT_THICKNESS,
                       show_frame: bool = True,
                       show_battery: bool = True,
                       show_rec: bool = True,
                       show_cross: bool = False,
                       show_timecode: bool = False,
                       timecode_text: str = "",
                       effect: EffectKey | str = DEFAULT_EFFECT,
                       custom_fonts: dict[str, str] | None = None,
                       retro_effect: int = DEFAULT_RETRO_EFFECT,
                       dot_style: str = DEFAULT_DOT_STYLE,
                       bg_box_opacity: float = 0.0,
                       custom_color: str = "",
                       rec_label: str = "REC",
                       show_red_dot: bool = True,
                       battery_bars: int = 4) -> Image.Image:
    """指定サイズと同寸の透過オーバーレイ(RGBA)を生成する。"""
    return create_rec_overlay_with_config(
        w, h, OverlayConfig(color=color, custom_color=custom_color, font_key=font_key,
                            thickness=thickness, show_frame=show_frame,
                            show_battery=show_battery, show_rec=show_rec,
                            show_cross=show_cross, show_timecode=show_timecode,
                            timecode_text=timecode_text, effect=effect,
                            retro_effect=retro_effect,
                            custom_fonts=dict(custom_fonts or {}),
                            dot_style=dot_style, bg_box_opacity=bg_box_opacity,
                            rec_label=rec_label, show_red_dot=show_red_dot,
                            battery_bars=battery_bars))


def create_rec_overlay_with_config(w: int, h: int, config: OverlayConfig) -> Image.Image:
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    s = min(w, h)  # 基準スケール
    m_ratio = config.margin_ratio if config.margin_ratio is not None else MARGIN_RATIO
    a_ratio = config.arm_len_ratio if config.arm_len_ratio is not None else ARM_LEN_RATIO
    margin = int(s * m_ratio)
    margin_x = margin
    margin_y = margin
    arm_len = int(s * a_ratio)
    thickness = _frame_thickness(s, config.thickness)
    mono = _mono_color(config.color, config.custom_color)
    bg_box_col = _bg_box_color(mono, config.bg_box_opacity)

    if config.show_frame:
        _draw_corner_frames(d, w, h, s, mono, margin_x, margin_y, arm_len, thickness)
    if config.show_battery:
        _draw_battery(d, s, margin_x, margin_y, thickness, mono,
                      active_bars=config.battery_bars,
                      bg_box_opacity=config.bg_box_opacity,
                      bg_box_color=bg_box_col)
    if config.show_rec:
        _draw_rec_indicator(overlay, d, w, s, margin_x, margin_y, thickness, mono,
                            config.font_key, config.custom_fonts,
                            rec_text=config.rec_label, show_red_dot=config.show_red_dot,
                            dot_style=config.dot_style,
                            bg_box_opacity=config.bg_box_opacity,
                            bg_box_color=bg_box_col,
                            red_dot_visible=config.red_dot_visible)
    if config.show_cross:
        _draw_center_cross(d, w, h, s, mono)
    if config.show_timecode:
        _draw_timecode(d, w, h, s, margin_x, margin_y, thickness,
                       mono, config.font_key, config.timecode_text,
                       config.custom_fonts,
                       bg_box_opacity=config.bg_box_opacity,
                       bg_box_color=bg_box_col)

    # UI劣化エフェクト: retro_effect (0..6) を最優先し、未指定(0)かつ effect がある場合は旧 effect
    eff_key: int | str = config.retro_effect
    if eff_key == 0 and config.effect not in ("off",):
        eff_key = config.effect
    color_hint = "black" if _color_luminance(mono) < 60.0 else "white"
    if eff_key != 0 and eff_key != "off":
        overlay = apply_ui_effects(overlay, eff_key, s, color_hint)

    return overlay


def composite_with_overlay(base: Image.Image, color: OverlayColor | str = "black",
                           font_key: str = DEFAULT_FONT,
                           thickness: ThicknessKey | int | str = DEFAULT_THICKNESS,
                           show_frame: bool = True,
                           show_battery: bool = True,
                           show_rec: bool = True,
                           show_cross: bool = False,
                           show_timecode: bool = False,
                           timecode_text: str = "",
                           effect: EffectKey | str = DEFAULT_EFFECT,
                           custom_fonts: dict[str, str] | None = None,
                           retro_effect: int = DEFAULT_RETRO_EFFECT,
                           dot_style: str = DEFAULT_DOT_STYLE,
                           bg_box_opacity: float = 0.0,
                           custom_color: str = "",
                           rec_label: str = "REC",
                           show_red_dot: bool = True,
                           battery_bars: int = 4) -> Image.Image:
    """ベース画像にREC枠を合成したRGBA画像を返す。"""
    return composite_with_config(
        base, OverlayConfig(color=color, custom_color=custom_color, font_key=font_key,
                            thickness=thickness, show_frame=show_frame,
                            show_battery=show_battery, show_rec=show_rec,
                            show_cross=show_cross, show_timecode=show_timecode,
                            timecode_text=timecode_text, effect=effect,
                            retro_effect=retro_effect,
                            custom_fonts=dict(custom_fonts or {}),
                            dot_style=dot_style, bg_box_opacity=bg_box_opacity,
                            rec_label=rec_label, show_red_dot=show_red_dot,
                            battery_bars=battery_bars))


def composite_with_config(base: Image.Image, config: OverlayConfig) -> Image.Image:
    w, h = base.size
    overlay = create_rec_overlay_with_config(w, h, config)
    bg = base.convert("RGBA")
    return Image.alpha_composite(bg, overlay)


def load_base_image(path: str | Path) -> Image.Image:
    """EXIF Orientationを反映して開く (外部ビューア表示と一致させる)。"""
    return ImageOps.exif_transpose(Image.open(path))


def prepare_image_for_save(img: Image.Image, dest_path: str | Path) -> Image.Image:
    """保存先拡張子に応じた変換。JPEGはRGB変換、それ以外はそのまま。"""
    if str(dest_path).lower().endswith((".jpg", ".jpeg")):
        return img.convert("RGB")
    return img


def save_composited_image(img: Image.Image, dest_path: str | Path) -> None:
    """合成済み画像を拡張子に応じて保存。JPEGは quality=95。"""
    is_jpeg = str(dest_path).lower().endswith((".jpg", ".jpeg"))
    out = prepare_image_for_save(img, dest_path)
    if is_jpeg:
        out.save(dest_path, quality=95)
    else:
        out.save(dest_path)
