"""UI劣化エフェクト (SPEC §3.6) の自動化。

- OFFは無操作・同寸RGBA
- RGBシフトは反対端に回り込まない (wrapなし)
- ブルームは発光域を広げる
- ブルーム弱は枠色で分岐する (白>黒)
- 低解像度化の基本性質
- プリセット定義とConfig (schema_version=8) の互換
"""
import pytest
from PIL import Image

from rec_config import EFFECT_CHOICES, OverlayConfig
from rec_overlay import (
    EFFECT_PRESETS,
    _apply_bloom,
    _apply_pixelation,
    _apply_rgb_shift,
    apply_ui_effects,
    composite_with_overlay,
    create_rec_overlay,
)

PRESETS = ["off", "oled", "2000s"]


def test_effect_choices_cover_presets():
    assert set(EFFECT_CHOICES.values()) == set(EFFECT_PRESETS) == set(PRESETS)
    assert OverlayConfig().effect == "off"


def test_off_is_noop():
    ov = create_rec_overlay(640, 360, effect="off")
    plain = create_rec_overlay(640, 360)
    assert ov.tobytes() == plain.tobytes()
    assert apply_ui_effects(ov, "off").tobytes() == ov.tobytes()


def test_all_off_with_effect_stays_transparent():
    """全要素OFF＋エフェクト: UI由来ピクセルがないため透明のまま。"""
    ov = create_rec_overlay(640, 360, show_frame=False, show_battery=False,
                            show_rec=False, show_cross=False,
                            show_timecode=False, timecode_text="",
                            effect="2000s")
    assert ov.getbbox() is None


def test_unknown_preset_raises():
    ov = create_rec_overlay(640, 360)
    with pytest.raises(ValueError):
        apply_ui_effects(ov, "no-such-preset")


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("size", [(640, 360), (300, 500)])
def test_all_presets_same_size_rgba(preset, size):
    w, h = size
    ov = create_rec_overlay(w, h, effect=preset)
    assert ov.mode == "RGBA"
    assert ov.size == (w, h)
    assert ov.getbbox() is not None  # いずれも何か描画される


def test_non_off_presets_differ_from_clean():
    clean = create_rec_overlay(640, 360, effect="off")
    for preset in ("oled", "2000s"):
        assert create_rec_overlay(640, 360, effect=preset).tobytes() != clean.tobytes(), preset


def test_shift_does_not_wrap():
    """R左シフトで消えた分が右端に回り込まない (offset採用時の欠陥の回帰)。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.putpixel((0, 32), (255, 255, 255, 255))
    out = _apply_rgb_shift(img, 1, 64)  # d = max(1, int(64*0.002)) = 1
    px = out.load()
    assert px[0, 32][:3] == (0, 255, 0)  # Rだけ左へ抜け、Gが残る
    assert px[63, 32][3] == 0  # 右端に回り込みなし
    assert px[1, 32][3] == 0  # Bは右へ1pxずれる


def test_shift_strong_moves_further_than_weak():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.putpixel((10, 32), (255, 255, 255, 255))
    weak = _apply_rgb_shift(img, 1, 64)
    strong = _apply_rgb_shift(img, 2, 64)
    assert weak.tobytes() != strong.tobytes()
    # 強はRが2px左へ: x=8にRが残る
    assert strong.load()[8, 32][0] == 255
    assert weak.load()[8, 32][0] == 0


def test_bloom_expands_glow_area():
    img = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    img.putpixel((48, 48), (255, 255, 255, 255))
    before = img.getbbox()
    after = _apply_bloom(img, "weak", 96).getbbox()
    assert after is not None and before is not None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    assert area(after) > area(before)
    strong = _apply_bloom(img, "strong", 96)
    assert strong.tobytes() != _apply_bloom(img, "weak", 96).tobytes()


def test_bloom_none_is_noop():
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    img.putpixel((16, 16), (255, 0, 0, 255))
    assert _apply_bloom(img, "none", 32).tobytes() == img.tobytes()


def test_bloom_weak_branches_by_color():
    """OLED弱は白>黒の効き。既定は白と等価 (後方互換)。

    1px点光源はぼかしでαが0に丸められ消えることがあるため、
    20px角の面光源で比較する。
    """
    from PIL import ImageDraw
    img = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([490, 490, 510, 510],
                                  fill=(255, 255, 255, 255))
    black = _apply_bloom(img, "weak", 1000, "black")
    white = _apply_bloom(img, "weak", 1000, "white")
    assert white.tobytes() != black.tobytes()
    area = lambda im: (lambda b: (b[2] - b[0]) * (b[3] - b[1]))(im.getbbox())
    assert area(white) > area(black)
    assert _apply_bloom(img, "weak", 1000).tobytes() == white.tobytes()


def test_oled_threads_frame_color():
    """黒枠OLEDは黒用パラメータで処理される (配線の回帰)。"""
    clean = create_rec_overlay(640, 360, color="black", effect="off")
    oled = create_rec_overlay(640, 360, color="black", effect="oled")
    assert oled.tobytes() == _apply_bloom(clean, "weak", 360, "black").tobytes()


def test_pixelation_keeps_size_and_jags():
    ov = create_rec_overlay(640, 360)
    out = _apply_pixelation(ov, 0.5)
    assert out.size == (640, 360)
    assert out.tobytes() != ov.tobytes()
    assert _apply_pixelation(ov, 1.0).tobytes() == ov.tobytes()


def test_effect_changes_composite_output():
    base = Image.new("RGB", (640, 360), (0, 128, 255))
    clean = composite_with_overlay(base, effect="off")
    retro = composite_with_overlay(base, effect="2000s")
    assert retro.size == (640, 360)
    assert retro.tobytes() != clean.tobytes()


def test_config_effect_dict_roundtrip_schema7():
    cfg = OverlayConfig(effect="oled")
    d = cfg.to_dict()
    assert d["schema_version"] == 8
    assert d["effect"] == "oled"
    assert OverlayConfig.from_dict(d) == cfg


def test_config_from_dict_backward_compat_without_effect():
    """effectなしの旧JSON (v4以前) はOFFとして読める。"""
    cfg = OverlayConfig.from_dict({"color": "white", "font_key": "Arial(標準)",
                                   "thickness": "large", "show_cross": True,
                                   "show_timecode": True,
                                   "timecode_text": "2026/09/14 PM 08:30"})
    assert cfg.effect == "off"


def test_config_effect_validation():
    OverlayConfig(effect="oled")
    with pytest.raises(ValueError):
        OverlayConfig(effect="vhs")
