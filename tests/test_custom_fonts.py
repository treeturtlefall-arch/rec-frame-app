"""カスタムフォント (SPEC §5) の自動化。

- 組込10種は不変・カスタムは OverlayConfig.custom_fonts に保存 (schema v6)
- 旧JSON (custom_fontsなし) は空として読める
- font_keyは組込or登録済みカスタムのみ許可
- 実ファイルがあれば描画に使われ、欠落してもフォールバックで落ちない
"""
import json
import shutil

import pytest
from PIL import ImageFont

from rec_config import (
    CONFIG_SCHEMA_VERSION,
    CUSTOM_FONT_EXTENSIONS,
    DEFAULT_FONT,
    FONT_CHOICES,
    OverlayConfig,
    get_all_font_names,
    get_font_browse_start_dir,
    get_system_font_dirs,
    load_user_config,
    resolve_custom_font_path,
    sanitize_custom_font_name,
    save_user_config,
    validate_custom_font_file,
)
from rec_overlay import (
    _custom_path_for,
    _load_font,
    create_rec_overlay,
    create_rec_overlay_with_config,
)


def _find_system_ttf():
    """実在するTTFを1件探す。無ければNone (環境依存のskip用)。"""
    import os
    from pathlib import Path

    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return p
    # 最終手段: PIL同梱や一般的な配置を走査
    for root in ("/usr/share/fonts", "C:/Windows/Fonts"):
        base = Path(root)
        if base.exists():
            for ext in (".ttf", ".otf"):
                found = next(base.rglob(f"*{ext}"), None)
                if found is not None:
                    return found
    return None


def test_schema_version_is_8():
    assert CONFIG_SCHEMA_VERSION == 8
    assert OverlayConfig().to_dict()["schema_version"] == 8


def test_builtin_choices_unchanged():
    assert len(FONT_CHOICES) == 10
    assert DEFAULT_FONT in FONT_CHOICES


def test_custom_fonts_default_empty():
    assert OverlayConfig().custom_fonts == {}


def test_old_json_without_custom_fonts_reads_empty(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"color": "white", "font_key": "Arial(標準)"}),
                      encoding="utf-8")
    cfg = load_user_config(target)
    assert cfg.custom_fonts == {}
    assert cfg.font_key == "Arial(標準)"


def test_roundtrip_with_custom_fonts(tmp_path):
    target = tmp_path / "config.json"
    cfg = OverlayConfig(font_key="MyFont",
                        custom_fonts={"MyFont": "C:/fonts/MyFont.ttf"})
    assert save_user_config(cfg, target) == target
    assert load_user_config(target) == cfg


def test_unknown_font_key_rejected():
    with pytest.raises(ValueError):
        OverlayConfig(font_key="no-such-font")


def test_custom_font_key_accepted():
    cfg = OverlayConfig(font_key="MyFont",
                        custom_fonts={"MyFont": "C:/fonts/MyFont.ttf"})
    assert cfg.font_key == "MyFont"


def test_custom_key_colliding_with_builtin_rejected():
    with pytest.raises(ValueError):
        OverlayConfig(font_key="Arial(標準)",
                      custom_fonts={"Arial(標準)": "C:/fonts/X.ttf"})


def test_with_and_without_custom_font(tmp_path):
    src = _find_system_ttf()
    if src is None:
        pytest.skip("no system TTF available")
    cfg = OverlayConfig().with_custom_font("MyTest", src)
    assert cfg.font_key == "MyTest"
    assert cfg.custom_fonts["MyTest"] == str(src)
    assert "MyTest" in get_all_font_names(cfg)
    back = cfg.without_custom_font("MyTest")
    assert back.custom_fonts == {}
    assert back.font_key == DEFAULT_FONT
    with pytest.raises(ValueError):
        OverlayConfig().without_custom_font("Arial(標準)")


def test_sanitize_avoids_builtin_and_duplicates():
    assert sanitize_custom_font_name("Arial(標準)", {}) == "Arial(標準) 2"
    dup = {"MyFont": "a.ttf"}
    assert sanitize_custom_font_name("MyFont", dup) == "MyFont 2"
    assert sanitize_custom_font_name("  ", {}) == "カスタムフォント"


def test_validate_custom_font_file(tmp_path):
    assert validate_custom_font_file(tmp_path / "nope.ttf") is not None
    bad = tmp_path / "font.txt"
    bad.write_text("x", encoding="utf-8")
    assert validate_custom_font_file(bad) is not None
    src = _find_system_ttf()
    if src is None:
        pytest.skip("no system TTF available")
    assert validate_custom_font_file(src) is None
    assert CUSTOM_FONT_EXTENSIONS >= {".ttf", ".otf", ".ttc"}


def test_resolve_custom_font_path():
    cfg = OverlayConfig(font_key="MyFont",
                        custom_fonts={"MyFont": "C:/fonts/MyFont.ttf"})
    assert resolve_custom_font_path("MyFont", cfg.custom_fonts) is not None
    assert resolve_custom_font_path("Arial(標準)", cfg.custom_fonts) is None
    assert resolve_custom_font_path("Gone", cfg.custom_fonts) is None


def test_load_font_uses_custom_file():
    src = _find_system_ttf()
    if src is None:
        pytest.skip("no system TTF available")
    font = _load_font(20, "MyFont", str(src))
    assert isinstance(font, ImageFont.FreeTypeFont)
    # 欠落パスはフォールバック (例外なし)
    fallback = _load_font(20, "Gone", "C:/nope/missing.ttf")
    assert fallback is not None


def test_overlay_with_custom_font_renders():
    src = _find_system_ttf()
    if src is None:
        pytest.skip("no system TTF available")
    cfg = OverlayConfig(font_key="MyFont", custom_fonts={"MyFont": str(src)})
    ov = create_rec_overlay_with_config(640, 360, cfg)
    assert ov.size == (640, 360)
    assert ov.getbbox() is not None


def test_overlay_with_missing_custom_font_falls_back():
    cfg = OverlayConfig(font_key="Gone",
                        custom_fonts={"Gone": "C:/nope/missing.ttf"})
    assert _custom_path_for("Gone", cfg.custom_fonts) is None
    ov = create_rec_overlay_with_config(640, 360, cfg)
    assert ov.size == (640, 360)
    assert ov.getbbox() is not None  # load_defaultで何か描画される


def test_legacy_create_rec_overlay_accepts_custom_fonts_kwarg():
    src = _find_system_ttf()
    if src is None:
        pytest.skip("no system TTF available")
    ov = create_rec_overlay(640, 360, font_key="MyFont",
                            custom_fonts={"MyFont": str(src)})
    assert ov.getbbox() is not None


def test_system_font_dirs_only_existing():
    dirs = get_system_font_dirs()
    assert isinstance(dirs, list)
    for p in dirs:
        assert p.is_dir()
    start = get_font_browse_start_dir()
    assert start is None or start.is_dir()
    if dirs:
        assert start == dirs[0]


def test_windows_user_fonts_dir_preferred_over_system():
    """Windowsでは通常フォルダのユーザー側を先頭に (システム側は仮想表示で空に見えるため)。"""
    import os

    if os.name != "nt":
        pytest.skip("Windows only")
    from pathlib import Path

    user_dir = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    system_dir = Path("C:/Windows/Fonts")
    if not (user_dir.is_dir() and system_dir.is_dir()):
        pytest.skip("both font dirs required")
    dirs = get_system_font_dirs()
    assert dirs.index(user_dir) < dirs.index(system_dir)
    assert get_font_browse_start_dir() == user_dir


def test_copied_font_file_usable(tmp_path):
    """GUI同様にfonts/へ複写した実体が描画に使えること。"""
    src = _find_system_ttf()
    if src is None:
        pytest.skip("no system TTF available")
    dest = tmp_path / "fonts" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    cfg = OverlayConfig().with_custom_font(dest.stem, dest)
    ov = create_rec_overlay_with_config(320, 200, cfg)
    assert ov.getbbox() is not None
