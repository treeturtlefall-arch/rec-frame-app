"""逆輸入機能（スコープ1 & 2）の単体・統合テスト。

検証項目:
- 6色プリセットおよびHEXカラー指定（custom_color）の描画
- 半透明座布団（bg_box_opacity）と知覚輝度連動反転色の適用
- 同梱OSSフォント6種の解決と描画
- ドットマーク素材（flat / glow 各色）の読み込みとアルファ合成
- 電池残量（0〜4本）およびREC文字列変更（rec_label）の描画
- 極小画像（短辺 94〜133px）での電池バー内高不足ガード
- レトロエフェクト（0〜6段階）の適用
- 新フィールドを含む設定の保存・復元互換性
"""

from dataclasses import asdict
import pytest
from PIL import Image

from rec_config import (
    ALL_BUILTIN_FONTS,
    BUNDLED_FONT_CHOICES,
    COLOR_PRESETS,
    OverlayConfig,
    discover_dot_assets,
    get_all_dot_styles,
    parse_color_to_rgba,
)
from rec_overlay import (
    RETRO_EFFECT_LEVELS,
    apply_ui_effects,
    composite_with_config,
    create_rec_overlay_with_config,
)


def test_color_presets_and_hex_parsing():
    """6色プリセットとHEXコードの解析が正しく動作すること。"""
    assert len(COLOR_PRESETS) == 6
    for name, hex_val in COLOR_PRESETS.items():
        rgba = parse_color_to_rgba(name)
        assert len(rgba) == 4
        assert rgba[3] == 255

    # HEXパース
    assert parse_color_to_rgba("#ff0000") == (255, 0, 0, 255)
    assert parse_color_to_rgba("#00FF00AA") == (0, 255, 0, 170)
    assert parse_color_to_rgba("invalid") is None


def test_custom_color_overlay_rendering():
    """custom_color にプリセット名またはHEXを指定して描画できること。"""
    base = Image.new("RGB", (640, 480), (40, 40, 40))

    # プリセット名指定
    cfg_red = OverlayConfig(custom_color="red")
    res_red = composite_with_config(base, cfg_red)
    assert res_red.size == (640, 480)

    cfg_cyan = OverlayConfig(custom_color="cyan")
    res_cyan = composite_with_config(base, cfg_cyan)
    assert res_cyan.size == (640, 480)

    # HEX指定
    cfg_hex = OverlayConfig(custom_color="#00FFCC")
    res_hex = composite_with_config(base, cfg_hex)
    assert res_hex.size == (640, 480)


def test_bundled_fonts_exist_and_render():
    """同梱OSSフォント6種すべてが解決され、正常に描画できること。"""
    assert len(BUNDLED_FONT_CHOICES) == 6
    assert len(ALL_BUILTIN_FONTS) == 16  # 既存10 + 同梱6

    base = Image.new("RGB", (640, 480), (100, 100, 100))
    for font_key in BUNDLED_FONT_CHOICES:
        cfg = OverlayConfig(font_key=font_key)
        out = composite_with_config(base, cfg)
        assert out.size == (640, 480)


def test_dot_assets_discovery_and_rendering():
    """ドット素材が正しく発見され、クラシックおよび素材スタイルで描画できること。"""
    assets = discover_dot_assets()
    styles = get_all_dot_styles()

    assert "classic" in styles
    # assets/dots に 10 ファイル (flat 5 + glow 5) があること
    assert len(assets) == 10
    assert "glow_red" in styles
    assert "flat_green" in styles

    base = Image.new("RGB", (640, 480), (30, 30, 30))

    # glow_red で描画
    cfg_glow = OverlayConfig(dot_style="glow_red")
    out_glow = composite_with_config(base, cfg_glow)
    assert out_glow.size == (640, 480)

    # 不明なスタイル時のフォールバック (classic)
    cfg_fallback = OverlayConfig(dot_style="unknown_dot_style")
    out_fb = composite_with_config(base, cfg_fallback)
    assert out_fb.size == (640, 480)


def test_bg_box_opacity_and_contrast():
    """半透明座布団が有効な場合、文字と対比した背景色が敷かれて描画されること。"""
    base = Image.new("RGB", (640, 480), (128, 128, 128))

    # 白文字（高輝度） -> 座布団は黒半透明
    cfg_white = OverlayConfig(custom_color="white", bg_box_opacity=0.5)
    out_white = composite_with_config(base, cfg_white)
    assert out_white.size == (640, 480)

    # 黒文字（低輝度） -> 座布団は白半透明
    cfg_black = OverlayConfig(custom_color="black", bg_box_opacity=0.5)
    out_black = composite_with_config(base, cfg_black)
    assert out_black.size == (640, 480)


def test_battery_bars_variation():
    """電池残量 0〜4 本で正常に描画できること。"""
    base = Image.new("RGB", (640, 480), (50, 50, 50))
    for bars in [0, 1, 2, 3, 4]:
        cfg = OverlayConfig(battery_bars=bars)
        out = composite_with_config(base, cfg)
        assert out.size == (640, 480)


def test_rec_label_customization():
    """REC文字を自由文字列に変更して描画できること。"""
    base = Image.new("RGB", (640, 480), (50, 50, 50))
    for label in ["REC", "LIVE", "STBY", "PLAY", ""]:
        cfg = OverlayConfig(rec_label=label)
        out = composite_with_config(base, cfg)
        assert out.size == (640, 480)


def test_tiny_image_battery_guard():
    """短辺が 94〜133px の極小画像でも電池バー内高不足ガードによりクラッシュしないこと。"""
    for size in [(94, 94), (100, 120), (133, 200)]:
        base = Image.new("RGB", size, (20, 20, 20))
        cfg = OverlayConfig(battery_bars=3)
        out = composite_with_config(base, cfg)
        assert out.size == size


def test_retro_effect_levels():
    """レトロエフェクト（0〜6段階）が正常に適用できること。"""
    assert len(RETRO_EFFECT_LEVELS) == 7
    overlay = Image.new("RGBA", (400, 300), (255, 255, 255, 200))

    for lvl in range(7):
        processed = apply_ui_effects(overlay, preset=lvl)
        assert processed.size == (400, 300)
        assert processed.mode == "RGBA"


def test_config_roundtrip_with_new_fields():
    """新フィールドを含む設定の保存・復元が完全に行えること。"""
    cfg = OverlayConfig(
        color="white",
        custom_color="#00EEFF",
        retro_effect=3,
        bg_box_opacity=0.45,
        dot_style="glow_amber",
        rec_label="RECORDING",
        show_red_dot=True,
        battery_bars=2,
        margin_ratio=0.035,
        arm_len_ratio=0.20,
    )
    d = asdict(cfg)
    assert d["custom_color"] == "#00EEFF"
    assert d["retro_effect"] == 3
    assert d["bg_box_opacity"] == 0.45
    assert d["dot_style"] == "glow_amber"
    assert d["rec_label"] == "RECORDING"
    assert d["battery_bars"] == 2
    assert d["margin_ratio"] == 0.035
    assert d["arm_len_ratio"] == 0.20

    restored = OverlayConfig.from_dict(d)
    assert restored.custom_color == "#00EEFF"
    assert restored.retro_effect == 3
    assert restored.bg_box_opacity == 0.45
    assert restored.dot_style == "glow_amber"
    assert restored.rec_label == "RECORDING"
    assert restored.battery_bars == 2
    assert restored.margin_ratio == 0.035
    assert restored.arm_len_ratio == 0.20


def test_ui_reflects_new_features(monkeypatch):
    """UIの各コントロール変更が _current_config() に正確に反映されること。"""
    import rec_frame_app
    import tkinter as tk

    monkeypatch.setattr(rec_frame_app, "load_user_config", OverlayConfig)
    monkeypatch.setattr(rec_frame_app, "save_user_config", lambda _config: None)

    try:
        app = rec_frame_app.App()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")

    try:
        app.withdraw()
        app.mode_var.set("detail")  # 詳細設定項目を _current_config() に反映させるため
        app.rec_label_var.set("TESTING")
        app.battery_bars_var.set(1)
        app.bg_box_opacity_var.set(0.6)
        app.dot_style_var.set("glow_red")
        app.retro_effect_var.set(4)

        cfg = app._current_config()
        assert cfg.rec_label == "TESTING"
        assert cfg.battery_bars == 1
        assert cfg.bg_box_opacity == 0.6
        assert cfg.dot_style == "glow_red"
        assert cfg.retro_effect == 4
    finally:
        for job in app.tk.call("after", "info"):
            try:
                app.after_cancel(job)
            except tk.TclError:
                pass
        app.destroy()

