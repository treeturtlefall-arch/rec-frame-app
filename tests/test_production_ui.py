"""採用B案を移植した本番UIの主要な状態遷移を検証する。"""
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest
import rec_frame_app
from rec_config import DEFAULT_FONT, OverlayConfig


def _destroy(app):
    for job in app.tk.call("after", "info"):
        try:
            app.after_cancel(job)
        except tk.TclError:
            pass
    app.destroy()


def test_production_ui_state_persistence_sample_and_custom_font(tmp_path, monkeypatch):
    managed_fonts = tmp_path / "preferences" / "fonts"
    loaded = OverlayConfig(
        color="white", thickness="large", effect="oled",
        show_frame=False, show_battery=True, show_rec=True,
        show_cross=True, show_timecode=True,
        timecode_text="2024/02/03 AM 04:05", timecode_from_exif=True,
        ui_language="en",
    )
    saved = []
    monkeypatch.setattr(rec_frame_app, "load_user_config", lambda: loaded)
    monkeypatch.setattr(rec_frame_app, "save_user_config", saved.append)
    monkeypatch.setattr(rec_frame_app, "get_user_fonts_dir", lambda: managed_fonts)

    try:
        app = rec_frame_app.App()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    app.withdraw()
    try:
        app.update_idletasks()
        assert app.mode_var.get() == "detail"
        assert app.language_var.get() == "en"
        assert app.language_label.cget("text") == "Language"
        assert "Elements" in app.tabs.tab(app.detail_page, "text")
        assert app.font_var.get() == loaded.font_key
        assert "Condensed" in app.font_display_var.get()
        assert app.effect_var.get() == "oled"
        assert app.effect_display_var.get() == "OLED (Soft glow)"
        assert app.tabs.tab(app.detail_page, "state") == "normal"
        assert app.tabs.select() == str(app.detail_page)
        assert str(app.timecode_entry["state"]) == "disabled"
        assert app.tc_year_spin.get() == "2024"
        assert str(app.save_button["state"]) == "disabled"

        with patch("tkinter.filedialog.askopenfilename", return_value="") as dialog:
            app.open_image()
        assert dialog.call_args.kwargs["title"] == "Select an image"
        with patch("tkinter.filedialog.askopenfilename", return_value="") as dialog:
            app._on_add_custom_font()
        assert dialog.call_args.kwargs["title"] == "Select a font file"
        with patch("tkinter.messagebox.showinfo") as notice:
            app.save_image()
        assert notice.call_args.args[:2] == ("Information", "Open an image first.")
        with patch("tkinter.filedialog.askdirectory", return_value="") as dialog:
            app.batch_images()
        assert dialog.call_args.kwargs["title"] == "Batch: Select the input folder"

        app.show_cross_var.set(False)
        app.timecode_text_var.set("2026/09/18 PM 08:30")
        app.mode_var.set("simple")
        app._on_mode_change()
        assert app.tabs.tab(app.detail_page, "state") == "hidden"
        assert app.tabs.select() == str(app.style_page)
        assert not app._current_config().show_cross
        assert app.show_timecode_var.get()  # 詳細設定値は保持される
        assert saved[-1].timecode_text == "2026/09/18 PM 08:30"

        app.mode_var.set("detail")
        app._on_mode_change()
        app.use_exif_var.set(False)
        app._on_exif_toggle()
        assert str(app.timecode_entry["state"]) == "normal"
        assert app.timecode_text_var.get() == "2026/09/18 PM 08:30"

        app.open_sample()
        assert app.src_image.size == (1600, 1000)
        assert app.src_path == "rec-frame-sample.png"
        assert app.result_image.size == app.src_image.size
        assert str(app.save_button["state"]) == "normal"
        before_language_pixels = app.result_image.tobytes()
        before_tab = app.tabs.select()
        before_text = app.timecode_text_var.get()
        app.language_display_var.set("日本語")
        app._on_language_selected()
        assert app.language_var.get() == "ja"
        assert app.language_label.cget("text") == "Language"
        assert app.tabs.select() == before_tab
        assert app.timecode_text_var.get() == before_text
        assert app.result_image.tobytes() == before_language_pixels
        assert saved[-1].ui_language == "ja"
        assert app.font_var.get() == loaded.font_key
        assert app.font_display_var.get() == loaded.font_key
        assert app.effect_var.get() == "oled"
        assert app.effect_display_var.get() == "OLED(微発光)"

        with patch("tkinter.filedialog.asksaveasfilename", return_value=""), \
                patch("rec_frame_app.save_composited_image") as save:
            app.save_image()
        save.assert_not_called()
        for answers in [("",), ("input", ""), ("input", "output")]:
            with patch("tkinter.filedialog.askdirectory", side_effect=answers), \
                    patch("tkinter.messagebox.askyesno", return_value=False), \
                    patch("rec_batch.process_folder") as batch:
                app.batch_images()
            batch.assert_not_called()

        output = tmp_path / "sample.png"
        app.timecode_text_var.set("save immediately")
        with patch("tkinter.filedialog.asksaveasfilename", return_value=str(output)), \
                patch("tkinter.messagebox.showinfo"):
            app.save_image()
        assert output.exists()
        assert app._full_config().timecode_text == "save immediately"

        source_font = Path("C:/Windows/Fonts/arial.ttf")
        if not source_font.exists():
            pytest.skip("A system TrueType font is required for the UI font-copy test")
        with patch("tkinter.filedialog.askopenfilename", return_value=str(source_font)):
            app._on_add_custom_font()
        registered = app.font_var.get()
        assert registered in app.custom_fonts
        copied = Path(app.custom_fonts[registered])
        assert copied.parent == managed_fonts and copied.exists()
        with patch("tkinter.messagebox.askyesno", return_value=True):
            app._on_remove_custom_font()
        assert registered not in app.custom_fonts
        assert not copied.exists()
        assert source_font.exists()
        assert app.font_var.get() == DEFAULT_FONT
    finally:
        _destroy(app)


def test_scroll_page_hides_bar_when_content_fits(monkeypatch):
    monkeypatch.setattr(rec_frame_app, "load_user_config", OverlayConfig)
    monkeypatch.setattr(rec_frame_app, "save_user_config", lambda _config: None)
    try:
        app = rec_frame_app.App()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    try:
        app.geometry("1160x900")
        app.update()
        app.style_page._size()
        assert not app.style_page.bar.winfo_ismapped()
        app.geometry("960x600")
        app.update()
        app.style_page._size()
        assert app.style_page.bar.winfo_ismapped()

        app.style_page.canvas.yview_moveto(0)
        app.style_page.canvas.event_generate("<MouseWheel>", delta=-120)
        app.update()
        assert app.style_page.canvas.yview()[0] > 0
        before = app.style_page.canvas.yview()
        app.canvas_label.event_generate("<MouseWheel>", delta=-120)
        app.update()
        assert app.style_page.canvas.yview() == before

        app.focus_force()
        with patch.object(app, "open_image") as opened:
            app.event_generate("<Control-o>")
            app.update()
            opened.assert_called_once()
        with patch.object(app, "save_image") as saved:
            app.event_generate("<Control-s>")
            app.update()
            saved.assert_called_once()
    finally:
        _destroy(app)
