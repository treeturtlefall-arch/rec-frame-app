"""SPEC.md §6 検証済み項目 + §9 ロードマップの自動化。

- 同寸出力・枠位置正常 (6サイズ)
- 四隅の端距離ピクセル一致
- 10フォント全描画・赤丸との中心合わせ維持
"""
import pytest
from PIL import Image

from rec_config import FONT_CHOICES, OverlayConfig, compose_timecode_text
from rec_overlay import (
    MARGIN_RATIO,
    THICKNESS_RATIOS,
    _frame_thickness,
    composite_with_overlay,
    create_rec_overlay,
    prepare_image_for_save,
)

from tests.conftest import (
    BLACK,
    RED,
    TRANSPARENT,
    VERIFIED_SIZES,
    WHITE,
    count_color,
)

_count_color = count_color


@pytest.mark.parametrize("w,h", VERIFIED_SIZES)
@pytest.mark.parametrize("color", ["black", "white"])
def test_output_same_size(w, h, color):
    ov = create_rec_overlay(w, h, color=color)
    assert ov.mode == "RGBA"
    assert ov.size == (w, h)


@pytest.mark.parametrize("w,h", VERIFIED_SIZES)
def test_composite_same_size_rgba(w, h):
    base = Image.new("RGB", (w, h), (0, 128, 255))
    out = composite_with_overlay(base)
    assert out.mode == "RGBA"
    assert out.size == (w, h)


def test_corners_equidistant_640x360():
    """SPEC §3.1: 640x360で四隅とも端距離10/10。右・下端は-1補正で一致。"""
    w, h = 640, 360
    s = min(w, h)
    margin = int(s * MARGIN_RATIO)
    assert margin == 10
    ov = create_rec_overlay(w, h, color="black")
    px = ov.load()
    # 四隅L字の起点ピクセルは枠色で不透明
    assert px[margin, margin] == BLACK  # 左上
    assert px[w - 1 - margin, margin] == BLACK  # 右上
    assert px[margin, h - 1 - margin] == BLACK  # 左下
    assert px[w - 1 - margin, h - 1 - margin] == BLACK  # 右下
    # 1px外側は透明 (端距離の裏付け)
    assert px[margin - 1, margin] == TRANSPARENT
    assert px[margin, margin - 1] == TRANSPARENT


@pytest.mark.parametrize("w,h", VERIFIED_SIZES)
def test_corners_equidistant_generic(w, h):
    s = min(w, h)
    margin = int(s * MARGIN_RATIO)
    ov = create_rec_overlay(w, h, color="black")
    px = ov.load()
    assert px[margin, margin][:3] == (0, 0, 0)
    assert px[w - 1 - margin, margin][:3] == (0, 0, 0)
    assert px[margin, h - 1 - margin][:3] == (0, 0, 0)
    assert px[w - 1 - margin, h - 1 - margin][:3] == (0, 0, 0)


def test_all_fonts_render():
    """10フォント全描画OK。各フォントでオーバーレイが空でないこと。"""
    assert len(FONT_CHOICES) == 10
    for key in FONT_CHOICES:
        ov = create_rec_overlay(640, 360, font_key=key)
        assert ov.size == (640, 360)
        # 何か描画されている (全透明でない)
        assert ov.getbbox() is not None, key



def test_red_dot_always_red():
    """赤丸は枠色切替に連動せず常に赤。"""
    for color in ("black", "white"):
        ov = create_rec_overlay(640, 360, color=color)
        assert _count_color(ov, RED) > 0, color


def test_color_switch_affects_frame_not_red():
    black_ov = create_rec_overlay(640, 360, color="black")
    white_ov = create_rec_overlay(640, 360, color="white")
    assert black_ov.tobytes() != white_ov.tobytes()
    assert _count_color(black_ov, BLACK) > 0
    assert _count_color(black_ov, WHITE) == 0
    assert _count_color(white_ov, WHITE) > 0
    assert _count_color(white_ov, BLACK) == 0
    # 赤は両方に存在
    assert _count_color(black_ov, RED) > 0
    assert _count_color(white_ov, RED) > 0


def test_center_stays_transparent():
    ov = create_rec_overlay(640, 360)
    assert ov.load()[320, 180] == TRANSPARENT


def test_config_validation():
    OverlayConfig(color="black")
    OverlayConfig(color="white")
    with pytest.raises(ValueError):
        OverlayConfig(color="red")
    with pytest.raises(ValueError):
        OverlayConfig(font_key="no-such-font")


def test_config_dict_roundtrip():
    cfg = OverlayConfig(color="white", font_key="Impact(凝縮テロップ風)")
    d = cfg.to_dict()
    assert d["color"] == "white"
    assert OverlayConfig.from_dict(d) == cfg


def test_prepare_image_for_save_jpeg_converts_rgb(tmp_path):
    img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    out_jpg = prepare_image_for_save(img, tmp_path / "a.jpg")
    assert out_jpg.mode == "RGB"
    out_png = prepare_image_for_save(img, tmp_path / "a.png")
    assert out_png.mode == "RGBA"


# --- 枠太さ 大・中・小 ---

def test_thickness_ratios_defined():
    assert THICKNESS_RATIOS == {"small": 0.005, "medium": 0.008, "large": 0.012}


def test_frame_thickness_values():
    # 1080p: 小5 / 中8 / 大12
    assert _frame_thickness(1080, "small") == 5
    assert _frame_thickness(1080, "medium") == 8
    assert _frame_thickness(1080, "large") == 12
    # 360p: 小は最低2pxで中と同値、大は4
    assert _frame_thickness(360, "small") == 2
    assert _frame_thickness(360, "medium") == 2
    assert _frame_thickness(360, "large") == 4


@pytest.mark.parametrize("thickness", ["small", "medium", "large"])
@pytest.mark.parametrize("w,h", VERIFIED_SIZES)
def test_thickness_output_same_size(w, h, thickness):
    ov = create_rec_overlay(w, h, thickness=thickness)
    assert ov.mode == "RGBA"
    assert ov.size == (w, h)
    assert ov.getbbox() is not None


@pytest.mark.parametrize("thickness", ["small", "medium", "large"])
def test_thickness_corners_equidistant(thickness):
    """太さを変えても四隅の端距離は不変。"""
    w, h = 640, 360
    s = min(w, h)
    margin = int(s * MARGIN_RATIO)
    ov = create_rec_overlay(w, h, color="black", thickness=thickness)
    px = ov.load()
    assert px[margin, margin][:3] == (0, 0, 0)
    assert px[w - 1 - margin, margin][:3] == (0, 0, 0)
    assert px[margin, h - 1 - margin][:3] == (0, 0, 0)
    assert px[w - 1 - margin, h - 1 - margin][:3] == (0, 0, 0)


def test_thickness_large_has_more_pixels():
    """大>中>小の順に枠ピクセルが増える (1920x1080で差が明確)。"""
    small = create_rec_overlay(1920, 1080, color="black", thickness="small")
    medium = create_rec_overlay(1920, 1080, color="black", thickness="medium")
    large = create_rec_overlay(1920, 1080, color="black", thickness="large")
    assert _count_color(small, BLACK) < _count_color(medium, BLACK)
    assert _count_color(medium, BLACK) < _count_color(large, BLACK)


def test_thickness_default_is_medium():
    default = create_rec_overlay(640, 360)
    medium = create_rec_overlay(640, 360, thickness="medium")
    assert default.tobytes() == medium.tobytes()


def test_config_thickness_validation():
    OverlayConfig(thickness="small")
    OverlayConfig(thickness="medium")
    OverlayConfig(thickness="large")
    with pytest.raises(ValueError):
        OverlayConfig(thickness="x-large")


def test_config_thickness_dict_roundtrip():
    cfg = OverlayConfig(color="white", thickness="large")
    d = cfg.to_dict()
    assert d["thickness"] == "large"
    assert OverlayConfig.from_dict(d) == cfg


def test_config_from_dict_backward_compat_without_thickness():
    """旧設定JSON {color, font_key} は中として読める。"""
    cfg = OverlayConfig.from_dict({"color": "white", "font_key": "Arial(標準)"})
    assert cfg.thickness == "medium"


# --- 簡易/詳細モード: 要素ON/OFF (SPEC §10.2) ---

def test_config_show_defaults_true():
    cfg = OverlayConfig()
    assert (cfg.show_frame, cfg.show_battery, cfg.show_rec) == (True, True, True)


def test_config_show_validation():
    with pytest.raises(ValueError):
        OverlayConfig(show_frame="yes")


def test_config_show_dict_roundtrip():
    cfg = OverlayConfig(show_frame=False, show_battery=False, show_rec=True)
    d = cfg.to_dict()
    assert d["schema_version"] == 8
    assert (d["show_frame"], d["show_battery"], d["show_rec"]) == (False, False, True)
    assert OverlayConfig.from_dict(d) == cfg


def test_config_from_dict_backward_compat_without_show():
    """旧JSON (show_*なし) は全ONとして読める。"""
    cfg = OverlayConfig.from_dict({"color": "white", "font_key": "Arial(標準)",
                                   "thickness": "large"})
    assert (cfg.show_frame, cfg.show_battery, cfg.show_rec) == (True, True, True)


def test_hide_frame_removes_corners_keeps_others():
    full = create_rec_overlay(640, 360, color="black")
    assert full.load()[10, 10] == BLACK
    ov = create_rec_overlay(640, 360, color="black", show_frame=False)
    assert ov.size == (640, 360)
    assert ov.load()[10, 10] == TRANSPARENT  # 四隅が消える
    assert ov.load()[21, 25] == BLACK  # 電池バーは残る
    assert _count_color(ov, RED) > 0  # RECは残る


def test_hide_battery_removes_bars_keeps_frame():
    ov = create_rec_overlay(640, 360, color="black", show_battery=False)
    assert ov.load()[21, 25] == TRANSPARENT  # 電池バー域が消える
    assert ov.load()[10, 10] == BLACK  # 枠は残る
    assert _count_color(ov, RED) > 0


def test_hide_rec_removes_red_keeps_frame():
    ov = create_rec_overlay(640, 360, color="black", show_rec=False)
    assert _count_color(ov, RED) == 0
    assert ov.load()[10, 10] == BLACK
    assert ov.load()[21, 25] == BLACK


def test_all_off_transparent_and_composite_is_base():
    ov = create_rec_overlay(640, 360, show_frame=False,
                            show_battery=False, show_rec=False)
    assert ov.getbbox() is None
    base = Image.new("RGB", (640, 360), (0, 128, 255))
    out = composite_with_overlay(base, show_frame=False,
                                 show_battery=False, show_rec=False)
    assert out.size == (640, 360)
    assert out.convert("RGB").tobytes() == base.tobytes()


# --- 中央十字 (詳細限定・既定OFF) ---

def test_config_cross_default_false():
    assert OverlayConfig().show_cross is False


def test_config_cross_dict_roundtrip():
    cfg = OverlayConfig(show_cross=True)
    d = cfg.to_dict()
    assert d["show_cross"] is True
    assert OverlayConfig.from_dict(d) == cfg


def test_config_from_dict_backward_compat_without_cross():
    """show_crossなしの旧JSON (v2以前) はOFFとして読める。"""
    cfg = OverlayConfig.from_dict({"color": "black", "thickness": "medium",
                                   "show_frame": True, "show_battery": True,
                                   "show_rec": True})
    assert cfg.show_cross is False
    legacy = OverlayConfig.from_dict({"color": "white", "font_key": "Arial(標準)"})
    assert legacy.show_cross is False


def test_cross_off_keeps_center_transparent():
    ov = create_rec_overlay(640, 360)
    assert ov.load()[320, 180] == TRANSPARENT


def test_cross_on_draws_center_pixel():
    ov = create_rec_overlay(640, 360, color="black", show_cross=True)
    assert ov.size == (640, 360)
    assert ov.load()[320, 180] == BLACK


def test_cross_line_is_thin():
    """中央十字は枠より細い線幅 (640x360で1px。対角隣は透明)。"""
    ov = create_rec_overlay(640, 360, color="black", show_cross=True)
    assert ov.load()[321, 181] == TRANSPARENT
    assert ov.load()[332, 180] == BLACK  # 腕の長さは不変


def test_cross_follows_mono_color():
    black = create_rec_overlay(640, 360, color="black", show_cross=True)
    white = create_rec_overlay(640, 360, color="white", show_cross=True)
    assert black.load()[320, 180] == BLACK
    assert white.load()[320, 180] == WHITE


@pytest.mark.parametrize("thickness", ["small", "medium", "large"])
def test_cross_independent_of_thickness(thickness):
    """中央十字は枠太さに連動しない (中心ピクセルは常に枠色)。"""
    ov = create_rec_overlay(640, 360, color="black",
                            thickness=thickness, show_cross=True)
    assert ov.load()[320, 180] == BLACK


# --- 日時表示 (右下・詳細限定・既定OFF・手入力、SPEC §3.5) ---

SAMPLE_TIMECODE = "2026/09/14 PM 08:30"


def _timecode_only(color="black", text=SAMPLE_TIMECODE, show=True):
    return create_rec_overlay(640, 360, color=color,
                              show_frame=False, show_battery=False,
                              show_rec=False, show_cross=False,
                              show_timecode=show, timecode_text=text)


def test_config_timecode_defaults():
    cfg = OverlayConfig()
    assert cfg.show_timecode is False
    assert cfg.timecode_text == ""


def test_config_timecode_validation():
    with pytest.raises(ValueError):
        OverlayConfig(show_timecode="yes")
    with pytest.raises(ValueError):
        OverlayConfig(timecode_text=123)


def test_config_timecode_dict_roundtrip():
    cfg = OverlayConfig(show_timecode=True, timecode_text=SAMPLE_TIMECODE)
    d = cfg.to_dict()
    assert d["schema_version"] == 8
    assert d["show_timecode"] is True
    assert d["timecode_text"] == SAMPLE_TIMECODE
    assert OverlayConfig.from_dict(d) == cfg


def test_config_from_dict_backward_compat_without_timecode():
    """timecodeなしの旧JSON (v3以前) はOFF・空として読める。"""
    cfg = OverlayConfig.from_dict({"color": "black", "thickness": "medium",
                                   "show_frame": True, "show_battery": True,
                                   "show_rec": True, "show_cross": False})
    assert cfg.show_timecode is False
    assert cfg.timecode_text == ""
    legacy = OverlayConfig.from_dict({"color": "white", "font_key": "Arial(標準)"})
    assert (legacy.show_timecode, legacy.timecode_text) == (False, "")


def test_timecode_off_keeps_overlay_transparent():
    ov = _timecode_only(show=False)
    assert ov.getbbox() is None


def test_timecode_empty_text_draws_nothing():
    for text in ("", "   "):
        ov = _timecode_only(show=True, text=text)
        assert ov.getbbox() is None, repr(text)


def test_timecode_on_draws_bottom_right():
    ov = _timecode_only(show=True)
    assert ov.getbbox() is not None
    px = ov.load()
    w, h = 640, 360
    # 他要素OFFのため左上・中央は透明のまま
    assert px[10, 10] == TRANSPARENT
    assert px[w // 2, h // 2] == TRANSPARENT
    # 右下一帯のどこかに不透明ピクセルがある
    assert any(px[x, y][3] != 0
               for x in range(w - 260, w - 10)
               for y in range(h - 45, h - 10))


def test_timecode_follows_mono_color():
    black = _timecode_only(color="black")
    white = _timecode_only(color="white")
    assert black.tobytes() != white.tobytes()
    assert _count_color(black, BLACK) > 0
    assert _count_color(black, WHITE) == 0
    assert _count_color(white, WHITE) > 0
    assert _count_color(white, BLACK) == 0


# --- 日時選択式の合成 (SPEC §10.3、検証緩和) ---

def test_compose_timecode_basic():
    assert compose_timecode_text(2026, 9, 14, "PM", 8, 30) == "2026/09/14 PM 08:30"


def test_compose_timecode_relaxed_no_calendar_check():
    """1800年・2月30日もそのまま通す (SF利用想定)。"""
    assert compose_timecode_text(1800, 2, 30, "AM", 12, 5) == "1800/02/30 AM 12:05"


def test_compose_timecode_accepts_strings():
    """Spinbox.get() の文字列をそのまま受け付ける。"""
    assert compose_timecode_text("2026", "9", "14", "PM", "8", "30") == "2026/09/14 PM 08:30"


def test_compose_timecode_invalid_raises():
    with pytest.raises(ValueError):
        compose_timecode_text("", 9, 14, "PM", 8, 30)


def test_composed_text_renders():
    """合成文がそのまま描画できる (全OFF＋日時のみ)。"""
    ov = create_rec_overlay(640, 360, show_frame=False, show_battery=False,
                            show_rec=False, show_cross=False, show_timecode=True,
                            timecode_text=compose_timecode_text(1800, 2, 30, "AM", 12, 5))
    assert ov.getbbox() is not None


# --- 赤丸＋RECの中央合わせ (インク中央、SPEC §3.3) ---

def _rec_only_vertical_diff(w, h, font_key, color="white"):
    """REC単独表示での赤丸中央と文字インク中央の垂直差を返す。

    他要素OFFのため右上ROIのみ走査する。anchor="lm"(行中央)時代は
    Bebas/Consolas等で-6px超のズレが出た。修正後は整数丸め±1px以内。
    """
    ov = create_rec_overlay(w, h, color=color, font_key=font_key,
                            show_frame=False, show_battery=False,
                            show_rec=True, show_cross=False,
                            show_timecode=False)
    s = min(w, h)
    x0 = max(0, w - int(s * 0.35) - 50)
    y1 = min(h, int(s * 0.25) + 50)
    px = ov.load()
    red_ys, txt_ys = [], []
    for y in range(0, y1):
        for x in range(x0, w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r > 200 and g < 80 and b < 80:
                red_ys.append(y)
            elif color == "white" and r > 200 and g > 200 and b > 200:
                txt_ys.append(y)
            elif color == "black" and r < 80 and g < 80 and b < 80:
                txt_ys.append(y)
    assert red_ys, f"no red dot: {w}x{h} {font_key}"
    assert txt_ys, f"no REC text: {w}x{h} {font_key}"
    return (min(txt_ys) + max(txt_ys)) / 2 - (min(red_ys) + max(red_ys)) / 2


@pytest.mark.parametrize("font_key", list(FONT_CHOICES))
@pytest.mark.parametrize("w,h", [(640, 360), (1920, 1080)])
def test_rec_dot_text_vertically_centered(w, h, font_key):
    assert abs(_rec_only_vertical_diff(w, h, font_key)) <= 1.0


# --- 極小画像 (短辺約93px以下、SPEC §1「どんな解像度でも」) ---

@pytest.mark.parametrize("w,h", [(64, 48), (48, 48), (32, 32), (16, 16)])
@pytest.mark.parametrize("color", ["black", "white"])
def test_tiny_images_composite_without_error(w, h, color):
    """極小画像でも落ちない。電池残量バーは内幅不足で省略される。"""
    base = Image.new("RGB", (w, h), (200, 30, 30))
    out = composite_with_overlay(base, color=color)
    assert out.size == (w, h)


@pytest.mark.parametrize("w,h", [(64, 48), (48, 48), (32, 32), (16, 16)])
def test_tiny_images_with_all_effects(w, h):
    """極小画像×全エフェクト×詳細全ONでも落ちない (smokeと同条件)。"""
    base = Image.new("RGB", (w, h), (200, 30, 30))
    out = composite_with_overlay(
        base, color="white", show_cross=True, show_timecode=True,
        timecode_text="2026/09/16 PM 08:30", effect="2000s")
    assert out.size == (w, h)
