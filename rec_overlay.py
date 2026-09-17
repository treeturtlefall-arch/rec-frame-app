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

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from rec_config import (
    DEFAULT_EFFECT,
    DEFAULT_FONT,
    DEFAULT_THICKNESS,
    FONT_CHOICES,
    EffectKey,
    OverlayColor,
    OverlayConfig,
    ThicknessKey,
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

# ━━━ UI劣化エフェクト (SPEC §3.6) ━━━
SHIFT_BASE_RATIO = 0.002  # RGBシフト基準量 max(1, int(s*0.002))。弱×1 / 強×2
BLOOM_WEAK_RATIO_WHITE = 0.006  # ブルーム弱・白枠の半径 max(1, int(s*0.006))
BLOOM_WEAK_ALPHA_WHITE = 190  # ブルーム弱・白枠の発光層α
BLOOM_WEAK_RATIO_BLACK = 0.005  # ブルーム弱・黒枠は少し抑える
BLOOM_WEAK_ALPHA_BLACK = 160
BLOOM_STRONG_RATIO = 0.008  # ブルーム強の半径 max(1, int(s*0.008))
BLOOM_STRONG_ALPHA = 220  # ブルーム強の発光層のα
PIXEL_SCALE_WEAK = 0.5  # 低解像度化 (弱)。縮小BILINEAR→拡大NEAREST

# プリセット定義: shift 0なし/1弱/2強、bloom none/weak/strong。
# CRT/VHSは画面全体への破壊処理となりコンセプトに合わないため不採用。
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


@lru_cache(maxsize=64)
def _load_font(size: int, font_key: str = DEFAULT_FONT,
               custom_path: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """選択フォントを読み込む。無ければフォールバック。

    lru_cache で同一サイズ・フォントの再読込を避ける (描画結果は同一)。
    カスタムは `custom_path` (絶対パス) を最優先で試し、失敗時は
    組込フォールバックに倒す (例外は出さず `load_default`)。
    """
    tried: list[str] = []
    if custom_path:
        tried.append(custom_path)
    elif font_key in FONT_CHOICES:
        tried.append(f"C:/Windows/Fonts/{FONT_CHOICES[font_key]}")
    else:
        # custom_fontsなしで未知名が来た場合 (旧API直呼び等) は既定名で解決
        tried.append(f"C:/Windows/Fonts/{FONT_CHOICES.get(DEFAULT_FONT, 'arial.ttf')}")
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


def _mono_color(color: OverlayColor | str) -> tuple[int, int, int, int]:
    return (255, 255, 255, 255) if color == "white" else (0, 0, 0, 255)


def _frame_thickness(s: int, thickness: ThicknessKey | str = DEFAULT_THICKNESS) -> int:
    """四隅L字枠の線太さ。大・中・小の比率で切替、最低2px。"""
    ratio = THICKNESS_RATIOS.get(thickness, THICKNESS_RATIOS["medium"])
    return max(MIN_THICKNESS, int(s * ratio))


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
) -> None:
    bat_w = int(s * BAT_W_RATIO)
    bat_h = int(s * BAT_H_RATIO)
    bat_x = margin_x + int(s * BAT_X_OFFSET_RATIO)
    bat_y = margin_y + thickness + int(s * BAT_Y_OFFSET_RATIO)
    bat_t = max(MIN_THICKNESS, int(s * BAT_T_RATIO))
    d.rectangle([bat_x, bat_y, bat_x + bat_w, bat_y + bat_h],
                outline=mono, width=bat_t)
    # 電池の突起 (右側)
    nub_w = int(bat_w * NUB_W_RATIO)
    nub_h = int(bat_h * NUB_H_RATIO)
    nub_x = bat_x + bat_w
    nub_y = bat_y + (bat_h - nub_h) // 2
    d.rectangle([nub_x, nub_y, nub_x + nub_w, nub_y + nub_h],
                fill=mono)
    # 電池残量バー (4本、内幅いっぱいに均等配置)
    pad = bat_t + 1
    avail = bat_w - pad * 2
    if avail <= 0:
        return  # 極小画像では内幅が取れないため残量バーを省略 (外枠・突起は描画済み)
    pitch = avail / BAT_BARS
    bar_w = pitch * 0.5
    for i in range(BAT_BARS):
        bx0 = bat_x + pad + i * pitch
        by0 = bat_y + pad
        bx1 = bx0 + bar_w
        by1 = bat_y + bat_h - pad
        d.rectangle([bx0, by0, bx1, by1], fill=mono)


def _draw_rec_indicator(
    d: ImageDraw.ImageDraw, w: int, s: int,
    margin_x: int, margin_y: int, thickness: int,
    mono: tuple[int, int, int, int], font_key: str,
    custom_fonts: dict[str, str] | None = None,
) -> None:
    rec_font_size = max(MIN_REC_FONT_SIZE, int(s * REC_FONT_RATIO))
    font = _load_font(rec_font_size, font_key, _custom_path_for(font_key, custom_fonts))
    rec_text = "REC"
    # テキスト幅を測って右寄せ配置。anchor="lt" 基準で測ると
    # bbox 原点が (0, 0) に揃い、タイトなインク高さが得られる。
    # anchor="lm" は行ボックス中央(アセンダ〜ディセンダ)のため、
    # ディセンダの大きいフォントで文字が上に浮く。インク中央合わせのため "lt" を使う。
    bbox = d.textbbox((0, 0), rec_text, font=font, anchor="lt")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    dot_r = int(s * DOT_R_RATIO)
    gap = int(s * REC_GAP_RATIO)
    block_w = dot_r * 2 + gap + text_w
    block_x = w - margin_x - int(s * REC_BLOCK_X_OFFSET_RATIO) - block_w
    # 微調整: 一式を少し下へ (短辺360pxで約3px相当、解像度に比例)
    rec_dy = int(s * REC_DY_RATIO)
    block_y = margin_y + thickness + int(s * REC_BLOCK_Y_OFFSET_RATIO) + rec_dy
    # 赤丸とREC文字のインク中央を同じ中心線 cy に揃える。
    # anchor="lt" でタイト上端基準にし、cy - text_h//2 に置くことで
    # フォントのアセンダ/ディセンダ差に依らず幾何中央が一致する。
    row_h = max(text_h, dot_r * 2)
    cy = block_y + row_h // 2
    d.ellipse([block_x, cy - dot_r, block_x + dot_r * 2, cy + dot_r],
              fill=RED)
    # REC文字 (枠色に連動)
    d.text((block_x + dot_r * 2 + gap - bbox[0], cy - text_h // 2 - bbox[1]),
           rec_text, font=font, fill=mono, anchor="lt")


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
) -> None:
    """右下の日時表示。枠色・RECフォントに連動、枠太さには連動しない。

    手入力テキストを単一行・右寄せ(anchor="rb")で描画する。
    空文字・空白のみの場合は何も描画しない。
    """
    if not text or not text.strip():
        return
    font_size = max(MIN_REC_FONT_SIZE, int(s * TIMECODE_FONT_RATIO))
    font = _load_font(font_size, font_key, _custom_path_for(font_key, custom_fonts))
    rec_dy = int(s * REC_DY_RATIO)  # 上下対称の隙間として再利用
    x = w - margin_x - int(s * TIMECODE_X_OFFSET_RATIO)
    y = h - 1 - margin_y - thickness - int(s * TIMECODE_Y_GAP_RATIO) - rec_dy
    d.text((x, y), text, font=font, fill=mono, anchor="rb")


# ━━━ 撮影日時モード (SPEC §3.5) ━━━
# EXIFタグの優先順: DateTimeOriginal → DateTimeDigitized → DateTime(IFD0)。
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
    """写真毎の日文字列を `EXIF→ファイルmtime→固定文` の順で解決する。

    例外は出さず、決まらなければ `fallback` を返す。PNGスクショ等
    EXIFを持たない画像でもmtimeで追従できる (SPEC §3.5)。
    """
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
    """1ch画像を水平シフトする。はみ出しは0クリア (wrapさせない)。

    `ImageChops.offset` は反対端に回り込むため不採用。Affineの逆写像で
    out(x) = in(x + dx) とし、空いた帯を `fillcolor=0` で埋める。
    dx>0 で内容が左へ移動する。
    """
    if dx == 0:
        return ch
    return ch.transform(ch.size, Image.AFFINE, (1, 0, dx, 0, 1, 0),
                        fillcolor=0)


def _apply_rgb_shift(overlay: Image.Image, level: int, s: int) -> Image.Image:
    """色収差: Rを左へ・Bを右へずらす。GとAは固定。level 1=弱 / 2=強。"""
    if level <= 0:
        return overlay
    d = max(1, int(s * SHIFT_BASE_RATIO)) * level
    r, g, b, a = overlay.split()
    return Image.merge("RGBA", (_shift_channel(r, d), g,
                                _shift_channel(b, -d), a))


def _apply_bloom(overlay: Image.Image, strength: str, s: int,
                 color: OverlayColor | str = "white") -> Image.Image:
    """発光: ぼかし複製を背後に敷き、元のUIを上に重ねる。

    弱は枠色で分岐する (白が最適・黒は少し抑える。SPEC §3.6)。
    強は色に依らない。
    """
    if strength == "none":
        return overlay
    if strength == "strong":
        ratio, alpha = BLOOM_STRONG_RATIO, BLOOM_STRONG_ALPHA
    elif color == "black":
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


def apply_ui_effects(overlay: Image.Image, preset: EffectKey | str = DEFAULT_EFFECT,
                     s: int | None = None, color: OverlayColor | str = "white") -> Image.Image:
    """描画済みUIレイヤーにプリセットのエフェクトを適用して返す (SPEC §3.6).

    順序は RGBシフト→ブルーム→低解像度化で固定。順序を変えると
    見た目が変わるため変えないこと。`"off"` は無操作でそのまま返す。
    `color` は枠色で、ブルーム弱の効き分けに使う。
    """
    if preset not in EFFECT_PRESETS:
        raise ValueError(f"unknown effect preset: {preset!r}")
    if preset == "off":
        return overlay
    if s is None:
        s = min(overlay.size)
    p = EFFECT_PRESETS[preset]
    overlay = _apply_rgb_shift(overlay, p["shift"], s)
    overlay = _apply_bloom(overlay, p["bloom"], s, color)
    overlay = _apply_pixelation(overlay, p["pixel_scale"])
    return overlay


def create_rec_overlay(w: int, h: int, color: OverlayColor | str = "black",
                       font_key: str = DEFAULT_FONT,
                       thickness: ThicknessKey | str = DEFAULT_THICKNESS,
                       show_frame: bool = True,
                       show_battery: bool = True,
                       show_rec: bool = True,
                       show_cross: bool = False,
                       show_timecode: bool = False,
                       timecode_text: str = "",
                       effect: EffectKey | str = DEFAULT_EFFECT,
                       custom_fonts: dict[str, str] | None = None) -> Image.Image:
    """指定サイズと同寸の透過オーバーレイ(RGBA)を生成する。

    全パラメータを画像サイズに対する相対値で決めるため、
    512x512 でも 2048x3072 でも見た目が崩れない。
    color: "black" または "white" (赤丸は常に赤のまま)。
    font_key: FONT_CHOICES の表示名または custom_fonts の登録名。
    thickness: "small" | "medium" | "large" (枠太さのみ。小=0.005/中=0.008/大=0.012)。
    show_frame / show_battery / show_rec: 各要素のON/OFF (SPEC §10.2)。
    show_cross: 中央十字のON/OFF (詳細限定・既定OFF)。
    show_timecode / timecode_text: 右下日時のON/OFFと手入力テキスト (SPEC §3.5、既定OFF/空)。
    effect: UI劣化エフェクトのプリセットキー (SPEC §3.6、既定"off")。
    custom_fonts: カスタム表示名→実ファイルの対応 (省略時は空)。
    """
    return create_rec_overlay_with_config(
        w, h, OverlayConfig(color=color, font_key=font_key, thickness=thickness,
                            show_frame=show_frame, show_battery=show_battery,
                            show_rec=show_rec, show_cross=show_cross,
                            show_timecode=show_timecode, timecode_text=timecode_text,
                            effect=effect,
                            custom_fonts=dict(custom_fonts or {})))


def create_rec_overlay_with_config(w: int, h: int, config: OverlayConfig) -> Image.Image:
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    s = min(w, h)  # 基準スケール
    margin = int(s * MARGIN_RATIO)
    margin_x = margin
    margin_y = margin
    arm_len = int(s * ARM_LEN_RATIO)
    thickness = _frame_thickness(s, config.thickness)
    mono = _mono_color(config.color)

    if config.show_frame:
        _draw_corner_frames(d, w, h, s, mono, margin_x, margin_y, arm_len, thickness)
    if config.show_battery:
        _draw_battery(d, s, margin_x, margin_y, thickness, mono)
    if config.show_rec:
        _draw_rec_indicator(d, w, s, margin_x, margin_y, thickness, mono,
                            config.font_key, config.custom_fonts)
    if config.show_cross:
        _draw_center_cross(d, w, h, s, mono)
    if config.show_timecode:
        _draw_timecode(d, w, h, s, margin_x, margin_y, thickness,
                       mono, config.font_key, config.timecode_text,
                       config.custom_fonts)

    # UI劣化エフェクトはベクター描画の完了後にUI層へ適用し、合成は不変 (SPEC §3.6)。
    # ブルーム弱は枠色で効きを分けるため config.color を渡す。
    if config.effect != "off":
        overlay = apply_ui_effects(overlay, config.effect, s, config.color)

    return overlay


def composite_with_overlay(base: Image.Image, color: OverlayColor | str = "black",
                           font_key: str = DEFAULT_FONT,
                           thickness: ThicknessKey | str = DEFAULT_THICKNESS,
                           show_frame: bool = True,
                           show_battery: bool = True,
                           show_rec: bool = True,
                           show_cross: bool = False,
                           show_timecode: bool = False,
                           timecode_text: str = "",
                           effect: EffectKey | str = DEFAULT_EFFECT,
                           custom_fonts: dict[str, str] | None = None) -> Image.Image:
    """ベース画像にREC枠を合成したRGBA画像を返す。"""
    return composite_with_config(
        base, OverlayConfig(color=color, font_key=font_key, thickness=thickness,
                            show_frame=show_frame, show_battery=show_battery,
                            show_rec=show_rec, show_cross=show_cross,
                            show_timecode=show_timecode, timecode_text=timecode_text,
                            effect=effect,
                            custom_fonts=dict(custom_fonts or {})))


def composite_with_config(base: Image.Image, config: OverlayConfig) -> Image.Image:
    w, h = base.size
    overlay = create_rec_overlay_with_config(w, h, config)
    bg = base.convert("RGBA")
    return Image.alpha_composite(bg, overlay)


def load_base_image(path: str | Path) -> Image.Image:
    """EXIF Orientationを反映して開く (外部ビューア表示と一致させる)。

    これが無いとスマホ写真等でプレビューとビューア表示の向き・比率が食い違う。
    """
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
