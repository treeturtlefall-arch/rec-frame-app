"""GUIとバッチの日時・エフェクト出力が同じになることを検証する。"""
import os
import tkinter as tk
from datetime import datetime

import pytest
from PIL import Image

import rec_frame_app
from rec_batch import process_single_file
from rec_config import OverlayConfig


@pytest.mark.parametrize("effect", ["off", "oled", "2000s"])
@pytest.mark.parametrize("timecode_source", ["fixed", "exif", "mtime"])
def test_gui_and_batch_render_identical_pixels(tmp_path, monkeypatch, effect, timecode_source):
    src = tmp_path / "photo.png"
    exif = Image.Exif()
    if timecode_source == "exif":
        exif[36867] = "2024:02:03 00:05:00"
    Image.new("RGB", (640, 360), (10, 20, 30)).save(src, exif=exif)
    stamp = datetime(2025, 6, 7, 12, 30).timestamp()
    os.utime(src, (stamp, stamp))
    config = OverlayConfig(
        color="white", effect=effect, show_cross=True, show_timecode=True,
        timecode_text="FIXED", timecode_from_exif=timecode_source != "fixed",
    )
    # 実際のユーザー設定を読み書きしない。
    monkeypatch.setattr(rec_frame_app, "load_user_config", lambda: config)
    monkeypatch.setattr(rec_frame_app, "save_user_config", lambda _: None)
    try:
        app = rec_frame_app.App()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    app.withdraw()
    try:
        app.src_path = str(src)
        app.src_image = rec_frame_app.load_base_image(src)
        rendered = app._render()
        expected_text = {
            "fixed": "FIXED", "exif": "2024/02/03 AM 12:05",
            "mtime": "2025/06/07 PM 12:30",
        }[timecode_source]
        assert app.timecode_text_var.get() == expected_text
        # 同じ日時の再描画では入力欄のtraceを再発火させない。
        pending = app._timecode_edit_job
        assert app._render().tobytes() == rendered.tobytes()
        assert app._timecode_edit_job == pending

        dest = tmp_path / "result.png"
        process_single_file(src, dest, config)
        with Image.open(dest) as actual:
            assert actual.mode == rendered.mode
            assert actual.size == rendered.size
            assert actual.tobytes() == rendered.tobytes()
        assert config.timecode_text == "FIXED"
    finally:
        if app._timecode_edit_job is not None:
            app.after_cancel(app._timecode_edit_job)
        app.destroy()


def test_missing_config_fields_have_independent_defaults():
    first = OverlayConfig.from_dict({"schema_version": 1, "unknown": True})
    second = OverlayConfig.from_dict({})
    assert first == second == OverlayConfig()
    first.custom_fonts["Custom"] = "custom.ttf"
    assert second.custom_fonts == {}
