"""CLI分離後の言語優先順位・終了コード・GUI起動分岐を検証する。"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

import rec_cli
import rec_frame_app
from rec_config import OverlayConfig
from rec_overlay import composite_with_config, load_base_image


@pytest.fixture(autouse=True)
def isolated_cli_config(monkeypatch):
    monkeypatch.setattr(rec_cli, "load_user_config", OverlayConfig)


def test_cli_module_does_not_require_tkinter():
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "import sys; sys.modules['tkinter'] = None; import rec_cli; "
         "assert 'rec_frame_app' not in sys.modules"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("arguments, expected", [
    ([], "GUIを開かず"),
    (["--config"], "without opening the GUI"),
    (["--config", "--lang", "ja"], "GUIを開かず"),
])
def test_help_language_priority(tmp_path, capsys, arguments, expected):
    config = tmp_path / "english.json"
    config.write_text(json.dumps({"ui_language": "en"}), encoding="utf-8")
    argv = list(arguments)
    if "--config" in argv:
        argv.insert(argv.index("--config") + 1, str(config))
    with pytest.raises(SystemExit) as exited:
        rec_cli.parse_cli_args([*argv, "--help"])
    assert exited.value.code == 0
    assert expected in capsys.readouterr().out


@pytest.mark.parametrize("argv", [
    ["--batch", "input"], ["--lang", "fr"], ["--config"],
])
def test_invalid_cli_arguments_return_2(argv, capsys):
    with pytest.raises(SystemExit) as exited:
        rec_cli.parse_cli_args(argv)
    assert exited.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("argv, language", [([], None), (["--lang", "en"], "en")])
def test_main_starts_gui_with_language_override(monkeypatch, argv, language):
    factory = Mock()
    monkeypatch.setattr(rec_frame_app, "App", factory)
    assert rec_frame_app.main(argv) == 0
    factory.assert_called_once_with(language_override=language)
    factory.return_value.mainloop.assert_called_once_with()


def test_main_batch_preserves_config_and_pixels_without_opening_gui(tmp_path, monkeypatch, capsys):
    factory = Mock(side_effect=AssertionError("Batch must not open the GUI"))
    monkeypatch.setattr(rec_frame_app, "App", factory)
    source, output = tmp_path / "in", tmp_path / "out"
    source.mkdir()
    Image.new("RGB", (640, 360), "#456").save(source / "photo.png")
    config = OverlayConfig(color="white", effect="oled", show_cross=True, ui_language="en")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
    assert rec_frame_app.main([
        "--batch", str(source), str(output), "--config", str(config_path)]) == 0
    assert "Succeeded: 1" in capsys.readouterr().out
    expected = composite_with_config(load_base_image(source / "photo.png"), config)
    assert load_base_image(output / "photo_rec.png").tobytes() == expected.tobytes()
    factory.assert_not_called()


def test_main_batch_failure_exit_codes(tmp_path, monkeypatch, capsys):
    factory = Mock(side_effect=AssertionError("Batch must not open the GUI"))
    monkeypatch.setattr(rec_frame_app, "App", factory)
    argv = ["--batch", str(tmp_path / "missing"), str(tmp_path / "out"), "--lang", "en"]
    assert rec_frame_app.main(argv) == 1
    assert "Error:" in capsys.readouterr().out
    config_path = tmp_path / "broken.json"
    config_path.write_text("{", encoding="utf-8")
    assert rec_frame_app.main([*argv, "--config", str(config_path)]) == 2
    assert "config" in capsys.readouterr().out.lower()
    factory.assert_not_called()
