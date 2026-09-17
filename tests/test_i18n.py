"""日英切替の翻訳カタログ・設定・バッチ・CLI互換を検証する。"""
from __future__ import annotations

import json
import string
import subprocess
import sys
from pathlib import Path

from PIL import Image

from rec_batch import process_folder
from rec_config import (
    CONFIG_SCHEMA_VERSION,
    OverlayConfig,
    load_user_config,
    save_user_config,
    validate_custom_font_file,
)
from rec_i18n import (
    BUILTIN_FONT_LABELS_EN,
    MESSAGES,
    builtin_font_label,
    effect_label,
    normalize_language,
    thickness_label,
    tr,
)
from rec_overlay import composite_with_config


def _fields(template: str) -> set[str]:
    return {name for _text, name, _spec, _conversion
            in string.Formatter().parse(template) if name}


def test_translation_catalogs_have_matching_keys_and_placeholders():
    assert set(MESSAGES["ja"]) == set(MESSAGES["en"])
    for key in MESSAGES["ja"]:
        assert _fields(MESSAGES["ja"][key]) == _fields(MESSAGES["en"][key]), key


def test_language_and_choice_labels_fallback_safely():
    assert normalize_language("en") == "en"
    assert normalize_language("invalid") == "ja"
    assert tr("ja", "language.label") == "Language"
    assert tr("en", "language.label") == "Language"
    assert tr("invalid", "action.open") == "画像を開く…"
    assert thickness_label("large", "en") == "Large"
    assert effect_label("oled", "en") == "OLED (Soft glow)"
    assert builtin_font_label("Consolas(等幅)", "en") == "Consolas (Monospace)"
    assert set(BUILTIN_FONT_LABELS_EN) == {
        "Arial(標準)", "Arial Narrow Bold(細長)", "Arial Black(極太)",
        "Impact(凝縮テロップ風)", "Bahnschrift(工業的)", "Consolas(等幅)",
        "Roboto Condensed", "Montserrat Medium", "Bebas Neue(縦長)",
        "OCRB(計測機器風)",
    }


def test_schema_v8_language_roundtrip_and_old_config_default(tmp_path):
    assert CONFIG_SCHEMA_VERSION == 8
    target = tmp_path / "config.json"
    config = OverlayConfig(color="white", ui_language="en")
    save_user_config(config, target)
    assert load_user_config(target) == config
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema_version"] == 8 and data["ui_language"] == "en"

    target.write_text(json.dumps({"schema_version": 7, "color": "white"}),
                      encoding="utf-8")
    assert load_user_config(target).ui_language == "ja"
    target.write_text(json.dumps({"ui_language": "xx"}), encoding="utf-8")
    assert load_user_config(target).ui_language == "ja"


def test_language_does_not_change_rendered_pixels():
    image = Image.new("RGB", (640, 360), (30, 60, 90))
    japanese = OverlayConfig(
        color="white", effect="oled", show_cross=True,
        show_timecode=True, timecode_text="2026/09/18 PM 08:30",
        ui_language="ja")
    english = OverlayConfig.from_dict({**japanese.to_dict(), "ui_language": "en"})
    assert composite_with_config(image, japanese).tobytes() == composite_with_config(
        image, english).tobytes()


def test_batch_errors_follow_selected_language(tmp_path):
    missing = tmp_path / "missing"
    english = process_folder(
        missing, tmp_path / "out", OverlayConfig(ui_language="en"))
    assert english.error_details[0].code == "input_missing"
    assert english.errors[0].startswith("Input folder not found:")
    japanese = process_folder(
        missing, tmp_path / "out", OverlayConfig(ui_language="ja"))
    assert japanese.errors[0].startswith("入力フォルダがありません:")


def test_font_validation_error_is_localized(tmp_path):
    missing = tmp_path / "missing.ttf"
    assert validate_custom_font_file(missing, "ja") == "ファイルが見つかりません"
    assert validate_custom_font_file(missing, "en") == "The file was not found"


def test_cli_help_switches_language(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "rec_frame_app.py"
    for language, expected in (("ja", "GUIを開かず"),
                               ("en", "without opening the GUI")):
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--lang", language, "--help"],
            cwd=repo_root, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0
        assert expected in result.stdout
    config = tmp_path / "english.json"
    config.write_text(json.dumps(OverlayConfig(ui_language="en").to_dict()),
                      encoding="utf-8")
    from_config = subprocess.run(
        [sys.executable, "-B", str(script), "--config", str(config), "--help"],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8")
    assert from_config.returncode == 0
    assert "without opening the GUI" in from_config.stdout


def test_cli_batch_english_output(tmp_path, capsys):
    from rec_frame_app import run_batch_cli

    source, output = tmp_path / "in", tmp_path / "out"
    source.mkdir()
    Image.new("RGB", (96, 64), "#456").save(source / "one.png")
    code = run_batch_cli(str(source), str(output), language="en")
    captured = capsys.readouterr().out
    assert code == 0
    assert "Succeeded: 1" in captured
    assert (output / "one_rec.png").exists()
