"""設定の自動記憶 (UI追加なし) のテスト。"""
import json

from rec_config import (
    OverlayConfig,
    compose_timecode_text,
    get_user_config_path,
    is_simple_equivalent,
    load_user_config,
    parse_timecode_text,
    save_user_config,
)


def test_user_config_path_suffix():
    p = get_user_config_path()
    assert p.name == "config.json"
    assert p.parent.name == "rec-frame-app"


def test_roundtrip_preserves_all_fields(tmp_path):
    target = tmp_path / "config.json"
    cfg = OverlayConfig(
        color="white", font_key="Impact(凝縮テロップ風)", thickness="large",
        show_frame=False, show_battery=False, show_rec=True,
        show_cross=True, show_timecode=True,
        timecode_text="2026/09/14 PM 08:30", effect="oled")
    assert save_user_config(cfg, target) == target
    assert load_user_config(target) == cfg


def test_missing_file_returns_defaults(tmp_path):
    assert load_user_config(tmp_path / "nope.json") == OverlayConfig()


def test_corrupted_json_returns_defaults(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{not json", encoding="utf-8")
    assert load_user_config(target) == OverlayConfig()


def test_non_dict_json_returns_defaults(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("[1, 2]", encoding="utf-8")
    assert load_user_config(target) == OverlayConfig()


def test_invalid_values_return_defaults(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"color": "red", "thickness": "huge"}), encoding="utf-8")
    assert load_user_config(target) == OverlayConfig()


def test_old_json_reads_as_simple_equivalent(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"color": "white", "font_key": "Consolas(等幅)"}), encoding="utf-8")
    cfg = load_user_config(target)
    assert cfg.color == "white"
    assert cfg.font_key == "Consolas(等幅)"
    assert cfg.thickness == "medium"
    assert is_simple_equivalent(cfg)


def test_is_simple_equivalent():
    assert is_simple_equivalent(OverlayConfig())
    assert not is_simple_equivalent(OverlayConfig(show_frame=False))
    assert not is_simple_equivalent(OverlayConfig(show_cross=True))
    assert not is_simple_equivalent(OverlayConfig(show_timecode=True))


def test_parse_timecode_text_valid():
    assert parse_timecode_text("2026/09/14 PM 08:30") == (2026, 9, 14, "PM", 8, 30)
    assert parse_timecode_text("  1800/2/5 AM 1:05  ") == (1800, 2, 5, "AM", 1, 5)


def test_parse_timecode_text_invalid():
    assert parse_timecode_text("") is None
    assert parse_timecode_text("invalid") is None
    assert parse_timecode_text("2026-09-14 20:30") is None
    assert parse_timecode_text("2026/09/14 XX 08:30") is None


def test_timecode_compose_and_parse_roundtrip():
    original = compose_timecode_text(2026, 9, 14, "PM", 8, 30)
    parsed = parse_timecode_text(original)
    assert parsed == (2026, 9, 14, "PM", 8, 30)
    assert compose_timecode_text(*parsed) == original
